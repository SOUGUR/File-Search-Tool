"""User identity and per-user rate limiting.

IDENTITY: the browser generates a random ID and sends it as `X-User-Id`. This
isolates users' documents from each other, but it is NOT authentication - anyone
who learns an ID can act as that user. For a public product, replace
`current_user` with real auth (e.g. verify a JWT from Firebase/Auth0/Clerk and
return its `sub`); nothing else in the code needs to change.

RATE LIMITING: an in-memory token bucket per (user, action). It is per worker
process, so the effective limit is roughly limit x workers. When you run several
replicas behind a load balancer, move the buckets to Redis.
"""
import re
import time

from fastapi import Header, HTTPException

_USER_ID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


async def current_user(x_user_id: str = Header(..., alias="X-User-Id")) -> str:
    if not _USER_ID.match(x_user_id):
        raise HTTPException(400, "X-User-Id must be 8-64 characters of letters, digits, - or _")
    return x_user_id


class RateLimiter:
    def __init__(self, capacity: int, per_seconds: float):
        self.capacity = capacity
        self.refill_rate = capacity / per_seconds
        self._buckets: dict[str, tuple[float, float]] = {}  # key -> (tokens, last_ts)

    def check(self, key: str) -> None:
        now = time.monotonic()
        tokens, last = self._buckets.get(key, (self.capacity, now))
        tokens = min(self.capacity, tokens + (now - last) * self.refill_rate)
        if tokens < 1:
            retry_after = int((1 - tokens) / self.refill_rate) + 1
            raise HTTPException(
                429, "Too many requests, slow down.", headers={"Retry-After": str(retry_after)}
            )
        self._buckets[key] = (tokens - 1, now)
        if len(self._buckets) > 50_000:  # bound memory: drop idle (full) buckets
            full = [k for k, (t, ts) in self._buckets.items() if t + (now - ts) * self.refill_rate >= self.capacity]
            for k in full:
                del self._buckets[k]
