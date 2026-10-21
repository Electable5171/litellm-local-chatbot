"""Errors that are shown to the user as a clean JSON body instead of a stack trace."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class ApiError(Exception):
    """A problem the browser can act on: a stable code, a readable message and an HTTP status."""

    def __init__(
        self, code: str, message: str, status: int = 400, retry_after_s: float | None = None
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.retry_after_s = retry_after_s

    def body(self) -> dict[str, object]:
        body: dict[str, object] = {"code": self.code, "message": self.message}
        if self.retry_after_s is not None:
            body["retry_after_s"] = self.retry_after_s
        return body


class LLMError(ApiError):
    """A problem talking to LiteLLM."""

    def __init__(
        self, code: str, message: str, status: int = 502, retry_after_s: float | None = None
    ):
        super().__init__(code, message, status, retry_after_s)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(status_code=exc.status, content={"error": exc.body()})
