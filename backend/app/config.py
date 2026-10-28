"""Application settings, read from the environment and an optional .env file.

The app fails fast with a clear message when a required value is missing.
"""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # LiteLLM (OpenAI-compatible API)
    litellm_base_url: str = "http://172.17.58.139:4000/v1"
    litellm_api_key: SecretStr = Field(description="LiteLLM virtual key for this app")
    chat_model: str = "qwen3.8"
    embedding_model: str = "llama-nemotron-embed-1b-v2"
    # Comma-separated model ids offered in the UI. Empty means only CHAT_MODEL.
    allowed_models: str = ""

    # Limits (the model accepts 262,144 tokens; the working budget is smaller on purpose)
    max_context_tokens: int = 262_144
    context_budget_tokens: int = 32_768
    max_output_tokens: int = 8_192  # reasoning tokens count towards this

    # Let the model write a short title for a chat after its first answer
    auto_titles: bool = True

    # Replace the oldest part of a long chat with a model-written summary (the messages are kept)
    auto_summary: bool = True
    summary_trigger_percent: int = Field(default=75, ge=30, le=100)  # of the input budget
    summary_keep_percent: int = Field(default=30, ge=10, le=60)  # newest messages left as they are
    summary_tokens: int = Field(default=1_000, ge=200, le=4_000)

    # Documents (RAG)
    max_upload_mb: int = Field(default=25, ge=1, le=200)
    max_pdf_pages: int = Field(default=500, ge=1)
    max_chunks_per_document: int = Field(default=3000, ge=1)
    chunk_tokens: int = Field(default=800, ge=100)
    chunk_overlap_tokens: int = Field(default=100, ge=0)
    rag_context_tokens: int = Field(default=9000, ge=500)
    rag_top_k: int = Field(default=6, ge=1, le=50)
    embedding_batch_size: int = Field(default=32, ge=1, le=256)

    # HTTP behaviour towards LiteLLM
    connect_timeout_s: float = 10.0
    request_timeout_s: float = 600.0
    max_retries: int = 4  # retries on 429 / 5xx / connection errors, with backoff

    # Local service
    host: str = "127.0.0.1"
    port: int = 8000
    data_dir: Path = Path("data")
    health_cache_s: float = 15.0

    @field_validator("litellm_base_url")
    @classmethod
    def _normalise_base_url(cls, value: str) -> str:
        """Accept the URL with or without a trailing slash or /v1; always end it in /v1."""
        url = value.strip().rstrip("/")
        if not url.startswith(("http://", "https://")):
            raise ValueError("LITELLM_BASE_URL must start with http:// or https://")
        if not url.endswith("/v1"):
            url += "/v1"
        return url

    @field_validator("host")
    @classmethod
    def _loopback_only(cls, value: str) -> str:
        """The app has no login, so it must only listen on this computer."""
        if value not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("HOST must be 127.0.0.1, localhost or ::1 (the app has no login)")
        return value

    @field_validator("context_budget_tokens")
    @classmethod
    def _budget_fits(cls, value: int) -> int:
        if value < 1024:
            raise ValueError("CONTEXT_BUDGET_TOKENS must be at least 1024")
        return value

    @property
    def model_choices(self) -> list[str]:
        """Model ids the UI may offer: ALLOWED_MODELS, or just the chat model."""
        items = [m.strip() for m in self.allowed_models.split(",") if m.strip()]
        return items or [self.chat_model]


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
