"""Freeze and run a larger, source-authored confirmation of BGE fusion 2:1/80.

This is a paired offline retrieval evaluation, not a chat/model benchmark.
No tuning, external inference, index changes, or automatic production edits.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import random
import re
import shutil
import time

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "data/technical/retrieval-benchmark-20261013/index"
PREVIOUS = ROOT / "eval_results/technical/bge-retrieval-improvements-20261015"
CONFIGS = [
    dict(id="current_rrf40", pool=40, dense_weight=1, lexical_weight=1, rerank=False),
    dict(id="weighted_rrf80", pool=80, dense_weight=2, lexical_weight=1, rerank=False),
]
BRANDS = ["Yamaha", "Kawasaki", "Honda", "Suzuki", "BMW", "Triumph", "Ducati",
          "Harley-Davidson", "KTM", "Aprilia", "MV-Agusta", "Moto-Guzzi", "Indian",
          "Benelli", "Mash", "Bimota", "Morini", "Royal-Enfield", "Victory (USA)",
          "Norton", "Cagiva", "CFMOTO", "Zero Motorcycles", "Buell"]

# Each selector identifies a verbatim fact, not a fabricated numerical answer.
FIELDS = {
    "seat": ("Châssis", r"Hauteur de selle"),
    "tank": ("Châssis", r"Réservoir\s*:.*\d"),
    "mass": ("Châssis", r"Poids (?:à sec|tous pleins faits)\s*:.*\d"),
    "length": ("Châssis", r"Longueur\s*:.*\d"),
    "power": ("Moteur", r"\b\d[\d ,]*(?:ch|kW)\b"),
    "torque": ("Moteur", r"\b\d[\d ,]*(?:mkg|Nm)\b"),
    "displacement": ("Moteur", r"\b\d[\d ,]* cc\b"),
    "cooling": ("Moteur", r"Refroidissement\s*:\s*\w"),
    "secondary": ("Transmission", r"secondaire"),
    "gearbox": ("Transmission", r"Boîte.*\d.*rapports"),
    "front_brake": ("Train avant", r"Frein"),
    "front_suspension": ("Train avant", r"Fourche|Suspension"),
    "rear_brake": ("Train arrière", r"Frein"),
    "rear_suspension": ("Train arrière", r"[Aa]mortisseur|Suspension"),
    "colours": ("Coloris", r"Coloris\s*:\s*\w"),
    "abs": ("Équipement de série", r"\bABS\b"),
}
SINGLE = [
    (["seat", "tank"], "Sur {a}, quelle hauteur de selle et quelle contenance de réservoir sont annoncées ?"),
    (["power", "torque"], "{a} : peux-tu relever puissance et couple avec leurs unités et les régimes indiqués ?"),
    (["secondary", "gearbox"], "Pour {a}, combien de rapports comporte la boîte et comment la roue arrière est-elle entraînée ?"),
    (["front_brake", "front_suspension"], "Quel frein et quel type de fourche trouve-t-on à l'avant de {a}, selon sa fiche ?"),
    (["rear_brake", "rear_suspension"], "Je cherche le frein et la suspension arrière de {a}. Que donne la fiche ?"),
    (["colours"], "Quelles teintes sont proposées sur la fiche de {a} ? Garde ce millésime précis."),
    (["displacement", "cooling"], "Pour {a}, relève la cylindrée réelle et le mode de refroidissement du moteur."),
    (["seat", "mass"], "{a} : donne la hauteur de selle et les masses documentées, en précisant à sec ou tous pleins faits."),
]
MULTI = [
    (["displacement", "tank"], "{a} : le nom commercial ne suffit pas, je veux la cylindrée en cc et la capacité du réservoir."),
    (["power", "mass"], "Pour {a}, relève la puissance et les poids disponibles avec leur type. Ne calcule pas de rapport poids/puissance."),
    (["secondary", "colours"], "Sur {a}, quelle transmission finale est indiquée et quelles couleurs sont listées ?"),
    (["front_brake", "rear_brake"], "Décris les freins avant et arrière de {a}, avec leurs dimensions lorsqu'elles sont présentes."),
    (["seat", "torque"], "Pour {a}, je voudrais la hauteur de selle ainsi que le couple moteur et son régime s'il est renseigné."),
    (["cooling", "secondary"], "{a} : quel refroidissement moteur et quel entraînement secondaire sont décrits ?"),
    (["tank", "colours"], "Combien de litres contient le réservoir de {a} et dans quels coloris cette fiche la présente-t-elle ?"),
    (["gearbox", "front_suspension"], "{a} : indique le nombre de rapports et la suspension avant avec son débattement s'il est écrit."),
]


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def facts(fiche, fields):
    result = []
    for field in fields:
        section, pattern = FIELDS[field]
        candidates = [d for d in fiche if d["section"] == section]
        if len(candidates) != 1:
            return None
        doc = candidates[0]
        excerpts = [s.strip() for s in doc["original_text"].split(";") if re.search(pattern, s, re.I)]
        if not excerpts:
            return None
        result.append(dict(field=field, passage_id=doc["id"], quotes=excerpts))
    return result


def identity(fiche):
    d = fiche[0]
    return f"{d['brand']} {d['model']} ({d['year']})"


def historical():
    """Inventory prior question/annotation files, not retrieval rankings."""
    files, identities, questions = [], set(), set()
    def visit(value):
        if isinstance(value, dict):
            if isinstance(value.get("question"), str):
                questions.add(value["question"].strip().casefold())
            for key, child in value.items():
                if key in {"supplied_scope_object_ids", "object_ids"} and isinstance(child, list):
                    identities.update(i for i in child if isinstance(i, str))
                if key == "object_id" and isinstance(child, str):
                    identities.add(child)
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
    for path in sorted((ROOT / "eval_results/technical").rglob("*.json")):
        if "bge-fusion-confirmation-20261015" in path.parts:
            continue
        if "question" in path.name or "annotations" in path.name:
            files.append(dict(path=str(path.relative_to(ROOT)), sha256=sha(path)))
            visit(json.loads(path.read_text()))
    return files, identities, questions


def make_case(qid, question, fiche_groups, fields, category):
    evidence, expected = {}, []
    for fiche in fiche_groups:
        selected = facts(fiche, fields)
        if not selected:
            raise ValueError("Question has no source fact")
        lookup = {d["id"]: d for d in fiche}
        for fact in selected:
            evidence[fact["passage_id"]] = lookup[fact["passage_id"]]
            expected.append({"identity": identity(fiche), **fact})
    unknowns = [q for fact in expected for q in fact["quotes"] if re.search(r"non défini|\bnc\b", q, re.I)]
    limits = ["Exact model/year required; source label and units retained; unknown is not absent."]
    if unknowns:
        limits.append("Missing source values must stay unknown: " + " ; ".join(unknowns))
    if any("≈" in q for fact in expected for q in fact["quotes"]):
        limits.append("Approximate source value; retain its approximation marker.")
    if any("nominale" in q for fact in expected for q in fact["quotes"]):
        limits.append("Retain nominal/maximum/other power labels separately; source consistency not verified and units not reconciled.")
    return dict(id=qid, split="fresh", question=question, category=category,
                answerability="partial" if unknowns else "answerable", required_groups=[[pid] for pid in evidence],
                gold_passages=[dict(id=pid, grade=2) for pid in evidence],
                positive_evidence=list(evidence.values()), expected_facts=expected,
                expected_limits=limits,
                supplied_scope_object_ids=[f[0]["object_id"] for f in fiche_groups],
                expected_identities=[{k: f[0][k] for k in ["object_id", "brand", "model", "year", "source_url", "source_sha256"]} for f in fiche_groups],
                judgements_complete_global=False,
                annotation={"author": "Assistant source-authored templates; source review before retrieval, no independent human panel",
                            "training_ready": False, "novelty": "New formulation and target IDs absent from inventoried prior question/annotation files"})


def prepare(bundle):
    if bundle.exists():
        raise FileExistsError("Preserve frozen bundle")
    inventory, excluded, old_questions = historical()
    docs = [json.loads(line) for line in (INDEX / "documents.jsonl").open()]
    fiches = defaultdict(list)
    for d in docs:
        fiches[d["object_id"]].append(d)
    used, cases = set(excluded), []
    source_seed = "bge-confirmation-20261015-v1"
    def order(items, salt):
        return sorted(items, key=lambda f: hashlib.sha256(f"{source_seed}:{salt}:{f[0]['object_id']}".encode()).hexdigest())
    def candidates(brand, fields):
        return [f for oid, f in fiches.items() if oid not in used and f[0]["brand"] == brand
                and 2000 <= f[0]["year"] <= 2026 and facts(f, fields)]
    for n in range(48):
        fields, template = (SINGLE if n < 16 else MULTI)[n % 8]
        brand = BRANDS[n % len(BRANDS)]
        if brand == "Zero Motorcycles":
            # Electric fiches do not have a fuel tank; use documented power/mass.
            fields, template = MULTI[1]
        eligible = order(candidates(brand, fields), str(n))
        # Prefer a predeclared year stratum, with a visible fallback for sparse brands.
        lo, hi = [(2000, 2010), (2011, 2020), (2021, 2026)][(n // 8) % 3]
        stratum = [f for f in eligible if lo <= f[0]["year"] <= hi]
        if not eligible:
            raise ValueError(f"No source for {brand} / {fields}")
        fiche = (stratum or eligible)[0]
        used.add(fiche[0]["object_id"])
        case = make_case(f"F{n+1:03}", template.format(a=identity(fiche)), [fiche], fields,
                         "single_section" if n < 16 else "multiple_sections")
        case["sampling"] = dict(brand=brand, preferred_year_range=[lo, hi], year_stratum_fallback=not bool(stratum))
        cases.append(case)
    # Eight same-model year comparisons; eight same-year nearby-name comparisons.
    for n in range(16):
        brand = BRANDS[n]
        fields = ["seat", "tank"] if n % 2 == 0 else ["power", "secondary"]
        eligible = order(candidates(brand, fields), f"pair{n}")
        selected = None
        for a in eligible:
            for b in eligible:
                if a is b:
                    continue
                x, y = a[0], b[0]
                if n < 8:
                    ok = x["model"] == y["model"] and 1 <= abs(x["year"] - y["year"]) <= 3
                else:
                    tokens_a = set(re.findall(r"\w+", x["model"].lower()))
                    tokens_b = set(re.findall(r"\w+", y["model"].lower()))
                    ok = x["year"] == y["year"] and x["model"] != y["model"] and len(tokens_a & tokens_b) >= 2
                if ok:
                    selected = [a, b]
                    break
            if selected:
                break
        if not selected:
            raise ValueError(f"No comparison pair for {brand}")
        used.update(f[0]["object_id"] for f in selected)
        subject = "hauteurs de selle et capacités de réservoir" if n % 2 == 0 else "puissances et transmissions secondaires"
        question = f"Compare {identity(selected[0])} et {identity(selected[1])} : leurs {subject} sont-elles identiques ? Sépare les deux fiches."
        cases.append(make_case(f"F{49+n:03}", question, selected, fields,
                               "year_comparison" if n < 8 else "nearby_model_comparison"))
    if any(c["question"].strip().casefold() in old_questions for c in cases):
        raise ValueError("Previously asked question")
    if len({c["question"] for c in cases}) != 64 or len({i for c in cases for i in c["supplied_scope_object_ids"]}) != 80:
        raise ValueError("Expected 64 distinct questions on 80 non-reused fiches")
    regression = []
    for part in ["bundle/dev.annotations.json", "bundle/check.annotations.json", "bundle-v2/check.annotations.json"]:
        for c in json.loads((PREVIOUS / part).read_text())["cases"]:
            regression.append(deepcopy(c) | {"split": "regression"})
    bundle.mkdir(parents=True)
    write(bundle / "fresh.annotations.json", {"cases": cases})
    write(bundle / "regression.annotations.json", {"cases": regression})
    write(bundle / "queries.json", {"cases": [{k: c[k] for k in ["id", "split", "question"]} for c in cases + regression]})
    write(bundle / "novelty-audit.json", {"files": inventory, "prior_target_ids_excluded": sorted(excluded),
          "fresh_target_ids": sorted({i for c in cases for i in c["supplied_scope_object_ids"]}),
          "target_overlap": [], "exact_question_overlap": [],
          "limit": "File-based novelty, not a claim of unseen model families or unpublished real user questions."})
    protocol = dict(created_utc=datetime.now(timezone.utc).isoformat(), status="frozen_before_first_retrieval",
          configs=CONFIGS, k=10, rrf_constant=60, repeats=3, shuffle_seed=20261015,
          cohort_counts={"fresh": len(cases), "regression": len(regression)}, fiches=80,
          brand_counts=dict(Counter(p["brand"] for c in cases for p in c["expected_identities"])),
          years=dict(sorted(Counter(p["year"] for c in cases for p in c["expected_identities"]).items())),
          categories=dict(Counter(c["category"] for c in cases)),
          selection="Candidate fixed from previous run-v2; no development/tuning on this new lot.",
          promotion_rule={"fresh_complete_gain_minimum": 5, "required_group_losses_any_case": 0,
                          "hit_at1_count_must_not_decline_in_either_cohort": True,
                          "one_sided_paired_exact_p_maximum": 0.05,
                          "max_median_latency": "max(baseline * 1.25, baseline + 0.010 seconds)",
                          "integrity_parity_and_determinism_required": True},
          model_inputs="Question text only, global 105687 passages, no oracle IDs/labels/answers.",
          limits=["Stratified, template-based assistant-authored questions, not an independent human evaluation.",
                  "Target fiches are disjoint within the new lot and from inventoried previous questions; families can recur.",
                  "Partial relevance annotations; exact source passage coverage is not final answer accuracy.",
                  "Known evidence includes explicit unknown markers; retrieving these markers does not establish an unknown fact. No abstention, scope resolution, multi-turn or chat generation measurement.",
                  "Three latency repetitions do not create additional independent questions.",
                  "Paired exact p-value is descriptive: same-brand/family questions can remain correlated."],
          index_manifest_sha256=sha(INDEX / "index-manifest.json"),
          files_sha256={p.name: sha(p) for p in bundle.glob("*.json")})
    write(bundle / "protocol.json", protocol)
    lines = ["# 64 questions inédites annotées — confirmation BGE-M3", "", "Questions construites depuis les sources avant toute recherche. Même assistant pour les gabarits et les annotations ; pas de panel indépendant. 80 fiches distinctes, sans réutilisation entre questions. Les références ne sont pas fournies au moteur.", ""]
    for c in cases:
        lines += [f"## {c['id']} — {c['category']}", "", c["question"], ""]
        for d in c["positive_evidence"]:
            lines += [f"- **{d['brand']} {d['model']} {d['year']} / {d['section']}** — [{d['id']}]({d['source_url']})", f"  - Source SHA-256 : `{d['source_sha256']}`", f"  - Texte : {d['original_text']}"]
        lines += ["", "Faits à retrouver :"]
        for f in c["expected_facts"]:
            lines.append(f"- {f['identity']} — {' ; '.join(f['quotes'])}")
        lines += [""]
    (bundle / "questions-annotees.md").write_text("\n".join(lines))
    # Include the readable annotation file in the frozen artifact set as well.
    protocol["files_sha256"]["questions-annotees.md"] = sha(bundle / "questions-annotees.md")
    write(bundle / "protocol.json", protocol)
    print(json.dumps({k: protocol[k] for k in ["cohort_counts", "fiches", "brand_counts", "years", "categories"]}, ensure_ascii=False))


def paired_analysis(cases, rankings):
    from benchmark_technical_retrieval import metrics
    details = []
    for c in cases:
        ids = {key: [p["id"] for p in rankings[(c["id"], key)]["ranking"]] for key in ["current_rrf40", "weighted_rrf80"]}
        before, after = (metrics(ids[key], c) for key in ["current_rrf40", "weighted_rrf80"])
        lost = [g for g in c["required_groups"] if set(g) & set(ids["current_rrf40"]) and not set(g) & set(ids["weighted_rrf80"])]
        gained = [g for g in c["required_groups"] if set(g) & set(ids["weighted_rrf80"]) and not set(g) & set(ids["current_rrf40"])]
        details.append(dict(id=c["id"], question=c["question"], category=c.get("category"),
                            baseline=before, candidate=after, lost_required_groups=lost, gained_required_groups=gained,
                            baseline_ids=ids["current_rrf40"], candidate_ids=ids["weighted_rrf80"]))
    wins = sum(d["candidate"]["all_groups_at10"] > d["baseline"]["all_groups_at10"] for d in details)
    losses = sum(d["candidate"]["all_groups_at10"] < d["baseline"]["all_groups_at10"] for d in details)
    discordant = wins + losses
    p = sum(math.comb(discordant, i) for i in range(wins, discordant + 1)) / 2**discordant if discordant else 1.0
    return dict(complete_wins=wins, complete_losses=losses, net_complete_gain=wins-losses,
                cases_with_lost_required_groups=[d["id"] for d in details if d["lost_required_groups"]],
                first_hit_wins=sum(d["candidate"]["hit_at1"] > d["baseline"]["hit_at1"] for d in details),
                first_hit_losses=sum(d["candidate"]["hit_at1"] < d["baseline"]["hit_at1"] for d in details),
                one_sided_paired_exact_p=p, details=details)


def promotion(paired, summaries, integrity):
    checks = {
        "fresh_complete_gain_at_least_five": paired["fresh"]["net_complete_gain"] >= 5,
        "no_required_group_loss": all(not s["cases_with_lost_required_groups"] for s in paired.values()),
        "no_first_hit_count_decline": all(s["first_hit_wins"] >= s["first_hit_losses"] for s in paired.values()),
        "paired_p_at_most_005": paired["fresh"]["one_sided_paired_exact_p"] <= .05,
        "latency_within_bound": all(s[1]["median_seconds"] <= max(s[0]["median_seconds"] * 1.25, s[0]["median_seconds"] + .010) for s in summaries.values()),
        "integrity_parity_and_determinism": all(integrity.values()),
    }
    return dict(eligible_for_chat_integration=all(checks.values()), checks=checks,
                failed_checks=[k for k, passed in checks.items() if not passed])


def run(bundle, output):
    if output.exists():
        raise FileExistsError("Preserve first confirmation run")
    protocol = json.loads((bundle / "protocol.json").read_text())
    if protocol["configs"] != CONFIGS or protocol["k"] != 10:
        raise ValueError("Frozen candidate differs")
    for name, expected in protocol["files_sha256"].items():
        if sha(bundle / name) != expected:
            raise ValueError("Questions or annotations changed after freeze")
    if sha(INDEX / "index-manifest.json") != protocol["index_manifest_sha256"]:
        raise ValueError("Frozen index manifest changed")
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1", EMBEDDER_DEVICE="mps")
    from improve_bge_retrieval import Search, aggregate
    from benchmark_technical_retrieval import model_spec
    from bikefinder_rag.catalog.sql_rag_service import CatalogService
    from bikefinder_rag.embeddings.embedder import _get_model
    source = ROOT / "data/technical/enrichment-full-20261012/pass2/catalogue.enriched.sqlite3"
    source_hash = sha(source)
    index_protocol = json.loads((INDEX / "protocol.json").read_text())
    if model_spec(Path(index_protocol["dense_model"]["path"])) != index_protocol["dense_model"]:
        raise ValueError("Pinned BGE files changed")
    output.mkdir(parents=True)
    shutil.copyfile(__file__, output / "runner-source.py")
    shutil.copyfile(ROOT / "scripts/improve_bge_retrieval.py", output / "search-source.py")
    shutil.copyfile(ROOT / "scripts/benchmark_technical_retrieval.py", output / "metrics-source.py")
    started = time.perf_counter()
    service = CatalogService(source, ROOT / "data/technical/sql-rag-service-v2/catalog.sqlite3", index=INDEX)
    index = service.index
    search = Search(index, None)
    metadata = dict(created_utc=datetime.now(timezone.utc).isoformat(), protocol_sha256=sha(bundle / "protocol.json"),
                    runner_sha256=sha(__file__), search_source_sha256=sha(ROOT / "scripts/improve_bge_retrieval.py"),
                    metrics_source_sha256=sha(ROOT / "scripts/benchmark_technical_retrieval.py"),
                    document_count=len(index.documents), source_sha256=source_hash,
                    remote_api_calls=0, model_training_steps=0, oracle_scope_used=False, baseline_parity=[])
    all_rows = []
    try:
        index.encoder("Préparation générique de la recherche technique.")
        metadata.update(device=str(_get_model().device), dtype=str(next(_get_model().parameters()).dtype),
                        preparation_seconds=time.perf_counter()-started)
        for question in ["Honda boîte de vitesses", "hauteur de selle réglable", "ABS shifter en option"]:
            actual, _ = index.search(question, [d["id"] for d in index.documents], 10)
            experimental = search.query(question, CONFIGS[0])
            equal = [d["id"] for d in actual] == [d["id"] for d in experimental["ranking"]]
            if not equal:
                raise ValueError("Current-service baseline mismatch")
            metadata["baseline_parity"].append(dict(query=question, identical_top10=equal))
        write(output / "metadata.json", metadata)
        queries = json.loads((bundle / "queries.json").read_text())["cases"]
        # Run all rankings before opening scoring annotations. No feedback loop.
        for repeat in range(protocol["repeats"]):
            shuffled = list(queries)
            random.Random(f"{protocol['shuffle_seed']}:{repeat}").shuffle(shuffled)
            for n, q in enumerate(shuffled):
                configurations = list(CONFIGS)
                random.Random(f"{protocol['shuffle_seed']}:{repeat}:{q['id']}").shuffle(configurations)
                for config in configurations:
                    row = dict(question_id=q["id"], split=q["split"], repeat=repeat, config=config["id"], **search.query(q["question"], config))
                    all_rows.append(row)
                    with (output / "rankings.jsonl").open("a") as stream:
                        stream.write(json.dumps(row, ensure_ascii=False) + "\n")
                if n % 16 == 0:
                    print(json.dumps(dict(repeat=repeat, completed_questions=n+1, total=len(queries))), flush=True)
        paired, summaries = {}, {}
        first = {(r["question_id"], r["config"]): r for r in all_rows if r["repeat"] == 0}
        for split in ["fresh", "regression"]:
            cases = json.loads((bundle / f"{split}.annotations.json").read_text())["cases"]
            paired[split] = paired_analysis(cases, first)
            summaries[split] = aggregate([r for r in all_rows if r["split"] == split], cases, CONFIGS)
            write(output / f"{split}.paired.json", paired[split])
            write(output / f"{split}.summary.json", summaries[split])
        manifest = json.loads((INDEX / "index-manifest.json").read_text())
        integrity = dict(source_unchanged=sha(source)==source_hash,
                         index_unchanged=all(sha(INDEX / name)==spec["sha256"] for name, spec in manifest["artifacts"].items()),
                         bge_files_unchanged=model_spec(Path(index_protocol["dense_model"]["path"]))==index_protocol["dense_model"],
                         frozen_inputs_unchanged=all(sha(bundle / name)==value for name, value in protocol["files_sha256"].items()),
                         baseline_parity=all(p["identical_top10"] for p in metadata["baseline_parity"]),
                         identical_repetitions=all(s["identical_rankings_over_repeats"] for cohort in summaries.values() for s in cohort))
        decision = promotion(paired, summaries, integrity)
        write(output / "integrity.json", integrity)
        write(output / "decision.json", decision)
        metadata.update(completed_utc=datetime.now(timezone.utc).isoformat(), total_seconds=time.perf_counter()-started,
                        status="completed_no_runtime_change", retrieval_calls=len(all_rows))
        write(output / "metadata.json", metadata)
        print(json.dumps(dict(summaries=summaries, decision=decision), ensure_ascii=False), flush=True)
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
    elif args.out is None:
        parser.error("run requires --out")
    else:
        run(args.bundle, args.out)
