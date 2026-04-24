-- CaseMatch-style corpus: full judgments + chunk embeddings for pgvector
-- Embedding dimension: 1536 (e.g. text-embedding-3-small); change if your model differs.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE cases (
    id                 BIGSERIAL PRIMARY KEY,
    source_uri         TEXT NOT NULL UNIQUE,
    title              TEXT,
    court              TEXT,
    decision_date      DATE,
    neutral_citation   TEXT,
    judge              TEXT,
    full_text          TEXT,
    outcome_label      TEXT,
    raw_metadata       JSONB DEFAULT '{}',
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE case_chunks (
    id            BIGSERIAL PRIMARY KEY,
    case_id       BIGINT NOT NULL REFERENCES cases (id) ON DELETE CASCADE,
    chunk_index   INT NOT NULL,
    kind          TEXT,
    content       TEXT NOT NULL,
    embedding     vector(1536),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT case_chunks_case_chunk_idx UNIQUE (case_id, chunk_index)
);

CREATE INDEX idx_cases_decision_date ON cases (decision_date);
CREATE INDEX idx_cases_court ON cases (court);
CREATE INDEX idx_case_chunks_case_id ON case_chunks (case_id);

-- Approximate vector index (tune / add after you have data; list distance requires ops)
-- CREATE INDEX idx_case_chunks_embedding ON case_chunks USING hnsw (embedding vector_cosine_ops);

CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_cases_updated
    BEFORE UPDATE ON cases
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
