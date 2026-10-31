"""Small metadata registry: which Gemini store belongs to which user, and the
status of each upload job.

Why keep this at all? Without it, finding a user's store means listing *every*
store in the Google project on each request - O(number of users). With it, it
is a single primary-key lookup.

SQLite (WAL mode) is safe across several worker processes on one host. For
multiple hosts/replicas, point the same queries at Postgres.
"""
import asyncio
import sqlite3
import time
from pathlib import Path
from typing import Optional

from .config import settings

_SCHEMA = """
CREATE TABLE IF NOT EXISTS user_stores (
    user_id     TEXT PRIMARY KEY,
    store_name  TEXT NOT NULL,
    created_at  REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS upload_jobs (
    job_id                TEXT PRIMARY KEY,
    user_id               TEXT NOT NULL,
    operation_name        TEXT NOT NULL,
    filename              TEXT NOT NULL,
    display_name          TEXT NOT NULL,
    status                TEXT NOT NULL,          -- processing | active | failed
    document_name         TEXT,
    error                 TEXT,
    max_tokens_per_chunk  INTEGER NOT NULL,
    max_overlap_tokens    INTEGER NOT NULL,
    created_at            REAL NOT NULL,
    updated_at            REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jobs_user ON upload_jobs(user_id, created_at DESC);
"""


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(settings.db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    Path(settings.db_path).parent.mkdir(parents=True, exist_ok=True)
    with _connect() as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(_SCHEMA)


def _run(sql: str, params: tuple = (), fetch: str = "") -> object:
    with _connect() as conn:
        cur = conn.execute(sql, params)
        if fetch == "one":
            row = cur.fetchone()
            return dict(row) if row else None
        if fetch == "all":
            return [dict(r) for r in cur.fetchall()]
        return cur.rowcount


async def _q(sql: str, params: tuple = (), fetch: str = ""):
    # sqlite3 is blocking; keep it off the event loop.
    return await asyncio.to_thread(_run, sql, params, fetch)


# ------------------------------------------------------------- user stores --


async def get_user_store(user_id: str) -> Optional[str]:
    row = await _q("SELECT store_name FROM user_stores WHERE user_id=?", (user_id,), "one")
    return row["store_name"] if row else None


async def claim_user_store(user_id: str, store_name: str) -> str:
    """Record store_name for user unless another worker already did; return the winner."""
    await _q(
        "INSERT OR IGNORE INTO user_stores(user_id, store_name, created_at) VALUES (?,?,?)",
        (user_id, store_name, time.time()),
    )
    return await get_user_store(user_id)  # type: ignore[return-value]


# ------------------------------------------------------------- upload jobs --


async def create_job(job: dict) -> None:
    cols = ",".join(job)
    marks = ",".join("?" for _ in job)
    await _q(f"INSERT INTO upload_jobs({cols}) VALUES ({marks})", tuple(job.values()))


async def get_job(user_id: str, job_id: str) -> Optional[dict]:
    return await _q(
        "SELECT * FROM upload_jobs WHERE job_id=? AND user_id=?", (job_id, user_id), "one"
    )


async def list_jobs(user_id: str, limit: int = 50) -> list[dict]:
    return await _q(
        "SELECT * FROM upload_jobs WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
        (user_id, limit),
        "all",
    )


async def update_job(job_id: str, **fields) -> None:
    fields["updated_at"] = time.time()
    sets = ",".join(f"{k}=?" for k in fields)
    await _q(f"UPDATE upload_jobs SET {sets} WHERE job_id=?", (*fields.values(), job_id))
