"""Split a model's streamed output into "reasoning" and "answer" text.

Models report their thinking in one of two ways:

* a separate field next to the answer (``reasoning_content``, or ``reasoning``), as qwen3.8 does
  through LiteLLM;
* inline in the answer, wrapped in ``<think> ... </think>``.

The parser accepts both, so the UI never needs to know which one a model uses. A tag can arrive
split across chunks (``<thi`` then ``nk>``); the parser holds back text that might be the start of
a tag until it can decide.
"""

from dataclasses import dataclass

OPEN_TAG = "<think>"
CLOSE_TAG = "</think>"


@dataclass(frozen=True)
class Piece:
    kind: str  # "reasoning" or "content"
    text: str


def _partial_tag_len(text: str, tag: str) -> int:
    """Length of the longest ending of ``text`` that is the beginning of ``tag``."""
    for length in range(min(len(text), len(tag) - 1), 0, -1):
        if text.endswith(tag[:length]):
            return length
    return 0


class ThinkingParser:
    def __init__(self) -> None:
        self._inline_reasoning = False
        self._pending = ""
        self._started = {"reasoning": False, "content": False}

    def feed(self, reasoning: str | None, content: str | None) -> list[Piece]:
        pieces: list[Piece] = []
        if reasoning:
            self._emit(pieces, "reasoning", reasoning)
        if content:
            self._pending += content
            self._scan(pieces, final=False)
        return pieces

    def flush(self) -> list[Piece]:
        """Call once when the stream ends: release any text that was held back."""
        pieces: list[Piece] = []
        self._scan(pieces, final=True)
        return pieces

    def _scan(self, pieces: list[Piece], *, final: bool) -> None:
        while self._pending:
            tag = CLOSE_TAG if self._inline_reasoning else OPEN_TAG
            kind = "reasoning" if self._inline_reasoning else "content"
            index = self._pending.find(tag)
            if index >= 0:
                self._emit(pieces, kind, self._pending[:index])
                self._pending = self._pending[index + len(tag) :]
                self._inline_reasoning = not self._inline_reasoning
                continue
            keep = 0 if final else _partial_tag_len(self._pending, tag)
            self._emit(pieces, kind, self._pending[: len(self._pending) - keep])
            self._pending = self._pending[len(self._pending) - keep :]
            return

    def _emit(self, pieces: list[Piece], kind: str, text: str) -> None:
        if not self._started[kind]:
            text = text.lstrip()  # models often start with blank lines
        if not text:
            return
        self._started[kind] = True
        pieces.append(Piece(kind, text))
