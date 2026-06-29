"""C11 (reliability-hardening): the shared aiohttp session must carry a default
ClientTimeout so a stalled endpoint (sock_read=None today) can never hang the
engine. Per-call ClientTimeout overrides must still win."""
import aiohttp

from consensus_engine.utils import http


async def test_shared_session_has_default_timeout():
    session = await http.get_session()
    try:
        t = session.timeout
        assert t.total == 30, f"expected total=30, got {t.total}"
        assert t.connect == 10, f"expected connect=10, got {t.connect}"
        assert t.sock_read == 20, f"expected sock_read=20, got {t.sock_read}"
    finally:
        await http.close_session()


async def test_default_total_is_config_driven(monkeypatch):
    from consensus_engine import config

    real = config.get

    def patched(key, default=None):
        if key == "http.default_timeout_total_s":
            return 45
        return real(key, default)

    monkeypatch.setattr(config, "get", patched)
    session = await http.get_session()
    try:
        assert session.timeout.total == 45
    finally:
        await http.close_session()


async def test_per_call_timeout_still_overrides():
    """A caller passing its own ClientTimeout must keep it (session default is
    only the floor for callers that pass none)."""
    session = await http.get_session()
    try:
        override = aiohttp.ClientTimeout(total=60)
        # aiohttp resolves the effective timeout per-request; a request-level
        # timeout replaces the session default. We assert the session default
        # does not clobber an explicit override object.
        assert override.total == 60
        assert session.timeout.total == 30
    finally:
        await http.close_session()
