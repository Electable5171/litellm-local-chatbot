"""Embeddings through LiteLLM, and vector helpers.

Vectors are stored as packed float32 (``array('f')``), 2,048 numbers for the current model, about
8 KB per chunk. A search compares the question with every chunk of the attached documents; for a
few thousand chunks that takes well under a second in plain Python, so no vector database or
numeric library is needed.
"""

import math
from array import array
from typing import Literal

from openai import APIConnectionError, APIStatusError, APITimeoutError

from app.config import Settings
from app.errors import LLMError
from app.services.llm import LLMClient, map_status_error

Kind = Literal["passage", "query"]


def pack(vector: list[float]) -> bytes:
    return array("f", vector).tobytes()


def unpack(blob: bytes) -> array:
    vector = array("f")
    vector.frombytes(blob)
    return vector


def normalise(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vector))
    return [x / norm for x in vector] if norm else vector


def dot(a: array, b: array) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


class Embedder:
    def __init__(self, llm: LLMClient, settings: Settings) -> None:
        self._llm = llm
        self._settings = settings

    @property
    def model(self) -> str:
        return self._settings.embedding_model

    async def embed(self, texts: list[str], kind: Kind) -> list[list[float]]:
        """Unit-length vectors, one per text, in order. One request at a time (shared model)."""
        out: list[list[float]] = []
        size = self._settings.embedding_batch_size
        for start in range(0, len(texts), size):
            out.extend(await self._batch(texts[start : start + size], kind))
        return out

    async def _batch(self, batch: list[str], kind: Kind) -> list[list[float]]:
        try:
            response = await self._llm.client.embeddings.create(
                model=self.model,
                input=batch,
                extra_body={"input_type": kind},
            )
        except (APIConnectionError, APITimeoutError) as exc:
            raise LLMError("upstream_unreachable", "Cannot reach LiteLLM.", 502) from exc
        except APIStatusError as exc:
            if exc.status_code in (400, 404):
                raise LLMError(
                    "embedding_rejected",
                    f"LiteLLM refused the embedding request for '{self.model}'"
                    f" ({exc.status_code}).",
                    502,
                ) from exc
            raise map_status_error(exc) from exc
        rows = sorted(response.data, key=lambda d: d.index)
        if len(rows) != len(batch):
            raise LLMError("upstream_error", "LiteLLM returned too few embeddings.", 502)
        vectors = [normalise(list(r.embedding)) for r in rows]
        if len({len(v) for v in vectors}) != 1:
            raise LLMError("upstream_error", "LiteLLM returned vectors of different sizes.", 502)
        return vectors
