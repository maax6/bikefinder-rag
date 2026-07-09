CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS motorcycles (
    id              SERIAL PRIMARY KEY,
    brand           TEXT NOT NULL,
    model           TEXT NOT NULL,
    year            INTEGER NOT NULL,
    category        TEXT NOT NULL,
    url             TEXT NOT NULL UNIQUE,

    displacement_ccm    REAL,
    weight_kg           REAL,
    power_hp             REAL,
    torque_nm            REAL,
    seat_height_mm       REAL,

    -- MSRP fallback (see README: bikez.com has no price field; real market
    -- listings are blocked by ToS/anti-bot on every French marketplace we
    -- checked, so this is filled from a separate, still-TBD source).
    msrp_eur             REAL,
    msrp_source          TEXT,

    raw_specs            JSONB NOT NULL DEFAULT '{}',
    scraped_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_motorcycles_brand ON motorcycles (brand);
CREATE INDEX IF NOT EXISTS idx_motorcycles_category ON motorcycles (category);
CREATE INDEX IF NOT EXISTS idx_motorcycles_year ON motorcycles (year);
CREATE INDEX IF NOT EXISTS idx_motorcycles_displacement ON motorcycles (displacement_ccm);

CREATE TABLE IF NOT EXISTS review_chunks (
    id              SERIAL PRIMARY KEY,
    motorcycle_id   INTEGER NOT NULL REFERENCES motorcycles(id) ON DELETE CASCADE,
    comment_text    TEXT NOT NULL,
    author          TEXT,
    posted_at       TEXT,
    embedding       vector(1024) NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_review_chunks_motorcycle ON review_chunks (motorcycle_id);

-- Approximate nearest-neighbor index; fine at pilot scale, revisit (HNSW
-- params / ivfflat lists) once the full catalog is loaded.
CREATE INDEX IF NOT EXISTS idx_review_chunks_embedding
    ON review_chunks USING hnsw (embedding vector_cosine_ops);
