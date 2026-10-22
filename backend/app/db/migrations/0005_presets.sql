-- Named system prompts ("instructions") the user can pick for a chat. Choosing one copies its text
-- into the chat, so editing or deleting a preset later does not change chats that used it.
CREATE TABLE prompt_presets (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    content    TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

INSERT INTO prompt_presets (id, name, content, created_at, updated_at) VALUES
 ('seed-1-concise', 'Concise',
  'Answer briefly and directly. Skip introductions and summaries. Use short sentences.',
  strftime('%Y-%m-%dT%H:%M:%f', 'now') || '+00:00', strftime('%Y-%m-%dT%H:%M:%f', 'now') || '+00:00'),
 ('seed-2-plain', 'Plain language',
  'Explain things in plain language for someone new to the topic. Define any technical term the first time you use it, and give a small example when it helps.',
  strftime('%Y-%m-%dT%H:%M:%f', 'now') || '+00:00', strftime('%Y-%m-%dT%H:%M:%f', 'now') || '+00:00'),
 ('seed-3-steps', 'Step by step',
  'Work through problems step by step and show the reasoning before the final answer. Say which assumptions you are making.',
  strftime('%Y-%m-%dT%H:%M:%f', 'now') || '+00:00', strftime('%Y-%m-%dT%H:%M:%f', 'now') || '+00:00'),
 ('seed-4-code', 'Code helper',
  'You are a careful senior engineer. Prefer small, working examples in fenced code blocks, mention edge cases and failure modes, and say when you are unsure instead of guessing.',
  strftime('%Y-%m-%dT%H:%M:%f', 'now') || '+00:00', strftime('%Y-%m-%dT%H:%M:%f', 'now') || '+00:00'),
 ('seed-5-critic', 'Critical reviewer',
  'Review the text or idea I give you critically. List the strongest problems first, explain why each matters, and suggest a concrete fix. Do not flatter.',
  strftime('%Y-%m-%dT%H:%M:%f', 'now') || '+00:00', strftime('%Y-%m-%dT%H:%M:%f', 'now') || '+00:00');
