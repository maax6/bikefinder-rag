"""Structured technical tools, with review retrieval retained for experiments.

All are typed-parameter function calls, never raw SQL from the LLM —
filter_specs builds a parameterized query from a fixed set of known
columns (column names are hardcoded in this file, values are always bound,
never interpolated), search_reviews runs a pgvector similarity search
with optional case-insensitive metadata filters (ILIKE, not `=`, so a
casing mismatch from the LLM doesn't silently return zero rows), and
get_bike_details returns one bike's full spec sheet including raw_specs.
"""

import math
import re
from typing import Any

# Brand/category matching ignores spacing, case and punctuation on both
# sides: bikez writes 'Super motard' and 'Harley-Davidson', LLMs (and
# users) write 'supermotard' and 'Harley Davidson' — a plain ILIKE would
# silently return zero rows on those.
_NORM_SQL = "regexp_replace(lower({column}), '[^a-z0-9]', '', 'g') LIKE %s"


def _normalized_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _norm_pattern(value: str) -> str:
    return "%" + _normalized_name(value) + "%"

FILTER_SPECS_SCHEMA = {
    "name": "filter_specs",
    "description": (
        "Filter motorcycles by structured specs (displacement, weight, power, "
        "torque, seat height, category, brand, model year). Use exact year bounds "
        "for a single model year. Returns at most 20 catalog entries, not an "
        "exhaustive market list. Numeric columns use the legacy normalization: "
        "weight_kg can be dry or wet; use the returned original specs before "
        "comparing measures. No equipment or color filter is available yet."
    ),
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "brand": {"type": "string", "description": "Exact or partial brand name, e.g. 'Honda'."},
            "category": {
                "type": "string",
                "description": (
                    "Category. Matches bikez labels (Sport, Enduro/offroad, "
                    "Custom/cruiser, Naked bike, Allround, Classic, Super motard, "
                    "Touring, Sport touring, Cross/motocross, Trial, Minibike, "
                    "Scooter, Speedway) and French ones (Roadster, Sportive, "
                    "Trail, Custom, Routière & GT, Supermotard, Enduro). Fuzzy, "
                    "case/spacing-insensitive."
                ),
            },
            "min_year": {
                "type": "integer",
                "description": (
                    "Lower bound on model year, inclusive. A decade always needs BOTH bounds: "
                    "'the 1980s' / 'les années 1950' means min_year=1980 AND max_year=1989 "
                    "(resp. 1950 and 1959)."
                ),
            },
            "max_year": {"type": "integer", "description": "Upper bound on model year, inclusive."},
            "min_displacement_ccm": {"type": "number"},
            "max_displacement_ccm": {"type": "number"},
            "min_weight_kg": {"type": "number"},
            "max_weight_kg": {"type": "number"},
            "min_power_hp": {"type": "number"},
            "max_power_hp": {"type": "number"},
            "min_torque_nm": {"type": "number"},
            "max_torque_nm": {"type": "number"},
            "min_seat_height_mm": {"type": "number"},
            "max_seat_height_mm": {"type": "number"},
            "order_by": {
                "type": "string",
                "description": (
                    "Sort column: year, displacement_ccm, weight_kg, power_hp, "
                    "torque_nm or seat_height_mm. Prefix with '-' for "
                    "descending. Default '-year'. Required for superlatives: "
                    "'the lightest X' needs order_by='weight_kg' with a small limit."
                ),
            },
            "count_only": {
                "type": "boolean",
                "description": (
                    "Return only how many motorcycles match the filters, instead of "
                    "listing them. Use for 'how many...' questions."
                ),
            },
            "limit": {"type": "integer", "minimum": 1, "maximum": 20,
                      "description": "Max rows to return, default 10, maximum 20."},
        },
    },
}

SEARCH_REVIEWS_SCHEMA = {
    "name": "search_reviews",
    "description": (
        "Semantic search over owner reviews and forum comments about specific "
        "motorcycles (known issues, ride impressions, maintenance tips). Two "
        "sources: bikez.com forums (English, lang='en') and motoplanete.com "
        "owner reviews (French, lang='fr', with a /5 rating). Use for qualitative "
        "questions. Optional filters narrow the search to a brand/model/category "
        "before ranking by similarity. Comments are attached to a model FAMILY "
        "(bikez.com shares one forum across every year and variant of a model), "
        "so each result carries the family name, the year range it covers, and "
        "the comment's own post date — attribute opinions to the family and its "
        "comment date, never to one specific model-year."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "REQUIRED — the topic to search for, in plain words, in the "
                    "USER'S language (the corpus mixes English forum comments and "
                    "French owner reviews; the embeddings are multilingual), "
                    "e.g. 'reliability problems breakdowns' / 'problèmes de fiabilité pannes'."
                ),
            },
            "brand": {"type": "string"},
            "model": {"type": "string"},
            "category": {"type": "string"},
            "limit": {"type": "integer", "description": "Max comments to return, default 5."},
        },
        "required": ["query"],
    },
}

