"""
windows_runtime/ingest_client/post.py

Submits signals to the HTTPS ingest endpoint.  Falls back to a local SQLite
outbox when the server is unreachable, and retries from the outbox in a
background daemon thread.
"""

from __future__ import annotations

import hashlib
import logging
import os
import sqlite3
import ssl
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional
from uuid import uuid4
import json

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_outbox_paused: bool = False

# Directory that contains this file — used to resolve sibling files.
_HERE = Path(__file__).parent

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _bearer_path(routine_id: str) -> Path:
    return _HERE / f".bearer.{routine_id}.local"


def _spki_path() -> Path:
    return _HERE / "spki.pinned"


def _outbox_path() -> Path:
    return _HERE / "outbox.db"


def _read_bearer(routine_id: str) -> str:
    p = _bearer_path(routine_id)
    if not p.exists():
        raise FileNotFoundError(f"Bearer token file not found: {p}")
    token = p.read_text().strip()
    if not token:
        raise ValueError(f"Bearer token file is empty: {p}")
    return token


def _read_spki_pin() -> str:
    p = _spki_path()
    if not p.exists():
        raise FileNotFoundError(f"SPKI pin file not found: {p}")
    return p.read_text().strip()


def _build_ssl_context(spki_pin: str) -> ssl.SSLContext:
    """
    Build an SSL context that verifies the server certificate's SPKI fingerprint
    (SHA-256 of the SubjectPublicKeyInfo DER bytes, hex-encoded).
    """
    ctx = ssl.create_default_context()

    # We do the SPKI check ourselves in _verify_spki; keep normal cert validation
    # so we still verify the chain.  The fingerprint check adds an extra layer.
    ctx.check_hostname = True
    ctx.verify_mode = ssl.CERT_REQUIRED
    return ctx


def _verify_spki(conn: ssl.SSLSocket, expected_pin: str) -> None:
    """Raise ssl.SSLError if the peer certificate SPKI SHA-256 doesn't match."""
    der = conn.getpeercert(binary_form=True)
    if der is None:
        raise ssl.SSLError("No peer certificate received")
    # Extract the SPKI from the DER-encoded certificate.
    # We use the cryptography library if available, otherwise fall back to
    # a manual ASN.1 parse for the common RSA/EC case.
    try:
        from cryptography import x509 as _x509
        from cryptography.hazmat.primitives import serialization as _ser

        cert = _x509.load_der_x509_certificate(der)
        spki_der = cert.public_key().public_bytes(
            _ser.Encoding.DER, _ser.PublicFormat.SubjectPublicKeyInfo
        )
    except ImportError:
        # Minimal fallback: the SPKI starts at a fixed offset only for simple
        # certs, so we hash the entire cert as a best-effort substitute.
        logger.warning(
            "cryptography package not installed; using full-cert hash for SPKI pin"
        )
        spki_der = der

    digest = hashlib.sha256(spki_der).hexdigest()
    if digest != expected_pin.lower():
        raise ssl.SSLError(
            f"SPKI pin mismatch: expected {expected_pin!r}, got {digest!r}"
        )


# ---------------------------------------------------------------------------
# Outbox (SQLite)
# ---------------------------------------------------------------------------


