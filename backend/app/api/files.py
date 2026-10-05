"""Small owner-scoped upload/read API; no OpenAI calls or arbitrary file paths."""

from sqlite3 import Error as SQLiteError

from fastapi import APIRouter, File, HTTPException, Path, Query, Request, Response, UploadFile
from starlette.concurrency import run_in_threadpool

from backend.app.api.conversations import resolve_owner
from backend.app.conversations.service import open_store
from backend.app.files.contracts import FILE_ID_PATTERN, MAX_UPLOAD_BYTES, FileImportError, FileSelection
from backend.app.files.ingestion import ingest_file
from backend.app.files.retrieval import retrieve_file_context
from backend.app.files import storage

router = APIRouter(prefix="/files")


def _read_or_import(function, *args, **kwargs):
    try:
        with open_store() as connection:
            return function(connection, *args, **kwargs)
    except FileImportError as error:
        raise HTTPException(400, str(error)) from None
    except (SQLiteError, OSError):
        raise HTTPException(500, "Could not access the local file store.") from None


@router.post("")
async def import_file(request: Request, response: Response, file: UploadFile = File(...)):
    owner = resolve_owner(request, response)
    try:
        data = await file.read(MAX_UPLOAD_BYTES + 1)
    finally:
        await file.close()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Import a file of at most 5 MB.")
    # Parsing and SQLite work must not block the async server's event loop.
    return await run_in_threadpool(_read_or_import, ingest_file, owner, file.filename, data)


@router.get("")
def imported_files(request: Request, response: Response,
                   limit: int = Query(default=100, ge=1, le=100), offset: int = Query(default=0, ge=0)):
    return {"files": _read_or_import(storage.list_files, resolve_owner(request, response), limit=limit, offset=offset)}


@router.post("/context")
def file_context(body: FileSelection, request: Request, response: Response):
    """An explicit diagnostic read; uploading never calls this or the model."""
    result = _read_or_import(retrieve_file_context, resolve_owner(request, response), body.model_dump())
    return {**result, "status": "provided" if result["count"] else "empty"}


@router.get("/{file_id}")
def imported_file(request: Request, response: Response, file_id: str = Path(pattern=FILE_ID_PATTERN)):
    result = _read_or_import(storage.get_file, resolve_owner(request, response), file_id)
    if result is None:
        raise HTTPException(404, "Imported file not found.")
    return result
