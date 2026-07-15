CREATE EXTENSION IF NOT EXISTS vector;

-- bikez.com shares one discussion forum per model *family*: every model-year
-- (and even renamed variants, e.g. CB 250 K 1 / CB 250 N) links to the same
-- /models/*-discussions.php page. Comments therefore belong to the family,
-- not to a specific model-year row — attaching them per-year both duplicated
-- every comment across variants and misattributed decade-old comments to
-- recent model-years.
CREATE TABLE IF NOT EXISTS model_families (
    id              SERIAL PRIMARY KEY,
    discussion_url  TEXT NOT NULL UNIQUE,
    brand           TEXT NOT NULL,
    family_name     TEXT NOT NULL,
    year_min        INTEGER NOT NULL,
    year_max        INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS motorcycles (
    id              SERIAL PRIMARY KEY,
    brand           TEXT NOT NULL,
    model           TEXT NOT NULL,
    year            INTEGER NOT NULL,
    category        TEXT NOT NULL,
    url             TEXT NOT NULL UNIQUE,

    -- NULL when the bikez page has no discussion forum linked.
    family_id       INTEGER REFERENCES model_families(id),

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
CREATE INDEX IF NOT EXISTS idx_motorcycles_family ON motorcycles (family_id);

CREATE TABLE IF NOT EXISTS review_chunks (
    id              SERIAL PRIMARY KEY,
    family_id       INTEGER NOT NULL REFERENCES model_families(id) ON DELETE CASCADE,
    comment_text    TEXT NOT NULL,
    author          TEXT,
    posted_at       TEXT,
    embedding       vector(1024) NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_review_chunks_family ON review_chunks (family_id);

-- One comment exists once per family, however many model-year rows link to
-- that family's forum. md5(comment_text) rather than the raw text because
-- btree index rows cap at ~2.7KB and forum comments run up to 65KB.
CREATE UNIQUE INDEX IF NOT EXISTS uq_review_chunks_family_comment
    ON review_chunks (family_id, author, posted_at, md5(comment_text));

-- Approximate nearest-neighbor index; fine at pilot scale, revisit (HNSW
-- params / ivfflat lists) once the full catalog is loaded.
CREATE INDEX IF NOT EXISTS idx_review_chunks_embedding
    ON review_chunks USING hnsw (embedding vector_cosine_ops);

-- NHTSA safety recalls (scripts/load_nhtsa_recalls.py), attached at family
-- level like review_chunks: a campaign names (make, model, year) and can
-- legitimately cover several of our families. The project's only objective
-- reliability signal — see the loader's docstring for the matching rules.
CREATE TABLE IF NOT EXISTS recalls (
    id              SERIAL PRIMARY KEY,
    family_id       INTEGER NOT NULL REFERENCES model_families(id),
    campno          TEXT NOT NULL,
    nhtsa_make      TEXT NOT NULL,
    nhtsa_model     TEXT NOT NULL,
    model_year      INTEGER,
    component       TEXT,
    defect          TEXT,
    consequence     TEXT,
    corrective      TEXT,
    units_affected  INTEGER,
    report_date     DATE,
    UNIQUE NULLS NOT DISTINCT (campno, family_id, model_year)
);
CREATE INDEX IF NOT EXISTS recalls_family_idx ON recalls (family_id);

-- Indicative used-market prices (scripts/load_used_prices.py): aggregates
-- of a 2022 European marketplace snapshot, per family and registration
-- year (reg_year NULL = whole-family rollup). Asking prices from one
-- point in time — a cote indicative, not a pricing service.
CREATE TABLE IF NOT EXISTS used_price_estimates (
    id              SERIAL PRIMARY KEY,
    family_id       INTEGER NOT NULL REFERENCES model_families(id),
    reg_year        INTEGER,
    n_listings      INTEGER NOT NULL,
    price_median    INTEGER NOT NULL,
    price_p25       INTEGER NOT NULL,
    price_p75       INTEGER NOT NULL,
    mileage_median  INTEGER,
    snapshot_year   INTEGER NOT NULL,
    UNIQUE NULLS NOT DISTINCT (family_id, reg_year)
);
CREATE INDEX IF NOT EXISTS used_price_family_idx ON used_price_estimates (family_id);

-- Sparse leg of the hybrid search: English full-text over the comments,
-- fused with the dense ranking (RRF) in search_reviews. The corpus is
-- English, so the 'english' config is the right one; French queries ride
-- on the dense leg (and the agent is told to query in English).
ALTER TABLE review_chunks ADD COLUMN IF NOT EXISTS comment_tsv tsvector
    GENERATED ALWAYS AS (to_tsvector('english', comment_text)) STORED;
CREATE INDEX IF NOT EXISTS idx_review_chunks_tsv ON review_chunks USING gin (comment_tsv);
