-- Documents are attached to a conversation; only attached documents are searched in that chat.
CREATE TABLE conversation_documents (
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    document_id     TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    created_at      TEXT NOT NULL,
    PRIMARY KEY (conversation_id, document_id)
);

-- The excerpts an answer was based on (JSON list), so they are still shown after a reload.
ALTER TABLE messages ADD COLUMN sources TEXT;
