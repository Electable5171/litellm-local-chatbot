from fastapi import APIRouter, Request

router = APIRouter(prefix="/api")


@router.get("/models")
async def models(request: Request) -> dict[str, object]:
    settings = request.app.state.settings
    upstream = set(await request.app.state.llm.list_models())
    return {
        "default": settings.chat_model,
        "models": [{"id": m, "available": m in upstream} for m in settings.model_choices],
    }
