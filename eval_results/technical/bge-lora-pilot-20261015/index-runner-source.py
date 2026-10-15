"""Local BGE-M3 LoRA pilot with source-checked explicit negatives and reserved brands.

Commands preserve datasets/checkpoints and never activate a chat or mutate its index.
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import random
import re
import shutil
import time

import numpy as np
from validate_bge_fusion import FIELDS, facts, identity, make_case, historical, sha, write
from benchmark_technical_retrieval import BM25, metrics, rank_scores, model_spec

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "data/technical/retrieval-benchmark-20261013/index"
BASE = Path("/Users/m4ks/.cache/huggingface/hub/models--BAAI--bge-m3/snapshots/5617a9f61b028005a4858fdac845db406aefb181")
RUNTIME = ROOT / "data/technical/bge-training-runtime-20261015"
TRAIN_BRANDS = ["Brough Superior", "Voxan", "QJ Motor", "Hyosung", "Daelim", "Derbi",
                "MZ / MuZ", "Orcal", "Rieju", "Laverda", "Macbor", "Brixton"]
DEV_BRANDS = ["Kove", "Zontes", "Ural", "FB Mondial"]
TEST_BRANDS = ["Gilera", "Kymco", "BSA", "Fantic", "Morbidelli", "GASGAS"]
TOPICS = [
    (["seat", "tank"], "Quelle hauteur de selle et quelle capacité de réservoir indique la fiche de {a} ?",
     "Pour {a}, donne la distance selle-sol et le volume de carburant embarqué, tels qu'ils sont écrits."),
    (["power", "torque"], "Puissance et couple de {a} : relève les valeurs, unités et régimes annoncés.",
     "Que sait-on de la puissance délivrée et du couple de {a}, avec leurs régimes ?"),
    (["secondary", "gearbox"], "Sur {a}, combien de rapports et quel entraînement final sont indiqués ?",
     "Comment {a} transmet-elle le mouvement à la roue et combien de vitesses sa boîte comporte-t-elle ?"),
    (["front_brake", "rear_brake"], "Quels freins avant et arrière la fiche de {a} décrit-elle ?",
     "Je veux comparer le freinage des deux roues de {a}. Relève les dimensions disponibles."),
    (["displacement", "tank"], "Quelle est la cylindrée réelle de {a}, et quel volume de réservoir est écrit ?",
     "Le nom de {a} peut être commercial : relève les cc et les litres de réservoir dans sa fiche."),
    (["seat", "torque"], "Pour {a}, indique hauteur de selle et couple avec son régime si disponible.",
     "À quelle hauteur s'assoit-on sur {a}, et quel couple son moteur fournit-il selon la fiche ?"),
    (["power", "mass"], "Relève la puissance et les poids documentés de {a}, avec la distinction sec/pleins.",
     "Pour {a}, donne les valeurs de puissance et de masse en gardant les libellés d'origine."),
    (["cooling", "secondary"], "Quel refroidissement et quelle transmission secondaire sont cités pour {a} ?",
     "Comment sont décrits le refroidissement du moteur et l'entraînement final de {a} ?"),
    (["colours"], "Quels coloris sont explicitement listés pour {a} ?",
     "Quelles teintes la fiche de {a} propose-t-elle pour ce millésime précis ?"),
    (["front_brake", "front_suspension"], "Décris la fourche et le frein avant de {a} à partir de la fiche.",
     "Quel matériel de suspension et de freinage est indiqué à l'avant de {a} ?"),
    (["rear_brake", "rear_suspension"], "Quel frein et quelle suspension arrière sont indiqués pour {a} ?",
     "À l'arrière de {a}, que décrit la fiche pour amortir et freiner ?"),
    (["gearbox", "front_suspension"], "Combien de rapports et quel type de fourche trouve-t-on sur {a} ?",
     "Pour {a}, relève le nombre de vitesses ainsi que la suspension avant."),
]
HP = dict(seed=20261015, epochs=2, batch_queries=2, learning_rate=3e-5,
          lora_rank=8, lora_alpha=16, lora_dropout=0.05, temperature=0.05,
          max_tokens=384, gradient_clip=1.0, explicit_negatives=4,
          loss="mean over positives of cross-entropy against that positive and four explicit negatives; no in-batch negatives",
          checkpoint_selection="lowest validation contrastive loss among epoch checkpoints; test and regression labels never used",
          dense_pool=40, lexical_pool=40, dense_weight=1, lexical_weight=1, rrf_constant=60)

def now():
    return datetime.now(timezone.utc).isoformat()

def documents():
    return [json.loads(line) for line in (INDEX / "documents.jsonl").open()]

def load_cases(directory, name):
    return json.loads((directory / f"{name}.json").read_text())["cases"]

def validate_partition(cases_by_split):
    brands, ids = {}, {}
    for split, cases in cases_by_split.items():
        brands[split] = {p["brand"] for c in cases for p in c["expected_identities"]}
        ids[split] = {p["object_id"] for c in cases for p in c["expected_identities"]}
    names = list(brands)
    for n, a in enumerate(names):
        for b in names[n+1:]:
            if brands[a] & brands[b] or ids[a] & ids[b]:
                raise ValueError(f"Split leakage: {a}/{b}")
    return {s: sorted(b) for s,b in brands.items()}

def eligible(fiche, fields):
    result = facts(fiche, fields)
    return bool(result) and not any(re.search(r"non défini|\bnc\b", q, re.I) for f in result for q in f["quotes"])

def prepare(bundle):
    if bundle.exists():
        raise FileExistsError("Keep first prepared dataset")
    docs = documents()
    fiches = defaultdict(list)
    for d in docs:
        fiches[d["object_id"]].append(d)
    inventory, old_ids, old_questions = historical()
    old = ROOT / "eval_results/technical/bge-fusion-confirmation-20261015/bundle"
    regression = load_cases(old, "fresh.annotations") + load_cases(old, "regression.annotations")
    old_ids.update(oid for c in regression for oid in c["supplied_scope_object_ids"])
    reserved_brands = {fiches[i][0]["brand"] for i in old_ids if i in fiches}
    all_new = set(TRAIN_BRANDS + DEV_BRANDS + TEST_BRANDS)
    if all_new & reserved_brands:
        raise ValueError("A new split shares a previously evaluated brand")
    output = {}
    for split, brands, count in [("train", TRAIN_BRANDS, 512), ("dev", DEV_BRANDS, 64), ("test", TEST_BRANDS, 64)]:
        rows, seen = [], set()
        for index in range(count):
            brand = brands[index % len(brands)]
            topic = (index // len(brands) + index) % len(TOPICS)
            chosen = None
            for delta in range(len(TOPICS)):
                fields, template, held_template = TOPICS[(topic + delta) % len(TOPICS)]
                candidates = [f for f in fiches.values() if f[0]["brand"] == brand and 1990 <= f[0]["year"] <= 2026
                              and eligible(f, fields) and (f[0]["object_id"], tuple(fields)) not in seen]
                if not candidates:
                    continue
                candidates.sort(key=lambda f: hashlib.sha256(f"{split}:{index}:{f[0]['object_id']}:20261015".encode()).hexdigest())
                chosen = candidates[0]
                break
            if chosen is None:
                raise ValueError(f"Not enough verified source examples for {split}/{brand}")
            question = (template if split == "train" else held_template).format(a=identity(chosen))
            if question.strip().casefold() in old_questions:
                raise ValueError("Old question reused")
            case = make_case(f"{split.upper()}-{index+1:04}", question, [chosen], fields, "source_authored")
            case.update(split=split, requested_fields=fields,
                        annotation={"author":"Assistant templates with automated exact-source checks; sampled manual source review, no independent human panel",
                                    "all_positive_sections_preserved":True})
            seen.add((chosen[0]["object_id"], tuple(fields)))
            rows.append(case)
        output[split] = rows
    output["regression"] = [deepcopy(c) | {"split":"regression"} for c in regression]
    partitions = validate_partition(output)
    bundle.mkdir(parents=True)
    for split,cases in output.items():
        write(bundle / f"{split}.json", {"cases":cases})
    write(bundle / "queries.json", {"cases":[{k:c[k] for k in ["id","split","question"]} for cases in output.values() for c in cases]})
    source_protocol = json.loads((INDEX/"protocol.json").read_text())
    protocol = dict(created_utc=now(), status="source_cases_frozen_before_mining_or_training", hyperparameters=HP,
                    counts={s:len(c) for s,c in output.items()}, brands=partitions,
                    unique_fiches={s:len({oid for c in cases for oid in c["supplied_scope_object_ids"]}) for s,cases in output.items()},
                    documents_sha256=sha(INDEX/"documents.jsonl"), index_manifest_sha256=sha(INDEX/"index-manifest.json"),
                    base_model=source_protocol["dense_model"], prior_question_inventory=inventory,
                    source_checks="Question contains exact canonical model/year; each expected quote is a verbatim source substring. Multiple useful sections all remain positive.",
                    negative_policy="Mine only within the same split brands. Identity mismatch is negative only for the explicit requested model/year. Same-identity sections qualify only when none of the requested fact patterns occurs. Never use held-out brands as training negatives.",
                    limitations=["Assistant-written templates and automatically verified labels, not 512 independent human judgements.",
                                 "Brands are disjoint across all four cohorts; training brands are smaller catalogue manufacturers, so coverage is biased.",
                                 "Repeated fiches within a split; examples are not statistically independent.",
                                 "Exact-source ranking only; no guarantees of final chat answer correctness, abstention or identity resolution."],
                    inference_promotion="Require improved complete@10 on the new test, no lost required groups on test/regression and no decline of first-hit counts. No automatic activation.",
                    files_sha256={p.name:sha(p) for p in bundle.glob("*.json")})
    write(bundle/"protocol.json",protocol)
    print(json.dumps({k:protocol[k] for k in ["counts","brands","unique_fiches"]},ensure_ascii=False),flush=True)

def check_bundle(bundle):
    p = json.loads((bundle/"protocol.json").read_text())
    if p["hyperparameters"] != HP:
        raise ValueError("Hyperparameters changed after freeze")
    for name,expected in p["files_sha256"].items():
        if sha(bundle/name) != expected:
            raise ValueError("Frozen case file changed")
    if sha(INDEX/"index-manifest.json") != p["index_manifest_sha256"] or sha(INDEX/"documents.jsonl") != p["documents_sha256"]:
        raise ValueError("Base index changed")
    return p

def offline():
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1",
                      TOKENIZERS_PARALLELISM="false")

def model_load(adapter=None, half=False):
    offline()
    import torch
    from sentence_transformers import SentenceTransformer
    if not torch.backends.mps.is_available():
        raise RuntimeError("MPS unavailable; do not silently start an unbounded CPU run")
    model = SentenceTransformer(str(BASE), device="mps", local_files_only=True,
                                model_kwargs={"torch_dtype":torch.float16 if half else torch.float32})
    model.max_seq_length=HP["max_tokens"]
    if adapter:
        model.load_adapter(str(adapter))
    return model

def negative_reason(case, doc):
    if doc["object_id"] not in case["supplied_scope_object_ids"]:
        return "different_explicit_model_or_year"
    if doc["id"] in {p["id"] for p in case["gold_passages"]}:
        return None
    if any(re.search(FIELDS[f][1],doc["original_text"],re.I) for f in case["requested_fields"]):
        return None
    return "same_identity_no_requested_fact_in_section"

def mine(bundle, out):
    protocol=check_bundle(bundle)
    if out.exists(): raise FileExistsError("Preserve first mining")
    docs=documents()
    vectors=np.load(INDEX/"vectors.npy",mmap_mode="r")
    model=model_load()
    out.mkdir(parents=True)
    all_mined={}
    for split in ["train","dev"]:
        cases=load_cases(bundle,split)
        allowed=np.array([i for i,d in enumerate(docs) if d["brand"] in protocol["brands"][split]])
        subset=vectors[allowed]
        queries=model.encode([c["question"] for c in cases],batch_size=16,normalize_embeddings=True,show_progress_bar=False)
        selected=[]
        for n,(case,q) in enumerate(zip(cases,queries)):
            scores=np.zeros(len(docs),dtype=np.float32)
            scores[allowed]=subset@q
            ranked=rank_scores(scores,allowed,100)
            valid=[(i,s,negative_reason(case,docs[i])) for i,s in ranked if negative_reason(case,docs[i])]
            identity=[x for x in valid if x[2]=="different_explicit_model_or_year"]
            section=[x for x in valid if x[2]=="same_identity_no_requested_fact_in_section"]
            picks=[]
            # Encourage identity discrimination and section discrimination, then fill by hardness.
            for pool,limit in [(identity,3),(section,1),(valid,HP["explicit_negatives"])]:
                for item in pool:
                    if item[0] not in {x[0] for x in picks} and len(picks)<HP["explicit_negatives"]:
                        picks.append(item)
                        if sum(x in pool for x in picks)>=limit: break
            if len(picks)!=HP["explicit_negatives"]: raise ValueError("Not enough approved negatives")
            row=deepcopy(case)
            row["negative_evidence"]=[dict(**docs[i],reason=reason,mined_dense_score=s,review="Rule-validated explicit identity/section mismatch") for i,s,reason in picks]
            row["mining_ranked_candidate_ids"]=[docs[i]["id"] for i,_ in ranked]
            selected.append(row)
        all_mined[split]=selected
        write(out/f"{split}.json",{"cases":selected})
        print(json.dumps({"mined":split,"queries":len(selected),"negatives":sum(len(c["negative_evidence"]) for c in selected)}),flush=True)
    validate_training_data(all_mined,protocol)
    texts=[t for cases in all_mined.values() for c in cases for t in [c["question"]]+[p["text"] for p in c["positive_evidence"]+c["negative_evidence"]]]
    lengths=[len(v) for v in model.tokenizer(texts,truncation=False,padding=False)["input_ids"]]
    if max(lengths)>HP["max_tokens"]: raise ValueError("Training would truncate")
    manifest=dict(created_utc=now(),protocol_sha256=sha(bundle/"protocol.json"),base_model_verified=model_spec(BASE)==protocol["base_model"],
                  max_input_tokens=max(lengths),files_sha256={p.name:sha(p) for p in out.glob("*.json")},
                  remote_api_calls=0,negative_reasons=dict(Counter(p["reason"] for c in all_mined["train"] for p in c["negative_evidence"])))
    write(out/"manifest.json",manifest)

def validate_training_data(data,protocol):
    for split,cases in data.items():
        for c in cases:
            positive={p["id"] for p in c["positive_evidence"]}
            if positive != {p["id"] for p in c["gold_passages"]}: raise ValueError("Positive lost")
            for p in c["negative_evidence"]:
                if p["brand"] not in protocol["brands"][split] or p["id"] in positive or not negative_reason(c,p):
                    raise ValueError("False negative or held-out leakage")
            for f in c["expected_facts"]:
                p=next(d for d in c["positive_evidence"] if d["id"]==f["passage_id"])
                if any(q not in p["original_text"] for q in f["quotes"]): raise ValueError("Invented source fact")

def contrastive_loss(embeddings, layouts):
    import torch
    losses=[]
    for q,positive,negative in layouts:
        # Each positive competes only against explicit negatives, never another useful proof.
        pos=embeddings[positive]@embeddings[q]
        neg=embeddings[negative]@embeddings[q]
        logits=torch.cat([pos[:,None],neg[None,:].expand(len(positive),-1)],dim=1)/HP["temperature"]
        losses.append(torch.nn.functional.cross_entropy(logits,torch.zeros(len(positive),dtype=torch.long,device=logits.device)))
    return torch.stack(losses).mean()

def batch_inputs(cases):
    texts,layouts=[],[]
    for c in cases:
        q=len(texts);texts.append(c["question"])
        positive=list(range(len(texts),len(texts)+len(c["positive_evidence"])))
        texts.extend(d["text"] for d in c["positive_evidence"])
        negative=list(range(len(texts),len(texts)+len(c["negative_evidence"])))
        texts.extend(d["text"] for d in c["negative_evidence"])
        layouts.append((q,positive,negative))
    return texts,layouts

def batch_loss(model,cases):
    from sentence_transformers.util import batch_to_device
    texts,layouts=batch_inputs(cases)
    features=batch_to_device(model.tokenize(texts),model.device)
    embeddings=model(features)["sentence_embedding"]
    return contrastive_loss(embeddings,layouts)

def validation_loss(model,cases):
    import torch
    model.eval();values=[]
    with torch.no_grad():
        for start in range(0,len(cases),HP["batch_queries"]):
            batch=cases[start:start+HP["batch_queries"]]
            values.append((float(batch_loss(model,batch).cpu()),len(batch)))
    return sum(loss*n for loss,n in values)/sum(n for _,n in values)

def adapter_save(model,path):
    path.mkdir(parents=True,exist_ok=False)
    model[0].auto_model.save_pretrained(str(path))
    if not (path/"adapter_model.safetensors").exists():
        raise ValueError("Adapter checkpoint missing")
    if (path/"model.safetensors").exists():
        raise ValueError("Expected adapter only, not a rewritten base")
    return {p.name:sha(p) for p in path.iterdir() if p.is_file()}

def train(bundle,mined,out,smoke=False):
    p=check_bundle(bundle)
    manifest=json.loads((mined/"manifest.json").read_text())
    if manifest["protocol_sha256"]!=sha(bundle/"protocol.json"):raise ValueError("Mined dataset mismatch")
    for name,value in manifest["files_sha256"].items():
        if sha(mined/name)!=value:raise ValueError("Mined data changed")
    if out.exists():raise FileExistsError("Preserve training run")
    from peft import LoraConfig,TaskType
    import torch
    random.seed(HP["seed"]);np.random.seed(HP["seed"]);torch.manual_seed(HP["seed"])
    model=model_load()
    model.add_adapter(LoraConfig(task_type=TaskType.FEATURE_EXTRACTION,r=HP["lora_rank"],
                      lora_alpha=HP["lora_alpha"],lora_dropout=HP["lora_dropout"],
                      target_modules=["query","value"],bias="none"))
    trainable=[parameter for name,parameter in model.named_parameters() if parameter.requires_grad]
    if any("lora_" not in name for name,param in model.named_parameters() if param.requires_grad):raise ValueError("Base parameter unfrozen")
    data={s:load_cases(mined,s) for s in ["train","dev"]}
    validate_training_data(data,p)
    out.mkdir(parents=True);shutil.copyfile(__file__,out/"runner-source.py")
    started=time.perf_counter()
    metadata=dict(started_utc=now(),smoke=smoke,script_sha256=sha(__file__),protocol_sha256=sha(bundle/"protocol.json"),
                  mined_manifest_sha256=sha(mined/"manifest.json"),parameters=sum(x.numel() for x in model.parameters()),
                  trainable_parameters=sum(x.numel() for x in trainable),hyperparameters=HP,
                  versions={pkg:importlib.metadata.version(pkg) for pkg in ["torch","sentence-transformers","transformers","peft","accelerate"]},
                  remote_api_calls=0,base_files_before=model_spec(BASE),device=str(model.device),dtype=str(next(model.parameters()).dtype))
    dev=data["dev"][:8] if smoke else data["dev"]
    metadata["baseline_dev_loss"]=validation_loss(model,dev)
    optimizer=torch.optim.AdamW(trainable,lr=HP["learning_rate"],weight_decay=.01)
    steps=0;checkpoints=[];last_report=time.perf_counter()
    initial={name:param.detach().cpu().clone() for name,param in model.named_parameters() if param.requires_grad}
    for epoch in range(1,1+(1 if smoke else HP["epochs"])):
        ordered=list(data["train"]);random.Random(HP["seed"]+epoch).shuffle(ordered)
        if smoke:ordered=ordered[:20*HP["batch_queries"]]
        epoch_losses=[]
        for start in range(0,len(ordered),HP["batch_queries"]):
            step_start=time.perf_counter();model.train();optimizer.zero_grad(set_to_none=True)
            loss=batch_loss(model,ordered[start:start+HP["batch_queries"]])
            if not torch.isfinite(loss):raise ValueError("Nonfinite loss")
            loss.backward()
            norm=torch.nn.utils.clip_grad_norm_(trainable,HP["gradient_clip"],error_if_nonfinite=True)
            optimizer.step();torch.mps.synchronize()
            steps+=1;value=float(loss.detach().cpu());epoch_losses.append(value)
            row=dict(epoch=epoch,step=steps,loss=value,gradient_norm=float(norm.detach().cpu()),
                     step_seconds=time.perf_counter()-step_start,allocated_bytes=torch.mps.current_allocated_memory(),
                     driver_bytes=torch.mps.driver_allocated_memory())
            with (out/"steps.jsonl").open("a") as f:f.write(json.dumps(row)+"\n")
            if steps%10==0 or time.perf_counter()-last_report>=20:
                print(json.dumps(row),flush=True);last_report=time.perf_counter()
        score=validation_loss(model,dev)
        path=out/f"epoch-{epoch}"
        checkpoint=dict(epoch=epoch,dev_loss=score,train_loss=float(np.mean(epoch_losses)),path=str(path),files_sha256=adapter_save(model,path))
        checkpoints.append(checkpoint)
        write(out/"checkpoints.json",checkpoints)
        print(json.dumps({"epoch_done":checkpoint}),flush=True)
    changed=sum(not torch.equal(initial[name],param.detach().cpu()) for name,param in model.named_parameters() if param.requires_grad)
    if not changed:raise ValueError("No adapter parameter changed")
    chosen=min(checkpoints,key=lambda c:c["dev_loss"])
    metadata.update(completed_utc=now(),total_seconds=time.perf_counter()-started,optimizer_steps=steps,
                    changed_adapter_tensors=changed,base_files_unchanged=model_spec(BASE)==metadata["base_files_before"],
                    checkpoints=checkpoints,selected_checkpoint=chosen["path"],selected_dev_loss=chosen["dev_loss"],
                    dev_loss_improved=chosen["dev_loss"]<metadata["baseline_dev_loss"],status="completed_not_activated")
    write(out/"result.json",metadata)
    print(json.dumps({k:metadata[k] for k in ["trainable_parameters","optimizer_steps","total_seconds","baseline_dev_loss","selected_dev_loss","dev_loss_improved","selected_checkpoint"]}),flush=True)

def encode_index(bundle,training,out):
    p=check_bundle(bundle)
    result=json.loads((training/"result.json").read_text())
    if result["smoke"]:raise ValueError("Do not index smoke checkpoint")
    selected=Path(result["selected_checkpoint"])
    chosen=next(c for c in result["checkpoints"] if c["path"]==str(selected))
    for name,value in chosen["files_sha256"].items():
        if sha(selected/name)!=value:raise ValueError("Adapter changed")
    if out.exists():raise FileExistsError("Keep candidate index")
    # Verify the encoding pipeline against a sample of the existing base index.
    # This bounds precision/tokenization drift before attributing changes to LoRA.
    import gc,torch
    docs=documents()
    control_ids=np.linspace(0,len(docs)-1,32,dtype=int)
    original=np.load(INDEX/"vectors.npy",mmap_mode="r")
    control_model=model_load(half=True)
    control=control_model.encode([docs[i]["text"] for i in control_ids],batch_size=32,
                                normalize_embeddings=True,show_progress_bar=False).astype(np.float32)
    reference=np.asarray(original[control_ids])
    cosines=np.sum(control*reference,axis=1)/(np.linalg.norm(control,axis=1)*np.linalg.norm(reference,axis=1))
    if float(cosines.min())<.9999:raise ValueError("Base encoding pipeline drift")
    encoding_control=dict(sample_documents=32,min_cosine=float(cosines.min()),max_abs_error=float(np.max(np.abs(control-reference))))
    del control_model;gc.collect();torch.mps.empty_cache()
    model=model_load(selected,half=True)
    # Merge for document encoding only, in memory; checkpoint/base files remain intact.
    from peft.tuners.lora import LoraLayer
    for layer in model.modules():
        if isinstance(layer,LoraLayer):
            layer.merge(safe_merge=True)
    lengths=[len(ids) for ids in model.tokenizer([d["text"] for d in docs],truncation=False,padding=False)["input_ids"]]
    if max(lengths)>HP["max_tokens"]:raise ValueError("Candidate documents would truncate")
    out.mkdir(parents=True)
    shutil.copyfile(__file__,out/"runner-source.py")
    vectors=np.lib.format.open_memmap(out/"vectors.npy",mode="w+",dtype=np.float32,shape=(len(docs),1024))
    started=time.perf_counter()
    for start in range(0,len(docs),512):
        texts=[d["text"] for d in docs[start:start+512]]
        batch=model.encode(texts,batch_size=32,normalize_embeddings=True,show_progress_bar=False)
        if not np.isfinite(batch).all():raise ValueError("Invalid document vector")
        vectors[start:start+len(batch)]=batch;vectors.flush()
        print(json.dumps({"encoded":start+len(batch),"total":len(docs),"elapsed_seconds":time.perf_counter()-started}),flush=True)
    write(out/"manifest.json",dict(completed_utc=now(),documents=len(docs),dimensions=1024,
          document_sha256=p["documents_sha256"],vectors_sha256=sha(out/"vectors.npy"),
          base_model=p["base_model"],adapter_path=str(selected),adapter_files_sha256=chosen["files_sha256"],
          dtype="float16 model, normalized float32 storage",max_tokens_observed=max(lengths),
          encoding_seconds=time.perf_counter()-started,training_result_sha256=sha(training/"result.json"),
          protocol_sha256=sha(bundle/"protocol.json"),status="complete_isolated_index",
          script_sha256=sha(out/"runner-source.py"),base_encoding_control=encoding_control))
    print(json.dumps({"index_complete":str(out)}),flush=True)

def evaluate(bundle,training,candidate,out):
    p=check_bundle(bundle)
    result=json.loads((training/"result.json").read_text())
    manifest=json.loads((candidate/"manifest.json").read_text())
    if manifest["training_result_sha256"]!=sha(training/"result.json") or sha(candidate/"vectors.npy")!=manifest["vectors_sha256"]:
        raise ValueError("Candidate index binding mismatch")
    if out.exists():raise FileExistsError("Keep first test evaluation")
    docs=documents();lookup={d["id"]:i for i,d in enumerate(docs)}
    lexical=BM25.load(INDEX);allowed=np.arange(len(docs))
    out.mkdir(parents=True);shutil.copyfile(__file__,out/"runner-source.py")
    # Final labels only score; they never enter an encoder or checkpoint selection.
    cases=load_cases(bundle,"test")+load_cases(bundle,"regression")
    lexical_rankings={c["id"]:[i for i,s in rank_scores(lexical.scores(c["question"]),allowed,40) if s>0] for c in cases}
    rows=[]
    for model_name,adapter,path in [("base",None,INDEX/"vectors.npy"),("lora",Path(result["selected_checkpoint"]),candidate/"vectors.npy")]:
        import torch,gc
        model=model_load(adapter)
        lengths=[len(t) for t in model.tokenizer([c["question"] for c in cases],truncation=False,padding=False)["input_ids"]]
        if max(lengths)>HP["max_tokens"]:raise ValueError("Evaluation query would truncate")
        vectors=np.load(path,mmap_mode="r")
        # Same query precision and frozen lexical/dense fusion settings for both.
        for n,c in enumerate(cases):
            started=time.perf_counter()
            q=model.encode([c["question"]],normalize_embeddings=True,show_progress_bar=False)[0]
            dense=[i for i,s in rank_scores(vectors@q,allowed,40)]
            fused=defaultdict(float)
            for ranking in [dense,lexical_rankings[c["id"]]]:
                for rank,i in enumerate(ranking,1):fused[i]+=1/(60+rank)
            hybrid=sorted(fused,key=lambda i:(-fused[i],i))[:10]
            for method,ranking in [("dense",dense[:10]),("hybrid",hybrid)]:
                ids=[docs[i]["id"] for i in ranking]
                row=dict(question_id=c["id"],split=c["split"],model=model_name,method=method,ranked_ids=ids,metrics=metrics(ids,c),
                         query_and_dense_seconds=time.perf_counter()-started)
                rows.append(row)
                with (out/"rankings.jsonl").open("a") as f:f.write(json.dumps(row,ensure_ascii=False)+"\n")
            if n%32==0:print(json.dumps({"evaluating":model_name,"completed":n+1,"total":len(cases)}),flush=True)
        del model;gc.collect();torch.mps.empty_cache()
    summary=[]
    for split in ["test","regression"]:
        for method in ["dense","hybrid"]:
            for model_name in ["base","lora"]:
                r=[x for x in rows if (x["split"],x["method"],x["model"])==(split,method,model_name)]
                summary.append(dict(split=split,method=method,model=model_name,questions=len(r),
                    complete_cases=sum(x["metrics"]["all_groups_at10"] for x in r),
                    hit_at1_cases=sum(x["metrics"]["hit_at1"] for x in r),
                    mean_recall_at10=float(np.mean([x["metrics"]["recall_at10"] for x in r]))))
    by={(r["question_id"],r["model"],r["method"]):r for r in rows}
    paired=[]
    for c in cases:
        a,b=[by[c["id"],m,"hybrid"] for m in ["base","lora"]]
        lost=[g for g in c["required_groups"] if set(g)&set(a["ranked_ids"]) and not set(g)&set(b["ranked_ids"])]
        gained=[g for g in c["required_groups"] if set(g)&set(b["ranked_ids"]) and not set(g)&set(a["ranked_ids"])]
        paired.append(dict(id=c["id"],split=c["split"],question=c["question"],lost_groups=lost,gained_groups=gained,
                           baseline_complete=a["metrics"]["all_groups_at10"],candidate_complete=b["metrics"]["all_groups_at10"]))
    write(out/"paired.json",paired)
    relevant={(r["split"],r["model"]):r for r in summary if r["method"]=="hybrid"}
    checks=dict(new_test_complete_gain=relevant["test","lora"]["complete_cases"]>relevant["test","base"]["complete_cases"],
                no_lost_evidence=not any(c["lost_groups"] for c in paired),
                no_first_hit_decline=all(relevant[s,"lora"]["hit_at1_cases"]>=relevant[s,"base"]["hit_at1_cases"] for s in ["test","regression"]),
                dev_loss_improved=result["dev_loss_improved"],
                base_files_unchanged=model_spec(BASE)==p["base_model"])
    write(out/"summary.json",dict(created_utc=now(),summary=summary,promotion_checks=checks,
          eligible_for_integration=all(checks.values()),activated=False,
          training_result_sha256=sha(training/"result.json"),candidate_manifest_sha256=sha(candidate/"manifest.json"),
          protocol_sha256=sha(bundle/"protocol.json"),remote_api_calls=0,
          limitations=p["limitations"]+["Single latency pass; no robust latency comparison. Full-index retrieval, not a live chat test."]))
    print(json.dumps({"summary":summary,"checks":checks},ensure_ascii=False),flush=True)

if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode",choices=["prepare","mine","smoke","train","index","evaluate"])
    parser.add_argument("--bundle",type=Path,required=True)
    parser.add_argument("--out",type=Path)
    parser.add_argument("--mined",type=Path)
    parser.add_argument("--training",type=Path)
    parser.add_argument("--index",type=Path)
    args=parser.parse_args()
    if args.mode=="prepare":prepare(args.bundle)
    elif args.mode=="mine":mine(args.bundle,args.out)
    elif args.mode in ["smoke","train"]:train(args.bundle,args.mined,args.out,args.mode=="smoke")
    elif args.mode=="index":encode_index(args.bundle,args.training,args.out)
    else:evaluate(args.bundle,args.training,args.index,args.out)
