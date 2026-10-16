"""Exact SQL identity, local BGE evidence, and source-only answer assembly.

Similarity ranks documents; it never establishes identity or legal eligibility.
Requested facts are checked against complete source rows and their passages.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import threading
import time
from zipfile import BadZipFile

import numpy as np

from bikefinder_rag.catalog.enriched import _rows, folded
from bikefinder_rag.embeddings import embedder

PROTOCOL = "technical-rag-canonical-v1"
MODEL_LOCK = threading.Lock()
ROOT = Path(__file__).resolve().parents[3]
MAX_FICHES = 3
MAX_DOCUMENTS = 8
LICENSE_LIMIT = ("Les passages cités sont des fiches techniques, pas des documents officiels A2. "
                 "Le certificat de bridage/homologation et la configuration de votre exemplaire "
                 "ne sont pas établis par ces preuves ; je ne certifie pas son éligibilité A2.")


def resolve_identities(conn, plan):
    models = plan.get("models", [])
    if not models or len(models) > MAX_FICHES or plan.get("unresolved_variant") or plan.get("variant_unknown") or plan.get("candidate_variants"):
        return [], ["Précise au maximum trois modèles, leurs variantes exactes et leurs millésimes."]
    rows, missing, seen = [], [], set()
    for model in models:
        brand, name = model.get("brand"), model.get("model")
        year = model.get("year", plan.get("identity", {}).get("year"))
        if not brand or not name or type(year) is not int:
            missing.append("Précise la marque, la variante exacte et le millésime de chaque moto.")
            continue
        found = _rows(conn, "SELECT id,brand,model,year,source_url,source_sha256,record "
                      "FROM technical_fiches WHERE lower(brand)=lower(%s) AND lower(model)=lower(%s) AND year=%s ORDER BY id",
                      [brand, name, year])
        if len(found) != 1:
            missing.append(f"Fiche exacte non identifiée : {brand} {name} ({year}). Aucune autre année ou variante substituée.")
            continue
        row = found[0]
        if (row["brand"].lower(), row["model"].lower(), row["year"]) != (brand.lower(), name.lower(), year):
            raise ValueError("SQL identity mismatch")
        if row["id"] not in seen:
            seen.add(row["id"])
            rows.append(row)
    return rows, missing


def documents(row):
    result = []
    for ordinal, section in enumerate(row["record"].get("technical_sections", [])):
        raw = section.get("text", "")
        if not raw.strip():
            continue
        title = section.get("section", "")
        result.append({"id": f"{row['id']}:section:{ordinal}", "object_id": row["id"],
                       "brand": row["brand"], "model": row["model"], "year": row["year"],
                       "source_url": row["source_url"], "source_sha256": row["source_sha256"],
                       "section": title, "original_text": raw,
                       "text": f"{row['brand']} {row['model']} {row['year']}\n{title}\n{raw}"})
    return result


def normalized_vectors(values, count):
    array = np.asarray(values, dtype=np.float32)
    if array.shape != (count, embedder.EMBEDDING_DIM) or not np.isfinite(array).all():
        raise ValueError("Invalid local embedding shape or values")
    norms = np.linalg.norm(array, axis=1, keepdims=True)
    if np.any(norms < 1e-8):
        raise ValueError("Empty embedding")
    return array / norms


def rank_documents(question, docs):
    if not docs:
        return [], {"document_cache_hit": False, "query_encoding_seconds": 0.0}
    key = hashlib.sha256(json.dumps({"protocol": PROTOCOL, "model": embedder.MODEL_NAME,
                                    "revision": embedder.MODEL_REVISION, "documents": docs},
                                   sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    directory = Path(os.getenv("BIKEFINDER_RAG_CACHE", str(ROOT / "data/technical/rag-cache")))
    directory.mkdir(parents=True, exist_ok=True)
    cache = directory / (key + ".npz")
    if not MODEL_LOCK.acquire(timeout=5):
        raise RuntimeError("Local retrieval busy")
    try:
        vectors, cache_hit = None, False
        if cache.exists():
            try:
                with np.load(cache, allow_pickle=False) as stored:
                    if stored["key"].item() != key:
                        raise ValueError("Cache key mismatch")
                    saved = stored["vectors"]
                    if hashlib.sha256(saved.tobytes()).hexdigest() != stored["vector_sha256"].item():
                        raise ValueError("Cache checksum mismatch")
                    vectors = normalized_vectors(saved, len(docs))
                    cache_hit = True
            except (OSError, ValueError, KeyError, BadZipFile):
                vectors = None
        started = time.perf_counter()
        if vectors is None:
            vectors = normalized_vectors(embedder.embed_texts([d["text"] for d in docs]), len(docs))
            with tempfile.NamedTemporaryFile(dir=directory, suffix=".npz", delete=False) as temporary:
                temporary_path = Path(temporary.name)
                np.savez(temporary, key=np.asarray(key), vectors=vectors,
                         vector_sha256=np.asarray(hashlib.sha256(vectors.tobytes()).hexdigest()))
            temporary_path.replace(cache)
        document_seconds = time.perf_counter() - started
        started = time.perf_counter()
        query = normalized_vectors([embedder.embed_text(question)], 1)[0]
        query_seconds = time.perf_counter() - started
        scores = vectors @ query
        ordered = sorted(range(len(docs)), key=lambda i: (-float(scores[i]), docs[i]["id"]))
        return [dict(docs[i], score=float(scores[i]), rank=n) for n, i in enumerate(ordered, 1)], {
            "document_cache_hit": cache_hit, "document_encoding_seconds": document_seconds,
            "query_encoding_seconds": query_seconds, "model": embedder.MODEL_NAME,
            "model_revision": embedder.MODEL_REVISION}
    finally:
        MODEL_LOCK.release()


def field_proofs(record, field, docs):
    from bikefinder_rag.agent.jev_router import selected_rows
    if field == "license":
        passages = [d for d in docs if "permis" in folded(d["original_text"]) or "brid" in folded(d["original_text"])]
        return passages, [d["original_text"] for d in passages]
    source_rows = ([r for r in record.get("spec_rows", []) if "equip" in folded(r["section"])
                   or ("transmission" in folded(r["section"]) and "shifter" in folded(r["value"]))]
                   if field == "equipment" else selected_rows(record, field))
    matched = []
    for proof in source_rows:
        value = " ".join(proof["value"].split())
        candidates = [d for d in docs if d["section"] == proof["section"]
                      and value and value in " ".join(d["original_text"].split())]
        if not candidates:
            return [], []  # A row alone must not masquerade as a retrieved passage.
        matched.extend(candidates)
    return list({d["id"]: d for d in matched}.values()), source_rows


def answer_from_sources(conn, question, plan, check_coverage=None):
    from bikefinder_rag.agent.jev_router import LABELS, TOPICS, quote
    started = time.perf_counter()
    rows, identity_missing = resolve_identities(conn, plan)
    missing = [{"kind": "identity", "message": message} for message in identity_missing]
    if not rows:
        return {"answer": " ".join(identity_missing), "route": "clarification", "evidence": {
            "sources": [], "missing": missing, "retrieval_executed": False}, "plan": plan}
    fields = list(dict.fromkeys(plan.get("fields") or ["full"]))
    output, sources, retrievals = [], [], []
    for row in rows:
        docs = documents(row)
        ranked, timing = rank_documents(question, docs)
        retrievals.append(dict(timing, object_id=row["id"]))
        selected = {d["id"]: dict(d, selection_reason="bge_top5") for d in ranked[:5]}
        proofs = {}
        for field in fields:
            required, values = field_proofs(row["record"], field, docs)
            proofs[field] = (required, values)
            for doc in required:
                if doc["id"] not in selected and len(selected) < MAX_DOCUMENTS:
                    ranked_doc = next(d for d in ranked if d["id"] == doc["id"])
                    selected[doc["id"]] = dict(ranked_doc, selection_reason="required_field")
        checked = None
        if check_coverage is not None:
            checked = check_coverage(question, fields, row, list(selected.values()))
            timing["proof_check"] = checked
            retrievals[-1]["proof_check"] = checked
        output += [f"### {row['brand']} {row['model']} ({row['year']})", ""]
        coverage = {}
        for field, (required, values) in proofs.items():
            source_covered = bool(required) and all(d["id"] in selected for d in required)
            status = checked["fields"].get(field, "unverified") if checked else "source_only"
            covered = source_covered and status != "missing"
            coverage[field] = {"covered": covered and status == "complete", "source_passages_available": source_covered,
                               "requested_facts_status": status, "required_passage_ids": [d["id"] for d in required]}
            label = "Permis / bridage mentionnés" if field == "license" else TOPICS.get(field, LABELS.get(field, field))
            if covered:
                text = " ; ".join(values) if field == "license" else quote(values)
                output.append(f"- **{label} — la fiche indique :** {text}")
                if status == "partial":
                    message = "Un détail demandé reste non documenté dans ces preuves ; les mentions ci-dessus ne le confirment pas"
                    output.append("  " + message + ".")
                    missing.append({"kind": "subfact", "object_id": row["id"], "field": field, "message": message})
                if status == "unverified":
                    message = "La fiche fournit ces mentions, mais leur couverture du détail demandé n'a pas pu être vérifiée"
                    missing.append({"kind": "verification", "object_id": row["id"], "field": field, "message": message})
            else:
                message = ("Non documenté dans les passages de cette fiche" if not required or status == "missing"
                           else "La couverture des faits demandés n'a pas pu être vérifiée" if status == "unverified"
                           else "Preuves incomplètes dans le contexte retenu")
                output.append(f"- **{label} :** {message}.")
                missing.append({"kind": "field", "object_id": row["id"], "field": field, "message": message})
        if "license" in fields and plan.get("a2_context") and not any(re.search(r"\ba2\b", folded(d["original_text"])) for d in docs):
            output.append("- **Mention A2 :** non retrouvée dans cette fiche. Ce manque ne prouve pas une incompatibilité réelle.")
            missing.append({"kind": "field", "object_id": row["id"], "field": "a2_mention", "message": "Mention A2 non retrouvée"})
        output.append(f"\n[Source — fiche exacte]({row['source_url']})")
        output.append("Preuves retenues : " + ", ".join(dict.fromkeys(d["section"] for d in selected.values())) + ".")
        sources.append({"object_id": row["id"], "brand": row["brand"], "model": row["model"],
                        "year": row["year"], "source_url": row["source_url"], "source_sha256": row["source_sha256"],
                        "identity_validation": "unique SQL row, full name (case-insensitive), exact year",
                        "coverage": coverage, "passages": list(selected.values())})
    if identity_missing:
        output += ["", "**Identités manquantes :** " + " ".join(identity_missing)]
    if any(m['kind'] == 'verification' for m in missing):
        output += ['', "La couverture de tous les détails demandés n'a pas pu être vérifiée ; les mentions citées restent disponibles."]
    if plan.get("a2_context"):
        output += ["", "**Limite des preuves :** " + LICENSE_LIMIT]
    if plan.get("legal_proof_required"):
        missing.append({"kind": "authority", "field": "a2_certification", "message": LICENSE_LIMIT})
    evidence = {"sources": sources, "missing": missing, "retrieval_executed": True,
                "retrievals": retrievals, "seconds": time.perf_counter() - started,
                "source_kind": "technical_fiche", "legal_certification": False}
    return {"answer": "\n".join(output), "route": "rag_partial" if missing else "rag_sources",
            "evidence": evidence, "plan": plan}
