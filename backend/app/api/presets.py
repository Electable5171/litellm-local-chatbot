from typing import Any

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field

from app.services.presets import PresetService

router = APIRouter(prefix="/api/presets")


class PresetIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    content: str = Field(min_length=1, max_length=20_000)


class PresetPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=60)
    content: str | None = Field(default=None, min_length=1, max_length=20_000)


def _service(request: Request) -> PresetService:
    return request.app.state.presets


@router.get("")
async def list_presets(request: Request) -> dict[str, Any]:
    return {"presets": await _service(request).list()}


@router.post("", status_code=201)
async def create_preset(body: PresetIn, request: Request) -> dict[str, Any]:
    return await _service(request).create(body.name, body.content)


@router.patch("/{preset_id}")
async def update_preset(preset_id: str, body: PresetPatch, request: Request) -> dict[str, Any]:
    return await _service(request).update(preset_id, **body.model_dump(exclude_unset=True))


@router.delete("/{preset_id}", status_code=204)
async def delete_preset(preset_id: str, request: Request) -> Response:
    await _service(request).delete(preset_id)
    return Response(status_code=204)