GET_BIKE_DETAILS_SCHEMA = {
    "name": "get_bike_details",
    "description": (
        "Full factory spec sheet for ONE specific motorcycle: fuel capacity, "
        "cooling system, transmission, tires, brakes, suspension, bore x "
        "stroke, and the original labels and units bikez.com lists. A model "
        "year is required; ask the user if it is missing. Returns up to three "
        "matching entries with source URLs; multiple entries can be distinct "
        "variants, so do not merge their values. For a comparison, call once "
        "per model with the SAME explicit year and cite each source."
    ),
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "model": {"type": "string", "description": "Model name, e.g. 'GSF 1200 Bandit'."},
            "brand": {"type": "string"},
            "year": {"type": "integer", "description": "Exact model year, if the user named one."},
        },
        "required": ["model", "year"],
    },
}

from bikefinder_rag.agent.catalog_tools import CATALOG_TOOLS, CATALOG_CALLS, execute_catalog_tool

TOOLS = [*CATALOG_TOOLS, FILTER_SPECS_SCHEMA, GET_BIKE_DETAILS_SCHEMA]

_SORTABLE_COLUMNS = {"year", "displacement_ccm", "weight_kg", "power_hp",
                     "torque_nm", "seat_height_mm"}
FILTER_SPECS_SCHEMA["input_schema"]["properties"]["order_by"]["enum"] = sorted(
    _SORTABLE_COLUMNS | {f"-{column}" for column in _SORTABLE_COLUMNS}
)

_FILTER_COLUMNS: list[tuple[str, str, str]] = [
    # (input arg, sql column, sql operator)
    ("min_year", "year", ">="),
    ("max_year", "year", "<="),
    ("min_displacement_ccm", "displacement_ccm", ">="),
    ("max_displacement_ccm", "displacement_ccm", "<="),
    ("min_weight_kg", "weight_kg", ">="),
    ("max_weight_kg", "weight_kg", "<="),
    ("min_power_hp", "power_hp", ">="),
    ("max_power_hp", "power_hp", "<="),
    ("min_torque_nm", "torque_nm", ">="),
    ("max_torque_nm", "torque_nm", "<="),
    ("min_seat_height_mm", "seat_height_mm", ">="),
    ("max_seat_height_mm", "seat_height_mm", "<="),
]


def filter_specs(conn, **kwargs: Any) -> list[dict]:
    clauses = ["1=1"]
    params: list[Any] = []

    if kwargs.get("brand"):
        clauses.append(_NORM_SQL.format(column="brand"))
        params.append(_norm_pattern(kwargs["brand"]))

    if kwargs.get("category"):
        # Match bikez's Category OR motoplanete's curated category_fr: bikez
        # can conflict with the French badge; return both labels so the
        # response can expose that disagreement.
        pattern = _norm_pattern(kwargs["category"])
        clauses.append(
            "(" + _NORM_SQL.format(column="category")
            + " OR " + _NORM_SQL.format(column="coalesce(category_fr, '')") + ")"
        )
        params.extend([pattern, pattern])

    for arg_name, column, operator in _FILTER_COLUMNS:
        value = kwargs.get(arg_name)
        if value is not None:
            clauses.append(f"{column} {operator} %s")
            params.append(value)

    if kwargs.get("count_only"):
        with conn.cursor() as cur:
            cur.execute(f"SELECT count(*) FROM motorcycles WHERE {' AND '.join(clauses)}", params)
            return [{"matching_motorcycles": cur.fetchone()[0]}]

    # Column names come from this whitelist, never from the LLM's string.
    order_by = str(kwargs.get("order_by") or "-year")
    direction = "DESC" if order_by.startswith("-") else "ASC"
    column = order_by.lstrip("-")
    if column not in _SORTABLE_COLUMNS:
        raise ValueError(f"Unsupported sort column: {order_by}")

    limit = min(int(kwargs.get("limit") or 10), 20)
    query = f"""
        SELECT brand, model, year, category, category_fr, displacement_ccm,
               weight_kg, power_hp, torque_nm, seat_height_mm, url, raw_specs,
               scraped_at
        FROM motorcycles
        WHERE {' AND '.join(clauses)}
        ORDER BY {column} {direction} NULLS LAST, brand, model, url
        LIMIT %s
    """
    params.append(limit)

    with conn.cursor() as cur:
        cur.execute(query, params)
        columns = [desc.name for desc in cur.description]
        rows = [dict(zip(columns, row)) for row in cur.fetchall()]
    for row in rows:
        _technical_specs(row, measures_only=True)
    return rows


