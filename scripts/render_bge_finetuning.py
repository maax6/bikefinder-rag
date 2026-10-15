#!/usr/bin/env python3
"""Build the offline fine-tuning appendix from the frozen, observed pilot.

No inference, training or network access. Refuse mismatched receipts or metrics.
"""
import argparse
import hashlib
import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "eval_results/technical/bge-lora-pilot-20261015"
DOCUMENTS = ROOT / "data/technical/retrieval-benchmark-20261013/index/documents.jsonl"
TEMPLATE = Path(__file__).with_name("templates") / "bge_finetuning.html"


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def read(root, name):
    return json.loads((root / name).read_text())


def require(condition, message):
    if not condition:
        raise ValueError(message)


def build_data(root, documents):
    protocol = read(root, "bundle/protocol.json")
    train = read(root, "train-v1/result.json")
    index = read(root, "index-manifest.json")
    evaluation = read(root, "evaluation-v1/summary.json")
    summary = read(root, "summary.json")
    annotation = read(root, "annotation-audit.json")
    provenance_names = ["bundle/protocol.json", "train-v1/result.json", "index-manifest.json",
                        "evaluation-v1/summary.json", "evaluation-v1/rankings.jsonl",
                        "evaluation-v1/paired.json", "annotation-audit.json",
                        "final-integrity-audit.json", "summary.json"]
    protocol_hash = digest(root / "bundle/protocol.json")
    require(all(receipt["protocol_sha256"] == protocol_hash for receipt in [train, index, evaluation]),
            "Protocol binding mismatch")
    require(index["training_result_sha256"] == digest(root / "train-v1/result.json"), "Training/index mismatch")
    require(evaluation["candidate_manifest_sha256"] == digest(root / "index-manifest.json"), "Evaluation/index mismatch")
    require(evaluation["training_result_sha256"] == digest(root / "train-v1/result.json"), "Evaluation/training mismatch")
    require(digest(documents) == protocol["documents_sha256"], "Canonical documents changed")
    for filename, expected in protocol["files_sha256"].items():
        require(digest(root / "bundle" / filename) == expected, f"Frozen data changed: {filename}")
    mined = read(root, "mined/manifest.json")
    require(train["mined_manifest_sha256"] == digest(root / "mined/manifest.json"), "Mining/training mismatch")
    require(digest(root / "mined/train.json") == mined["files_sha256"]["train.json"], "Training examples changed")

    raw_cases = read(root, "bundle/test.json")["cases"] + read(root, "bundle/regression.json")["cases"]
    rows = [json.loads(line) for line in (root / "evaluation-v1/rankings.jsonl").open()]
    rankings = {(r["question_id"], r["method"], r["model"]): r for r in rows}
    require(len(rows) == len(rankings) == len(raw_cases) * 4, "Missing or duplicate rankings")
    cases = []
    required_ids = set()
    for case in raw_cases:
        entry = {key: case[key] for key in ["id", "split", "question", "required_groups", "expected_facts"]}
        entry["methods"] = {}
        for method in ["hybrid", "dense"]:
            pair = {}
            for model in ["base", "lora"]:
                row = rankings[case["id"], method, model]
                ids = row["ranked_ids"]
                hits = [bool(set(group) & set(ids)) for group in case["required_groups"]]
                complete = all(hits)
                first = bool(set(ids[:1]) & set().union(*map(set, case["required_groups"])))
                require(complete == bool(row["metrics"]["all_groups_at10"]), "Coverage mismatch")
                require(first == bool(row["metrics"]["hit_at1"]), "First-hit mismatch")
                pair[model] = dict(ids=ids, hits=hits, complete=complete, first=first)
                required_ids.update(ids)
            pair["lost"] = sum(a and not b for a, b in zip(pair["base"]["hits"], pair["lora"]["hits"]))
            pair["gained"] = sum(b and not a for a, b in zip(pair["base"]["hits"], pair["lora"]["hits"]))
            entry["methods"][method] = pair
        required_ids.update(i for group in case["required_groups"] for i in group)
        cases.append(entry)

    for metric in evaluation["summary"]:
        items = [c["methods"][metric["method"]][metric["model"]] for c in cases if c["split"] == metric["split"]]
        require(len(items) == metric["questions"], "Question count mismatch")
        require(sum(x["complete"] for x in items) == metric["complete_cases"], "Complete aggregate mismatch")
        require(sum(x["first"] for x in items) == metric["hit_at1_cases"], "First-hit aggregate mismatch")
    require(summary["retrieval_results"] == evaluation["summary"], "Summary results mismatch")
    require(sum(c["methods"]["hybrid"]["lost"] > 0 for c in cases) == summary["questions_losing_evidence"],
            "Lost-evidence count mismatch")
    require(not summary["activated"] and not evaluation["eligible_for_integration"], "Update the appendix decision for a new run")

    # One source-checked example per training brand, selected before considering any results.
    all_train = read(root, "mined/train.json")["cases"]
    seen_brands, examples = set(), []
    for case in all_train:
        brand = case["expected_identities"][0]["brand"]
        if brand in seen_brands:
            continue
        seen_brands.add(brand)
        examples.append(dict(id=case["id"], question=case["question"], brand=brand,
                             positive_ids=[p["id"] for p in case["positive_evidence"]],
                             negatives=[dict(id=p["id"], reason=p["reason"]) for p in case["negative_evidence"]]))
        required_ids.update(p["id"] for p in case["positive_evidence"] + case["negative_evidence"])
    keys = ["id", "brand", "model", "year", "section", "original_text", "source_url", "text_sha256"]
    source_docs = {}
    with documents.open() as stream:
        for line in stream:
            d = json.loads(line)
            if d["id"] in required_ids:
                source_docs[d["id"]] = {k: d[k] for k in keys}
    require(required_ids == source_docs.keys(), "Missing source passage")
    parity = read(root, "evaluation-v1/baseline-parity.json")
    selected = next(c for c in train["checkpoints"] if c["path"] == train["selected_checkpoint"])
    return dict(schema="bikefinder-bge-lora-appendix-v1", experiment_date="2026-10-15",
                results=evaluation["summary"], cases=cases, documents=source_docs, examples=examples,
                counts=protocol["counts"], brands=protocol["brands"], fiches=protocol["unique_fiches"],
                training=dict(parameters=train["parameters"], trainable=train["trainable_parameters"],
                              seconds=train["total_seconds"], steps=train["optimizer_steps"],
                              baseline_loss=train["baseline_dev_loss"], selected_epoch=selected["epoch"],
                              checkpoints=[{k: c[k] for k in ["epoch", "dev_loss", "train_loss"]} for c in train["checkpoints"]],
                              hyperparameters=train["hyperparameters"], versions=train["versions"]),
                index=dict(documents=index["documents"], dimensions=index["dimensions"], seconds=index["encoding_seconds"],
                           max_tokens=index["max_tokens_observed"], control=index["base_encoding_control"]),
                checks=evaluation["promotion_checks"], parity=parity, tests=summary["tests"],
                annotation={k: annotation[k] for k in ["canonical_passage_bindings_checked", "manual_review_count",
                            "train_positive_occurrences", "train_negative_occurrences", "annotations_by_independent_human"]},
                hashes=dict(protocol=protocol_hash, documents=protocol["documents_sha256"],
                            adapter=selected["files_sha256"]["adapter_model.safetensors"], vectors=index["vectors_sha256"]),
                provenance=[dict(file=name, sha256=digest(root / name)) for name in provenance_names],
                api_cost_usd=summary["remote_api_usd"], activated=False)


