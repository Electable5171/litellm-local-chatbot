-- Where a chat's title came from: 'draft' = the first question, shortened (a model-written title
-- may replace it), 'llm' = written by the model, 'user' = typed by the user (never replaced).
-- Existing chats keep their titles.
ALTER TABLE conversations ADD COLUMN title_source TEXT NOT NULL DEFAULT 'user';
