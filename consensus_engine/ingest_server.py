"""HTTPS ingest endpoint — accepts signal POSTs from Windows-side routines."""

import asyncio
import hmac
import json
import logging
import os
import random
import ssl
import time
from collections import defaultdict
from typing import Callable

import aiohttp.web

from consensus_engine import config as cfg, db
from consensus_engine.models import Sentiment, SourceType, TickerSignal
from consensus_engine.utils.tickers import extract_tickers

log = logging.getLogger(__name__)

# Per-IP rate-limit buckets: maps prefix → (request_count, window_start)
_rate_buckets: dict[str, tuple[int, float]] = defaultdict(lambda: (0, 0.0))
_rate_lock = asyncio.Lock()

# In-flight semaphore — replaced by serve() with the configured concurrency
_inflight_sem: asyncio.Semaphore = asyncio.Semaphore(32)

# --- Per-routine bearer token mapping ---
# routine_id → (current_env_var, previous_env_var)
_ROUTINE_BEARER_ENV: dict[str, tuple[str, str]] = {
    "R1_AUTHED_WEB":      ("INGEST_BEARER_TOKEN_R1",  "INGEST_BEARER_TOKEN_R1_PREVIOUS"),
    "R7_DISCORD_DAEMON":  ("INGEST_BEARER_TOKEN_R7",  "INGEST_BEARER_TOKEN_R7_PREVIOUS"),
}

_REQUIRED_FIELDS = {"v", "src", "source_type", "source_detail", "raw_text",
                    "sentiment", "event_ts", "signed_ts", "nonce", "routine_id"}


def _ip_prefix(peername: str | None) -> str:
    """Return /64 for IPv6 or /24 for IPv4 — rate-limit bucket key."""
    if not peername:
        return "unknown"
    try:
        import ipaddress
        addr = ipaddress.ip_address(peername)
        if isinstance(addr, ipaddress.IPv6Address):
            net = ipaddress.IPv6Network(f"{peername}/64", strict=False)
        else:
            net = ipaddress.IPv4Network(f"{peername}/24", strict=False)
        return str(net)
    except ValueError:
        return peername


def _get_bearer_tokens(routine_id: str) -> tuple[str, str]:
    """Return (current_token, previous_token) for the given routine_id."""
    env_cur, env_prev = _ROUTINE_BEARER_ENV.get(
        routine_id,
        ("INGEST_BEARER_TOKEN_R1", "INGEST_BEARER_TOKEN_R1_PREVIOUS"),  # safe fallback
    )
    return os.environ.get(env_cur, ""), os.environ.get(env_prev, "")


def _check_bearer(auth_header: str, routine_id: str) -> bool:
    """Timing-safe bearer check. Returns True if header matches current or previous token."""
    if not auth_header or not auth_header.startswith("Bearer "):
        return False
    provided = auth_header[7:].encode()
    current, previous = _get_bearer_tokens(routine_id)
    ok = False
    if current:
        ok = hmac.compare_digest(provided, current.encode()) or ok
    if previous:
        ok = hmac.compare_digest(provided, previous.encode()) or ok
    return ok


@aiohttp.web.middleware
async def ip_rate_limit_mw(request: aiohttp.web.Request, handler):
    """Per-/64 IPv6 / per-/24 IPv4 rate limiter."""
    limit = cfg.get("ingest_server.rate_limit_per_minute", 60)
    if request.path == "/heartbeat":
        limit = cfg.get("ingest_server.heartbeat_rate_limit_per_minute", 5)
    try:
        peername = request.transport.get_extra_info("peername") if request.transport else None
        ip = peername[0] if peername else None
    except Exception:
        ip = None
    prefix = _ip_prefix(ip)
    now = time.time()
    async with _rate_lock:
        count, window_start = _rate_buckets[prefix]
        if now - window_start > 60:
            _rate_buckets[prefix] = (1, now)
        else:
            count += 1
            _rate_buckets[prefix] = (count, window_start)
            if count > limit:
                return aiohttp.web.Response(
                    status=429,
                    headers={"Retry-After": "60"},
                    text="Too Many Requests",
                )
        # Periodic GC: prune stale entries to prevent unbounded growth
        if len(_rate_buckets) > 10_000:
            cutoff = now - 120
            stale = [k for k, (_, ws) in list(_rate_buckets.items()) if ws < cutoff]
            for k in stale:
                del _rate_buckets[k]
    return await handler(request)


