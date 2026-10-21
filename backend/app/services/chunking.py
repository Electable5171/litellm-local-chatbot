"""Split document text into overlapping chunks for embedding.

Text is cut at paragraph and sentence boundaries where possible, so a chunk reads naturally.
Each chunk remembers the page where it starts.
"""

import re
from dataclasses import dataclass

from app.services.extract import Page
from app.services.tokens import ApproxTokenCounter, TokenCounter

_SENTENCE = re.compile(r"(?<=[.!?])\s+")


@dataclass(frozen=True)
class Chunk:
    ordinal: int
    page: int | None
    text: str
    tokens: int


def _units(pages: list[Page], limit: int, counter: TokenCounter) -> list[tuple[int | None, str]]:
    """Paragraphs, split further (sentences, then characters) when one is longer than ``limit``."""
    units: list[tuple[int | None, str]] = []
    for page in pages:
        for para in re.split(r"\n\s*\n", page.text):
            para = para.strip()
            if not para:
                continue
            if counter.count(para) <= limit:
                units.append((page.number, para))
                continue
            for sentence in _SENTENCE.split(para):
                sentence = sentence.strip()
                while counter.count(sentence) > limit:
                    cut = max(1, len(sentence) * limit // counter.count(sentence))
                    units.append((page.number, sentence[:cut]))
                    sentence = sentence[cut:].strip()
                if sentence:
                    units.append((page.number, sentence))
    return units


def chunk_pages(
    pages: list[Page],
    *,
    target_tokens: int = 800,
    overlap_tokens: int = 100,
    counter: TokenCounter | None = None,
) -> list[Chunk]:
    counter = counter or ApproxTokenCounter()
    overlap_tokens = min(overlap_tokens, target_tokens // 2)
    units = [(p, t, counter.count(t)) for p, t in _units(pages, target_tokens, counter)]
    chunks: list[Chunk] = []
    current: list[tuple[int | None, str, int]] = []
    size = 0
    fresh = 0  # units in ``current`` that are not yet part of an emitted chunk (not just overlap)

    def emit() -> None:
        text = "\n\n".join(t for _, t, _ in current)
        chunks.append(Chunk(len(chunks), current[0][0], text, sum(n for _, _, n in current)))

    for unit in units:
        if current and size + unit[2] > target_tokens:
            emit()
            keep: list[tuple[int | None, str, int]] = []
            kept = 0
            for previous in reversed(current):  # carry the last units over as overlap
                if kept + previous[2] > overlap_tokens:
                    break
                keep.insert(0, previous)
                kept += previous[2]
            current, size, fresh = keep, kept, 0
        current.append(unit)
        size += unit[2]
        fresh += 1
    if fresh:
        emit()
    return chunks
