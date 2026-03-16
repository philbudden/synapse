CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS captures (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source TEXT,
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now(),
    classification JSONB,
    classification_model TEXT,
    classified_at TIMESTAMPTZ
);

-- Ensure new columns exist when re-running init.sql against an existing DB.
ALTER TABLE captures ADD COLUMN IF NOT EXISTS classification JSONB;
ALTER TABLE captures ADD COLUMN IF NOT EXISTS classification_model TEXT;
ALTER TABLE captures ADD COLUMN IF NOT EXISTS classified_at TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS memories (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    capture_id UUID REFERENCES captures(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    embedding VECTOR(768)
);

-- Note: ivfflat indexes require ANALYZE for best performance.
CREATE INDEX IF NOT EXISTS memories_embedding_idx
ON memories
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);
