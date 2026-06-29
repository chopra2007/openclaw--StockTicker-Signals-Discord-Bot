"""Global aiohttp session singleton for connection pooling.

All HTTP requests in the engine share one session backed by a
TCPConnector(limit=30).  Call get_session() to obtain it and
close_session() on shutdown.
"""

import asyncio
import logging
from typing import Optional

import aiohttp

from consensus_engine import config

log = logging.getLogger("consensus_engine.utils.http")

_session: Optional[aiohttp.ClientSession] = None
_lock: Optional[asyncio.Lock] = None


def _get_lock() -> asyncio.Lock:
    global _lock
    if _lock is None:
        _lock = asyncio.Lock()
    return _lock


async def get_session() -> aiohttp.ClientSession:
    """Return the shared ClientSession, creating or recreating it as needed."""
    global _session
    lock = _get_lock()
    async with lock:
        if _session is None or _session.closed:
            connector = aiohttp.TCPConnector(limit=30)
            # C11 (reliability-hardening): a default timeout so a stalled
            # endpoint can never hang the engine. aiohttp's stock default leaves
            # sock_read=None (no read cap) — the documented hang vector. A
            # caller passing its own ClientTimeout per-request still overrides
            # this floor. Only `total` is config-tunable; connect/sock_read are
            # conservative fixed guards.
            timeout = aiohttp.ClientTimeout(
                total=config.get("http.default_timeout_total_s", 30),
                connect=10,
                sock_read=20,
            )
            _session = aiohttp.ClientSession(connector=connector, timeout=timeout)
            log.debug("Created shared aiohttp session")
    return _session


async def close_session() -> None:
    """Close and discard the shared session.  Call once on engine shutdown."""
    global _session
    if _session is not None and not _session.closed:
        await _session.close()
        log.debug("Shared aiohttp session closed")
    _session = None
