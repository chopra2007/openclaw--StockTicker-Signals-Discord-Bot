"""Global aiohttp session singleton for connection pooling.

All HTTP requests in the engine share one session backed by a
TCPConnector(limit=30).  Call get_session() to obtain it and
close_session() on shutdown.
"""

import asyncio
import logging
from typing import Optional

import aiohttp

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
            _session = aiohttp.ClientSession(connector=connector)
            log.debug("Created shared aiohttp session")
    return _session


async def close_session() -> None:
    """Close and discard the shared session.  Call once on engine shutdown."""
    global _session
    if _session is not None and not _session.closed:
        await _session.close()
        log.debug("Shared aiohttp session closed")
    _session = None
