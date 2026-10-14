"""Read-only SQL identity and locally prepared constructor/catalogue evidence."""
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import re
import time

import numpy as np

from bikefinder_rag.catalog.enriched import _rows, folded
from bikefinder_rag.catalog.research import literal_name
from bikefinder_rag.catalog.technical_rag import normalized_vectors
from bikefinder_rag.embeddings import embedder

ROOT = Path(__file__).resolve().parents[3]


def supports(question):
    sources = json.loads((Path(__file__).with_name("manufacturer_sources.json")).read_text())["sources"]
    return any(literal_name(a, question) for s in sources for a in s["aliases"])


class Corpus:
    def __init__(self, root, *, encode=None, rerank=None):
        self.root, self.encode = Path(root), encode or embedder.embed_text
        from bikefinder_rag.embeddings.experiment_reranker import rank
        self.rerank = rerank or rank
        self.manifest = json.loads((self.root / "manifest.json").read_text())
        if self.manifest["revision"] != embedder.MODEL_REVISION:
            raise ValueError("Prepared index uses another embedding revision")
        for name, expected in self.manifest["files"].items():
            if hashlib.sha256((self.root / name).read_bytes()).hexdigest() != expected:
                raise ValueError("Prepared index checksum mismatch")
        self.docs = [json.loads(line) for line in (self.root / "documents.jsonl").read_text().splitlines()]
        self.vectors = normalized_vectors(np.load(self.root / "vectors.npy", allow_pickle=False), len(self.docs))
        self.sources = self.manifest["sources"]
        self.stamps = {}
        for source in self.sources:
            snapshot = Path(source["snapshot"])
            if hashlib.sha256(snapshot.read_bytes()).hexdigest() != source["sha256"]:
                raise ValueError("Constructor snapshot checksum mismatch")
            self.stamps[str(snapshot)] = (snapshot.stat().st_mtime_ns, snapshot.stat().st_size)

    def retrieve(self, conn, question, history):
        started = time.perf_counter()
        # An amended source cannot keep using the old prepared embedding.
        for name, stamp in self.stamps.items():
            p = Path(name)
            if (p.stat().st_mtime_ns, p.stat().st_size) != stamp:
                raise ValueError("Constructor source changed; prepare a new index")
        previous = " ".join(m["content"] for m in history[-4:] if m.get("role") == "user" and isinstance(m.get("content"), str))
        text = question if any(literal_name(a, question) for s in self.sources for a in s["aliases"]) else previous + " " + question
        groups = {}
        for source in self.sources:
            matches = [a for a in source["aliases"] if literal_name(a, text)]
            if matches:
                groups.setdefault((source["brand"], source["family"]), set()).update(matches)
        missing = []
        if not groups:
            return {"passages": [], "missing": [{"message": "Modèle ou famille non identifié dans ce corpus expérimental."}], "scopes": [], "timing": {}}
        mentions = [(literal_name(a, question), key) for key, matches in groups.items() for a in matches]
        mentions = [(m, key) for m, key in mentions if m]
        qualifiers = {key: [] for key in groups}
        for qualifier in re.finditer(r"\b(?:edition|finition|version)\s+([a-z0-9-]+)", folded(question)):
            if qualifier[1] in {"de", "en", "avec", "sans", "pour", "manuelle", "automatique", "actuelle", "source"} or qualifier[1].isdigit():
                continue
            preceding = [(m.end(), key) for m, key in mentions if m.end() <= qualifier.start()]
            following = [(m.start(), key) for m, key in mentions if m.start() >= qualifier.end()]
            owner = max(preceding)[1] if preceding else min(following)[1] if following else next(iter(groups)) if len(groups) == 1 else None
            if owner:
                qualifiers[owner].append(qualifier[1])
            else:
                return {"passages": [], "missing": [{"message": "Précise la famille concernée par cette version ou édition."}], "scopes": [], "timing": {}}
        candidates = []
        scopes = []
        for (brand, family), matches in groups.items():
            numeric_names = [re.sub(r"[^a-z0-9]", "", folded(a)) for a in matches if re.search(r"\d", a)]
            model_numbers = {int(n) for a in numeric_names for n in re.findall(r"\d+", a)}
            years, market_years = set(), {}
            for alias in matches:
                mention = literal_name(alias, text)
                tail = text[mention.end():mention.end()+45] if mention else ""
                dated = re.match(r"\s*(?:[,(]\s*)?(?:(?:de|en|millesime|annee|modele)\s+)?((?:19|20)\d{2})\b", folded(tail))
                if dated and int(dated[1]) not in model_numbers:
                    region = re.split(r"[?:;.!]", folded(tail)[dated.end():], maxsplit=1)[0]
                    named_markets = (["France"] if re.search(r"franc", region) else []) + (["USA"] if re.search(r"americ|etats.unis|\busa\b", region) else [])
                    if len(named_markets) == 1:
                        market_years.setdefault(named_markets[0], set()).add(int(dated[1]))
                    else:
                        years.add(int(dated[1]))
            both_markets = bool(re.search(r"franc", folded(question)) and re.search(r"americ|etats.unis|\busa\b", folded(question)))
            docs = [(i, d) for i, d in enumerate(self.docs) if d["brand"] == brand and d["family"] == family
                    and (not numeric_names or any(n in re.sub(r"[^a-z0-9]", "", folded(d["model"])) for n in numeric_names))
                    and (not (years | market_years.get(d["market"], set())) or d["year"] in (years | market_years.get(d["market"], set()))
                         or (d["kind"] == "manufacturer" and d["year"] is None and int(d["published"][:4]) in (years | market_years.get(d["market"], set()))))
                    and (not qualifiers[(brand, family)] or all(q in folded(d["model"]) for q in qualifiers[(brand, family)]))]
            preferred_market = "USA" if re.search(r"americ|etats.unis|\busa\b", folded(question)) else "France"
            explicit_market = bool(re.search(r"franc|americ|etats.unis|\busa\b", folded(question)))
            if not both_markets and (explicit_market or any(d["kind"] == "manufacturer" and d["market"] == preferred_market for _, d in docs)):
                docs = [(i, d) for i, d in docs if d["kind"] != "manufacturer" or d["market"] == preferred_market]
            scopes.append({"brand": brand, "family": family, "passages_available": len(docs)})
            if not docs:
                missing.append({"message": f"Information non établie pour {brand} {max(matches, key=len)} : modèle, année ou édition non documenté par les sources disponibles."})
            candidates.extend(docs)
        if not candidates:
            return {"passages": [], "missing": missing, "scopes": scopes, "timing": {"retrieval_seconds": time.perf_counter() - started}}
        encoding_started = time.perf_counter()
        temporal = bool(re.search(r"\b(?:annee\w*|dates?|millesim\w*|present\w*|annonc\w*|livraison\w*|depuis)\b", folded(question)))
        temporal_query = ["Date de présentation et commercialisation du modèle, premières livraisons, année et millésime."] if temporal else []
        queries = list(dict.fromkeys([question, *temporal_query, *[s.strip() for s in re.split(r"[?!;]", question) if len(s.strip()) > 25]]))[:3]
        query_vectors = []
        for query in dict.fromkeys(queries):
            semantic = query
            for alias in sorted({a for s in self.sources for a in s["aliases"]} | {s["brand"] for s in self.sources}, key=len, reverse=True):
                match = literal_name(alias, semantic)
                if match:
                    semantic = semantic[:match.start()] + " " + semantic[match.end():]
            semantic = re.sub(r"\b(?:19|20)\d{2}\b", " ", semantic)
            if re.search(r"\b(?:automati\w*|embray\w*|rapports?|transmissions?|dct|asa|boites?)\b", folded(query)):
                semantic += " transmission boîte de vitesses embrayage automatique manual DCT ASA"
            query_vectors.append(normalized_vectors([self.encode(semantic if len(semantic.strip()) > 15 else query)], 1)[0])
        scores = self.vectors[[i for i, _ in candidates]] @ np.asarray(query_vectors).T
        encoding_seconds = time.perf_counter() - encoding_started
        us = bool(re.search(r"americ|etats.unis|\busa\b", folded(question)))
        selected, context_chars = [], 0
        for scope in scopes:
            ranked_queries = []
            for query_index in range(len(query_vectors)):
                dense = sorted([(float(scores[j, query_index]) + (0.12 if d["kind"] == "manufacturer" else 0)
                              + (0.04 if d.get("market") == ("USA" if us else "France") else 0), d)
                             for j, (_, d) in enumerate(candidates) if d["brand"] == scope["brand"] and d["family"] == scope["family"]],
                            key=lambda pair: (-pair[0], pair[1]["id"]))[:16]
                reranked = self.rerank(queries[min(query_index, len(queries)-1)], [d["model"] + "\n" + d["section"] + "\n" + d["original_text"] for _, d in dense]) if dense else []
                ranked_queries.append(sorted([(s + (0.05 if d["kind"] == "manufacturer" else 0), d) for s, (_, d) in zip(reranked, dense)], key=lambda pair: (-pair[0], pair[1]["id"])))
            pool = [r[0] for r in ranked_queries if r] + (ranked_queries[0][:4] if ranked_queries else [])
            if both_markets:
                for market in ["France", "USA"]:
                    first = next((pair for pair in ranked_queries[0] if pair[1]["kind"] == "manufacturer" and pair[1]["market"] == market), None)
                    if first:
                        pool.insert(0, first)
            chosen = list({doc["id"]: (score, doc) for score, doc in pool}.values())[:4]
            for score, doc in chosen:
                if context_chars + len(doc["original_text"]) > 7000:
                    break
                selected.append(doc)
                context_chars += len(doc["original_text"])
        validate_started = time.perf_counter()
        ids = {d["object_id"] for d in selected if d["kind"] == "catalogue"}
        constructor = {d["object_id"] for d in selected if d["kind"] == "manufacturer"}
        bindings = [b for s in self.sources if s["id"] in constructor for b in s["sql_bindings"]]
        ids.update(b["id"] for b in bindings)
        actual = {r["id"]: r for r in _rows(conn, "SELECT id,brand,model,year,source_url,source_sha256,record FROM technical_fiches WHERE id=ANY(%s)", [list(ids)])}
        for binding in bindings:
            row = actual.get(binding["id"])
            if not row or any(row[k] != binding[k] for k in ["brand", "model", "year", "source_sha256"]):
                raise ValueError("Constructor catalogue binding no longer matches live SQL")
        passages = []
        for doc in selected:
            if doc["kind"] == "catalogue":
                row = actual.get(doc["object_id"])
                if (not row or any(row[k] != doc[k] for k in ["brand", "model", "year", "source_sha256", "source_url"])
                        or not any(s["section"] == doc["section"] and s["text"] == doc["original_text"] for s in row["record"]["technical_sections"])):
                    raise ValueError("Catalogue passage no longer matches live SQL")
            passages.append({"id": f"P{len(passages)+1}", "passage_id": doc["id"], "identity": {k: doc[k] for k in ["object_id", "brand", "model", "year"]},
                "section": doc["section"], "text": doc["original_text"], "market": doc["market"], "published": doc["published"],
                "source_url": doc["source_url"], "source_sha256": doc["source_sha256"], "publisher": doc["publisher"], "kind": doc["kind"]})
        return {"passages": passages, "missing": missing, "scopes": scopes,
                "timing": {"query_encoding_and_ranking_seconds": encoding_seconds,
                           "sql_validation_seconds": time.perf_counter() - validate_started,
                           "retrieval_seconds": time.perf_counter() - started}}


@lru_cache(maxsize=1)
def get_corpus():
    return Corpus(os.getenv("BIKEFINDER_EXPERIMENT_INDEX", str(ROOT / "data/technical/catalog-experiment-20261014/index-v3")))
