"""The agent's three tools.

All are typed-parameter function calls, never raw SQL from the LLM —
filter_specs builds a parameterized query from a fixed set of known
columns (column names are hardcoded in this file, values are always bound,
never interpolated), search_reviews runs a pgvector similarity search
with optional case-insensitive metadata filters (ILIKE, not `=`, so a
casing mismatch from the LLM doesn't silently return zero rows), and
get_bike_details returns one bike's full spec sheet including raw_specs.
"""

import re
from typing import Any

from bikefinder_rag.embeddings.embedder import embed_text

# Brand/category matching ignores spacing, case and punctuation on both
# sides: bikez writes 'Super motard' and 'Harley-Davidson', LLMs (and
# users) write 'supermotard' and 'Harley Davidson' — a plain ILIKE would
# silently return zero rows on those.
_NORM_SQL = "regexp_replace(lower({column}), '[^a-z0-9]', '', 'g') LIKE %s"


def _norm_pattern(value: str) -> str:
    return "%" + re.sub(r"[^a-z0-9]", "", value.lower()) + "%"

FILTER_SPECS_SCHEMA = {
    "name": "filter_specs",
    "description": (
        "Filter motorcycles by structured specs (displacement, weight, power, "
        "seat height, category, brand, year, price). Use for precise numeric or "
        "categorical constraints, e.g. 'naked bikes between 600 and 900cc under 8000 EUR'."
    ),
    "input_schema": {
        "type": "object",
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
            "min_seat_height_mm": {"type": "number"},
            "max_seat_height_mm": {"type": "number"},
            "max_msrp_eur": {
                "type": "number",
                "description": "MSRP is sparsely populated (bikez.com has no price field; see README) — treat absence of results as 'unknown', not 'too expensive'.",
            },
            "order_by": {
                "type": "string",
                "description": (
                    "Sort column: year, displacement_ccm, weight_kg, power_hp, "
                    "torque_nm, seat_height_mm or msrp_eur. Prefix with '-' for "
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
            "limit": {"type": "integer", "description": "Max rows to return, default 10."},
        },
    },
}

SEARCH_REVIEWS_SCHEMA = {
    "name": "search_reviews",
    "description": (
        "Semantic search over owner/forum comments about specific motorcycles "
        "(known issues, ride impressions, maintenance tips). Use for qualitative "
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
                    "REQUIRED — the topic to search for, in plain words and any "
                    "language, e.g. 'reliability problems breakdowns'."
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
        "stroke, and every other spec bikez.com lists. Use when the user asks "
        "about a spec of a specific bike that filter_specs doesn't return. "
        "Returns the most recent model-years unless a year is given."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "model": {"type": "string", "description": "Model name, e.g. 'GSF 1200 Bandit'."},
            "brand": {"type": "string"},
            "year": {"type": "integer", "description": "Exact model year, if the user named one."},
        },
        "required": ["model"],
    },
}

TOOLS = [FILTER_SPECS_SCHEMA, SEARCH_REVIEWS_SCHEMA, GET_BIKE_DETAILS_SCHEMA]

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
    ("min_seat_height_mm", "seat_height_mm", ">="),
    ("max_seat_height_mm", "seat_height_mm", "<="),
    ("max_msrp_eur", "msrp_eur", "<="),
]


def filter_specs(conn, **kwargs: Any) -> list[dict]:
    clauses = ["1=1"]
    params: list[Any] = []

    if kwargs.get("brand"):
        clauses.append(_NORM_SQL.format(column="brand"))
        params.append(_norm_pattern(kwargs["brand"]))

    if kwargs.get("category"):
        # Match bikez's Category OR motoplanete's curated category_fr: bikez
        # mislabels recent bikes ('Super motard' Transalps), the French badge
        # is the reliable one where present.
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
    sortable = {"year", "displacement_ccm", "weight_kg", "power_hp",
                "torque_nm", "seat_height_mm", "msrp_eur"}
    order_by = str(kwargs.get("order_by") or "-year")
    direction = "DESC" if order_by.startswith("-") else "ASC"
    column = order_by.lstrip("-")
    if column not in sortable:
        column, direction = "year", "DESC"

    limit = int(kwargs.get("limit") or 10)
    query = f"""
        SELECT brand, model, year, category, category_fr, displacement_ccm,
               weight_kg, power_hp, torque_nm, seat_height_mm, msrp_eur, url
        FROM motorcycles
        WHERE {' AND '.join(clauses)}
        ORDER BY {column} {direction} NULLS LAST
        LIMIT %s
    """
    params.append(limit)

    with conn.cursor() as cur:
        cur.execute(query, params)
        columns = [desc.name for desc in cur.description]
        return [dict(zip(columns, row)) for row in cur.fetchall()]


