"""Rough token counting and fitting a conversation into the context budget.

The real tokenizer is not used yet. The estimate leans high on purpose (3 characters per token
for plain text, one token per other character), so a conversation is trimmed a little early
rather than rejected by the model.
"""

import math
from collections.abc import Sequence
from typing import Protocol

from app.errors import ApiError

PER_MESSAGE_OVERHEAD = 4
SAFETY_MARGIN = 256


class TokenCounter(Protocol):
    def count(self, text: str) -> int: ...


class ApproxTokenCounter:
    def count(self, text: str) -> int:
        if not text:
            return 0
        ascii_chars = sum(1 for ch in text if ord(ch) < 128)
        return math.ceil(ascii_chars / 3) + (len(text) - ascii_chars)


def fit_to_budget(
    messages: Sequence[dict[str, str]], budget_tokens: int, counter: TokenCounter
) -> tuple[list[dict[str, str]], int]:
    """Drop the oldest non-system messages until the conversation fits.

    Returns the messages to send and how many were dropped. The newest message is always kept;
    if it alone does not fit, the request is rejected.
    """

    def size(msgs: Sequence[dict[str, str]]) -> int:
        return sum(counter.count(m["content"]) + PER_MESSAGE_OVERHEAD for m in msgs)

    kept = list(messages)
    dropped = 0
    while size(kept) > budget_tokens:
        index = next((i for i, m in enumerate(kept[:-1]) if m["role"] != "system"), None)
        if index is None:
            raise ApiError(
                "context_too_long",
                "This message is too long for the model's working budget. Shorten it.",
                status=413,
            )
        del kept[index]
        dropped += 1
    return kept, dropped