def search_reviews(conn, query: str, brand: str | None = None, model: str | None = None,
                    category: str | None = None, limit: int | None = None) -> list[dict]:
    # The default technical path needs neither review model in memory.
    from bikefinder_rag.embeddings import reranker
    from bikefinder_rag.embeddings.embedder import embed_text

    clauses = ["1=1"]
    params: list[Any] = []

    if brand:
        clauses.append(_NORM_SQL.format(column="f.brand"))
        params.append(_norm_pattern(brand))
    if model:
        # Word-by-word match against brand+model of the member model-years:
        # LLMs phrase the model loosely ('GSF 1200 Bandit' for the DB's
        # 'GSF 1200 N Bandit', or 'Harley-Davidson Electra Glide' with the
        # brand folded in), so a whole-string substring match silently
        # returns nothing. Each word must appear somewhere in the member's
        # 'Brand Model' string instead.
        words = model.split() or [model]
        member_match = " AND ".join(["(m.brand || ' ' || m.model) ILIKE %s"] * len(words))
        clauses.append(
            f"EXISTS (SELECT 1 FROM motorcycles m WHERE m.family_id = f.id AND {member_match})"
        )
        params.extend(f"%{word}%" for word in words)
    if category:
        clauses.append(
            "EXISTS (SELECT 1 FROM motorcycles m WHERE m.family_id = f.id AND "
            + _NORM_SQL.format(column="m.category")
            + ")"
        )
        params.append(_norm_pattern(category))

    query_vector = embed_text(query)
    limit = int(limit or 5)
    # Hybrid, three stages: (1) a dense shortlist (HNSW) and a sparse
    # full-text shortlist (GIN) run as two separately-indexed queries;
    # (2) reciprocal rank fusion merges them — sparse catches the exact
    # terms dense blurs (model codes, 'brakes'), dense catches the
    # paraphrases sparse can't see; (3) the cross-encoder reranks the
    # fused pool when enabled. The corpus is bilingual (English forums,
    # French owner reviews), so the sparse leg runs an English and a French
    # tsquery and keeps the better rank of the two.
    fetch = min(max(limit * 6, 20), 50) if reranker.enabled() else max(limit * 3, 15)

    select = """
        SELECT rc.id, f.brand, f.family_name AS model_family,
               f.year_min AS family_year_min, f.year_max AS family_year_max,
               rc.comment_text, rc.author, rc.posted_at,
               rc.source, rc.lang, rc.rating,
               rc.embedding <=> %s::vector AS distance
        FROM review_chunks rc
        JOIN model_families f ON f.id = rc.family_id
    """
    where = " WHERE " + " AND ".join(clauses)

    with conn.cursor() as cur:
        # pgvector's HNSW scan returns at most `hnsw.ef_search` candidates
        # (default 40), so a LIMIT above it silently comes back short — a
        # `fetch` of 50 yields 43 rows. Harmless at the tool's default
        # limit of 5 (fetch 30), but the shortlist this function documents
        # is `fetch`, so ask the index for at least that many.
        # SET takes no bind parameter; `fetch` is our own int, never user input.
        cur.execute(f"SET hnsw.ef_search = {max(int(fetch), 40)}")
        cur.execute(select + where + " ORDER BY rc.embedding <=> %s::vector LIMIT %s",
                    [query_vector, *params, query_vector, fetch])
        columns = [desc.name for desc in cur.description]
        dense = [dict(zip(columns, row)) for row in cur.fetchall()]

        # websearch_to_tsquery ANDs the words, which is right when it hits
        # ('brake noise') and returns nothing on longer phrasings ('KTM SMC
        # supermoto opinions'); fall back to OR so the rare exact term
        # still gets its shot — ts_rank_cd favors multi-word matches anyway.
        # NULL distance: computing the 1024-dim cosine for every full-text
        # candidate before the sort costs seconds on common words.
        sparse_select = select.replace("rc.embedding <=> %s::vector AS distance",
                                       "NULL::float AS distance")
        sparse = []
        for ts_query in (query, " or ".join(query.split())):
            cur.execute(
                sparse_select + where
                + " AND (rc.comment_tsv @@ websearch_to_tsquery('english', %s)"
                + "      OR rc.comment_tsv_fr @@ websearch_to_tsquery('french', %s))"
                + " ORDER BY GREATEST(ts_rank_cd(rc.comment_tsv, websearch_to_tsquery('english', %s)),"
                + "                   ts_rank_cd(rc.comment_tsv_fr, websearch_to_tsquery('french', %s))) DESC"
                + " LIMIT %s",
                [*params, ts_query, ts_query, ts_query, ts_query, fetch])
            sparse = [dict(zip(columns, row)) for row in cur.fetchall()]
            if sparse:
                break

    fused: dict[int, dict] = {}
    for rows_ in (dense, sparse):
        for rank, row in enumerate(rows_):
            entry = fused.setdefault(row["id"], {**row, "rrf": 0.0})
            entry["rrf"] = round(entry["rrf"] + 1.0 / (60 + rank), 5)
    pool = sorted(fused.values(), key=lambda r: r["rrf"], reverse=True)[:fetch]

    if reranker.enabled() and len(pool) > limit:
        scores = reranker.rerank(query, [r["comment_text"] for r in pool])
        for row, score in zip(pool, scores):
            row["rerank_score"] = round(score, 4)
        pool.sort(key=lambda r: r["rerank_score"], reverse=True)

    for row in pool:
        row.pop("id", None)
    return pool[:limit]


