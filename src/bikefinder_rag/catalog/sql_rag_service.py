"""Common read-only catalogue tools over a frozen SQLite source and projection.

Preparation is separate from requests. No model tool can write the source or
projection, execute arbitrary SQL, download models, or access external pages.
"""
from __future__ import annotations

from collections import defaultdict
import hashlib
import itertools
import json
import math
from pathlib import Path
import re
import sqlite3
import time
import uuid

from bikefinder_rag.agent.sql_rag_contract import FIELDS, TOOLS, VERSION
from bikefinder_rag.catalog.enriched import folded
from bikefinder_rag.catalog.measures import project


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


class ArgumentError(ValueError):
    """An invalid request with a bounded, machine-readable repair hint."""

    def __init__(self, message, **details):
        super().__init__(message)
        self.details = details


def validate(schema, value, path="arguments"):
    """Validate the closed JSON-schema subset used by our six tool contracts."""
    kind = schema.get("type")
    valid = {"object": lambda: isinstance(value, dict), "array": lambda: isinstance(value, list),
             "string": lambda: isinstance(value, str), "integer": lambda: type(value) is int,
             "number": lambda: type(value) in (int, float) and math.isfinite(value),
             "boolean": lambda: type(value) is bool}
    if kind and not valid[kind]():
        raise ArgumentError(f"{path}: expected {kind}", argument=path, expected_type=kind)
    if "enum" in schema and value not in schema["enum"]:
        raise ArgumentError(f"{path}: unsupported value", argument=path, allowed_values=schema["enum"])
    if kind == "object":
        props = schema["properties"]
        if set(value) - set(props) or set(schema.get("required", [])) - set(value):
            raise ArgumentError(f"{path}: unsupported or missing keys", argument=path,
                                allowed_keys=list(props), missing_keys=sorted(set(schema.get("required", [])) - set(value)),
                                unsupported_keys=sorted(set(value) - set(props)))
        for key, child in value.items():
            validate(props[key], child, f"{path}.{key}")
    elif kind == "array":
        if not schema.get("minItems", 0) <= len(value) <= schema.get("maxItems", math.inf):
            raise ValueError(f"{path}: invalid array length")
        for child in value:
            validate(schema["items"], child, path + "[]")
        if schema.get("uniqueItems") and len({canonical(v) for v in value}) != len(value):
            raise ValueError(f"{path}: duplicate items")
    elif kind == "string":
        if not value.strip() or not schema.get("minLength", 0) <= len(value) <= schema.get("maxLength", math.inf):
            raise ValueError(f"{path}: invalid string length")
    elif kind in ("number", "integer"):
        if not schema.get("minimum", -math.inf) <= value <= schema.get("maximum", math.inf):
            raise ValueError(f"{path}: value out of bounds")


def identity_match(query, name):
    """Normalize model spelling but preserve numeric and short variant tokens."""
    target = folded(name)
    target = re.sub(r"(?<=\d)[ \u00a0\u202f](?=\d{3}(?:\D|$))", "", target)
    words = re.findall(r"[a-z0-9]+", target)
    tokens = re.findall(r"[a-z0-9]+(?:[-_/][a-z0-9]+)*", folded(query))
    for token in tokens:
        code = re.sub(r"[^a-z0-9]", "", token)
        if code.isdigit():
            # Keep separators: compacting "650 2020" must not become 6502020.
            if not re.search(r"(?<!\d)" + re.escape(code) + r"(?!\d)", target):
                return False
        elif len(code) == 1:
            if not re.search(r"\b" + re.escape(code) + r"\b", target):
                return False
        elif code.isalpha() and len(code) <= 3:
            if not re.search(r"(?<![a-z])" + re.escape(code) + r"(?![a-z])", target):
                return False
        elif re.search(r"[a-z]", code) and re.search(r"\d", code):
            parts = re.findall(r"[a-z]+|\d+", code)
            pattern = r"(?<![a-z0-9])" + r"[\s\-_/]*".join(map(re.escape, parts)) + r"(?![a-z0-9])"
            if not re.search(pattern, target):
                return False
        else:
            # A compound may be written together or as whole adjacent words.
            # Do not manufacture a word from a suffix and the next word's prefix
            # ("Twin Gold" -> "wing"), or by removing intervening numbers.
            if any(code in word for word in words):
                continue
            joined_match = False
            for start in range(len(words)):
                joined = ""
                for word in words[start:]:
                    if not word.isalpha():
                        break
                    joined += word
                    if len(joined) >= len(code):
                        joined_match = joined == code
                        break
                if joined_match:
                    break
            if not joined_match:
                return False
    return bool(tokens)