def render(root, documents, out):
    data = build_data(root, documents)
    rows = []
    for method in ["hybrid", "dense"]:
        for split in ["test", "regression"]:
            before, after = [next(r for r in data["results"] if (r["method"], r["split"], r["model"]) ==
                                 (method, split, model)) for model in ["base", "lora"]]
            complete = f'{int(before["complete_cases"])} → {int(after["complete_cases"])} / {before["questions"]}'
            first = f'{int(before["hit_at1_cases"])} → {int(after["hit_at1_cases"])} / {before["questions"]}'
            color = "good" if after["complete_cases"] >= before["complete_cases"] else "bad"
            rows.append(f'<tr><th scope="row">{"Hybride" if method == "hybrid" else "Dense seul"} · '
                        f'{"nouveau test" if split == "test" else "anciens cas"}</th>'
                        f'<td class="{color}"><strong>{complete}</strong></td><td>{first}</td></tr>')
    losses = []
    for case in data["cases"]:
        pair = case["methods"]["hybrid"]
        if pair["lost"]:
            losses.append(f'<li><strong>{html.escape(case["id"])}</strong> — {html.escape(case["question"])}</li>')
    serialized = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    require("/Users/" not in serialized, "Do not publish local account paths")
    page = TEMPLATE.read_text().replace("__RESULT_ROWS__", "\n".join(rows))
    page = page.replace("__LOSS_LIST__", "\n".join(losses)).replace("__PILOT_DATA__", serialized)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page)
    print(json.dumps(dict(out=str(out), bytes=out.stat().st_size,
                          cases=len(data["cases"]), passages=len(data["documents"]), examples=len(data["examples"]))))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pilot", type=Path, default=PILOT)
    parser.add_argument("--documents", type=Path, default=DOCUMENTS)
    parser.add_argument("--out", type=Path, default=ROOT / "docs/benchmark-finetuning.html")
    args = parser.parse_args()
    render(args.pilot, args.documents, args.out)
