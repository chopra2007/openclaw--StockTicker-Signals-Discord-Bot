"""C20 (reliability-hardening): process-wide concurrency cap for unauthenticated
Yahoo (yfinance) fetches.

yfinance hits the same unauth Yahoo host from three places — the options-flow
watcher, max-pain, and peer comparison. With no shared cap they fan out
concurrently and trip Yahoo's per-IP throttle (429s / silent timeouts). A single
bounded semaphore shared across all three call sites is the root-cause fix for
that timeout/throttle class.

Signal-first: the semaphore is only ever held around an *enrichment* fetch
(`run_in_executor` of a blocking yfinance call), never around the instant-alert
decision. A contended acquire waits at most ~one fetch, which is strictly better
than the 429 failure that no cap produces.

The semaphore is created lazily on the running event loop (mirroring the lazy
lock in utils/http.py) and re-created if the loop changes, so it is safe under
pytest's per-test event loops without binding to a dead loop at import time.
"""
import asyncio
from typing import Optional

from consensus_engine import config

_DEFAULT_CONCURRENCY = 3

_sem: Optional[asyncio.Semaphore] = None
_sem_loop = None


def _max_concurrency() -> int:
    try:
        return max(1, int(config.get("yahoo.max_concurrency", _DEFAULT_CONCURRENCY)))
    except (TypeError, ValueError):
        return _DEFAULT_CONCURRENCY


def get_yahoo_semaphore() -> asyncio.Semaphore:
    """Return the shared Yahoo-fetch semaphore for the running event loop.

    Lazily created and bound to the current loop; re-created when the loop
    changes. Must be called from within a running event loop.
    """
    global _sem, _sem_loop
    loop = asyncio.get_running_loop()
    if _sem is None or _sem_loop is not loop:
        _sem = asyncio.Semaphore(_max_concurrency())
        _sem_loop = loop
    return _sem