def standard_identity_match(query, brand, model, year):
    """A named base variant requires an exact designation, never a shortest name."""
    normalized = folded(query)
    if not re.search(r"\bstandard\b", normalized):
        return False
    stripped = re.sub(r"\bstandard\b", " ", normalized)
    compact = lambda text: re.sub(r"[^a-z0-9]", "", folded(str(text)))
    identities = (model, f"{brand} {model}", f"{model} {year}", f"{brand} {model} {year}")
    return compact(stripped) in {compact(identity) for identity in identities}


def selector_key(value):
    """Case/accent/whitespace normalization; punctuation is still meaningful."""
    return " ".join(folded(value).split())


def literal_match(term, text):
    tokens = re.findall(r"\w+", folded(term))
    if not tokens:
        return False
    return bool(re.search(r"(?<!\w)" + r"\W+".join(map(re.escape, tokens)) + r"(?!\w)", folded(text)))


def field_rows(record, fields):
    """Keep original numeric evidence, including ranges the projection rejects."""
    def belongs(row, field):
        label, value = folded(row["label"]), folded(row["value"])
        if field == "seat_height_mm":
            return label.startswith("hauteur de selle")
        if field == "weight_dry_kg":
            return "poids a sec" in label
        if field == "weight_wet_kg":
            return "poids tous pleins faits" in label or "poids en ordre de marche" in label
        if field == "autonomy_km":
            return "autonomie" in label
        if field == "catalog_price_eur":
            return row["section"] == "Tarifs" and label == "france — version de base"
        units = {"displacement_ccm": r"\bcc\b", "power_ch": r"\bch\b", "torque_nm": r"\b(?:nm|mkg)\b"}
        return row["section"] == "Moteur" and not label.startswith("rapport") and bool(re.search(units.get(field, r"(?!)"), value))
    return [r for r in record["spec_rows"] if any(belongs(r, field) for field in fields)]


