"""Deterministic catalogue views: preserve facts once, retain raw receipts elsewhere."""
from copy import deepcopy

from bikefinder_rag.catalog.sql_rag_service import canonical


VIEW_VERSION = "catalogue-compact-v2"
AUDIT_KEYS = {"source_sha256", "input_hash", "text_sha256", "sha256", "timing_ms"}


def compact_result(result):
    """Deduplicate source payloads without dropping identities, values or evidence.

    Equipment decisions and original passages remain in the evidence table. The
    payload points to them by evidence ID instead of repeating the same text.
    Hashes and generated SQL are audit material in the unchanged raw receipt.
    """
    if result.get("view", {}).get("format") == VIEW_VERSION:
        return deepcopy(result)
    if result.get("view", {}).get("format"):
        raise ValueError("Recompacting an older context format requires the original tool receipt")
    def auditless(value):
        if isinstance(value, dict):
            return {k: auditless(v) for k, v in value.items() if k not in AUDIT_KEYS}
        if isinstance(value, list):
            return [auditless(v) for v in value]
        return value

    view = auditless(deepcopy(result))
    evidence = {}
    for proof in view.get("evidence", []):
        eid = proof["evidence_id"]
        if eid in evidence and evidence[eid] != proof:
            raise ValueError("Conflicting source proofs for the same evidence ID")
        evidence[eid] = proof
    sources, policies, inline_identities = {}, {}, {}

    def collect_sources(value):
        if isinstance(value, dict):
            if all(k in value for k in ("brand", "model", "year", "source_url")):
                oid = value.get("object_id") or value.get("id")
                if oid:
                    source = {k: value[k] for k in ("brand", "model", "year", "source_url")}
                    if oid in sources and sources[oid] != source:
                        raise ValueError("Conflicting source identity for the same catalogue object")
                    sources[oid] = source
                    if value.get("id") == oid and "kind" not in value:
                        inline_identities[oid] = value
            for child in value.values():
                collect_sources(child)
        elif isinstance(value, list):
            for child in value:
                collect_sources(child)

    collect_sources(view.get("payload", {}))
    collect_sources(view.get("evidence", []))

    # Equipment decisions expose original source passages with their own stable
    # IDs. Those IDs are already visible to the model and must be citable. Only
    # this known source-bearing path is promoted, never an arbitrary nested id.
    candidates = {}
    for parent in list(evidence.values()):
        decision = parent.get("equipment", {}).get("decision")
        oid = parent.get("object_id")
        if not isinstance(decision, dict) or not isinstance(oid, str):
            continue
        for passage in decision.get("passages", []):
            if (isinstance(passage, dict) and isinstance(passage.get("id"), str)
                    and passage["id"].startswith(oid + ":")
                    and isinstance(passage.get("section"), str) and passage["section"]
                    and isinstance(passage.get("text"), str) and passage["text"]
                    and (oid in sources or parent.get("source_url"))):
                candidates.setdefault(passage["id"], []).append((parent, passage))

    promoted = set()
    for eid, records in candidates.items():
        parent, passage = records[0]
        oid = parent["object_id"]
        fact = (oid, passage["section"], passage["text"])
        if any((p["object_id"], source["section"], source["text"]) != fact for p, source in records):
            continue  # Conflicting copies retain their original nested text.
        existing = evidence.get(eid)
        if existing:
            if existing.get("kind") not in {"source_row", "passage"} or existing.get("claim_scope") == "identity_only":
                continue
            existing_text = existing.get("text")
            existing_section = existing.get("section")
            if "row" in existing:
                row = existing["row"]
                existing_section = row.get("section")
                label, value = row.get("label", ""), row.get("value", "")
                existing_text = f"{label} : {value}" if label else value
            if (existing.get("object_id"), existing_section, existing_text) != fact:
                continue
        else:
            evidence[eid] = {"evidence_id": eid, "kind": "passage", "object_id": oid,
                             "section": passage["section"], "text": passage["text"]}
            if parent.get("source_url"):
                evidence[eid]["source_url"] = parent["source_url"]
        evidence[eid]["origin_equipment_evidence_ids"] = sorted({p["evidence_id"] for p, _ in records})
        promoted.add(eid)

    for parent in list(evidence.values()):
        decision = parent.get("equipment", {}).get("decision")
        if isinstance(decision, dict):
            decision["passages"] = [{"evidence_id": p["id"]} if isinstance(p, dict) and p.get("id") in promoted else p
                                    for p in decision.get("passages", [])]

    for oid in inline_identities:
        eid = oid + ":identity"
        existing = evidence.get(eid)
        if existing and (existing.get("kind") != "source_row" or any(k in existing for k in ("row", "text", "equipment"))
                         or existing.get("object_id", existing.get("id", oid)) != oid):
            raise ValueError("Identity citation collides with a non-identity source proof")
        evidence.setdefault(eid, {"evidence_id": eid, "kind": "source_row", "object_id": oid})
        evidence[eid]["claim_scope"] = "identity_only"
        evidence[eid]["object_id"] = oid

    for proof in evidence.values():
        if proof.get("kind") == "aggregate":
            proof.pop("sql", None)
            proof.pop("parameters", None)
        equipment = proof.get("equipment")
        if equipment and isinstance(equipment.get("decision"), dict):
            decision = equipment["decision"]
            # These attributes are identical to the enclosing evidence/entry.
            # Keep the stage, reasons, market and every original source passage.
            for key in ("case_id", "object_id", "equipment", "status", "source_url"):
                decision.pop(key, None)
            policy = {k: decision.pop(k) for k in ("stage", "reasons", "market") if k in decision}
            if policy:
                policy_id = next((pid for pid, saved in policies.items() if saved == policy), None)
                if policy_id is None:
                    policy_id = f"p{len(policies) + 1}"
                    policies[policy_id] = policy
                decision["policy_id"] = policy_id
        if equipment and equipment.get("evidence_ids") == [proof["evidence_id"]]:
            equipment.pop("evidence_ids")  # The enclosing proof already declares this exact ID.
        oid = proof.get("object_id") or (proof.get("id") if proof.get("id") in sources else None)
        if oid in sources:
            proof["object_id"] = oid
            identity = sources[oid]
            proof["subject"] = f"{identity['brand']} {identity['model']} ({identity['year']})"
            for key in ("brand", "model", "year", "source_url"):
                proof.pop(key, None)
            if proof.get("id") == oid:
                proof.pop("id")
        if proof.get("id") == proof["evidence_id"]:
            proof.pop("id")

    def payload_references(value, object_id=None):
        if isinstance(value, list):
            return [payload_references(v, object_id) for v in value]
        if not isinstance(value, dict):
            return value
        if value.get("id") in sources and all(k in value for k in ("brand", "model", "year", "source_url")):
            identity = {k: v for k, v in value.items() if k != "source_url"}
            if value["id"] in inline_identities:
                identity["evidence_id"] = value["id"] + ":identity"
            return identity
        eid = value.get("evidence_id")
        if eid in evidence and value.get("kind") == "passage":
            return {"evidence_id": eid}
        if isinstance(value.get("identity"), dict):
            object_id = value["identity"].get("id", object_id)
        rewritten = {}
        for key, child in value.items():
            if key == "equipment" and isinstance(child, list):
                rewritten[key] = []
                for entry in child:
                    delivered = deepcopy(entry)
                    if any(eid in evidence for eid in entry.get("evidence_ids", [])):
                        delivered.pop("decision", None)
                    rewritten[key].append(delivered)
            elif key == "original_rows" and isinstance(child, list):
                raw_rows = {canonical(p["row"]) for p in evidence.values()
                            if "row" in p and p.get("object_id") == object_id}
                # Non-comparable numeric ranges can occur only in original_rows.
                # Keep every row that does not already exist in the evidence table.
                rewritten[key] = [r for r in child if canonical(r) not in raw_rows]
            else:
                rewritten[key] = payload_references(child, object_id)
        return rewritten

    view["payload"] = payload_references(view.get("payload", {}))
    rows = view["payload"].get("rows")
    if isinstance(rows, list) and rows:
        members = [row["identity"]["id"] for row in rows if isinstance(row.get("identity"), dict)]
        total = view["payload"].get("total_matches")
        view["payload"]["page_scope"] = {"object_ids": members, "returned": len(members), "total_matches": total,
            "all_matches_in_page": total == len(members) and view["pagination"].get("returned") == len(members)
                                   and view["pagination"].get("next_cursor") is None,
            "identity_evidence_ids": [oid + ":identity" for oid in members]}
        aggregate = evidence.get(view["payload"].get("aggregate_evidence_id"), {})
        if "criteria" in aggregate:
            view["payload"]["page_scope"]["criteria"] = deepcopy(aggregate["criteria"])
    view["evidence"] = list(evidence.values())
    view["sources"] = sources
    if policies:
        view["classification_policies"] = policies
    view["view"] = {"format": VIEW_VERSION, "raw_receipt_retained": True,
                    "audit_fields_omitted": True, "duplicate_source_text_referenced": True,
                    "identity_labels_inline": True, "identity_proofs_scope": "identity_only",
                    "original_equipment_sources_citable": True,
                    "source_identity_and_url_lookup": "sources[object_id or identity.id]",
                    "decision_policy_lookup": "classification_policies[policy_id]",
                    "content_omitted": False}
    if candidates.keys() - promoted:
        view["view"]["non_promoted_equipment_source_ids"] = sorted(candidates.keys() - promoted)
    return view