def search_reviews(conn, query: str, brand: str | None = None, model: str | None = None,
                    category: str | None = None, limit: int | None = None) -> list[dict]:
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

    sql = f"""
        SELECT f.brand, f.family_name AS model_family,
               f.year_min AS family_year_min, f.year_max AS family_year_max,
               rc.comment_text, rc.author, rc.posted_at,
               rc.embedding <=> %s::vector AS distance
        FROM review_chunks rc
        JOIN model_families f ON f.id = rc.family_id
        WHERE {' AND '.join(clauses)}
        ORDER BY rc.embedding <=> %s::vector
        LIMIT %s
    """
    params_with_vector = [query_vector, *params, query_vector, limit]

    with conn.cursor() as cur:
        cur.execute(sql, params_with_vector)
        columns = [desc.name for desc in cur.description]
        return [dict(zip(columns, row)) for row in cur.fetchall()]


# bikez spec pages carry navigation/ad rows in the same table as real specs;
# they'd only pad the tool result and tempt the model into offering features
# (insurance quotes, parts shopping) this assistant doesn't have.
_RAW_SPECS_NOISE = {"Rating", "Ask questions", "Update specs", "Related bikes",
                    "Maintenance", "Insurance costs"}


def get_bike_details(conn, model: str, brand: str | None = None, year: int | None = None) -> list[dict]:
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

    sql = f"""
        SELECT brand, model, year, category, category_fr, displacement_ccm,
               weight_kg, power_hp, torque_nm, seat_height_mm, msrp_eur, url,
               raw_specs
        FROM motorcycles
        WHERE {' AND '.join(clauses)}
        ORDER BY year DESC
        LIMIT 3
    """
    with conn.cursor() as cur:
        cur.execute(sql, params)
        columns = [desc.name for desc in cur.description]
        rows = [dict(zip(columns, row)) for row in cur.fetchall()]

    for row in rows:
        specs = row.pop("raw_specs", None) or {}
        # "Loading..." is bikez's client-side placeholder — some scraped
        # cells still carry it; a blank is more honest than echoing it.
        row["specs"] = {
            k: v for k, v in specs.items()
            if k not in _RAW_SPECS_NOISE and v and v.strip() and v.strip() != "Loading..."
        }
    return rows


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


def execute_tool(conn, tool_name: str, tool_input: dict) -> list[dict]:
    # Tool-calling LLMs (local models especially) sometimes emit argument
    # names that drift from the schema (e.g. "models" instead of "model", or
    # drop a required one like "query" entirely). Remap the known near-misses,
    # drop the rest, and say so in the tool result — a silent repair hides the
    # mistake from the model, so it never self-corrects; a TypeError likewise
    # becomes a tool_result instead of crashing the whole loop.
    if tool_name == "filter_specs":
        known = FILTER_SPECS_SCHEMA["input_schema"]["properties"]
        call = filter_specs
    elif tool_name == "search_reviews":
        known = SEARCH_REVIEWS_SCHEMA["input_schema"]["properties"]
        call = search_reviews
    elif tool_name == "get_bike_details":
        known = GET_BIKE_DETAILS_SCHEMA["input_schema"]["properties"]
        call = get_bike_details
    else:
        raise ValueError(f"Unknown tool: {tool_name}")

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
            notes.append(f"ignored unknown argument '{key}'")

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
    except TypeError as e:
        results = [{"error": f"Invalid arguments for {tool_name}: {e}"}]

    if notes:
        return [{"notes": notes}, *(results or [{"info": "No matching rows."}])]
    return results
