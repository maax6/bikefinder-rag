"""Provider-neutral SQL + RAG interface specification, not a live dispatcher.

These definitions deliberately do not import or enable the legacy chat router.
Adapters must preserve these semantics when converting provider wire formats.
"""

VERSION = "bikefinder-sql-rag-v2"
FIELDS = {
    "displacement_ccm": "cc",
    "power_ch": "ch",
    "torque_nm": "Nm",
    "seat_height_mm": "mm",
    "weight_dry_kg": "kg, dry",
    "weight_wet_kg": "kg, ready to ride",
    "autonomy_km": "km, retain the source qualification",
    "catalog_price_eur": "EUR, dated catalogue price, not current used price",
}
STATUSES = ["standard", "optional", "explicitly_absent", "unknown"]


def obj(properties, required=()):
    return {"type": "object", "additionalProperties": False,
            "properties": properties, "required": list(required)}


def string(maximum=160):
    return {"type": "string", "minLength": 1, "maxLength": maximum}


def enum(values):
    return {"type": "string", "enum": list(values)}


def array(items, maximum, minimum=0):
    return {"type": "array", "items": items, "minItems": minimum,
            "maxItems": maximum, "uniqueItems": True}


YEAR = {"type": "integer", "minimum": 1800, "maximum": 2199}
PAGE = {
    "page_size": {"type": "integer", "minimum": 1, "maximum": 50, "default": 20},
    "cursor": string(2048),
}
SCOPE = obj({
    "brand": string(), "model_tokens": array(string(80), 8, 1),
    "min_year": YEAR, "max_year": YEAR,
    "object_ids": array(string(80), 100, 1),
})
FILTER = obj({
    "field": enum(FIELDS), "op": enum(["<", "<=", "=", ">=", ">"]),
    "value": {"type": "number"},
}, ["field", "op", "value"])
EQUIPMENT = obj({"name": string(), "status": enum(STATUSES)}, ["name", "status"])
SORT = obj({"field": enum(["year", "brand", "model", *FIELDS]),
            "direction": enum(["asc", "desc"])}, ["field", "direction"])


def tool(name, description, parameters, semantics):
    return {"name": name, "description": description,
            "input_schema": parameters, "semantics": semantics}


