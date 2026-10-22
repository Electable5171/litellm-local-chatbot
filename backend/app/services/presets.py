"""Named system prompts."""

from typing import Any

from app.db import repo
from app.db.database import Database
from app.errors import ApiError


def preset_json(row: repo.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "content": row["content"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _not_found() -> ApiError:
    return ApiError("preset_not_found", "That preset does not exist.", 404)


class PresetService:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def list(self) -> list[dict[str, Any]]:
        return [preset_json(r) for r in await self._db.run(repo.list_presets)]

    async def create(self, name: str, content: str) -> dict[str, Any]:
        name = " ".join(name.split())
        if not name or not content.strip():
            raise ApiError("invalid_preset", "A preset needs a name and some text.", 400)
        return preset_json(await self._db.run(lambda c: repo.create_preset(c, name, content)))

    async def update(
        self, preset_id: str, *, name: str | None = None, content: str | None = None
    ) -> dict[str, Any]:
        if name is not None:
            name = " ".join(name.split())
            if not name:
                raise ApiError("invalid_preset", "The name cannot be empty.", 400)
        if content is not None and not content.strip():
            raise ApiError("invalid_preset", "The text cannot be empty.", 400)
        row = await self._db.run(
            lambda c: repo.update_preset(c, preset_id, name=name, content=content)
        )
        if row is None:
            raise _not_found()
        return preset_json(row)

    async def delete(self, preset_id: str) -> None:
        if not await self._db.run(lambda c: repo.delete_preset(c, preset_id)):
            raise _not_found()
