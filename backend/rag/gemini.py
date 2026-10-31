"""One shared Gemini client for the whole process, plus back-pressure.

- Async client (`client.aio`) so one worker can serve many concurrent users
  while they wait on Google, instead of blocking a thread per request.
- SDK-level retries with exponential backoff + jitter for 429/5xx.
- A semaphore caps in-flight Gemini calls per worker so a traffic spike queues
  here briefly instead of blowing through your Google quota.
"""
import asyncio
from contextlib import asynccontextmanager

from fastapi import HTTPException
from google import genai
from google.genai import types

from ..config import settings

client = genai.Client(
    api_key=settings.gemini_api_key or None,
    http_options=types.HttpOptions(
        timeout=120_000,  # ms
        retry_options=types.HttpRetryOptions(
            attempts=4,
            initial_delay=1.0,
            max_delay=20.0,
            exp_base=2.0,
            jitter=1.0,
            http_status_codes=[408, 429, 500, 502, 503, 504],
        ),
    ),
)
aio = client.aio

_slots = asyncio.Semaphore(settings.max_concurrent_gemini_calls)


@asynccontextmanager
async def gemini_slot():
    try:
        await asyncio.wait_for(_slots.acquire(), timeout=settings.gemini_queue_timeout_s)
    except asyncio.TimeoutError:
        raise HTTPException(503, "Server is busy, please retry shortly.", headers={"Retry-After": "5"})
    try:
        yield
    finally:
        _slots.release()
