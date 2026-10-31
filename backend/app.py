import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from google.genai import errors as genai_errors
from pydantic import ValidationError

from . import db
from .config import PROJECT_DIR, settings
from .rag import ingest, query
from .rag.stores import available_models, default_model, shared_store_name
from .schemas import (
    CHUNK_TOKENS_RANGE,
    DEFAULT_CHUNK_TOKENS,
    DEFAULT_OVERLAP_TOKENS,
    OVERLAP_TOKENS_RANGE,
    ChatRequest,
    ChatResponse,
    DocumentOut,
    UploadJob,
    UploadOptions,
)
from .security import RateLimiter, current_user

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("app")

FRONTEND_DIR = PROJECT_DIR / "frontend"

chat_limiter = RateLimiter(settings.chat_requests_per_minute, 60)
upload_limiter = RateLimiter(settings.uploads_per_hour, 3600)


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init_db()
    if not settings.gemini_api_key:
        log.warning("GEMINI_API_KEY is not set - every Gemini call will fail")
    yield


app = FastAPI(title="Gemini RAG Chatbot", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(genai_errors.APIError)
async def gemini_error(_, exc: genai_errors.APIError):
    """Turn Google errors into meaningful HTTP codes instead of a blanket 500."""
    code = exc.code or 502
    status = code if code in (400, 403, 404, 413, 429) else 502
    if code in (401, 403) or "API key" in str(exc.message):
        status = 502  # server misconfiguration, not the end user's fault
    log.warning("Gemini API error %s: %s", code, exc.message)
    return JSONResponse({"detail": f"Gemini: {exc.message or exc.status}"}, status_code=status)


# ------------------------------------------------------------------ health --


@app.get("/healthz")
async def healthz():
    """Liveness probe for Docker / load balancers. Deliberately makes no Gemini call."""
    return {"status": "ok"}


# ----------------------------------------------------------------- options --


@app.get("/api/options")
async def options():
    """Everything the UI needs to render its settings forms (ranges, defaults, models)."""
    return {
        "models": await available_models(),
        "default_model": await default_model(),
        "shared_store_available": bool(await shared_store_name()),
        "chunking": {
            "max_tokens_per_chunk": {"default": DEFAULT_CHUNK_TOKENS, "min": CHUNK_TOKENS_RANGE[0], "max": CHUNK_TOKENS_RANGE[1]},
            "max_overlap_tokens": {"default": DEFAULT_OVERLAP_TOKENS, "min": OVERLAP_TOKENS_RANGE[0], "max": OVERLAP_TOKENS_RANGE[1]},
        },
        "limits": {
            "max_upload_mb": settings.max_upload_mb,
            "max_documents_per_user": settings.max_documents_per_user,
            "allowed_extensions": settings.allowed_extensions,
            "chat_requests_per_minute": settings.chat_requests_per_minute,
            "uploads_per_hour": settings.uploads_per_hour,
        },
    }


# -------------------------------------------------------------------- chat --


@app.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest, user: str = Depends(current_user)):
    chat_limiter.check(user)
    return await query.answer(user, req)


# --------------------------------------------------------------- documents --


@app.post("/api/uploads", response_model=UploadJob, status_code=202)
async def upload(
    file: UploadFile = File(...),
    options: str = Form("{}", description="JSON-encoded UploadOptions"),
    user: str = Depends(current_user),
):
    try:
        opts = UploadOptions.model_validate_json(options)
    except ValidationError as e:
        raise HTTPException(422, e.errors(include_url=False, include_context=False))
    upload_limiter.check(user)
    return await ingest.start_upload(user, file, opts)


@app.get("/api/uploads", response_model=list[UploadJob])
async def list_uploads(user: str = Depends(current_user)):
    return await ingest.list_jobs(user)


@app.get("/api/uploads/{job_id}", response_model=UploadJob)
async def upload_status(job_id: str, user: str = Depends(current_user)):
    return await ingest.refresh_job(user, job_id)


@app.get("/api/documents", response_model=list[DocumentOut])
async def documents(user: str = Depends(current_user)):
    return await ingest.list_documents(user)


@app.delete("/api/documents/{document_name:path}", status_code=204)
async def delete_document(document_name: str, user: str = Depends(current_user)):
    await ingest.delete_document(user, document_name)


# ---------------------------------------------------------------- frontend --

app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


@app.get("/", include_in_schema=False)
async def index():
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    # Browsers request /favicon.ico on their own; serve the SVG icon there too.
    return FileResponse(FRONTEND_DIR / "favicon.svg", media_type="image/svg+xml")
