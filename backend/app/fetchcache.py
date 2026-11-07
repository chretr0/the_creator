"""Fetch-with-cache for live upstream sources.

Each successful response is kept in memory for a TTL and written to data/cache/ so the demo keeps
working (marked stale, with the original retrieval time) when an upstream is down.
"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.config import settings

# Generic client name; no personal contact details are sent upstream.
USER_AGENT = "NewWorlds-hackathon/0.1 (scenario sandbox; low-volume, cached)"

_memory: dict[str, tuple[float, "Fetched"]] = {}


@dataclass
class Fetched:
    body: str
    retrieved_at: str
    stale: bool
    error: str | None = None


def _cache_path(namespace: str, key: str) -> Path:
    digest = hashlib.sha256(key.encode()).hexdigest()[:24]
    return Path(settings.cache_dir) / namespace / f"{digest}.json"


def _get(url: str, data: bytes | None, timeout_s: float) -> str:
    """One request, retried once after a pause on 429/503/504 (Overpass slot limits)."""
    for attempt in range(2):
        req = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                return resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 503, 504) and attempt == 0:
                time.sleep(3)
                continue
            raise
    raise RuntimeError("unreachable")


def fetch(namespace: str, url: str, ttl_s: int, *, data: bytes | None = None, timeout_s: float = 25,
          cache_key: str | None = None) -> Fetched:
    """GET (or POST when `data`) with memory + disk caching. Raises only if no cached copy exists."""
    key = cache_key or url + (data.decode() if data else "")
    now = time.time()
    hit = _memory.get(key)
    if hit and now - hit[0] < ttl_s:
        return hit[1]

    path = _cache_path(namespace, key)
    # A fresh disk copy (e.g. after a restart) is reused rather than re-querying the upstream.
    if path.exists() and now - path.stat().st_mtime < ttl_s:
        saved = json.loads(path.read_text())
        fetched = Fetched(body=saved["body"], retrieved_at=saved["retrievedAt"], stale=False)
        _memory[key] = (path.stat().st_mtime, fetched)
        return fetched
    try:
        body = _get(url, data, timeout_s)
        fetched = Fetched(body=body, retrieved_at=datetime.now(UTC).isoformat(timespec="seconds"), stale=False)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"url": url, "retrievedAt": fetched.retrieved_at, "body": body}))
        _memory[key] = (now, fetched)
        return fetched
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        if path.exists():
            saved = json.loads(path.read_text())
            return Fetched(body=saved["body"], retrieved_at=saved["retrievedAt"], stale=True, error=str(exc))
        raise
