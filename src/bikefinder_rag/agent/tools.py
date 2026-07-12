"""The agent's two tools.

Both are typed-parameter function calls, never raw SQL from the LLM —
filter_specs builds a parameterized query from a fixed set of known
columns (column names are hardcoded in this file, values are always bound,
never interpolated), and search_reviews runs a pgvector similarity search
with optional case-insensitive metadata filters (ILIKE, not `=`, so a
casing mismatch from the LLM doesn't silently return zero rows).
"""

from typing import Any

from bikefinder_rag.embeddings.embedder import embed_text

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
                "description": "bikez.com category, e.g. 'Naked bike', 'Sport', 'Touring', 'Enduro/offroad'.",
            },
            "min_year": {"type": "integer"},
            "max_year": {"type": "integer"},
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
            "query": {"type": "string", "description": "The question or topic to search for, in any language."},
            "brand": {"type": "string"},
            "model": {"type": "string"},
            "category": {"type": "string"},
            "limit": {"type": "integer", "description": "Max comments to return, default 5."},
        },
        "required": ["query"],
    },
}

TOOLS = [FILTER_SPECS_SCHEMA, SEARCH_REVIEWS_SCHEMA]

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
        clauses.append("brand ILIKE %s")
        params.append(f"%{kwargs['brand']}%")

    if kwargs.get("category"):
        clauses.append("category ILIKE %s")
        params.append(f"%{kwargs['category']}%")

    for arg_name, column, operator in _FILTER_COLUMNS:
        value = kwargs.get(arg_name)
        if value is not None:
            clauses.append(f"{column} {operator} %s")
            params.append(value)

    limit = int(kwargs.get("limit") or 10)
    query = f"""
        SELECT brand, model, year, category, displacement_ccm, weight_kg,
               power_hp, torque_nm, seat_height_mm, msrp_eur, url
        FROM motorcycles
        WHERE {' AND '.join(clauses)}
        ORDER BY year DESC
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
        clauses.append("f.brand ILIKE %s")
        params.append(f"%{brand}%")
    if model:
        # Match against the member model-years, so 'CB 250 N' finds the
        # 'CB 250' family the comment actually belongs to.
        clauses.append(
            "EXISTS (SELECT 1 FROM motorcycles m WHERE m.family_id = f.id AND m.model ILIKE %s)"
        )
        params.append(f"%{model}%")
    if category:
        clauses.append(
            "EXISTS (SELECT 1 FROM motorcycles m WHERE m.family_id = f.id AND m.category ILIKE %s)"
        )
        params.append(f"%{category}%")

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


def execute_tool(conn, tool_name: str, tool_input: dict) -> list[dict]:
    # Tool-calling LLMs (local models especially) sometimes emit argument
    # names that drift from the schema (e.g. "models" instead of "model", or
    # drop a required one like "query" entirely). Drop anything unrecognized,
    # and turn a resulting TypeError into a tool_result the model can see
    # and self-correct on next turn, instead of crashing the whole loop.
    if tool_name == "filter_specs":
        known = FILTER_SPECS_SCHEMA["input_schema"]["properties"]
        call = filter_specs
    elif tool_name == "search_reviews":
        known = SEARCH_REVIEWS_SCHEMA["input_schema"]["properties"]
        call = search_reviews
    else:
        raise ValueError(f"Unknown tool: {tool_name}")

    filtered_input = {k: v for k, v in tool_input.items() if k in known}
    try:
        return call(conn, **filtered_input)
    except TypeError as e:
        return [{"error": f"Invalid arguments for {tool_name}: {e}"}]
