"""Document ingestion with user-chosen chunking + metadata.

Indexing at Google is asynchronous. Instead of holding the HTTP request open (or
running a background poller that dies with the process), we store the Google
operation name and let the client poll /api/uploads/{job_id}. Any worker or
replica can answer that poll, so the app stays stateless and horizontally scalable.
"""
import mimetypes
import os
import tempfile
import time
import uuid

from fastapi import HTTPException, UploadFile
from google.genai import types

from .. import db
from ..config import settings
from ..schemas import DocumentOut, UploadJob, UploadOptions
from .gemini import aio, gemini_slot
from .stores import ensure_user_store, get_store, user_store_name

_CHUNK = 1024 * 1024


def build_upload_config(options: UploadOptions, display_name: str, mime_type: str | None) -> dict:
    """Translate validated user options into Google's UploadToFileSearchStoreConfig."""
    metadata = []
    for m in options.metadata:
        entry: dict = {"key": m.key}
        if isinstance(m.value, list):
            entry["string_list_value"] = {"values": m.value}
        elif isinstance(m.value, (int, float)):
            entry["numeric_value"] = float(m.value)
        else:
            entry["string_value"] = m.value
        metadata.append(entry)
    config: dict = {
        "display_name": display_name,
        "chunking_config": {
            "white_space_config": {
                "max_tokens_per_chunk": options.chunking.max_tokens_per_chunk,
                "max_overlap_tokens": options.chunking.max_overlap_tokens,
            }
        },
    }
    if metadata:
        config["custom_metadata"] = metadata
    if mime_type:
        config["mime_type"] = mime_type
    return config


async def _spool_to_disk(file: UploadFile, suffix: str) -> str:
    """Stream the upload to a temp file, enforcing the size limit without
    loading the whole file into memory."""
    limit = settings.max_upload_mb * 1024 * 1024
    fd, path = tempfile.mkstemp(suffix=suffix)
    size = 0
    try:
        with os.fdopen(fd, "wb") as out:
            while chunk := await file.read(_CHUNK):
                size += len(chunk)
                if size > limit:
                    raise HTTPException(413, f"File exceeds {settings.max_upload_mb} MB limit")
                out.write(chunk)
        if size == 0:
            raise HTTPException(400, "File is empty")
        return path
    except BaseException:
        os.remove(path)
        raise


async def start_upload(user_id: str, file: UploadFile, options: UploadOptions) -> UploadJob:
    filename = os.path.basename(file.filename or "upload")
    ext = os.path.splitext(filename)[1].lower()
    if ext not in settings.allowed_extensions:
        raise HTTPException(415, f"Unsupported file type '{ext}'. Allowed: {', '.join(settings.allowed_extensions)}")

    store_name = await ensure_user_store(user_id)
    store = await get_store(store_name)
    doc_count = (store.active_documents_count or 0) + (store.pending_documents_count or 0)
    if doc_count >= settings.max_documents_per_user:
        raise HTTPException(409, f"Document limit reached ({settings.max_documents_per_user}). Delete some first.")

    display_name = options.display_name or filename
    mime_type = mimetypes.guess_type(filename)[0] or file.content_type
    config = build_upload_config(options, display_name, mime_type)

    path = await _spool_to_disk(file, ext)
    try:
        async with gemini_slot():
            op = await aio.file_search_stores.upload_to_file_search_store(
                file_search_store_name=store_name, file=path, config=config
            )
    finally:
        os.remove(path)

    now = time.time()
    job = {
        "job_id": uuid.uuid4().hex,
        "user_id": user_id,
        "operation_name": op.name,
        "filename": filename,
        "display_name": display_name,
        "status": "processing",
        "document_name": None,
        "error": None,
        "max_tokens_per_chunk": options.chunking.max_tokens_per_chunk,
        "max_overlap_tokens": options.chunking.max_overlap_tokens,
        "created_at": now,
        "updated_at": now,
    }
    await db.create_job(job)
    if op.done:
        return await refresh_job(user_id, job["job_id"])
    return UploadJob(**job)


async def refresh_job(user_id: str, job_id: str) -> UploadJob:
    job = await db.get_job(user_id, job_id)
    if not job:
        raise HTTPException(404, "Upload job not found")
    if job["status"] == "processing":
        async with gemini_slot():
            op = await aio.operations.get(
                types.UploadToFileSearchStoreOperation(name=job["operation_name"])
            )
        if op.done:
            if op.error:
                job.update(status="failed", error=str(op.error.get("message", op.error)))
            else:
                job.update(status="active", document_name=getattr(op.response, "document_name", None))
            await db.update_job(job_id, status=job["status"], error=job["error"], document_name=job["document_name"])
    return UploadJob(**job)


async def list_jobs(user_id: str) -> list[UploadJob]:
    return [UploadJob(**j) for j in await db.list_jobs(user_id)]


def _metadata_dict(doc: types.Document) -> dict:
    out = {}
    for m in doc.custom_metadata or []:
        if m.string_list_value is not None:
            out[m.key] = list(m.string_list_value.values or [])
        elif m.numeric_value is not None:
            out[m.key] = m.numeric_value
        else:
            out[m.key] = m.string_value
    return out


async def list_documents(user_id: str) -> list[DocumentOut]:
    store_name = await user_store_name(user_id)
    if not store_name:
        return []
    docs = []
    async with gemini_slot():
        pager = await aio.file_search_stores.documents.list(parent=store_name, config={"page_size": 20})
        async for d in pager:
            docs.append(
                DocumentOut(
                    name=d.name,
                    display_name=d.display_name,
                    state=d.state.value if d.state else None,
                    size_bytes=d.size_bytes,
                    mime_type=d.mime_type,
                    created_at=d.create_time.isoformat() if d.create_time else None,
                    metadata=_metadata_dict(d),
                )
            )
    return docs


async def delete_document(user_id: str, document_name: str) -> None:
    store_name = await user_store_name(user_id)
    # Ownership check: the document must live inside this user's own store.
    if not store_name or not document_name.startswith(f"{store_name}/documents/"):
        raise HTTPException(404, "Document not found")
    async with gemini_slot():
        await aio.file_search_stores.documents.delete(name=document_name, config={"force": True})