# bikez spec pages carry navigation/ad rows in the same table as real specs;
# they'd only pad the tool result and tempt the model into offering features
# (insurance quotes, parts shopping) this assistant doesn't have.
_RAW_SPECS_NOISE = {"Rating", "Ask questions", "Update specs", "Related bikes",
                    "Maintenance", "Insurance costs"}


def _technical_specs(row: dict, *, measures_only: bool = False) -> None:
    """Keep original units/qualifiers alongside legacy numeric columns."""
    specs = row.pop("raw_specs", None) or {}
    row["specs"] = {
        k: v for k, v in specs.items()
        if k not in _RAW_SPECS_NOISE and isinstance(v, str)
        and v.strip() and v.strip() != "Loading..."
        and (not measures_only or k.lower() in {
            "displacement", "engine size", "weight incl. oil, gas, etc",
            "weight", "dry weight", "power output", "power", "output",
            "effect", "torque", "seat height",
        })
    }
    if row.get("scraped_at") is not None:
        row["scraped_at"] = str(row["scraped_at"])


def get_bike_details(conn, model: str, brand: str | None = None, year: int | None = None,
                     *, include_family_context: bool = False) -> list[dict]:
    # Same word-by-word matching rationale as search_reviews' model filter.
    words = model.split() or [model]
    clauses = ["(brand || ' ' || model) ILIKE %s"] * len(words)
    params: list[Any] = [f"%{word}%" for word in words]

    if brand:
        clauses.append(_NORM_SQL.format(column="brand"))
        params.append(_norm_pattern(brand))
    if year is not None:
        clauses.append("year = %s")
        params.append(int(year))

    # A precise variant name must win over a loose word match: the word 'N'
    # in 'GSF 1200 N Bandit' also appears inside 'Bandit' on the S variant.
    exact_name = _normalized_name(model)
    exact_sql = (
        "(regexp_replace(lower(model), '[^a-z0-9]', '', 'g') = %s OR "
        "regexp_replace(lower(brand || ' ' || model), '[^a-z0-9]', '', 'g') = %s)"
    )
    params.extend([exact_name, exact_name])

    sql = f"""
        SELECT brand, model, year, category, category_fr, displacement_ccm,
               weight_kg, power_hp, torque_nm, seat_height_mm, url,
               raw_specs, scraped_at, family_id
        FROM motorcycles
        WHERE {' AND '.join(clauses)}
        ORDER BY {exact_sql} DESC, year DESC, brand, model, url
        LIMIT 4
    """
    with conn.cursor() as cur:
        cur.execute(sql, params)
        columns = [desc.name for desc in cur.description]
        rows = [dict(zip(columns, row)) for row in cur.fetchall()]

    exact_rows = [row for row in rows if exact_name in {
        _normalized_name(row["model"]),
        _normalized_name(row["brand"] + " " + row["model"]),
    }]
    rows = exact_rows or rows
    truncated = len(rows) > 3
    rows = rows[:3]
    family_ids = {row.pop("family_id") for row in rows} - {None}
    for row in rows:
        _technical_specs(row)
    if truncated:
        rows.append({"info": "More than three matching entries. Narrow the model/variant; do not merge these specs.",
                     "truncated": True})
    if include_family_context and family_ids:
        rows.append(_family_context(conn, sorted(family_ids)))
    return rows


