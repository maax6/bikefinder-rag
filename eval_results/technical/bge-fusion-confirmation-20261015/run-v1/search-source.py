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
PRESERVING_CONFIGS = [
    CONFIGS[1], CONFIGS[3],
    {"id": "current_top10_rerank", "pool": 40, "dense_weight": 1, "lexical_weight": 1, "rerank": True, "rerank_top": 10},
    {"id": "weighted80_top10_rerank", "pool": 80, "dense_weight": 2, "lexical_weight": 1, "rerank": True, "rerank_top": 10},
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


def prepare_preserving(bundle, previous):
    """Freeze a follow-up hypothesis with new source-authored verification queries."""
    if bundle.exists():
        raise FileExistsError("Preserve the first follow-up bundle")
    docs = {d["id"]: d for d in (json.loads(line) for line in (INDEX / "documents.jsonl").read_text().splitlines())}
    # Authored from source texts only, before any retrieval on these questions.
    specifications = [
        ("N01", "La Benelli TRK 702 de 2024 fait-elle exactement 702 cm³, et quel volume de réservoir sa fiche annonce-t-elle ?",
         ["82de97d8bd7c06a4:section:4", "82de97d8bd7c06a4:section:0"],
         ["698 cc ; réservoir 20 litres."], []),
        ("N02", "Pour la Benelli TRK 702 de 2024, quels coloris sont écrits et la liste des équipements cite-t-elle une prise pour charger par USB ?",
         ["82de97d8bd7c06a4:section:9", "82de97d8bd7c06a4:section:5"],
         ["Blanc, vert, gris ; Prise USB citée."], []),
        ("N03", "Norden 901 et Norden 901 Expedition, toutes deux Husqvarna de 2024 : compare leurs plages de hauteur de selle et leurs masses à sec, sans mélanger avec les masses pleins faits.",
         ["21606eee41941d98:section:0", "d265440b3c2379f5:section:0"],
         ["Norden : 859–879 mm et 204 kg à sec ; Expedition : 875–895 mm et 214,50 kg à sec."],
         ["Conserver la base à sec ; la masse tous pleins de la Norden ne remplace pas celle de l'Expedition."]),
        ("N04", "Sur la Husqvarna Norden 901 Expedition 2024, le shifter est-il de série ou en option et la fiche cite-t-elle une selle et des poignées chauffantes ?",
         ["d265440b3c2379f5:section:2", "d265440b3c2379f5:section:5"],
         ["Shifter de série ; selle chauffante et poignées chauffantes citées."], []),
        ("N05", "MV-Agusta 800 Brutale RR 2024 : donne le couple avec son régime et la hauteur de selle. Pour la masse, la fiche fournit-elle le poids à sec et celui tous pleins faits ?",
         ["7d541ca9f7fcb48a:section:4", "7d541ca9f7fcb48a:section:0"],
         ["8,87 mkg à 10 250 tr/min ; selle 830 mm ; masse à sec 175 kg."],
         ["La masse tous pleins faits n'est pas fournie dans le châssis conservé ; ne pas la calculer à partir du poids à sec."]),
        ("N06", "Compare seulement les puissances et leurs régimes des MV-Agusta 1000 Brutale RR et 800 Brutale R de 2024. Je veux bien la R pour la 800, pas la RR.",
         ["6227564fdba62dba:section:4", "9c06a50dd48f827e:section:4"],
         ["1000 RR : 208 ch à 13 000 tr/min ; 800 R : 112 ch à 11 000 tr/min."],
         ["La 800 RR est une autre variante ; sa puissance ne remplace pas celle de la 800 R."]),
        ("N07", "Sur l'Indian 1133 Scout Bobber de 2024, la transmission secondaire est-elle par chaîne ou courroie et quels coloris sont listés ?",
         ["ea8331c72ff1d845:section:2", "ea8331c72ff1d845:section:9"],
         ["Secondaire par courroie ; beige, rouge, bleu, vert, noir."], []),
        ("N08", "Entre l'Indian 1133 Scout et la 1133 Scout Bobber de 2024, les fiches donnent-elles les mêmes longueur et largeur ? Compare ces dimensions, sans prendre la Bobber Twenty.",
         ["330083be410a87e9:section:0", "ea8331c72ff1d845:section:0"],
         ["Scout : 2 324 mm de longueur et 916 mm de largeur ; Bobber : 2 274 mm et 926 mm."],
         ["Conserver chaque identité ; Bobber Twenty est une autre fiche."]),
    ]
    fresh = []
    for qid, question, proof_ids, facts, limits in specifications:
        positives = [deepcopy(docs[pid]) | {"grade": 2} for pid in proof_ids]
        identities = {p["object_id"]: {k: p[k] for k in ["object_id", "brand", "model", "year", "source_url", "source_sha256"]} for p in positives}
        if any(p["year"] != 2024 for p in positives):
            raise ValueError("Fresh source year differs")
        fresh.append({"id": qid, "split": "check", "question": question,
            "answerability": "partial" if qid == "N05" else "answerable", "category": "new_multi_evidence_source_question",
            "supplied_scope_object_ids": list(identities), "expected_identities": list(identities.values()),
            "positive_evidence": positives, "gold_passages": [{"id": pid, "grade": 2} for pid in proof_ids],
            "required_groups": [[pid] for pid in proof_ids], "expected_facts": facts, "expected_limits": limits,
            "judgements_complete_global": False,
            "annotation": {"author": "Same assistant, source-only before first retrieval; not independently authored",
                           "first_retrieval_not_yet_run": True, "new_question_formulation": True},
            "confusable_passages": []})
    development = json.loads((previous / "dev.annotations.json").read_text())["cases"]
    audit = json.loads((previous / "coverage_audit.annotations.json").read_text())["cases"]
    protocol = deepcopy(json.loads((previous / "protocol.json").read_text()))
    bundle.mkdir(parents=True)
    for name, cases in [("dev", development), ("check", fresh), ("coverage_audit", audit)]:
        write(bundle / f"{name}.annotations.json", {"cases": cases})
    write(bundle / "queries.json", {"cases": [{k: c[k] for k in ["id", "split", "question"]} for c in development + fresh + audit]})
    protocol.update(created_utc=datetime.now(timezone.utc).isoformat(), configs=PRESERVING_CONFIGS,
        baseline_bundle_sha256=sha256_file(previous / "protocol.json"),
        hypothesis="Rerank only the ten passages already retained by each parent retrieval; preserve their entire proof set while improving order.",
        brands=brand_partition(development + fresh), case_counts={"dev": 11, "check": 8, "coverage_audit": 4},
        verification_origin="Eight source-authored new formulations, four brands absent from development; same author, eight distinct fiches with reuse across questions, no independent panel.",
        verification_unique_fiches=len({p["object_id"] for c in fresh for p in c["positive_evidence"]}),
        selection_constraint="Verification labels are interpreted for scoring only after selection.json is saved; their fingerprints are checked beforehand.",
        previous_experiment="v1 wide reranking improved first hit but reduced verification completeness. v1 is preserved and not re-scored.",
        limits=["Development questions were already observed; follow-up hypothesis follows v1 verification failure.",
                "New verification questions were source-authored and frozen before their first retrieval, but not independently authored.",
                "Several verification questions share fiches; eight questions do not mean eight independent motorcycles.",
                "Global judgments are incomplete; unjudged passages are not automatically irrelevant.",
                "No training, cloud inference, chat activation or source/index mutation."],
        files_sha256={p.name: sha256_file(p) for p in bundle.glob("*.json")})
    write(bundle / "protocol.json", protocol)
    print(json.dumps({"prepared_followup": str(bundle), "counts": protocol["case_counts"], "brands": protocol["brands"]}), flush=True)


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
        retrieval_candidates = list(candidates)
        retrieval_seconds = time.perf_counter() - started
        rerank_seconds = 0
        if config["rerank"]:
            candidates = candidates[:config.get("rerank_top", config["pool"])]
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
                "retrieval_candidate_ids": [self.documents[i]["id"] for i, _ in retrieval_candidates],
                "timing": {"total_seconds": time.perf_counter() - started, "dense_pipeline_seconds": encoded_seconds,
                           "retrieval_seconds": retrieval_seconds, "rerank_seconds": rerank_seconds}}


