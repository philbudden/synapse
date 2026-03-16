CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS captures (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source TEXT,
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS memories (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    capture_id UUID REFERENCES captures(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    embedding VECTOR(768)
);

-- For small datasets, sequential scans are fine; ivfflat helps once the dataset grows.
-- Note: ivfflat indexes require ANALYZE for best performance.
-- ivfflat is approximate; for small datasets, large `lists` can behave poorly.
-- Tune `lists` upward as your dataset grows (rule of thumb: ~sqrt(rows)).
CREATE INDEX IF NOT EXISTS memories_embedding_idx
ON memories
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 1);
