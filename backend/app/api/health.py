import os
import time

from fastapi import APIRouter, Request

from app import __version__

router = APIRouter(prefix="/api")


@router.get("/health")
async def health(request: Request) -> dict[str, object]:
    settings = request.app.state.settings
    probe = await request.app.state.health.check()
    chat_available = (settings.chat_model in probe.model_ids) if probe.reachable else None
    ok = probe.reachable and chat_available is True
    return {
        "status": "ok" if ok else "degraded",
        "version": __version__,
        "pid": os.getpid(),  # lets the stop script be sure which process is this app
        "litellm": {
            "base_url": settings.litellm_base_url,
            "reachable": probe.reachable,
            "latency_ms": probe.latency_ms,
            "error": probe.error,
            "checked_age_s": round(time.time() - probe.checked_at, 1),
        },
        "chat_model": {"id": settings.chat_model, "available": chat_available},
    }