def evidence_ids(value):
    found = set()
    if isinstance(value, dict):
        if isinstance(value.get("evidence_id"), str):
            found.add(value["evidence_id"])
        for key, child in value.items():
            if (key == "evidence_ids" or key.endswith("_evidence_ids")) and isinstance(child, list):
                found.update(e for e in child if isinstance(e, str))
        for key, child in value.items():
            if key not in {"evidence_id", "evidence_ids"}:
                found.update(evidence_ids(child))
    elif isinstance(value, list):
        for child in value:
            found.update(evidence_ids(child))
    return found


def bounded_result(result, maximum, *, protected_evidence=(), protected_fields=()):
    """Return a fact-preserving compact view, or an explicitly partial page.

    Wide lists first omit entire secondary numeric columns uniformly, preserving
    page identities and equipment. Fields used by filters/missing criteria, cited
    measures and explicitly protected sort fields remain. Only then can complete
    result items be removed with their unused proofs. Source text is never clipped.
    """
    if maximum < 0:
        raise ValueError("Tool result cannot fit the remaining context budget")
    view = deepcopy(result) if result.get("view", {}).get("format") == VIEW_VERSION else compact_result(result)
    protected = set(protected_evidence)
    source_proofs = {p["evidence_id"]: p for p in view.get("evidence", [])}

    def proof_closure(ids):
        required, pending = set(ids), list(ids)
        while pending:
            proof = source_proofs.get(pending.pop())
            if proof:
                added = evidence_ids(proof) - required
                required.update(added)
                pending.extend(added)
        return required

    required_fields = {field for field in protected_fields if isinstance(field, str)}
    required_fields.update(field for field in view["view"].get("protected_fields", []) if isinstance(field, str))
    criteria = [proof.get("criteria", {}) for proof in source_proofs.values() if proof.get("kind") == "aggregate"]
    criteria.append(view["payload"].get("page_scope", {}).get("criteria", {}))
    for criterion in criteria:
        required_fields.update(f["field"] for f in criterion.get("numeric_filters", [])
                               if isinstance(f, dict) and isinstance(f.get("field"), str))
        required_fields.update(field for field in criterion.get("missing_fields", []) if isinstance(field, str))
    protected_proofs = proof_closure(protected)
    for row in view["payload"].get("rows", []):
        required_fields.update(field for field, measure in row.get("measures", {}).items()
                               if evidence_ids(measure) & protected_proofs)
    # Persist sort/protected field requirements for a later history reduction,
    # even when the first result does not need shrinking.
    view["view"]["protected_fields"] = sorted(required_fields)
    if len(canonical(view)) <= maximum:
        return view
    view["status"] = "partial"
    view["coverage"].update(exhaustive=False, truncation_reason="context_budget")
    view["view"]["content_omitted"] = True
    view["view"].setdefault("omissions", {})
    if not any(m.get("subject") == "tool_response" and m.get("field") == "context" for m in view["missing"]):
        view["missing"].insert(0, {"subject": "tool_response", "field": "context",
                                   "reason": "Context page is partial. Use smaller pages or explicit fields/sections; count remains global."})

    def options():
        payload = view["payload"]
        found = []
        for key in ("rows", "fiches", "matrix", "candidates", "passages"):
            if isinstance(payload.get(key), list) and payload[key]:
                # Never remove a row that carries an already accepted citation.
                index = next((i for i in range(len(payload[key]) - 1, -1, -1)
                              if not (evidence_ids(payload[key][i]) & protected)), None)
                if index is not None:
                    found.append((len(canonical(payload[key][index])), key, index))
        return found

    def referenced_values(value):
        if isinstance(value, dict):
            return set().union(*(referenced_values(v) for v in value.values())) if value else set()
        if isinstance(value, list):
            return set().union(*(referenced_values(v) for v in value)) if value else set()
        return {value} if isinstance(value, str) else set()

    def prune_source_tables(current):
        used = referenced_values(current["payload"]) | referenced_values(current["evidence"])
        current["sources"] = {oid: source for oid, source in current.get("sources", {}).items() if oid in used}
        if "classification_policies" in current:
            current["classification_policies"] = {pid: policy for pid, policy in current["classification_policies"].items() if pid in used}

    def prune_proofs(current):
        referenced = proof_closure(evidence_ids(current["payload"]) | protected)
        current["evidence"] = [proof for proof in current["evidence"]
                               if proof["evidence_id"] in referenced or proof.get("kind") == "aggregate"]
        prune_source_tables(current)

    def omit_numeric_column():
        rows = view["payload"].get("rows", [])
        fields = {field for row in rows for field in row.get("measures", {})} - required_fields
        original_size = len(canonical(view))
        choices = []
        for field in sorted(fields):
            candidate = deepcopy(view)
            for row in candidate["payload"]["rows"]:
                row.get("measures", {}).pop(field, None)
            omitted = set(candidate["view"].get("fields_omitted", [])) | {field}
            candidate["view"]["fields_omitted"] = sorted(omitted)
            candidate["view"]["omissions"]["measure_fields"] = len(omitted)
            prune_proofs(candidate)
            saved = original_size - len(canonical(candidate))
            if saved > 0:
                choices.append((saved, field, candidate))
        if not choices:
            return False
        _, _, chosen = max(choices, key=lambda choice: (choice[0], choice[1]))
        view.clear()
        view.update(chosen)
        return True

    while len(canonical(view)) > maximum:
        if omit_numeric_column():
            continue
        choices = options()
        if choices:
            _, key, index = max(choices)
            view["payload"][key].pop(index)
            view["view"]["omissions"][key] = view["view"]["omissions"].get(key, 0) + 1
            prune_proofs(view)
            continue
        # Missing lists may contain one entry per omitted field/fiche. Preserve
        # the explicit truncation notice and disclose their reduced count.
        if len(view["missing"]) > 1:
            view["missing"].pop()
            view["view"]["omissions"]["missing"] = view["view"]["omissions"].get("missing", 0) + 1
            continue
        raise ValueError("Tool result cannot fit the remaining context budget")
    payload = view["payload"]
    key = next((k for k in ("rows", "candidates", "passages", "fiches", "matrix") if k in payload), None)
    if key and view["pagination"].get("returned") is not None:
        view["pagination"]["returned"] = min(view["pagination"]["returned"], len(payload[key]))
    return view
