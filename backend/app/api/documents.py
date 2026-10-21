from typing import Any
from urllib.parse import unquote

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from app.errors import ApiError
from app.services.documents import DocumentService

router = APIRouter(prefix="/api/documents")


def _service(request: Request) -> DocumentService:
    return request.app.state.documents


@router.get("")
async def list_documents(request: Request) -> dict[str, Any]:
    return {"documents": await _service(request).list()}


@router.post("")
async def upload_document(request: Request) -> JSONResponse:
    """Upload one file: the request body is the file, ``X-Filename`` is its (URL-encoded) name.

    The content type must be application/octet-stream. Other web pages cannot send that to this
    app without a browser permission check, which this app never grants.
    """
    service = _service(request)
    if request.headers.get("content-type", "").split(";")[0].strip().lower() != (
        "application/octet-stream"
    ):
        raise ApiError("unsupported_media_type", "Send the file as application/octet-stream.", 415)
    filename = unquote(request.headers.get("x-filename", ""))
    if not filename:
        raise ApiError("invalid_file", "The X-Filename header is missing.", 400)
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > service.max_bytes:
        raise ApiError("file_too_large", "The file is too large.", 413)
    data = bytearray()
    async for part in request.stream():
        data += part
        if len(data) > service.max_bytes:
            raise ApiError("file_too_large", "The file is too large.", 413)
    document, created = await service.upload(filename, bytes(data))
    return JSONResponse(document, status_code=201 if created else 200)


@router.get("/{document_id}")
async def get_document(document_id: str, request: Request) -> dict[str, Any]:
    return await _service(request).get(document_id)


@router.delete("/{document_id}", status_code=204)
async def delete_document(document_id: str, request: Request) -> Response:
    await _service(request).delete(document_id)
    return Response(status_code=204)
