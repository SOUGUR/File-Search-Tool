"""Store resolution: one shared knowledge base + one private store per user.

Isolation model: each user's documents live in their own File Search store, so a
user can never retrieve another user's chunks, whatever metadata_filter they send.
"""
import asyncio
import logging
import time
from typing import Optional

from google.genai import types

from .. import db
from ..config import settings
from .gemini import aio, gemini_slot

log = logging.getLogger(__name__)

# Lock striping: bounded memory however many users exist.
_locks = [asyncio.Lock() for _ in range(256)]


def _lock_for(key: str) -> asyncio.Lock:
    return _locks[hash(key) % len(_locks)]


# ------------------------------------------------------------- shared store --

_shared: dict = {"name": None, "checked_at": 0.0}
_SHARED_TTL = 300  # re-check every 5 min so an admin upload shows up without restart


async def shared_store_name() -> Optional[str]:
    """Resource name of the admin-managed shared store, or None if not created yet."""
    if not settings.shared_store_display_name:
        return None
    if _shared["name"] or time.monotonic() - _shared["checked_at"] < _SHARED_TTL:
        return _shared["name"]
    async with _lock_for("__shared__"):
        if _shared["name"] or time.monotonic() - _shared["checked_at"] < _SHARED_TTL:
            return _shared["name"]
        try:
            async with gemini_slot():
                pager = await aio.file_search_stores.list(config={"page_size": 20})
                async for s in pager:
                    if s.display_name == settings.shared_store_display_name:
                        _shared["name"] = s.name
                        break
        except Exception as e:  # don't take chat down if listing fails
            log.warning("Could not resolve shared store: %s", e)
        _shared["checked_at"] = time.monotonic()
        return _shared["name"]


# --------------------------------------------------------------- user store --


async def user_store_name(user_id: str) -> Optional[str]:
    """The user's store, or None if they have never uploaded anything."""
    return await db.get_user_store(user_id)


async def ensure_user_store(user_id: str) -> str:
    existing = await db.get_user_store(user_id)
    if existing:
        return existing
    async with _lock_for(user_id):  # dedupe concurrent first uploads in this worker
        existing = await db.get_user_store(user_id)
        if existing:
            return existing
        config: dict = {"display_name": f"{settings.user_store_prefix}{user_id}"}
        if settings.embedding_model:
            config["embedding_model"] = settings.embedding_model
        async with gemini_slot():
            store = await aio.file_search_stores.create(config=config)
        winner = await db.claim_user_store(user_id, store.name)
        if winner != store.name:  # another worker won the race; clean up ours
            log.info("Store race for %s, deleting duplicate %s", user_id, store.name)
            async with gemini_slot():
                await aio.file_search_stores.delete(name=store.name, config={"force": True})
        return winner


async def get_store(name: str) -> types.FileSearchStore:
    async with gemini_slot():
        return await aio.file_search_stores.get(name=name)


# ------------------------------------------------------------------ models --

_models: dict = {"list": [], "fetched_at": 0.0}
_MODELS_TTL = 3600
_SKIP = ("embedding", "image", "tts", "audio", "live", "veo", "imagen", "robotics", "computer-use")


async def available_models() -> list[str]:
    """Models users may pick: ALLOWED_MODELS if set, else discovered from the API."""
    if settings.allowed_models:
        return list(settings.allowed_models)
    if _models["list"] and time.monotonic() - _models["fetched_at"] < _MODELS_TTL:
        return _models["list"]
    names: list[str] = []
    ttl_offset = 0.0
    try:
        async with gemini_slot():
            pager = await aio.models.list()
            async for m in pager:
                short = (m.name or "").removeprefix("models/")
                actions = m.supported_actions or []
                if "generateContent" in actions and short.startswith("gemini") and not any(
                    s in short for s in _SKIP
                ):
                    names.append(short)
    except Exception as e:
        log.warning("Model discovery failed: %s", e)
        ttl_offset = _MODELS_TTL - 60  # failure: retry in a minute, not an hour
    names = sorted(set(names), reverse=True) or [settings.default_model]
    _models.update(list=names, fetched_at=time.monotonic() - ttl_offset)
    return names


async def default_model() -> str:
    models = await available_models()
    if settings.default_model in models:
        return settings.default_model
    flash = [m for m in models if "flash" in m and "lite" not in m]
    return (flash or models)[0]