def prepare_catalog(snapshot, destination):
    """Build an immutable derived SQL projection without changing the source."""
    snapshot, destination = Path(snapshot).resolve(), Path(destination).resolve()
    if destination.exists():
        raise FileExistsError("Choose a new projection path; existing projections are immutable")
    destination.parent.mkdir(parents=True, exist_ok=True)
    source_sha = digest(snapshot)
    temporary = destination.with_name(destination.name + "." + uuid.uuid4().hex + ".tmp")
    source = sqlite3.connect(snapshot.as_uri() + "?mode=ro", uri=True)
    source.row_factory = sqlite3.Row
    source.execute("PRAGMA query_only=ON")
    target = sqlite3.connect(temporary)
    count = passages = 0
    try:
        target.execute("CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT NOT NULL)")
        numeric = ",".join(f"{key} REAL" for key in FIELDS)
        target.execute(f"CREATE TABLE fiches(id TEXT PRIMARY KEY,brand TEXT,model TEXT,year INTEGER,source_url TEXT,source_sha256 TEXT,record TEXT,proof TEXT,{numeric})")
        target.execute("CREATE TABLE equipment(object_id TEXT,name TEXT,status TEXT,decision TEXT,PRIMARY KEY(object_id,name))")
        target.execute("CREATE TABLE passages(id TEXT PRIMARY KEY,object_id TEXT,section TEXT,text TEXT,text_sha256 TEXT)")
        for row in source.execute("SELECT * FROM objects ORDER BY id"):
            record = json.loads(row["record"])
            values, proof = project(record)
            target.execute("INSERT INTO fiches VALUES(" + ",".join("?" for _ in range(8 + len(FIELDS))) + ")",
                           (row["id"], row["brand"], row["model"], row["year"], row["url"], row["source_sha256"], row["record"], canonical(proof),
                            *[values["price_eur" if f == "catalog_price_eur" else f] for f in FIELDS]))
            for n, p in enumerate(record["technical_sections"]):
                target.execute("INSERT INTO passages VALUES(?,?,?,?,?)", (f"{row['id']}:section:{n}", row["id"], p["section"], p["text"], hashlib.sha256(p["text"].encode()).hexdigest()))
                passages += 1
            count += 1
        target.executemany("INSERT INTO equipment VALUES(?,?,?,?)", source.execute("SELECT object_id,equipment,status,decision FROM equipment"))
        target.execute("CREATE INDEX identity_idx ON fiches(brand,year,model,id)")
        target.execute("CREATE INDEX equipment_idx ON equipment(name,status,object_id)")
        target.execute("CREATE INDEX passage_idx ON passages(object_id,section,id)")
        meta = {"source_sha256": source_sha, "contract_version": VERSION,
                "parser_sha256": digest(Path(__file__).with_name("measures.py")),
                "fiches": str(count), "passages": str(passages)}
        target.executemany("INSERT INTO meta VALUES(?,?)", meta.items())
        target.commit()
        if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok" or digest(snapshot) != source_sha:
            raise ValueError("Source changed or derived database failed integrity check")
        target.close()
        # Exclusive create preserves immutability even if another preparer won a race.
        import os
        os.link(temporary, destination)
        temporary.unlink()
        manifest = {**meta, "projection_sha256": digest(destination), "source": str(snapshot)}
        destination.with_suffix(destination.suffix + ".json").write_text(canonical(manifest) + "\n")
        return manifest
    finally:
        source.close()
        target.close()
        temporary.unlink(missing_ok=True)


