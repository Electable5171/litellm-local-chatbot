-- Conversations and their messages. Times are ISO-8601 UTC text, so they sort correctly.
CREATE TABLE conversations (
    id               TEXT PRIMARY KEY,
    title            TEXT NOT NULL DEFAULT '',
    model            TEXT NOT NULL,
    thinking_enabled INTEGER NOT NULL DEFAULT 1,
    system_prompt    TEXT NOT NULL DEFAULT '',
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);

CREATE TABLE messages (
    id                TEXT PRIMARY KEY,
    conversation_id   TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    position          INTEGER NOT NULL,
    role              TEXT NOT NULL CHECK (role IN ('system', 'user', 'assistant')),
    content           TEXT NOT NULL DEFAULT '',
    reasoning         TEXT NOT NULL DEFAULT '',
    -- streaming: being written; complete; cancelled: the reader stopped it; error: it failed
    status            TEXT NOT NULL CHECK (status IN ('streaming', 'complete', 'cancelled', 'error')),
    error_code        TEXT,
    error_message     TEXT,
    finish_reason     TEXT,
    prompt_tokens     INTEGER,
    completion_tokens INTEGER,
    latency_ms        INTEGER,
    ttft_ms           INTEGER,
    thinking_ms       INTEGER,
    trimmed           INTEGER NOT NULL DEFAULT 0,
    created_at        TEXT NOT NULL,
    UNIQUE (conversation_id, position)
);

CREATE INDEX idx_conversations_updated ON conversations (updated_at DESC);