def _family_context(conn, family_ids: list[int]) -> dict:
    """Recalls and used-price estimates for the matched families, appended
    as one extra dict so the spec rows stay clean."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT model_year, component, left(defect, 180), units_affected
            FROM recalls WHERE family_id = ANY(%s)
            ORDER BY model_year DESC NULLS LAST LIMIT 5
            """,
            (family_ids,),
        )
        recalls = [
            {"model_year": y, "component": c, "defect": d, "units_affected": u}
            for y, c, d, u in cur.fetchall()
        ]
        cur.execute("SELECT count(*) FROM recalls WHERE family_id = ANY(%s)", (family_ids,))
        recall_count = cur.fetchone()[0]

        cur.execute(
            """
            SELECT n_listings, price_median, price_p25, price_p75,
                   mileage_median, snapshot_year
            FROM used_price_estimates
            WHERE family_id = ANY(%s) AND reg_year IS NULL
            ORDER BY n_listings DESC LIMIT 1
            """,
            (family_ids,),
        )
        cote = cur.fetchone()

    context: dict[str, Any] = {"known_us_recalls_total": recall_count}
    if recalls:
        context["recent_recalls"] = recalls
    if cote:
        context["used_price_estimate"] = {
            "n_listings": cote[0], "price_median_eur": cote[1],
            "price_p25_eur": cote[2], "price_p75_eur": cote[3],
            "mileage_median_km": cote[4],
            "note": f"asking prices from a {cote[5]} European marketplace snapshot",
        }
    return context


# Near-miss argument names observed from local models: remap instead of
# dropping, so e.g. 'model_family: Aprilia Tuono 125' still reaches the
# search instead of silently widening it to the whole corpus.
_ARG_ALIASES = {
    "model_family": "model",
    "models": "model",
    "bike": "model",
    "motorcycle": "model",
    "brands": "brand",
    "categories": "category",
}


_REVIEW_EXCERPT_MAX_CHARS = 2000


def _review_excerpt(row: dict) -> dict:
    """Bound the agent's evidence without changing the stored/ranked review."""
    result = dict(row)
    text = result.get("comment_text")
    if not isinstance(text, str) or len(text) <= _REVIEW_EXCERPT_MAX_CHARS:
        return result

    # Reserve one character for the ellipsis. Prefer a nearby sentence or
    # paragraph end, then a word boundary; never discard most of the excerpt
    # just because a long paragraph has only one early sentence boundary.
    prefix = text[:_REVIEW_EXCERPT_MAX_CHARS - 1]
    cut = max((m.end() for m in re.finditer(r"[.!?](?=\s)|\n", prefix)), default=0)
    if cut < _REVIEW_EXCERPT_MAX_CHARS // 2:
        cut = max((m.start() for m in re.finditer(r"\s+", prefix)), default=0)
        if cut < _REVIEW_EXCERPT_MAX_CHARS // 2:
            cut = len(prefix)
    result.update(
        comment_text=prefix[:cut].rstrip() + "…",
        text_truncated=True,
        original_text_chars=len(text),
        excerpt_note="Partial excerpt: the rest of this comment was omitted.",
    )
    return result


