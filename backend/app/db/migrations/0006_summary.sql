-- A running summary of the oldest part of a long chat. The messages stay as they are; the model is
-- shown the summary instead of the messages up to and including position ``summary_through``.
ALTER TABLE conversations ADD COLUMN summary TEXT NOT NULL DEFAULT '';
ALTER TABLE conversations ADD COLUMN summary_through INTEGER NOT NULL DEFAULT 0;
