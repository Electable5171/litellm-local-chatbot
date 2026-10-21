"""Run the app: ``uv run python -m app`` (listens on 127.0.0.1 only)."""

import logging
import sys

import uvicorn
from pydantic import ValidationError

from app.config import get_settings
from app.main import create_app


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    try:
        settings = get_settings()
    except ValidationError as exc:
        print("Configuration problem (see .env.example):", file=sys.stderr)
        for err in exc.errors():
            name = ".".join(str(p) for p in err["loc"]).upper() or "SETTINGS"
            print(f"  - {name}: {err['msg']}", file=sys.stderr)
        raise SystemExit(2) from None
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port, log_level="info")


if __name__ == "__main__":
    main()