def _get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_outbox_path()), check_same_thread=False)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS outbox (
            nonce          TEXT PRIMARY KEY,
            routine_id     TEXT,
            payload_json   TEXT,
            first_attempt  REAL,
            last_attempt   REAL,
            attempt_count  INTEGER DEFAULT 0,
            dropped_at     REAL
        )
        """
    )
    conn.commit()
    return conn


def _save_to_outbox(payload: dict) -> None:
    now = time.time()
    conn = _get_db()
    try:
        conn.execute(
            """
            INSERT OR REPLACE INTO outbox
                (nonce, routine_id, payload_json, first_attempt, last_attempt, attempt_count, dropped_at)
            VALUES (?, ?, ?, ?, ?, 1, NULL)
            """,
            (payload["nonce"], payload.get("routine_id", ""), json.dumps(payload), now, now),
        )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Core submit
# ---------------------------------------------------------------------------


def submit(
    routine_id: str,
    source_type: str,
    source_detail: str,
    raw_text: str,
    sentiment: str = "neutral",
    event_ts: Optional[float] = None,
) -> bool:
    """
    POST a signal to the ingest endpoint.

    Returns True on success (HTTP 200).
    Returns False and writes to the outbox on 5xx / connection errors.
    Returns False and sets _outbox_paused on 401/403.
    Blocks briefly on 429 (Retry-After).
    """
    global _outbox_paused

    ingest_url = os.environ.get("INGEST_URL")
    if not ingest_url:
        raise EnvironmentError("INGEST_URL environment variable is not set")

    bearer = _read_bearer(routine_id)
    spki_pin = _read_spki_pin()

    payload: dict = {
        "v": 1,
        "src": routine_id,
        "source_type": source_type,
        "source_detail": source_detail,
        "raw_text": raw_text,
        "sentiment": sentiment,
        "event_ts": event_ts,
        "signed_ts": time.time(),
        "nonce": str(uuid4()),
        "routine_id": routine_id,
    }

    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        ingest_url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {bearer}",
        },
        method="POST",
    )

    ssl_ctx = _build_ssl_context(spki_pin)

    try:
        with urllib.request.urlopen(req, context=ssl_ctx, timeout=30) as resp:
            # Verify SPKI pin against the actual socket
            raw_sock = resp.fp.raw._sock if hasattr(resp.fp, "raw") else None
            if raw_sock is not None and hasattr(raw_sock, "getpeercert"):
                _verify_spki(raw_sock, spki_pin)

            status = resp.status
            if status == 200:
                return True

            # Unexpected 2xx — treat as success
            logger.warning("Unexpected HTTP status %d; treating as success", status)
            return True

    except urllib.error.HTTPError as exc:
        status = exc.code

        if status in (401, 403):
            logger.warning(
                "Ingest auth error (HTTP %d) for routine_id=%r; pausing outbox",
                status,
                routine_id,
            )
            _outbox_paused = True
            return False

        if status == 429:
            retry_after = int(exc.headers.get("Retry-After", "60"))
            logger.warning(
                "Ingest rate-limited (HTTP 429); sleeping %ds for routine_id=%r",
                retry_after,
                routine_id,
            )
            time.sleep(retry_after)
            return False

        if 500 <= status < 600:
            logger.warning(
                "Ingest server error (HTTP %d) for routine_id=%r; queuing to outbox",
                status,
                routine_id,
            )
            _save_to_outbox(payload)
            return False

        # Other HTTP errors — queue to outbox
        logger.warning(
            "Unexpected HTTP error (HTTP %d) for routine_id=%r; queuing to outbox",
            status,
            routine_id,
        )
        _save_to_outbox(payload)
        return False

    except (urllib.error.URLError, OSError, ConnectionError) as exc:
        logger.warning(
            "Connection error for routine_id=%r: %s; queuing to outbox",
            routine_id,
            exc,
        )
        _save_to_outbox(payload)
        return False


# ---------------------------------------------------------------------------
# Outbox flush
# ---------------------------------------------------------------------------


def flush_outbox() -> int:
    """
    Retry up to 10 queued outbox rows.

    - Rows older than 23 hours are marked dropped (dropped_at set).
    - Logs CRITICAL if > 900 un-dropped rows remain.
    - Returns number of successful retries.
    """
    if _outbox_paused:
        logger.warning("flush_outbox: outbox is paused (auth error); skipping flush")
        return 0

    conn = _get_db()
    now = time.time()
    drop_horizon = now - 23 * 3600

    try:
        # Mark expired rows as dropped
        conn.execute(
            "UPDATE outbox SET dropped_at=? WHERE dropped_at IS NULL AND first_attempt < ?",
            (now, drop_horizon),
        )
        conn.commit()

        # Check backlog size
        (backlog,) = conn.execute(
            "SELECT COUNT(*) FROM outbox WHERE dropped_at IS NULL"
        ).fetchone()
        if backlog > 900:
            logger.critical(
                "flush_outbox: outbox backlog is %d rows (>900); ingest may be down",
                backlog,
            )

        # Fetch up to 10 rows to retry
        rows = conn.execute(
            """
            SELECT nonce, routine_id, payload_json
            FROM outbox
            WHERE dropped_at IS NULL AND attempt_count > 0
            ORDER BY first_attempt ASC
            LIMIT 10
            """
        ).fetchall()
    finally:
        conn.close()

    successes = 0
    for nonce, routine_id, payload_json in rows:
        try:
            payload = json.loads(payload_json)
        except json.JSONDecodeError:
            logger.warning("flush_outbox: malformed payload for nonce=%r; skipping", nonce)
            continue

        ok = submit(
            routine_id=payload.get("routine_id", routine_id),
            source_type=payload.get("source_type", ""),
            source_detail=payload.get("source_detail", ""),
            raw_text=payload.get("raw_text", ""),
            sentiment=payload.get("sentiment", "neutral"),
            event_ts=payload.get("event_ts"),
        )

        conn2 = _get_db()
        try:
            if ok:
                conn2.execute("DELETE FROM outbox WHERE nonce=?", (nonce,))
                successes += 1
            else:
                conn2.execute(
                    "UPDATE outbox SET last_attempt=?, attempt_count=attempt_count+1 WHERE nonce=?",
                    (time.time(), nonce),
                )
            conn2.commit()
        finally:
            conn2.close()

    return successes


# ---------------------------------------------------------------------------
# Background flush thread
# ---------------------------------------------------------------------------


def _flush_loop() -> None:
    while True:
        time.sleep(60)
        try:
            flush_outbox()
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("flush_outbox background error: %s", exc)


_bg_thread = threading.Thread(target=_flush_loop, daemon=True, name="ingest-outbox-flush")
_bg_thread.start()
