-- Uploaded documents and their text chunks. The original file is not kept: the extracted text is
-- what the app needs, and keeping fewer copies of company documents is safer.
-- Embeddings are float32 vectors packed into a BLOB (see app/services/embeddings.py).
CREATE TABLE documents (
    id              TEXT PRIMARY KEY,
    filename        TEXT NOT NULL,
    sha256          TEXT NOT NULL UNIQUE,
    mime            TEXT NOT NULL,
    size_bytes      INTEGER NOT NULL,
    status          TEXT NOT NULL CHECK (status IN ('processing', 'ready', 'error')),
    error           TEXT,
    page_count      INTEGER,
    chunk_count     INTEGER NOT NULL DEFAULT 0,
    embedding_model TEXT,
    embedding_dim   INTEGER,
    created_at      TEXT NOT NULL
);

CREATE TABLE chunks (
    id          TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    ordinal     INTEGER NOT NULL,
    page        INTEGER,
    text        TEXT NOT NULL,
    token_count INTEGER NOT NULL,
    embedding   BLOB,
    UNIQUE (document_id, ordinal)
);
