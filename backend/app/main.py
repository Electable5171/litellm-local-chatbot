"""FastAPI application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.api import health, models
from app.config import Settings, get_settings
from app.errors import install_error_handlers
from app.middleware import RequestIdMiddleware
from app.services.health import HealthService
from app.services.llm import LLMClient

FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


def create_app(settings: Settings | None = None, llm: LLMClient | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        app.state.settings = settings
        app.state.llm = llm or LLMClient(settings)
        app.state.health = HealthService(app.state.llm, settings.health_cache_s)
        try:
            yield
        finally:
            await app.state.llm.aclose()

    app = FastAPI(title="litellm-local-chatbot", version=__version__, lifespan=lifespan)
    app.add_middleware(RequestIdMiddleware)
    install_error_handlers(app)
    app.include_router(health.router)
    app.include_router(models.router)

    # Serve the built React app from the same process (one URL on the laptop). Must come last.
    if FRONTEND_DIST.is_dir():
        app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
    return app