class CatalogService:
    def __init__(self, snapshot, projection, *, index=None, encoder=None, sql_timeout=3):
        self.snapshot, self.projection = Path(snapshot).resolve(), Path(projection).resolve()
        manifest = json.loads(self.projection.with_suffix(self.projection.suffix + ".json").read_text())
        self.snapshot_id = digest(self.snapshot)
        if manifest["source_sha256"] != self.snapshot_id or manifest["projection_sha256"] != digest(self.projection):
            raise ValueError("Source or projection checksum changed")
        if manifest["parser_sha256"] != digest(Path(__file__).with_name("measures.py")) or manifest["contract_version"] != VERSION:
            raise ValueError("Projection parser/contract changed; prepare a new projection")
        self.conn = sqlite3.connect(self.projection.as_uri() + "?mode=ro", uri=True)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA query_only=ON")
        self.conn.create_function("identity_match", 2, identity_match, deterministic=True)
        self.conn.create_function("standard_identity_match", 4, standard_identity_match, deterministic=True)
        self.conn.create_function("literal_match", 2, literal_match, deterministic=True)
        self.conn.create_function("folded", 1, folded, deterministic=True)
        self.sql_timeout = sql_timeout
        self.cursors = {}
        self.equipment_names = [r[0] for r in self.conn.execute("SELECT DISTINCT name FROM equipment ORDER BY name")]
        self.section_names = [r[0] for r in self.conn.execute("SELECT DISTINCT section FROM passages ORDER BY section")]
        self.equipment_aliases = {alias: "shifter" for alias in ["quickshifter", "quick shifter", "quick-shifter"]
                                  if "shifter" in self.equipment_names}
        self.index = None
        if index is not None:
            from bikefinder_rag.catalog.sql_rag_retrieval import FrozenRetrieval
            self.index = FrozenRetrieval(index, self, encoder=encoder)

    def close(self):
        self.conn.close()

    def _sql(self, sql, parameters=()):
        deadline = time.monotonic() + self.sql_timeout
        self.conn.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
        try:
            return [dict(r) for r in self.conn.execute(sql, parameters)]
        finally:
            self.conn.set_progress_handler(None, 0)

    def _envelope(self, payload=None, *, status="ok", evidence=(), missing=(), scope=None, searched=0, passage_count=None, pagination=None):
        return {"status": status, "snapshot_id": self.snapshot_id, "payload": payload or {}, "evidence": list(evidence),
                "missing": list(missing), "coverage": {"requested_scope": scope or {}, "searched_fiches": searched,
                "searched_passages": passage_count, "exhaustive": True, "truncation_reason": None},
                "pagination": pagination or {"returned": 0, "total": 0, "next_cursor": None}, "timing_ms": 0}

    def _restore_cursor(self, name, arguments):
        if "cursor" not in arguments:
            return arguments, 0
        saved = self.cursors.get(arguments["cursor"])
        if not saved or saved["name"] != name:
            raise ValueError("Cursor unavailable for this service/snapshot/tool")
        for key, value in arguments.items():
            if key != "cursor" and (key not in saved["args"] or canonical(value) != canonical(saved["args"][key])):
                raise ValueError("Cursor criteria changed")
        return dict(saved["args"]), saved["offset"]

    def _normalize_selectors(self, arguments):
        """Normalize only values with one registered target; do not guess names."""
        args = dict(arguments)
        issues, allowed = [], {}

        def normalize(value, kind, names, aliases=None):
            if value in names:
                return value
            key = selector_key(value)
            candidates = [name for name in names if selector_key(name) == key]
            if not candidates and aliases and key in aliases:
                candidates = [aliases[key]]
            if len(candidates) == 1:
                return candidates[0]
            # Suggestions are literal prefixes/contained phrases, never fuzzy substitutions.
            suggestions = candidates or [name for name in names
                                         if key in selector_key(name) or selector_key(name) in key][:3]
            issues.append({"argument": kind, "value": value, "suggested_values": suggestions})
            allowed[kind] = names
            return value

        if "sections" in args:
            args["sections"] = [normalize(value, "sections", self.section_names) for value in args["sections"]]
        if "equipment_names" in args:
            args["equipment_names"] = [normalize(value, "equipment_names", self.equipment_names, self.equipment_aliases)
                                       for value in args["equipment_names"]]
        if "equipment_filters" in args:
            args["equipment_filters"] = [{**criterion, "name": normalize(criterion["name"], "equipment_names",
                                                                         self.equipment_names, self.equipment_aliases)}
                                         for criterion in args["equipment_filters"]]
        if issues:
            raise ArgumentError("Unsupported or ambiguous section/equipment name; use a registered name.",
                                invalid_values=issues, allowed_values=allowed,
                                next_action="Correct the selectors; no catalogue search was performed.")
        return args

    def _page(self, name, args, offset, total, returned, page_size):
        cursor = None
        if offset + returned < total:
            cursor = uuid.uuid4().hex
            self.cursors[cursor] = {"name": name, "args": dict(args), "offset": offset + page_size}
        return {"returned": returned, "total": total, "next_cursor": cursor}

    def _validate_scope_ids(self, scope):
        requested = scope.get("object_ids", [])
        if not requested:
            return
        found = {row["id"] for row in self._sql("SELECT id FROM fiches WHERE id IN (" +
                                                ",".join("?" for _ in requested) + ")", requested)}
        unknown = [oid for oid in requested if oid not in found]
        if unknown:
            raise ArgumentError("The requested scope contains catalogue IDs that do not exist; no count or selection was produced.",
                                argument="arguments.scope.object_ids", unknown_object_ids=unknown,
                                next_action="Reuse the exact IDs from a prior tool result or resolve_models. Do not drop, guess or substitute an ID; the scope must be corrected before comparing counts.")

    def execute(self, name, arguments):
        started = time.perf_counter()
        definition = next((t for t in TOOLS if t["name"] == name), None)
        try:
            if definition is None:
                raise ValueError("Unknown tool")
            validate(definition["input_schema"], arguments)
            arguments = self._normalize_selectors(arguments)
            validate(definition["input_schema"], arguments)
            if name == "query_catalog" and arguments.get("mode") == "count" and "cursor" in arguments:
                raise ValueError("Counts do not accept a cursor")
            if name == "search_passages" and arguments["mode"] == "hybrid" and ("cursor" in arguments or "literal_terms" in arguments):
                raise ValueError("Hybrid retrieval does not accept cursor or literal_terms")
            args, offset = self._restore_cursor(name, arguments)
            scope = args.get("scope", {})
            if scope.get("min_year", 1800) > scope.get("max_year", 2199):
                raise ValueError("Year bounds are reversed")
            self._validate_scope_ids(scope)
            result = getattr(self, "_" + name)(args, offset)
        except (ValueError, TypeError, KeyError) as exc:
            result = self._envelope({"error": str(exc), **getattr(exc, "details", {})}, status="invalid_arguments")
            result["coverage"].update(exhaustive=False, truncation_reason="invalid_arguments")
        except (sqlite3.Error, TimeoutError, OSError) as exc:
            result = self._envelope({"error": type(exc).__name__}, status="unavailable")
            result["coverage"].update(exhaustive=False, truncation_reason="execution_unavailable")
        result["timing_ms"] = round((time.perf_counter() - started) * 1000, 3)
        return result

    def _scope(self, scope, alias="f"):
        clauses, params = ["1=1"], []
        for field, op, value in [("brand", "=", scope.get("brand")), ("year", ">=", scope.get("min_year")), ("year", "<=", scope.get("max_year"))]:
            if value is not None:
                clauses.append(f"folded({alias}.brand)=folded(?)" if field == "brand" else f"{alias}.{field} {op} ?")
                params.append(value)
        for token in scope.get("model_tokens", []):
            clauses.append(f"identity_match(?,{alias}.model)")
            params.append(token)
        if scope.get("object_ids"):
            clauses.append(f"{alias}.id IN (" + ",".join("?" for _ in scope["object_ids"]) + ")")
            params.extend(scope["object_ids"])
        return clauses, params

    def _identity(self, row):
        return {k: row[k] for k in ["id", "brand", "model", "year", "source_url", "source_sha256"]}

    def _describe_catalog(self, args, offset):
        fields = {f: {"unit": unit, "known": self._sql(f"SELECT count(*) n FROM fiches WHERE {f} IS NOT NULL")[0]["n"]} for f, unit in FIELDS.items()}
        count = self._sql("SELECT count(*) n FROM fiches")[0]["n"]
        passages = self._sql("SELECT count(*) n FROM passages")[0]["n"]
        return self._envelope({"snapshot_id": self.snapshot_id, "fiche_count": count, "passage_count": passages,
            "fields": fields, "equipment_names": self.equipment_names, "section_names": self.section_names,
            "selector_normalization": {"rule": "Case, accents and whitespace normalize only to an unambiguous registered name.",
                                       "equipment_aliases": self.equipment_aliases},
            "supported_filters": ["brand", "model_tokens", "year_bounds", "object_ids", "numeric", "equipment_status", "missing_numeric"],
            "unsupported": ["current_used_price", "riding_category", "market_coverage", "individual_homologation"]}, searched=count)

    def _resolve_models(self, args, offset):
        scope_clauses, scope_params = self._scope(args.get("scope", {}))
        clauses, params = list(scope_clauses), list(scope_params)
        clauses.append("identity_match(?,f.brand || ' ' || f.model || ' ' || f.year)")
        params.append(args["query"])
        base = " FROM fiches f WHERE " + " AND ".join(clauses)
        total = self._sql("SELECT count(*) n" + base, params)[0]["n"]
        resolution = None
        if not total and re.search(r"\bstandard\b", folded(args["query"])):
            base = " FROM fiches f WHERE " + " AND ".join([*scope_clauses, "standard_identity_match(?,f.brand,f.model,f.year)"])
            params = [*scope_params, args["query"]]
            total = self._sql("SELECT count(*) n" + base, params)[0]["n"]
            if total:
                resolution = {"requested_query": args["query"], "normalization": "standard_to_exact_base_designation",
                              "rule": "After removing 'standard', the full model designation must match exactly; years remain separate."}
        size = args.get("page_size", 20)
        rows = self._sql("SELECT f.*" + base + " ORDER BY year DESC,brand,model,id LIMIT ? OFFSET ?", [*params, size, offset])
        evidence = [{"evidence_id": r["id"] + ":identity", "kind": "source_row", **self._identity(r)} for r in rows]
        payload = {"candidates": [self._identity(r) for r in rows], "total_candidates": total, "ambiguity": total > 1}
        if resolution:
            payload["resolution"] = resolution
        if not total:
            payload["next_action"] = "Report this identity as missing or ask for clarification. Removing a variant/year token changes the requested identity."
        return self._envelope(payload,
            status="not_found" if not total else "ambiguous" if total > 1 else "ok", evidence=evidence,
            scope=args.get("scope"), searched=self._sql("SELECT count(*) n FROM fiches")[0]["n"],
            pagination=self._page("resolve_models", args, offset, total, len(rows), size))

    def _criteria(self, args):
        clauses, params = self._scope(args.get("scope", {}))
        for c in args.get("numeric_filters", []):
            clauses.append(f"f.{c['field']} {c['op']} ?")
            params.append(c["value"])
        for c in args.get("equipment_filters", []):
            if c["status"] == "unknown":
                clauses.append("NOT EXISTS(SELECT 1 FROM equipment e WHERE e.object_id=f.id AND e.name=? AND e.status!='unknown')")
                params.append(c["name"])
            else:
                clauses.append("EXISTS(SELECT 1 FROM equipment e WHERE e.object_id=f.id AND e.name=? AND e.status=?)")
                params.extend([c["name"], c["status"]])
        if args.get("missing_fields"):
            clauses.append("(" + " OR ".join(f"f.{f} IS NULL" for f in args["missing_fields"]) + ")")
        return " FROM fiches f WHERE " + " AND ".join(clauses), params

    def _query_catalog(self, args, offset):
        base, params = self._criteria(args)
        total = self._sql("SELECT count(*) n" + base, params)[0]["n"]
        aggregate_args = {k: v for k, v in args.items() if k not in {"cursor", "page_size", "mode", "fields", "sort"}}
        aggregate_id = "aggregate:" + hashlib.sha256((self.snapshot_id + canonical(aggregate_args)).encode()).hexdigest()[:24]
        evidence = [{"evidence_id": aggregate_id, "kind": "aggregate", "snapshot_id": self.snapshot_id,
                     "criteria": aggregate_args, "sql": "SELECT f.id" + base, "parameters": params, "count": total}]
        unknown = []
        for criterion in args.get("numeric_filters", []):
            scope_clauses, scope_params = self._scope(args.get("scope", {}))
            n = self._sql("SELECT count(*) n FROM fiches f WHERE " + " AND ".join([*scope_clauses, f"f.{criterion['field']} IS NULL"]), scope_params)[0]["n"]
            unknown.append({"criterion": criterion, "unknown_in_requested_scope": n})
        for criterion in args.get("equipment_filters", []):
            scope_clauses, scope_params = self._scope(args.get("scope", {}))
            n = self._sql("SELECT count(*) n FROM fiches f WHERE " + " AND ".join([*scope_clauses,
                "NOT EXISTS(SELECT 1 FROM equipment e WHERE e.object_id=f.id AND e.name=? AND e.status!='unknown')"]), [*scope_params, criterion["name"]])[0]["n"]
            unknown.append({"criterion": criterion, "unknown_in_requested_scope": n})
        rows = []
        size = args.get("page_size", 20)
        if args["mode"] == "list":
            sorts = args.get("sort", [{"field": "year", "direction": "desc"}, {"field": "brand", "direction": "asc"}, {"field": "model", "direction": "asc"}])
            order = ",".join(f"f.{s['field']} IS NULL,f.{s['field']} {s['direction']}" for s in sorts) + ",f.id"
            selected = self._sql("SELECT f.*" + base + " ORDER BY " + order + " LIMIT ? OFFSET ?", [*params, size, offset])
            fields = args.get("fields", sorted({c["field"] for c in args.get("numeric_filters", [])}))
            for row in selected:
                fiche, proof, _ = self._fiche(row, fields, [], [e["name"] for e in args.get("equipment_filters", [])], compact=True)
                rows.append(fiche)
                evidence.extend(proof)
        return self._envelope({"total_matches": total, "rows": rows, "aggregate_evidence_id": aggregate_id,
            "unknown_exclusions": unknown}, evidence=evidence, scope=args.get("scope"),
            searched=self._sql("SELECT count(*) n FROM fiches f WHERE " + " AND ".join(self._scope(args.get("scope", {}))[0]), self._scope(args.get("scope", {}))[1])[0]["n"],
            pagination=self._page("query_catalog", args, offset, total, len(rows), size) if args["mode"] == "list" else {"returned": 0, "total": total, "next_cursor": None})

    def _fiche(self, row, fields, sections, equipment_names, compact=False):
        record, projected_proof = json.loads(row["record"]), json.loads(row["proof"])
        identity = self._identity(row)
        evidence, missing, measures = [], [], {}
        original = record["spec_rows"]
        for field in fields:
            key = "price_eur" if field == "catalog_price_eur" else field
            ids = []
            for n, raw in enumerate(original):
                if raw in projected_proof.get(key, []):
                    eid = f"{row['id']}:row:{n}"
                    ids.append(eid)
                    evidence.append({"evidence_id": eid, "kind": "source_row", "object_id": row["id"], "source_url": row["source_url"], "source_sha256": row["source_sha256"], "row": raw})
            measures[field] = {"value": row[field], "unit": FIELDS[field], "evidence_ids": ids,
                "qualification": "estimated_not_measured" if field == "autonomy_km" else "dated_catalogue_price" if field == "catalog_price_eur" else None}
            if row[field] is None:
                missing.append({"subject": row["id"], "field": field, "reason": "No unambiguous comparable numeric value"})
        passages = []
        for p in self._sql("SELECT * FROM passages WHERE object_id=? ORDER BY id", [row["id"]]):
            if sections is not None and p["section"] not in sections:
                continue
            p = {**p, **{k: identity[k] for k in ["brand", "model", "year", "source_url", "source_sha256"]}, "evidence_id": p["id"], "kind": "passage"}
            passages.append(p)
            evidence.append(p)
        equipment = []
        for name in equipment_names:
            found = self._sql("SELECT * FROM equipment WHERE object_id=? AND name=?", [row["id"], name])
            entry = {"name": name, "status": found[0]["status"] if found else "unknown", "decision": json.loads(found[0]["decision"]) if found else None}
            eid = row["id"] + ":equipment:" + hashlib.sha256(name.encode()).hexdigest()[:12]
            entry["evidence_ids"] = [eid]
            evidence.append({"evidence_id": eid, "kind": "source_row", "object_id": row["id"], "source_url": row["source_url"], "source_sha256": row["source_sha256"], "equipment": entry})
            equipment.append(entry)
            if entry["status"] == "unknown":
                missing.append({"subject": row["id"], "field": name, "reason": "Equipment status unknown"})
        fiche = {"identity": identity, "measures": measures, "equipment": equipment, "passages": passages}
        if not compact:
            selected_rows = field_rows(record, fields)
            fiche["original_rows"] = original if sections is None else [r for r in original if r in selected_rows or r["section"] in sections]
        return fiche, evidence, missing

    def _get_fiches(self, args, offset):
        fiches, evidence, missing = [], [], []
        for oid in args["object_ids"]:
            rows = self._sql("SELECT * FROM fiches WHERE id=?", [oid])
            if not rows:
                missing.append({"subject": oid, "field": "identity", "reason": "Unknown fiche ID; no substitution"})
                continue
            any_selector = any(k in args for k in ["fields", "sections", "equipment_names"])
            fields = args.get("fields", [] if any_selector else list(FIELDS))
            sections = args.get("sections")
            if "fields" in args and "sections" not in args:
                record = json.loads(rows[0]["record"])
                sections = sorted({r["section"] for r in field_rows(record, fields)})
            if "equipment_names" in args and "sections" not in args and "fields" not in args:
                sections = []
            names = args.get("equipment_names", [] if any_selector else [e["name"] for e in self._sql("SELECT name FROM equipment WHERE object_id=? ORDER BY name", [oid])])
            fiche, proof, unknown = self._fiche(rows[0], fields, sections, names)
            fiches.append(fiche)
            evidence.extend(proof)
            missing.extend(unknown)
        return self._envelope({"fiches": fiches}, status="not_found" if not fiches else "partial" if any(m["field"] == "identity" for m in missing) else "ok",
            evidence=evidence, missing=missing, scope={"object_ids": args["object_ids"]}, searched=len(fiches))

    def _compare_fiches(self, args, offset):
        result = self._get_fiches({**args, "sections": []}, offset)
        fiches = result["payload"]["fiches"]
        deltas = []
        for first, second in itertools.combinations(fiches, 2):
            for field in args["fields"]:
                a, b = first["measures"][field], second["measures"][field]
                deltas.append({"first_id": first["identity"]["id"], "second_id": second["identity"]["id"], "field": field,
                    "second_minus_first": None if a["value"] is None or b["value"] is None else b["value"] - a["value"],
                    "evidence_ids": a["evidence_ids"] + b["evidence_ids"]})
        result["payload"] = {"matrix": fiches, "deltas": deltas}
        return result

    def _search_passages(self, args, offset):
        clauses, params = self._scope(args.get("scope", {}))
        if args.get("sections"):
            clauses.append("p.section IN (" + ",".join("?" for _ in args["sections"]) + ")")
            params.extend(args["sections"])
        base = " FROM passages p JOIN fiches f ON f.id=p.object_id WHERE " + " AND ".join(clauses)
        searched = self._sql("SELECT count(*) n" + base, params)[0]["n"]
        fiche_count = self._sql("SELECT count(DISTINCT f.id) n" + base, params)[0]["n"]
        limit = args.get("limit", 8)
        if args["mode"] == "literal":
            if not args.get("literal_terms"):
                raise ArgumentError("Literal search requires literal_terms", argument="arguments.literal_terms",
                                    required="One to eight explicit words/phrases, matched with OR within the requested scope.",
                                    next_action="Supply literal_terms; use hybrid mode for a natural-language relevance query.")
            base += " AND (" + " OR ".join("literal_match(?,p.text)" for _ in args["literal_terms"]) + ")"
            params.extend(args["literal_terms"])
            total = self._sql("SELECT count(*) n" + base, params)[0]["n"]
            direction = "DESC" if args.get("order") == "year_desc" else "ASC"
            rows = self._sql("SELECT p.*,f.brand,f.model,f.year,f.source_url,f.source_sha256" + base + f" ORDER BY f.year {direction},f.brand,f.model,p.id LIMIT ? OFFSET ?", [*params, limit, offset])
            page = self._page("search_passages", args, offset, total, len(rows), limit)
            diagnostics = {"mode": "literal", "total_literal_matches": total, "earliest_claim_scope": "Selected terms/sections/catalogue only, not official launch"}
        else:
            if self.index is None:
                return self._envelope({"error": "Validated dense/lexical index unavailable"}, status="unavailable", scope=args.get("scope"))
            ids = [r["id"] for r in self._sql("SELECT p.id" + base, params)]
            rows, diagnostics = self.index.search(args["query"], ids, limit)
            if args.get("order") in {"year_asc", "year_desc"}:
                rows.sort(key=lambda p: (p["year"], p["model"], p["id"]), reverse=args["order"] == "year_desc")
            total = len(rows)
            page = {"returned": total, "total": None, "next_cursor": None}
        evidence = [{**p, "evidence_id": p["id"], "kind": "passage"} for p in rows]
        return self._envelope({"passages": evidence, "retrieval": diagnostics}, status="ok" if rows else "not_found", evidence=evidence,
            scope=args.get("scope"), searched=fiche_count, passage_count=searched, pagination=page)
