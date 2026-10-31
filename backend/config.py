"""Central configuration, read once from environment variables (and backend/.env).

Every tunable lives here so the same image can be deployed with different limits
per environment without code changes.
"""
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BACKEND_DIR.parent

# Real environment variables win over the .env file (useful in Docker / cloud).
load_dotenv(BACKEND_DIR / ".env", override=False)


def _int(name: str, default: int) -> int:
    return int(os.getenv(name, default))


def _list(name: str, default: str = "") -> tuple[str, ...]:
    return tuple(x.strip() for x in os.getenv(name, default).split(",") if x.strip())


@dataclass(frozen=True)
class Settings:
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")

    # --- Models -------------------------------------------------------------
    # Default model for answering. Must support the File Search tool.
    default_model: str = os.getenv("DEFAULT_MODEL", "gemini-3-flash-preview")
    # Comma-separated allowlist shown to users. Empty = discover from the API.
    allowed_models: tuple[str, ...] = _list("ALLOWED_MODELS")
    # Embedding model for newly created stores ("" = Google's default).
    embedding_model: str = os.getenv("EMBEDDING_MODEL", "")

    # --- Stores -------------------------------------------------------------
    # Display name of the admin-managed knowledge base every user can query.
    # Filled by `python -m backend.rag.upload_docs`. Empty disables it.
    shared_store_display_name: str = os.getenv("SHARED_STORE_NAME", "my-rag-store")
    # Each user gets a private store named <prefix><user_id>.
    user_store_prefix: str = os.getenv("USER_STORE_PREFIX", "user-")

    # --- Persistence --------------------------------------------------------
    db_path: str = os.getenv("DB_PATH", str(BACKEND_DIR / "var" / "app.db"))

    # --- Capacity & abuse protection ---------------------------------------
    # Max Gemini calls in flight per worker process; extra requests queue.
    max_concurrent_gemini_calls: int = _int("MAX_CONCURRENT_GEMINI_CALLS", 16)
    # Seconds a request waits for a free slot before failing with 503.
    gemini_queue_timeout_s: int = _int("GEMINI_QUEUE_TIMEOUT_S", 30)
    chat_requests_per_minute: int = _int("CHAT_REQUESTS_PER_MINUTE", 20)
    uploads_per_hour: int = _int("UPLOADS_PER_HOUR", 30)
    max_upload_mb: int = _int("MAX_UPLOAD_MB", 100)  # Google's hard limit is 100 MB
    max_documents_per_user: int = _int("MAX_DOCUMENTS_PER_USER", 50)

    allowed_extensions: tuple[str, ...] = _list(
        "ALLOWED_EXTENSIONS",
        ".pdf,.txt,.md,.csv,.html,.htm,.json,.xml,.docx,.xlsx,.pptx,.py,.java,.js,.ts",
    )
    cors_origins: tuple[str, ...] = _list("CORS_ORIGINS", "*")


settings = Settings()
