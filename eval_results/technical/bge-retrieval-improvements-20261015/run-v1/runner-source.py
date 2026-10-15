"""Annotate known retrieval errors and test frozen BGE retrieval alternatives.

Offline, read-only, full-corpus experiment. Development and verification brands
are disjoint, but all questions were previously observed: this is a regression
study, not a new independent holdout. No model training or chat change.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import random
import time

import numpy as np

from benchmark_technical_retrieval import BM25, metrics, model_spec, rank_scores, sha256_file

ROOT = Path(__file__).resolve().parents[1]
HISTORY = ROOT / "eval_results/technical/retrieval-benchmark-20261013"
INDEX = ROOT / "data/technical/retrieval-benchmark-20261013/index"
DEV = [1, 5, 7, 10, 15, 16, 23, 28, 38, 39, 41]
CHECK = [4, 8, 12, 22, 26, 33, 34, 40, 44]
AUDIT = [45, 46, 48, 49]
CONFIGS = [
    {"id": "dense", "pool": 40, "dense_weight": 1, "lexical_weight": 0, "rerank": False},
    {"id": "current_rrf40", "pool": 40, "dense_weight": 1, "lexical_weight": 1, "rerank": False},
    {"id": "weighted_rrf40", "pool": 40, "dense_weight": 2, "lexical_weight": 1, "rerank": False},
    {"id": "weighted_rrf80", "pool": 80, "dense_weight": 2, "lexical_weight": 1, "rerank": False},
    {"id": "rerank40", "pool": 40, "dense_weight": 1, "lexical_weight": 1, "rerank": True},
    {"id": "rerank80", "pool": 80, "dense_weight": 1, "lexical_weight": 1, "rerank": True},
]
NOTES = {
    1: ("wrong_model", "Le premier passage concerne la 450 SR, pas la 450 MT ; selle, longueur et masse ne sont pas transférables."),
    5: ("wrong_variant_multi_evidence", "La Stone Corsa ne remplace pas la Stone. Il faut les deux passages moteur et transmission pour air/cardan."),
    7: ("incomplete_comparison", "Les passages Y-AMT seuls ne prouvent pas les caractéristiques de la version manuelle ; couvrir les deux fiches et moteur/transmission."),
    10: ("excluded_variant", "La demande exclut Adventure : son châssis donne une selle 890–910 mm, contre 850–870 mm pour la GS demandée."),
    15: ("qualification_control", "Conserver « shifter en option ». Le premier résultat est déjà juste ; vérifier que le réglage ne le dégrade pas."),
    16: ("partial_evidence_control", "Conserver transmission et équipements pour shifter/Launch Control. Ne pas déduire bidirectionnel d'une mention de shifter."),
    23: ("wrong_year_missing_fact", "La fiche 2026 ou 2025 ne prouve pas l'équipement 2024. USB est cité ; démarrage sans clé reste non établi dans la fiche visée."),
    28: ("excluded_variant", "Les coloris de Monster SP ou Monster Hunter ne sont pas ceux de la Monster standard explicitement demandée."),
    38: ("incomplete_comparison", "Lire train avant et châssis des deux Africa Twin : une preuve Adventure Sports ne couvre pas la standard."),
    39: ("incomplete_comparison", "La SE Performance ne remplace pas la SE ; lire les deux trains avant standard/SE, sans transformer une absence de mention Brembo en absence de marque."),
    41: ("wrong_year_changes_fact", "Le premier passage GT+ 2025 semi-robotisé répondrait faux à une comparaison des transmissions 2024 ; conserver aussi les preuves de radar."),
    4: ("wrong_section_mass_basis", "Un passage moteur ne couvre pas selle/poids. Conserver séparément 181 kg à sec et 196 kg tous pleins faits dans Châssis."),
    8: ("wrong_year_incomplete", "L'édition anniversaire 2026 ou la fiche 2025 ne prouve pas les valeurs 2024 ; il faut moteur et châssis pour 776 cc, selle et réservoir."),
    12: ("missing_second_topic", "Le moteur répond à l'angle de 60°, mais la hauteur de selle est dans Châssis ; ne pas s'arrêter au premier bon passage."),
    22: ("missing_qualification", "La transmission seule ne prouve pas la mention du contrôle de traction ; conserver aussi la liste des équipements 2024."),
    26: ("colour_control", "Le résultat correct bleu/noir doit rester prioritaire ; la Tribute Edition n'établit pas toutes les combinaisons de la version visée."),
    33: ("exact_a2_variant_control", "La R A2 annonce 94 ch ; la R voisine 120 ch. Conserver moteur et mention de permis, sans certifier un exemplaire."),
    34: ("missing_second_topic_source_limit", "La puissance 20 ch n'établit pas A2 ; restituer la rubrique ne mentionnant que A, sans transformer ce silence en incompatibilité réglementaire."),
    40: ("incomplete_comparison_qualification", "Conserver les deux années et transmission/équipements utiles : shifter option en 2024, série en 2025 ; régulateur 2024 non cité, pas déclaré absent."),
    44: ("wrong_section_ambiguous_year", "Les passages moteur/permis ne prouvent pas les coloris ; comparer les deux rubriques Coloris et conserver la limite sur la datation de l'exemplaire."),
    45: ("coverage_authority_gap", "Une mention commerciale A2 n'est ni le certificat officiel de bridage ni un numéro d'homologation."),
    46: ("coverage_gap", "La fiche technique n'est pas un schéma constructeur de câblage ; aucun numéro de broche ne doit être inventé."),
    48: ("coverage_authority_market_gap", "La fiche conservée ne constitue pas le document BMW d'homologation US demandé."),
    49: ("coverage_gap", "Un intervalle de contrôle du jeu aux soupapes exige une source d'entretien absente de ce corpus de fiches."),
}


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def fuse(dense, lexical, config):
    scores = defaultdict(float)
    for ranking, weight in [(dense, config["dense_weight"]), (lexical, config["lexical_weight"])]:
        if weight:
            for rank, (index, _) in enumerate(ranking[:config["pool"]], 1):
                scores[index] += weight / (60 + rank)
    return sorted(scores.items(), key=lambda p: (-p[1], p[0]))[:config["pool"]]


def brand_partition(cases):
    dev = {p["brand"] for c in cases if c["split"] == "dev" for p in c["expected_identities"]}
    check = {p["brand"] for c in cases if c["split"] == "check" for p in c["expected_identities"]}
    if dev & check:
        raise ValueError("Development and verification share brands")
    return {"dev": sorted(dev), "check": sorted(check)}


def prepare(bundle):
    if bundle.exists():
        raise FileExistsError("Preserve the first annotated bundle")
    original = json.loads((HISTORY / "questions-holdout.json").read_text())
    history = json.loads((HISTORY / "holdout-global-firstpass-traces.json").read_text())
    documents = [json.loads(line) for line in (INDEX / "documents.jsonl").read_text().splitlines()]
    docs = {d["id"]: d for d in documents}
    by_object = {d["object_id"]: {k: d[k] for k in ["object_id", "brand", "model", "year", "source_url", "source_sha256"]} for d in documents}
    traces = {(r["question_id"], r["method"]): r for r in history["rows"]}
    cases = []
    for split, numbers in [("dev", DEV), ("check", CHECK), ("coverage_audit", AUDIT)]:
        for number in numbers:
            qid = f"HOLDOUT-{number:03d}"
            q = deepcopy(next(q for q in original["questions"] if q["id"] == qid))
            q["split"] = split
            kind, note = NOTES[number]
            positives = [{"grade": gold["grade"], **docs[gold["id"]]} for gold in q["gold_passages"] if gold["grade"] > 0]
            historic = traces[(qid, "dense")]
            positive_ids = {p["id"] for p in positives}
            scope = set(q["supplied_scope_object_ids"])
            confusions = []
            for ranked in historic["ranking"]:
                if ranked["id"] in positive_ids:
                    continue
                d = docs[ranked["id"]]
                # No unjudged global candidate is automatically a negative.
                if number in AUDIT:
                    label = "insufficient_authority_or_document_type"
                elif d["object_id"] not in scope:
                    label = "outside_requested_identity_not_universally_irrelevant"
                else:
                    label = "other_section_in_requested_identity_review_needed"
                confusions.append({"historical_dense_rank": ranked["rank"], "label": label,
                                   "training_negative_approved": False, **d})
                if len(confusions) == 2:
                    break
            q.update(annotation={"error_type": kind, "explanation_fr": note,
                     "review": "Assistant source review using existing source-only annotations; no independent human review",
                     "training_ready": False},
                     expected_identities=[by_object[o] for o in q["supplied_scope_object_ids"]],
                     positive_evidence=positives, confusable_passages=confusions,
                     historical_dense_metrics=historic["metrics"],
                     historical_dense_top10_ids=[p["id"] for p in historic["ranking"]])
            for proof in positives:
                if proof["object_id"] not in scope:
                    raise ValueError("Annotated positive is outside supplied identity")
            cases.append(q)
    partition = brand_partition(cases)
    bundle.mkdir(parents=True)
    for split in ["dev", "check", "coverage_audit"]:
        write(bundle / f"{split}.annotations.json", {"cases": [c for c in cases if c["split"] == split]})
    # Ranking code consumes questions only; annotations never enter the models.
    write(bundle / "queries.json", {"cases": [{"id": c["id"], "split": c["split"], "question": c["question"]} for c in cases]})
    index_manifest = json.loads((INDEX / "index-manifest.json").read_text())
    protocol = {"created_utc": datetime.now(timezone.utc).isoformat(), "date": "2026-10-15",
        "status": "frozen_before_new_candidate_execution", "index": str(INDEX),
        "index_manifest_sha256": sha256_file(INDEX / "index-manifest.json"),
        "document_count": len(documents), "document_sha256": sha256_file(INDEX / "documents.jsonl"),
        "configs": CONFIGS, "repeats": 3, "seed": 20261015, "rrf_constant": 60, "k": 10,
        "brands": partition, "case_counts": {s: sum(c["split"] == s for c in cases) for s in ["dev", "check", "coverage_audit"]},
        "model_inputs": "Only question text and canonical indexed source documents; no oracle identity, labels or references",
        "selection_rule": "Development only: maximize complete required groups at10, then hit@1, then nDCG@10; tied configs prefer lower median time",
        "selection_constraint": "Verification annotation file is opened after selection.json is saved; verification never retunes the choice",
        "baseline": "Exact current FrozenRetrieval algorithm: 40 per branch, positive BM25 scores only, equal RRF weights, constant 60",
        "precision": "BGE query encoder float32 from current embedder; stored document vectors remain frozen original float16-computed normalized float32. Reranker float16 MPS, max_length512",
        "limits": ["Previously observed, error-enriched regression cases; not an independent holdout or market accuracy estimate.",
                   "Brand-disjoint partitions reduce sharing but do not erase prior exposure.",
                   "Global relevance judgments are incomplete. Unjudged passages are not necessarily irrelevant.",
                   "Coverage audit has no supported positive proof or calibrated abstention threshold.",
                   "No training, cloud inference, chat activation or source/index mutation."],
        "files_sha256": {p.name: sha256_file(p) for p in bundle.glob("*.json")},
        "index_artifacts": index_manifest["artifacts"]}
    write(bundle / "protocol.json", protocol)
    print(json.dumps({"bundle": str(bundle), "counts": protocol["case_counts"], "brands": partition}), flush=True)


class Search:
    def __init__(self, index, reranker):
        self.index, self.reranker = index, reranker
        self.documents, self.vectors = index.documents, index.vectors
        self.allowed = np.arange(len(self.documents), dtype=np.int64)
        self.lexical = BM25.load(index.directory)

    def query(self, text, config):
        started = time.perf_counter()
        query = np.asarray(self.index.encoder(text), dtype=np.float32)
        if query.shape != (1024,) or not np.isfinite(query).all() or np.linalg.norm(query) < 1e-8:
            raise ValueError("Invalid BGE query vector")
        query /= np.linalg.norm(query)
        dense = rank_scores(self.vectors @ query, self.allowed, config["pool"])
        encoded_seconds = time.perf_counter() - started
        lexical = []
        if config["lexical_weight"]:
            scores = self.lexical.scores(text)
            lexical = [(i, s) for i, s in rank_scores(scores, self.allowed, config["pool"]) if s > 0]
        candidates = fuse(dense, lexical, config)
        retrieval_seconds = time.perf_counter() - started
        rerank_seconds = 0
        if config["rerank"]:
            pairs = [(text, self.documents[i]["text"]) for i, _ in candidates]
            encoded = self.reranker.tokenizer([p[0] for p in pairs], [p[1] for p in pairs], truncation=False, padding=False)
            if any(len(tokens) > 512 for tokens in encoded["input_ids"]):
                raise ValueError("A reranker pair would be truncated")
            rerank_started = time.perf_counter()
            predicted = np.asarray(self.reranker.predict(pairs, batch_size=16, show_progress_bar=False), dtype=np.float32).reshape(-1)
            if len(predicted) != len(candidates) or not np.isfinite(predicted).all():
                raise ValueError("Invalid reranker output")
            ranking = sorted([(i, float(score)) for (i, _), score in zip(candidates, predicted)], key=lambda p: (-p[1], p[0]))
            rerank_seconds = time.perf_counter() - rerank_started
        else:
            ranking = candidates
        return {"ranking": [{"id": self.documents[i]["id"], "object_id": self.documents[i]["object_id"],
                             "score": score} for i, score in ranking[:10]],
                "candidate_ids": [self.documents[i]["id"] for i, _ in candidates],
                "timing": {"total_seconds": time.perf_counter() - started, "dense_pipeline_seconds": encoded_seconds,
                           "retrieval_seconds": retrieval_seconds, "rerank_seconds": rerank_seconds}}


def aggregate(rows, annotations):
    by_id = {c["id"]: c for c in annotations}
    summary = []
    for config in CONFIGS:
        measured = [r for r in rows if r["config"] == config["id"]]
        first = [r for r in measured if r["repeat"] == 0]
        evaluated = [(r, metrics([p["id"] for p in r["ranking"]], by_id[r["question_id"]])) for r in first]
        values = {key: float(np.mean([m[key] for _, m in evaluated])) for key in
                  ["hit_at1", "recall_at10", "ndcg_at10", "all_groups_at10"]}
        latencies = [r["timing"]["total_seconds"] for r in measured]
        identical = all([p["id"] for p in r["ranking"]] ==
                        [p["id"] for p in next(s for s in first if s["question_id"] == r["question_id"])["ranking"]]
                        for r in measured)
        summary.append({"config": config["id"], "questions": len(first), **values,
                        "hit_at1_cases": sum(m["hit_at1"] for _, m in evaluated),
                        "complete_at10_cases": sum(m["all_groups_at10"] for _, m in evaluated),
                        "median_seconds": float(np.median(latencies)), "max_seconds": float(np.max(latencies)),
                        "identical_rankings_over_repeats": identical})
    return summary


def select_config(summary):
    return max(summary, key=lambda s: (s["all_groups_at10"], s["hit_at1"], s["ndcg_at10"], -s["median_seconds"]))


def run(bundle, output):
    if output.exists():
        raise FileExistsError("Preserve first execution")
    protocol = json.loads((bundle / "protocol.json").read_text())
    if protocol["configs"] != CONFIGS:
        raise ValueError("Candidate configurations changed after freeze")
    for filename, expected in protocol["files_sha256"].items():
        if sha256_file(bundle / filename) != expected:
            raise ValueError("Frozen annotations or questions changed")
    if sha256_file(INDEX / "index-manifest.json") != protocol["index_manifest_sha256"]:
        raise ValueError("Frozen index manifest changed")
    queries = json.loads((bundle / "queries.json").read_text())["cases"]
    output.mkdir(parents=True)
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1", EMBEDDER_DEVICE="mps")
    from sentence_transformers import CrossEncoder
    from bikefinder_rag.catalog.sql_rag_service import CatalogService
    from bikefinder_rag.embeddings.embedder import _get_model
    source = ROOT / "data/technical/enrichment-full-20261012/pass2/catalogue.enriched.sqlite3"
    source_before = sha256_file(source)
    began = time.perf_counter()
    service = CatalogService(source, ROOT / "data/technical/sql-rag-service-v2/catalog.sqlite3", index=INDEX)
    index = service.index
    index.encoder("Préparation générique de la recherche technique.")
    index_protocol = json.loads((INDEX / "protocol.json").read_text())
    reranker_path = Path(index_protocol["reranker_model"]["path"])
    if model_spec(reranker_path) != index_protocol["reranker_model"]:
        raise ValueError("Pinned reranker files changed")
    reranker = CrossEncoder(str(reranker_path), device="mps", max_length=512, local_files_only=True)
    reranker.model.half()
    reranker.predict([("Question technique générique", "Une fiche conserve son identité et ses sources.")], show_progress_bar=False)
    search = Search(index, reranker)
    metadata = {"created_utc": datetime.now(timezone.utc).isoformat(), "protocol_sha256": sha256_file(bundle / "protocol.json"),
                "script_sha256": sha256_file(__file__), "source_sha256": source_before,
                "preparation_seconds": time.perf_counter() - began, "document_count": len(index.documents),
                "remote_api_calls": 0, "model_training_steps": 0,
                "bge_device": str(_get_model().device), "bge_dtype": str(next(_get_model().parameters()).dtype),
                "reranker_dtype": str(next(reranker.model.parameters()).dtype), "oracle_scope_used": False,
                "baseline_parity": []}
    # Compare our reproduction with the current service on three generic probes,
    # without reference IDs and before any scored query.
    for text in ["Honda boîte de vitesses", "hauteur de selle réglable", "ABS shifter en option"]:
        original, _ = index.search(text, [d["id"] for d in index.documents], 10)
        reproduced = search.query(text, next(c for c in CONFIGS if c["id"] == "current_rrf40"))
        if [p["id"] for p in original] != [p["id"] for p in reproduced["ranking"]]:
            raise ValueError("Experimental baseline differs from current service")
        metadata["baseline_parity"].append({"query": text, "identical_top10": True})
    write(output / "metadata.json", metadata)
    all_rows = []
    try:
        for split in ["dev", "check"]:
            group = [q for q in queries if q["split"] == split]
            for repeat in range(protocol["repeats"]):
                for q in group:
                    configs = list(CONFIGS)
                    random.Random(f"{protocol['seed']}:{q['id']}:{repeat}").shuffle(configs)
                    for config in configs:
                        receipt = search.query(q["question"], config)
                        row = {"question_id": q["id"], "split": split, "repeat": repeat, "config": config["id"], **receipt}
                        all_rows.append(row)
                        with (output / "rankings.jsonl").open("a") as stream:
                            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
                    print(json.dumps({"split": split, "repeat": repeat, "case": q["id"]}), flush=True)
            annotations = json.loads((bundle / f"{split}.annotations.json").read_text())["cases"]
            summary = aggregate([r for r in all_rows if r["split"] == split], annotations)
            write(output / f"{split}.summary.json", summary)
            if split == "dev":
                chosen = select_config(summary)
                write(output / "selection.json", {"chosen_config": chosen["config"], "development_score": chosen,
                     "rule": protocol["selection_rule"], "verification_annotations_opened": False,
                     "protocol_sha256": sha256_file(bundle / "protocol.json")})
                print(json.dumps({"selected_on_dev": chosen["config"], "summary": summary}), flush=True)
            else:
                print(json.dumps({"verification_summary": summary}), flush=True)
        audit = []
        for q in [q for q in queries if q["split"] == "coverage_audit"]:
            for cid in ["current_rrf40", chosen["config"]]:
                if any(r["question_id"] == q["id"] and r["config"] == cid for r in audit):
                    continue
                result = search.query(q["question"], next(c for c in CONFIGS if c["id"] == cid))
                audit.append({"question_id": q["id"], "config": cid, "positive_evidence_available": False,
                              "retrieval_is_not_abstention": True, **result})
        write(output / "coverage-audit.json", audit)
        metadata.update(source_unchanged=sha256_file(source) == source_before,
                        index_manifest_unchanged=sha256_file(INDEX / "index-manifest.json") == protocol["index_manifest_sha256"],
                        status="completed_no_training_no_activation", total_seconds=time.perf_counter() - began)
        if not metadata["source_unchanged"] or not metadata["index_manifest_unchanged"]:
            raise ValueError("Source or index manifest mutated")
        write(output / "metadata.json", metadata)
    finally:
        service.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["prepare", "run"])
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    if args.mode == "prepare":
        prepare(args.bundle)
    else:
        run(args.bundle, args.out)