def aggregate(rows, annotations, configurations=CONFIGS):
    by_id = {c["id"]: c for c in annotations}
    summary = []
    for config in configurations:
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
    configurations = protocol["configs"]
    if configurations != CONFIGS and configurations != PRESERVING_CONFIGS:
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
                    configs = list(configurations)
                    random.Random(f"{protocol['seed']}:{q['id']}:{repeat}").shuffle(configs)
                    for config in configs:
                        receipt = search.query(q["question"], config)
                        row = {"question_id": q["id"], "split": split, "repeat": repeat, "config": config["id"], **receipt}
                        all_rows.append(row)
                        with (output / "rankings.jsonl").open("a") as stream:
                            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
                    print(json.dumps({"split": split, "repeat": repeat, "case": q["id"]}), flush=True)
            annotations = json.loads((bundle / f"{split}.annotations.json").read_text())["cases"]
            summary = aggregate([r for r in all_rows if r["split"] == split], annotations, configurations)
            write(output / f"{split}.summary.json", summary)
            if split == "dev":
                chosen = select_config(summary)
                write(output / "selection.json", {"chosen_config": chosen["config"], "development_score": chosen,
                     "rule": protocol["selection_rule"], "verification_labels_used_for_selection": False,
                     "protocol_sha256": sha256_file(bundle / "protocol.json")})
                print(json.dumps({"selected_on_dev": chosen["config"], "summary": summary}), flush=True)
            else:
                print(json.dumps({"verification_summary": summary}), flush=True)
        audit = []
        for q in [q for q in queries if q["split"] == "coverage_audit"]:
            for cid in ["current_rrf40", chosen["config"]]:
                if any(r["question_id"] == q["id"] and r["config"] == cid for r in audit):
                    continue
                result = search.query(q["question"], next(c for c in configurations if c["id"] == cid))
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
    parser.add_argument("mode", choices=["prepare", "prepare-preserving", "run"])
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--previous-bundle", type=Path)
    args = parser.parse_args()
    if args.mode == "prepare":
        prepare(args.bundle)
    elif args.mode == "prepare-preserving":
        prepare_preserving(args.bundle, args.previous_bundle)
    else:
        run(args.bundle, args.out)
