-- Hybrid local embedding: BAAI/bge-small-en-v1.5 (384). Replaces 1536-dim from 001.
-- Run after 001. Destructive to case_chunks (rebuild with correct dimension).

DROP TABLE IF EXISTS case_chunks CASCADE;

CREATE TABLE case_chunks (
    id                 BIGSERIAL PRIMARY KEY,
    case_id            BIGINT NOT NULL REFERENCES cases (id) ON DELETE CASCADE,
    chunk_index        INT NOT NULL,
    kind               TEXT,
    content            TEXT NOT NULL,
    embedding          vector(384) NOT NULL,
    embedding_model    TEXT NOT NULL DEFAULT 'BAAI/bge-small-en-v1.5',
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT case_chunks_case_chunk_idx UNIQUE (case_id, chunk_index)
);

CREATE INDEX idx_case_chunks_case_id ON case_chunks (case_id);
CREATE INDEX idx_case_chunks_model ON case_chunks (embedding_model);

-- Optional: after bulk load, analyze then create HNSW for cosine
-- CREATE INDEX CONCURRENTLY idx_case_chunks_hnsw ON case_chunks
--   USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);

ALTER TABLE cases ADD COLUMN IF NOT EXISTS source_public_url TEXT;

CREATE TABLE IF NOT EXISTS sync_state (
    key        TEXT PRIMARY KEY,
    value      TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ingestion_runs (
    id              BIGSERIAL PRIMARY KEY,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at    TIMESTAMPTZ,
    status          TEXT NOT NULL,
    source          TEXT,
    items_fetched   INT,
    items_embedded  INT,
    error           TEXT
);

CREATE TABLE IF NOT EXISTS search_events (
    id            BIGSERIAL PRIMARY KEY,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    query         TEXT,
    result_count  INT,
    client_hash   TEXT,
    latency_ms    INT
);

CREATE INDEX IF NOT EXISTS idx_search_events_created ON search_events (created_at);
