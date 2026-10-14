"""A terminal response channel, separate from the six catalogue query tools."""
ANSWER_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["answer", "claims", "missing", "needs_clarification"],
    "properties": {"answer": {"type": "string", "minLength": 1, "maxLength": 30000},
        "claims": {"type": "array", "maxItems": 100, "items": {"type": "object", "additionalProperties": False, "required": ["text", "evidence_ids"],
            "properties": {"text": {"type": "string", "minLength": 1}, "evidence_ids": {"type": "array", "minItems": 1, "uniqueItems": True, "items": {"type": "string", "minLength": 1}}}}},
        "missing": {"type": "array", "maxItems": 100, "items": {"type": "object", "additionalProperties": False, "required": ["subject", "reason"],
            "properties": {"subject": {"type": "string", "minLength": 1}, "reason": {"type": "string", "minLength": 1}}}},
        "needs_clarification": {"type": "boolean"}}}

SUBMIT_ANSWER = {"name": "submit_answer", "description": "Finish this user turn by submitting the French answer. In claims.evidence_ids, copy exact evidence_id values from delivered proofs. An object_id selects a fiche and is not a proof; an identity_only proof establishes identity, not a numeric value or equipment status. Always use this terminal response function instead of plain prose. It performs no catalogue query. Never submit it together with another tool call.", "input_schema": ANSWER_SCHEMA}
