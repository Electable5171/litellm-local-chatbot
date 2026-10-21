"""Errors that are shown to the user as a clean JSON body instead of a stack trace."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class LLMError(Exception):
    """A problem talking to LiteLLM, mapped to an HTTP status the browser can act on."""

    def __init__(
        self, code: str, message: str, status: int = 502, retry_after_s: float | None = None
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.retry_after_s = retry_after_s


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(LLMError)
    async def _llm_error(_: Request, exc: LLMError) -> JSONResponse:
        body: dict[str, object] = {"code": exc.code, "message": exc.message}
        if exc.retry_after_s is not None:
            body["retry_after_s"] = exc.retry_after_s
        return JSONResponse(status_code=exc.status, content={"error": body})