def _validate_technical_arguments(schema: dict, arguments: dict) -> str | None:
    for name in schema.get("required", []):
        if name not in arguments:
            return f"'{name}' is required; ask for an explicit model year when missing"
    for name, value in arguments.items():
        field = schema["properties"][name]
        kind = field["type"]
        if kind == "string":
            if not isinstance(value, str) or not value.strip():
                return f"'{name}' must be a nonempty string"
        elif kind == "boolean":
            if not isinstance(value, bool):
                return f"'{name}' must be a boolean"
        elif kind in {"integer", "number"}:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return f"'{name}' must be a {kind}"
            if kind == "integer" and not isinstance(value, int):
                return f"'{name}' must be an integer"
            try:
                finite = math.isfinite(value)
            except OverflowError:
                finite = False
            if not finite or value < 0:
                return f"'{name}' must be finite and nonnegative"
            if name in {"year", "min_year", "max_year"} and value < 1:
                return f"'{name}' must be a positive model year"
            if value < field.get("minimum", 0) or value > field.get("maximum", math.inf):
                return f"'{name}' is outside the supported bounds"
        if "enum" in field and value not in field["enum"]:
            return f"'{name}' is unsupported: {value}"
    for name, lower in arguments.items():
        if name.startswith("min_"):
            upper = arguments.get("max_" + name[4:])
            if upper is not None and lower > upper:
                return f"contradictory bounds for '{name[4:]}'"
    return None


def execute_tool(conn, tool_name: str, tool_input: dict, *, allow_reviews: bool = False) -> list[dict]:
    if tool_name in CATALOG_CALLS:
        return execute_catalog_tool(conn, tool_name, tool_input, _validate_technical_arguments)
    # Tool-calling LLMs (local models especially) sometimes emit argument
    # names that drift from the schema (e.g. "models" instead of "model", or
    # drop a required one like "query" entirely). Remap the known near-misses,
    # Reject unsupported technical filters before querying: returning a wider
    # search would falsely imply that the user's constraints were applied.
    # Historical review experiments retain their explicit repair behaviour.
    if tool_name == "filter_specs":
        known = FILTER_SPECS_SCHEMA["input_schema"]["properties"]
        call = filter_specs
    elif tool_name == "search_reviews":
        if not allow_reviews:
            return [{"error": "Owner reviews are disabled in the technical catalog. Use technical sheets; do not infer specifications from opinions."}]
        known = SEARCH_REVIEWS_SCHEMA["input_schema"]["properties"]
        call = search_reviews
    elif tool_name == "get_bike_details":
        known = GET_BIKE_DETAILS_SCHEMA["input_schema"]["properties"]
        call = get_bike_details
    else:
        return [{"error": f"Unknown tool: {tool_name}"}]

    if not isinstance(tool_input, dict):
        return [{"error": f"Invalid arguments for {tool_name}: expected an object."}]

    filtered_input: dict[str, Any] = {}
    notes = []
    for key, value in tool_input.items():
        alias = _ARG_ALIASES.get(key)
        if key in known:
            filtered_input[key] = value
        elif alias in known and alias not in tool_input:
            filtered_input[alias] = value
            notes.append(f"interpreted unknown argument '{key}' as '{alias}'")
        else:
            if tool_name != "search_reviews":
                return [{"error": f"Unsupported argument '{key}' for {tool_name}; no search was executed."}]
            notes.append(f"ignored unknown argument '{key}'")

    if tool_name != "search_reviews":
        schema = FILTER_SPECS_SCHEMA if tool_name == "filter_specs" else GET_BIKE_DETAILS_SCHEMA
        error = _validate_technical_arguments(schema["input_schema"], filtered_input)
        if error:
            return [{"error": f"Invalid arguments for {tool_name}: {error}. No search was executed."}]

    # Weak tool-callers (local models especially) sometimes drop the required
    # query even when the rest of the call is fine. Searching for general
    # owner impressions of the requested bike beats erroring out — models
    # read the error as "this bike has no reviews" and give up.
    if tool_name == "search_reviews" and not filtered_input.get("query"):
        topic = " ".join(
            str(filtered_input[k]) for k in ("brand", "model", "category") if filtered_input.get(k)
        )
        filtered_input["query"] = f"owner opinions experiences known issues {topic}".strip()
        notes.append("required argument 'query' was missing; searched for general owner impressions")

    try:
        results = call(conn, **filtered_input)
    except (TypeError, ValueError) as e:
        results = [{"error": f"Invalid arguments for {tool_name}: {e}"}]

    if tool_name == "search_reviews":
        results = [_review_excerpt(row) for row in results]

    if notes:
        return [{"notes": notes}, *(results or [{"info": "No matching rows."}])]
    return results