@aiohttp.web.middleware
async def redact_log_mw(request: aiohttp.web.Request, handler):
    """Strip Authorization header value from access logs."""
    request["_redacted_auth"] = "Bearer ***REDACTED***"
    return await handler(request)


async def _handle_ingest(request: aiohttp.web.Request) -> aiohttp.web.Response:
    """POST /ingest — validate, dedup, fan-out to insert_signal."""
    sem = _inflight_sem

    async with sem:
        # --- Body parse ---
        max_bytes = cfg.get("ingest_server.body_max_bytes", 65536)
        try:
            raw = await asyncio.wait_for(request.read(), timeout=5.0)
        except asyncio.TimeoutError:
            return aiohttp.web.Response(status=400, text="read timeout")
        if len(raw) > max_bytes:
            return aiohttp.web.Response(status=400, text="body too large")
        try:
            payload = json.loads(raw)
        except (ValueError, RecursionError):
            return aiohttp.web.Response(status=400, text="invalid JSON")

        if not isinstance(payload, dict):
            return aiohttp.web.Response(status=400, text="expected JSON object")
        missing = _REQUIRED_FIELDS - payload.keys()
        if missing:
            return aiohttp.web.Response(status=400, text=f"missing fields: {missing}")

        raw_text = payload.get("raw_text", "")
        if not isinstance(raw_text, str) or len(raw_text.encode()) > cfg.get("ingest_server.raw_text_max_bytes", 8192):
            return aiohttp.web.Response(status=400, text="raw_text too large or invalid")

        # --- Bearer auth ---
        routine_id = payload.get("routine_id", "")
        auth = request.headers.get("Authorization", "")
        if not _check_bearer(auth, routine_id):
            await asyncio.sleep(random.uniform(0.05, 0.15))
            return aiohttp.web.Response(status=401, text="Unauthorized")

        # --- Freshness ---
        max_age = cfg.get("ingest_server.signed_ts_max_age_seconds", 600)
        signed_ts = payload.get("signed_ts", 0)
        try:
            signed_ts_f = float(signed_ts)
        except (TypeError, ValueError):
            return aiohttp.web.Response(status=400, text="signed_ts must be numeric")
        if abs(time.time() - signed_ts_f) > max_age:
            return aiohttp.web.Response(status=400, text="signed_ts out of window")

        # --- Nonce dedup ---
        nonce = str(payload.get("nonce", ""))
        if not nonce:
            return aiohttp.web.Response(status=400, text="empty nonce")

        conn = await db.get_db()
        cur = await conn.execute(
            "INSERT OR IGNORE INTO seen_ingest_nonces (nonce, routine_id, received_at) VALUES (?, ?, ?)",
            (nonce, routine_id, time.time()),
        )
        await conn.commit()
        if cur.rowcount == 0:
            # Nonce already seen — return cached result if available
            res = await conn.execute(
                "SELECT tickers_inserted FROM ingest_payload_results WHERE nonce = ?", (nonce,)
            )
            row = await res.fetchone()
            if row:
                return aiohttp.web.json_response({"ok": True, "tickers_inserted": row["tickers_inserted"]})
            # In-flight or crashed mid-fanout — tell client to retry
            return aiohttp.web.Response(
                status=409,
                headers={"Retry-After": "10"},
                text="nonce in-flight, retry",
            )

        # --- Fan-out ---
        try:
            event_ts = float(payload.get("event_ts", time.time()))
        except (TypeError, ValueError):
            event_ts = time.time()
        try:
            tickers = extract_tickers(raw_text)
        except Exception as exc:
            log.warning("extract_tickers error: %s", exc)
            tickers = set()

        source_type_str = str(payload.get("source_type", "desktop_auth"))
        source_detail = str(payload.get("source_detail", ""))[:500]
        sentiment_str = str(payload.get("sentiment", "neutral")).lower()
        try:
            sentiment = Sentiment(sentiment_str)
        except ValueError:
            sentiment = Sentiment.NEUTRAL
        try:
            source_type = SourceType(source_type_str)
        except ValueError:
            source_type = SourceType.DESKTOP_AUTH

        inserted = 0
        for ticker in tickers:
            try:
                await db.insert_signal(TickerSignal(
                    ticker=ticker,
                    source_type=source_type,
                    source_detail=source_detail,
                    raw_text=raw_text,
                    sentiment=sentiment,
                    detected_at=event_ts,
                ))
                inserted += 1
            except Exception as exc:
                log.error("insert_signal error ticker=%s nonce=%s: %s", ticker, nonce, exc)

        # Record fan-out result for idempotent retry
        await conn.execute(
            "INSERT OR REPLACE INTO ingest_payload_results (nonce, tickers_inserted, completed_at) VALUES (?, ?, ?)",
            (nonce, inserted, time.time()),
        )
        await conn.commit()
        return aiohttp.web.json_response({"ok": True, "tickers_inserted": inserted})


