from typing import Annotated, Any

from fastapi import APIRouter, Query, Request

from app.errors import ApiError
from app.services.stats import RANGES

router = APIRouter(prefix="/api")


@router.get("/stats")
async def stats(
    request: Request,
    range: Annotated[str, Query()] = "7d",  # noqa: A002 (the query parameter is called range)
    tz: Annotated[int, Query(ge=-840, le=840, description="minutes east of UTC")] = 0,
) -> dict[str, Any]:
    """Usage figures from the answers stored on this computer."""
    if range not in RANGES:
        raise ApiError("invalid_range", f"range must be one of: {', '.join(RANGES)}.", 400)
    return await request.app.state.stats.stats(range, tz)