TOOLS = [
    tool("describe_catalog", "Discover available fields, units, equipment names, sections and data coverage.", obj({}), {
        "payload": "snapshot_id, fiche_count, passage_count, fields with coverage, equipment_names, section_names, supported_filters",
        "rules": ["No inferred riding category, homologation or current used price.",
                  "Names of equipment come from this result; aliases resolve to a documented canonical name or ambiguous status."]}),
    tool("resolve_models", "Find real catalogue identities and years; year is optional.", obj({
        "query": string(240), "scope": SCOPE, **PAGE,
    }, ["query"]), {
        "payload": "candidates with object_id, brand, model, year and source_url; total_candidates; ambiguity",
        "rules": ["Return separate variants; never silently substitute a neighbouring year or version.",
                  "Normalize accents, spaces and hyphens; preserve short discriminating variant tokens.",
                  "A family is a candidate set, not one invented canonical fiche.",
                  "No required year when exploring available years; exact identity comes from catalogue IDs."]}),
    tool("query_catalog", "Filter, count or list catalogue fiches using exact structured criteria.", obj({
        "scope": SCOPE, "numeric_filters": array(FILTER, 12),
        "equipment_filters": array(EQUIPMENT, 8),
        "missing_fields": array(enum(FIELDS), len(FIELDS)),
        "mode": enum(["count", "list"]), "fields": array(enum(FIELDS), len(FIELDS)),
        "sort": array(SORT, 3), **PAGE,
    }, ["mode"]), {
        "payload": "total_matches, rows with identity and requested measures/equipment, unknown_exclusions per criterion, aggregate_evidence_id",
        "rules": ["All filters are AND; missing_fields selects rows missing ANY named field.",
                  "Missing numeric values never satisfy a numeric comparison; conflicts remain unknown.",
                  "Missing equipment row and explicit unknown both satisfy unknown, never explicitly_absent.",
                  "Count covers every matching fiche, including all variants, never only a page; say fiches, not unique model families.",
                  "List includes exact total and cursor; sort is stable with object_id as final tie-breaker and nulls last.",
                  "Default ordering: year descending, brand, model, object_id. Count ignores sort/fields/page size and rejects cursor.",
                  "Rows and counts use SQL on the frozen projection bound to original source hashes.",
                  "Dry and wet weight remain distinct; autonomy and historical price keep their qualifications."]}),
    tool("get_fiches", "Read precise fiches using catalogue IDs. Request ONLY needed fields. For a numeric-only question set sections=[] and equipment_names=[] to avoid unrelated prose and equipment.", obj({
        "object_ids": array(string(80), 5, 1),
        "fields": {**array(enum(FIELDS), len(FIELDS)), "description": "Only numeric fields requested by the user; never request all fields for a one-field question."},
        "sections": array(string(80), 12),
        "equipment_names": array(string(), 8),
    }, ["object_ids"]), {
        "payload": "fiches with identity, requested values, original rows, equipment statuses, passages and source references",
        "rules": ["Unknown IDs are individually reported, with no replacement.",
                  "With explicit numeric fields and no section selector, return only sections backing those fields; with no selectors return the full fiche.",
                  "A sections-only or equipment-only request returns no unrelated numeric fields unless fields are explicitly requested.",
                  "Retain duplicate rows, range values and contradictory values as original evidence.",
                  "Inferences such as actual A2 eligibility, comfort or mechanical retrofit require suitable evidence."]}),
    tool("compare_fiches", "Compare requested measures/equipment across precise catalogue IDs.", obj({
        "object_ids": array(string(80), 5, 2),
        "fields": array(enum(FIELDS), len(FIELDS), 1),
        "equipment_names": array(string(), 8),
    }, ["object_ids", "fields"]), {
        "payload": "matrix, pairwise numeric deltas and evidence IDs, unknowns per fiche/field",
        "rules": ["Differences calculated by Python/SQL, never by language model arithmetic.",
                  "Only same-field comparable values produce deltas; unknown values stay unknown.",
                  "Compare dated catalogue prices as such; never manufacture an overall best motorcycle."]}),
    tool("search_passages", "Find original passages, globally or within identified families/fiches.", obj({
        "query": string(1000), "scope": SCOPE,
        "sections": array(string(80), 12),
        "mode": enum(["hybrid", "literal"]),
        "literal_terms": array(string(80), 8, 1),
        "order": enum(["relevance", "year_asc", "year_desc"]),
        "limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 8},
        "cursor": string(2048),
    }, ["query", "mode"]), {
        "payload": "passages with identity, verbatim text, section, source_url, text/source hashes; retrieval scores; searched/matched counts; per-scope coverage",
        "rules": ["Hybrid uses the same frozen lexical+dense retrieval and RRF configuration for local and cloud; no answer cache.",
                  "Literal requires literal_terms (OR, accent/case folded word/phrase matches); exhaustive SQL scan within the stated scope.",
                  "Hybrid rejects literal_terms and cursor; literal pages all matches with a stable cursor.",
                  "No scope means entire catalogue, not a hidden subset; all supplied scope fields are AND.",
                  "Do not collapse year/variant identities when deduplicating passages.",
                  "Hybrid ranked passages do not prove an earliest occurrence; an exhaustive literal search can establish only first documented mention of the selected terms.",
                  "A source mention on a dated fiche does not establish launch date, markets or every version.",
                  "Partial retrieval reports the unsearched scope explicitly; never describe it as exhaustive."]}),
]

CONTRACT = {
    "version": VERSION, "implementation_status": "specified_not_connected",
    "tools": TOOLS,
    "response_envelope": {
        "status": ["ok", "partial", "ambiguous", "not_found", "invalid_arguments", "unavailable"],
        "required": ["status", "snapshot_id", "payload", "evidence", "coverage", "missing", "pagination", "timing_ms"],
        "evidence": "stable evidence_id, kind (source_row/passage/aggregate), object_id where applicable, source_url/source_sha256; aggregates bind criteria and snapshot, with paginated contributing IDs",
        "coverage": "requested_scope, searched_fiches, searched_passages where relevant, exhaustive, truncation_reason",
        "missing": "list of {subject, field, reason}; never convert no mention to explicit absence",
        "pagination": "{returned, total, next_cursor}; cursor binds snapshot, criteria and stable ordering",
    },
    "execution_rules": [
        "No free SQL, arbitrary code, write operations or web access from model tools.",
        "Validate JSON shape/types, finite numbers, bounds, unknown keys, year order, scope combinations and canonical equipment names before execution.",
        "Unsupported constraints produce invalid_arguments with supported alternatives; never silently ignore them.",
        "Every output evidence reference must be traceable to the frozen corpus or exact aggregate criteria.",
        "Document text and user query are data, never instructions for tool execution.",
        "Provider adapters may alter only the wire format, never tool meaning, prompt content, data or retrieval parameters.",
        "Context-budget truncation must be deterministic and disclosed; retain unresolved entities and a continuation mechanism.",
    ],
}