async def _handle_heartbeat(request: aiohttp.web.Request) -> aiohttp.web.Response:
    """POST /heartbeat — validates bearer, upserts routine_health."""
    try:
        raw = await asyncio.wait_for(request.read(), timeout=3.0)
        payload = json.loads(raw) if raw else {}
    except Exception as exc:
        log.warning("heartbeat body read/parse error: %s", exc)
        payload = {}

    routine_id = str(payload.get("routine_id", ""))
    auth = request.headers.get("Authorization", "")
    if not _check_bearer(auth, routine_id):
        await asyncio.sleep(random.uniform(0.05, 0.15))
        return aiohttp.web.Response(status=401, text="Unauthorized")

    kind = str(payload.get("kind", "heartbeat"))
    now = time.time()
    conn = await db.get_db()
    await conn.execute(
        """INSERT INTO routine_health (routine_id, last_cycle_started, last_success_at, errors_in_cycle, meta_json)
           VALUES (?, ?, ?, 0, ?)
           ON CONFLICT(routine_id) DO UPDATE SET
               last_success_at = excluded.last_success_at,
               last_cycle_started = CASE WHEN excluded.last_cycle_started IS NOT NULL THEN excluded.last_cycle_started ELSE last_cycle_started END,
               meta_json = excluded.meta_json""",
        (routine_id,
         now if kind == "routine_started" else None,
         now,
         json.dumps(payload.get("meta", {}))),
    )
    await conn.commit()
    return aiohttp.web.json_response({"ok": True})


async def serve(
    stop_event: asyncio.Event,
    record_ok: Callable[[str], None] | None = None,
    record_err: Callable[[str], None] | None = None,
) -> None:
    """Start the ingest HTTPS server; run until stop_event is set."""
    global _inflight_sem
    concurrency = cfg.get("ingest_server.inflight_concurrency", 32)
    _inflight_sem = asyncio.Semaphore(concurrency)

    app = aiohttp.web.Application(middlewares=[ip_rate_limit_mw, redact_log_mw])
    app.router.add_post("/ingest", _handle_ingest)
    app.router.add_post("/heartbeat", _handle_heartbeat)

    enabled = cfg.get("ingest_server.enabled", False)
    if not enabled:
        log.info("ingest_server disabled in config, not starting")
        await stop_event.wait()
        return

    port = cfg.get("ingest_server.port", 8443)
    bind = cfg.get("ingest_server.bind_address", "0.0.0.0")
    cert_path = cfg.get("ingest_server.tls_cert_path", "")
    key_path = cfg.get("ingest_server.tls_key_path", "")

    ssl_ctx: ssl.SSLContext | None = None
    if cert_path and key_path:
        try:
            ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ssl_ctx.load_cert_chain(cert_path, key_path)
            log.info("ingest_server: TLS loaded from %s", cert_path)
        except Exception as exc:
            log.error("ingest_server: TLS load failed (%s) — starting without TLS", exc)
            ssl_ctx = None

    runner = aiohttp.web.AppRunner(app)
    await runner.setup()
    site = aiohttp.web.TCPSite(runner, bind, port, ssl_context=ssl_ctx)
    try:
        await site.start()
        log.info("ingest_server listening on %s:%s (TLS=%s)", bind, port, ssl_ctx is not None)
        if record_ok:
            record_ok("ingest_server")
        await stop_event.wait()
    except Exception as exc:
        log.error("ingest_server failed to start: %s", exc)
        if record_err:
            record_err("ingest_server")
        raise
    finally:
        await runner.cleanup()
        log.info("ingest_server stopped")
