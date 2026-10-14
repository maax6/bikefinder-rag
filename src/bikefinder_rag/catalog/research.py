"""Catalogue exploration without a required year; every passage keeps SQL identity."""
import hashlib
import json
from functools import lru_cache
import os
from pathlib import Path
import re

import numpy as np

from bikefinder_rag.catalog.enriched import _rows, folded
from bikefinder_rag.catalog.technical_rag import documents, normalized_vectors, rank_documents
from bikefinder_rag.embeddings import embedder

ROOT = Path(__file__).resolve().parents[3]
MAX_FICHES = 500
MAX_PASSAGES = 3


def compact(value):
    return re.sub(r"[^a-z0-9]", "", folded(value))


def literal_name(value, text):
    name = compact(value)
    return re.search(r"(?<!\w)" + r"[\s-]*".join(re.escape(c) for c in name) + r"(?!\w)", folded(text)) if name else None


@lru_cache(maxsize=1)
def load_index(path, stamp):
    """Reuse an immutable local index, never silently trust changed source text."""
    directory = Path(path)
    manifest = json.loads((directory / "index-manifest.json").read_text())
    for name in ["documents.jsonl", "vectors.npy", "protocol.json"]:
        digest = hashlib.sha256()
        with (directory / name).open("rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(block)
        if digest.hexdigest() != manifest["artifacts"][name]["sha256"]:
            raise ValueError("Local search index checksum mismatch")
    protocol = json.loads((directory / "protocol.json").read_text())
    if protocol["dense_model"]["revision"] != embedder.MODEL_REVISION:
        raise ValueError("Local search index model revision mismatch")
    rows = [json.loads(line) for line in (directory / "documents.jsonl").open()]
    vectors = np.load(directory / "vectors.npy", mmap_mode="r", allow_pickle=False)
    if vectors.shape != (len(rows), embedder.EMBEDDING_DIM):
        raise ValueError("Local search index shape mismatch")
    return {row["id"]: (i, row) for i, row in enumerate(rows)}, vectors


def rank_passages(query, docs):
    directory = Path(os.getenv("BIKEFINDER_RESEARCH_INDEX", str(ROOT / "data/technical/retrieval-benchmark-20261013/index")))
    try:
        files = [directory / name for name in ["index-manifest.json", "documents.jsonl", "vectors.npy", "protocol.json"]]
        indexed, vectors = load_index(str(directory.resolve()), tuple((f.stat().st_mtime_ns, f.stat().st_size) for f in files))
        indices = []
        for doc in docs:
            i, saved = indexed[doc["id"]]
            if any(saved[k] != doc[k] for k in ["object_id", "brand", "model", "year", "section", "source_url", "source_sha256", "original_text", "text"]):
                raise ValueError("Local index does not match the live SQL source")
            indices.append(i)
        selected = normalized_vectors(vectors[indices], len(docs))
        query_vector = normalized_vectors([embedder.embed_text(query)], 1)[0]
        scores = selected @ query_vector
        ordered = sorted(range(len(docs)), key=lambda i: (-float(scores[i]), docs[i]["id"]))
        return [dict(docs[i], score=float(scores[i])) for i in ordered], {"index": "verified_local_index", "documents": len(docs), "model_revision": embedder.MODEL_REVISION}
    except (OSError, ValueError, KeyError):
        ranked, timing = rank_documents(query, docs)
        return ranked, {**timing, "index": "live_source_cache"}


class CatalogResearch:
    """One request's tools and evidence; SQL is parameterized, no generated SQL."""
    def __init__(self, conn, question, history=None, *, scope_checker=None):
        self.conn, self.question = conn, question
        self.scope_checker = scope_checker
        previous = [m["content"] for m in (history or [])[-4:] if m.get("role") == "user" and isinstance(m.get("content"), str)]
        self.input_text = " ".join([*previous, question])
        self.scopes, self.selected, self.searches, self.scope_passages = {}, {}, [], {}
        brands = _rows(conn, "SELECT DISTINCT brand FROM technical_fiches ORDER BY brand", [])
        self.expected_brands = [b["brand"] for b in brands if re.search(r"(?<!\w)" + re.escape(folded(b["brand"])) + r"(?!\w)", folded(question))]
        from bikefinder_rag.agent import jev_router
        self.expected_models = jev_router.entities(conn, question)[0]

    def execute(self, name, arguments):
        definitions = {"lookup_models": (self.lookup_models, {"brand", "model_query", "min_year", "max_year"}),
                       "research_catalog": (self.research_catalog, {"brand", "model_query", "min_year", "max_year", "query", "section", "mode", "terms"}),
                       "search_passages": (self.search_passages, {"scope_id", "query", "section", "mode", "terms"})}
        if name not in definitions or set(arguments) - definitions[name][1]:
            raise ValueError("Unknown catalogue tool or arguments")
        try:
            return definitions[name][0](**arguments)
        except TypeError as exc:
            raise ValueError("Missing or invalid catalogue tool arguments") from exc

    def research_catalog(self, brand, model_query, query, section="", mode="semantic", terms=None, min_year=None, max_year=None):
        scope = self.lookup_models(brand, model_query, min_year, max_year)
        result = self.search_passages(scope["scope_id"], query, section, mode, terms)
        return {**result, "brand": brand, "model_query": model_query, "variants": scope["variants"]}

    def lookup_models(self, brand, model_query, min_year=None, max_year=None):
        if not isinstance(brand, str) or not isinstance(model_query, str) or not 1 <= len(model_query) <= 80 or len(brand) > 80:
            raise ValueError("A literal model/family name is required")
        if not literal_name(model_query, self.input_text) or (brand and not literal_name(brand, self.input_text)):
            raise ValueError("Use only model/family and brand names present in the user's request")
        for qualifier in re.finditer(r"\b(?:edition|finition|version)\s+([a-z0-9-]+)", folded(self.question)):
            label = qualifier[1]
            mention = literal_name(model_query, self.question)
            if mention:
                between = folded(self.question)[min(mention.end(), qualifier.end()):max(mention.start(), qualifier.start())]
                if re.search(r"\b(?:et|ou|vs|versus)\b|[,;]", between):
                    continue
            if label not in {"de", "en", "sans", "avec", "pour", "ou", "et", "qui", "exacte", "actuelle", "source", "catalogue"} and not label.isdigit() and label not in folded(model_query):
                raise ValueError("An explicit edition/variant remains unresolved; retain its name in the lookup")
        years = {int(n) for n in re.findall(r"\b(?:18|19|20|21)\d{2}\b", self.input_text)} - {int(n) for n in re.findall(r"\d+", model_query)}
        for value in [min_year, max_year]:
            if value is not None and (type(value) is not int or value not in years):
                raise ValueError("No invented year constraint; search all years when the year is to be discovered")
        if min_year is not None and max_year is not None and min_year > max_year:
            raise ValueError("Invalid year range")
        clauses, params = [], []
        if brand:
            clauses.append("regexp_replace(lower(brand),'[^a-z0-9]','','g')=%s")
            params.append(compact(brand))
        for word in re.findall(r"[a-z0-9]+", folded(model_query)):
            if word in {"edition", "finition", "version"}:
                continue
            if len(word) <= 3:
                clauses.append("model ~* %s")
                params.append(r"\m" + re.escape(word) + r"\M")
            else:
                clauses.append("regexp_replace(lower(model),'[^a-z0-9]','','g') LIKE %s")
                params.append("%" + word + "%")
        if not clauses:
            raise ValueError("A model/family scope is required")
        for value, operator in [(min_year, ">="), (max_year, "<=")]:
            if value is not None:
                clauses.append("year " + operator + " %s")
                params.append(value)
        rows = _rows(self.conn, "SELECT id,brand,model,year,source_url,source_sha256,record FROM technical_fiches WHERE " + " AND ".join(clauses) + " ORDER BY year,model,id LIMIT %s", params + [MAX_FICHES + 1])
        if len(rows) > MAX_FICHES:
            raise ValueError("Scope exceeds 500 fiches; narrow the model/family, not an invented year")
        if len({r["id"] for r in rows}) != len(rows):
            raise ValueError("Duplicate SQL identities")
        scope_id = "S" + str(len(self.scopes) + 1)
        variants = {}
        for row in rows:
            variants.setdefault((row["brand"], row["model"]), []).append(row["year"])
        summary = {"scope_id": scope_id, "brand": brand, "model_query": model_query, "fiches": len(rows),
                   "variants": [{"brand": b, "model": m, "first_year": min(y), "last_year": max(y), "fiches": len(y)} for (b, m), y in variants.items()]}
        self.scopes[scope_id] = {"rows": rows, "summary": summary, "searched": False, "missing": []}
        return summary

    def search_passages(self, scope_id, query, section="", mode="semantic", terms=None):
        if scope_id not in self.scopes or not isinstance(query, str) or not 1 <= len(query) <= 500 or not isinstance(section, str) or len(section) > 80:
            raise ValueError("Use a returned scope_id and a bounded passage query")
        if mode not in {"semantic", "earliest_mention"}:
            raise ValueError("Unsupported passage search mode")
        terms = terms or []
        if not isinstance(terms, list) or len(terms) > 6 or any(not isinstance(t, str) or not 1 <= len(t) <= 80 for t in terms):
            raise ValueError("Invalid literal search terms")
        if mode == "earliest_mention" and not terms:
            raise ValueError("Earliest mention requires explicit terms; similarity is not chronology")
        scope = self.scopes[scope_id]
        docs = [doc for row in scope["rows"] for doc in documents(row)
                if not section or folded(section) in folded(doc["section"])]
        ranked, timing = rank_passages(query, docs) if docs else ([], {"index": "none"})
        from bikefinder_rag.agent.jev_router import TOPICS
        structural_words = {word for title in [*[t.split(":")[0] for t in TOPICS.values()], *[d["section"] for d in docs]] for word in re.findall(r"\w+", folded(title))}
        effective_terms = [t for t in terms if folded(t) not in structural_words]
        if mode == "earliest_mention" and not effective_terms:
            raise ValueError("Earliest mention needs a distinctive property, not catalogue field/section names; use semantic to read a topic")
        matched = [doc for doc in docs if any(re.search(r"(?<!\w)" + re.escape(folded(t)) + r"(?!\w)", folded(doc["original_text"])) for t in effective_terms)] if effective_terms else []
        earliest = sorted(matched, key=lambda d: (d["year"], d["brand"], d["model"], d["id"]))
        selected = list({d["id"]: d for d in [*earliest[:MAX_PASSAGES], *ranked[:MAX_PASSAGES]]}.values())
        if earliest:
            selected.sort(key=lambda d: (d["year"], d["model"], d["id"]))
        scope["older_semantic_clues"] = bool(earliest and any(d["year"] < earliest[0]["year"] for d in ranked[:MAX_PASSAGES]))
        scope["missing"] = []
        if effective_terms and not earliest:
            scope["missing"].append("Aucune mention des termes « " + ", ".join(effective_terms) + " » retrouvée dans les sections examinées. Cela ne prouve pas l'absence de l'équipement ou d'une option.")
        if not docs:
            scope["missing"].append("Aucun passage source disponible dans cette sélection de fiches et de sections.")
        self.scope_passages[scope_id] = selected
        self.selected = {doc["id"]: doc for passages in self.scope_passages.values() for doc in passages}
        scope["searched"] = True
        response = {"scope_id": scope_id, "query": query, "mode": mode, "terms": terms, "effective_terms": effective_terms,
                    "searched_fiches": len(scope["rows"]), "searched_passages": len(docs), "matching_mentions": len(matched),
                    "earliest_matching_mention_year": earliest[0]["year"] if earliest else None,
                    "older_semantic_clues": scope["older_semantic_clues"],
                    "scope_note": "Le premier millésime lexical concerne uniquement les termes choisis. Les voisins BGE peuvent décrire le même fait avec d'autres mots et une année antérieure : les examiner et compléter les termes si nécessaire. Aucune date officielle de lancement ni absence réelle établie.",
                    "passages": [{k: d[k] for k in ["id", "object_id", "brand", "model", "year", "section", "original_text", "source_url"]} for d in selected],
                    "missing": list(scope["missing"]), "retrieval": timing}
        self.searches.append(response)
        return response

    def needs_review(self):
        return [s["summary"]["model_query"] + " : des passages BGE antérieurs utilisent peut-être un autre vocabulaire ; examiner les textes avant de conclure sur la première année"
                for s in self.scopes.values() if s.get("older_semantic_clues")]

    def incomplete(self):
        covered_brands = {row["brand"] for scope in self.scopes.values() if scope["searched"] for row in scope["rows"]}
        covered_models = {(row["brand"], row["model"]) for scope in self.scopes.values() if scope["searched"] for row in scope["rows"]}
        return (["Recherche non effectuée pour " + brand for brand in self.expected_brands if brand not in covered_brands]
                + ["Famille/modèle non recherché : " + m["brand"] + " " + m["model"] for m in self.expected_models
                   if (m["brand"], m["model"]) not in covered_models]
                + [s["summary"]["model_query"] + " : passages non recherchés" for s in self.scopes.values() if not s["searched"]])

    def result(self, question):
        sources, missing, output = {}, [], []
        all_rows = {row["id"]: row for s in self.scopes.values() for row in s["rows"]}
        for doc in self.selected.values():
            row = all_rows[doc["object_id"]]
            source = sources.setdefault(row["id"], {"object_id": row["id"], **{k: row[k] for k in ["brand", "model", "year", "source_url", "source_sha256"]},
                "identity_validation": "SQL primary key, canonical name, actual year and source hash; year discovered in catalogue",
                "coverage": {}, "passages": []})
            source["passages"].append(doc)
        for scope in self.scopes.values():
            label = (scope["summary"]["brand"] + " " + scope["summary"]["model_query"]).strip()
            missing += [{"kind": "scope", "message": label + " — " + m} for m in scope["missing"]]
            if not scope["rows"]:
                missing.append({"kind": "identity", "message": label + " — aucune fiche correspondante ; aucune variante de remplacement choisie."})
            elif self.scope_checker and scope["searched"]:
                checked = self.scope_checker(question, scope["summary"], self.scope_passages.get(scope["summary"]["scope_id"], []))
                scope["summary"]["proof_check"] = checked
                if checked["status"] != "supported":
                    missing.append({"kind": "scope", "message": label + " — Les passages récupérés ne suffisent pas à établir tous les faits demandés pour cette famille (" + checked["status"] + "). Une absence de preuve n'est pas une preuve d'absence."})
        missing += [{"kind": "scope", "message": message} for message in self.incomplete()]
        missing.append({"kind": "authority", "message": "Les millésimes documentés dans ce catalogue ne prouvent pas une date officielle de lancement ni la disponibilité de chaque version ou option."})
        for source in sources.values():
            output.append("**" + source["brand"] + " " + source["model"] + " (" + str(source["year"]) + ")** : " +
                          " ; ".join(d["original_text"] for d in source["passages"]) + " [Fiche source](" + source["source_url"] + ")")
        return {"answer": "\n\n".join(output) or "Aucune preuve source n'a été récupérée pour cette demande.",
                "route": "catalog_research_sources", "plan": {"operation": "research", "source_question": question,
                    "a2_context": bool(re.search(r"\ba2\b", folded(question)))},
                "jev_calls": sum(s["summary"].get("proof_check", {}).get("jev_calls", 0) for s in self.scopes.values()),
                "evidence": {"retrieval_executed": bool(self.searches), "sources": list(sources.values()), "missing": missing,
                    "research_scopes": self.searches, "legal_certification": False}}
