"""
windows_runtime/R7_DISCORD_DAEMON/daemon.py

Windows pywinauto UIA daemon for Discord message capture.
Polls Discord UI at ~6x/hour, captures new messages, submits to ingest server.

Usage (direct):
    python daemon.py

Usage (via Task Scheduler):
    python <abs-path>\\daemon.py
    (Task Scheduler action — see install.ps1)

Dependencies:
    pip install pywinauto==0.6.8

Config:
    Copy config.example.json → config.json and edit before first run.
    INGEST_URL must be set as an environment variable (or set in Task Scheduler action).

Logs:
    %APPDATA%\\openclaw\\r7.log  (also echoed to stderr)
"""

from __future__ import annotations

import ctypes
import hashlib
import json
import logging
import os
import pathlib
import random
import sys
import time
from ctypes import wintypes
from datetime import datetime, timezone
from typing import Any

# ---------------------------------------------------------------------------
# Path setup — add parent dir so ingest_client is importable
# ---------------------------------------------------------------------------

_DAEMON_DIR = pathlib.Path(__file__).parent
sys.path.insert(0, str(_DAEMON_DIR.parent))

from ingest_client import submit  # noqa: E402  (after sys.path update)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_CONFIG_FILE = _DAEMON_DIR / "config.json"
_LOG_DIR = pathlib.Path(os.environ.get("APPDATA", pathlib.Path.home())) / "openclaw"
_LOG_FILE = _LOG_DIR / "r7.log"

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


def load_config() -> dict[str, Any]:
    """Read config.json from the same directory as daemon.py."""
    if not _CONFIG_FILE.exists():
        raise FileNotFoundError(
            f"config.json not found at {_CONFIG_FILE}. "
            "Copy config.example.json → config.json and edit."
        )
    with _CONFIG_FILE.open() as fh:
        cfg = json.load(fh)

    # Apply defaults for optional keys
    cfg.setdefault("poll_jitter_s", 30)
    cfg.setdefault("human_activity_timeout_s", 300)
    cfg.setdefault("max_message_age_s", 3600)
    cfg.setdefault("heartbeat_interval_s", 60)
    cfg.setdefault("log_level", "INFO")
    cfg.setdefault("channels", [])
    cfg.setdefault("poll_interval_s", 600)
    return cfg


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


def setup_logging(level: str) -> None:
    """File handler to %APPDATA%/openclaw/r7.log + stderr."""
    _LOG_DIR.mkdir(parents=True, exist_ok=True)

    numeric_level = getattr(logging, level.upper(), logging.INFO)
    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    datefmt = "%Y-%m-%dT%H:%M:%S"

    root = logging.getLogger()
    root.setLevel(numeric_level)

    # File handler
    fh = logging.FileHandler(_LOG_FILE, encoding="utf-8")
    fh.setLevel(numeric_level)
    fh.setFormatter(logging.Formatter(fmt, datefmt=datefmt))
    root.addHandler(fh)

    # Stderr handler
    sh = logging.StreamHandler(sys.stderr)
    sh.setLevel(numeric_level)
    sh.setFormatter(logging.Formatter(fmt, datefmt=datefmt))
    root.addHandler(sh)


logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Human activity gate (ctypes GetCursorPos)
# ---------------------------------------------------------------------------

_user32 = ctypes.WinDLL("user32", use_last_error=True)


def get_cursor_pos() -> tuple[int, int]:
    """Return (x, y) of current cursor position via Win32 GetCursorPos."""
    pt = wintypes.POINT()
    if not _user32.GetCursorPos(ctypes.byref(pt)):
        raise ctypes.WinError(ctypes.get_last_error())
    return (pt.x, pt.y)


def human_activity_gate(timeout_s: int) -> None:
    """
    Block until the cursor has moved within the last ``timeout_s`` seconds.

    Samples cursor position every 30 s; if position is unchanged for
    ``timeout_s`` seconds, keeps waiting.  Returns as soon as movement
    is detected.
    """
    last_pos = get_cursor_pos()
    last_move_ts = time.time()

    while True:
        time.sleep(30)
        now = time.time()
        pos = get_cursor_pos()
        if pos != last_pos:
            last_pos = pos
            last_move_ts = now

        idle_seconds = now - last_move_ts
        if idle_seconds < timeout_s:
            return  # Activity within window — proceed

        logger.debug(
            "human_activity_gate: cursor idle %.0fs (threshold %ds); waiting…",
            idle_seconds,
            timeout_s,
        )


# ---------------------------------------------------------------------------
# Discord window
# ---------------------------------------------------------------------------


def find_discord_window() -> Any:
    """
    Connect to the Discord window via pywinauto UIA backend.
    Returns the top-level window wrapper.
    Raises RuntimeError if Discord is not found after 3 attempts.
    """
    import pywinauto  # noqa: PLC0415

    last_exc: Exception | None = None
    for attempt in range(1, 4):
        try:
            app = pywinauto.Application(backend="uia").connect(
                title_re=".*Discord.*", timeout=10
            )
            win = app.top_window()
            logger.debug("find_discord_window: connected on attempt %d", attempt)
            return win
        except Exception as exc:  # pylint: disable=broad-except
            last_exc = exc
            logger.warning(
                "find_discord_window: attempt %d/3 failed: %s", attempt, exc
            )
            if attempt < 3:
                time.sleep(5)

    raise RuntimeError(
        f"Could not connect to Discord window after 3 attempts: {last_exc}"
    )


# ---------------------------------------------------------------------------
# Message extraction
# ---------------------------------------------------------------------------


def get_channel_messages(window: Any, channel_name: str) -> list[dict[str, Any]]:
    """
    Navigate to ``channel_name`` in the Discord window, scroll to bottom,
    extract visible message elements.

    Returns a list of dicts:
        {
            "automation_id": str,
            "sender": str,
            "text": str,
            "timestamp": str,   # ISO-8601 string from Discord, may be empty
        }

    On any failure (channel not found, element query error) logs a warning
    and returns an empty list so the caller can continue to the next channel.
    """
    messages: list[dict[str, Any]] = []

    try:
        # Locate the channel in the channel list and click it
        channel_list = window.child_window(control_type="List", found_index=0)
        channel_item = channel_list.child_window(
            title_re=f".*{channel_name}.*", control_type="ListItem"
        )
        channel_item.click_input()
        time.sleep(1.5)  # Allow Discord to load messages

        # Scroll to bottom — Discord binds End key or Ctrl+End
        msg_scroller = window.child_window(control_type="ScrollBar", found_index=0)
        try:
            msg_scroller.scroll("down", "page", count=20)
        except Exception:  # pylint: disable=broad-except
            pass  # Best-effort scroll

        # Extract message group elements
        msg_container = window.child_window(
            auto_id="chat-messages", control_type="List"
        )
        items = msg_container.children(control_type="ListItem")

        for item in items:
            try:
                automation_id = item.automation_id() or ""
                # Sender: first Text child that looks like a username
                sender = ""
                text_children = item.children(control_type="Text")
                for tc in text_children:
                    val = tc.window_text().strip()
                    if val:
                        sender = val
                        break

                # Full text: concatenate all Text children beyond the first
                full_parts: list[str] = []
                for tc in text_children[1:]:
                    val = tc.window_text().strip()
                    if val:
                        full_parts.append(val)
                full_text = " ".join(full_parts)

                # Timestamp: look for a child with a time attribute
                timestamp = ""
                try:
                    ts_el = item.child_window(control_type="Text", title_re=r".*\d{1,2}:\d{2}.*")
                    timestamp = ts_el.window_text().strip()
                except Exception:  # pylint: disable=broad-except
                    pass

                if full_text:  # Skip empty messages
                    messages.append(
                        {
                            "automation_id": automation_id,
                            "sender": sender,
                            "text": full_text,
                            "timestamp": timestamp,
                        }
                    )
            except Exception as item_exc:  # pylint: disable=broad-except
                logger.debug(
                    "get_channel_messages: skipping item due to error: %s", item_exc
                )
                continue

    except Exception as exc:  # pylint: disable=broad-except
        logger.warning(
            "get_channel_messages: failed to read channel %r: %s", channel_name, exc
        )

    return messages


# ---------------------------------------------------------------------------
# Dedup + suppression
# ---------------------------------------------------------------------------


def make_dedup_key(msg: dict[str, Any]) -> str:
    """SHA-256 of automation_id | sender | first 50 chars of text."""
    raw = f"{msg['automation_id']}|{msg['sender']}|{msg['text'][:50]}"
    return hashlib.sha256(raw.encode()).hexdigest()


def suppress_same_sender(sender: str, last_seen_times: dict[str, float]) -> bool:
    """Return True (suppress) if this sender was seen less than 60 seconds ago."""
    last = last_seen_times.get(sender)
    if last is None:
        return False
    return (time.time() - last) < 60


# ---------------------------------------------------------------------------
# Heartbeat
# ---------------------------------------------------------------------------


def send_heartbeat(stats: dict[str, Any]) -> None:
    """Submit a heartbeat payload to the ingest server."""
    try:
        submit("R7", "heartbeat", "daemon", json.dumps(stats))
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("send_heartbeat: failed: %s", exc)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


def main_loop(config: dict[str, Any]) -> None:
    """
    Core poll loop:
      - Waits for human activity (cursor movement within threshold)
      - Connects to Discord window
      - Iterates over configured channels, extracts new messages, submits them
      - Sends periodic heartbeats
      - Sleeps for poll_interval_s ± poll_jitter_s between iterations
    """
    setup_logging(config.get("log_level", "INFO"))
    logger.info("R7 Discord daemon starting. Channels: %s", config["channels"])

    seen_keys: set[str] = set()
    last_sender_times: dict[str, float] = {}
    last_heartbeat: float = time.time()
    messages_sent: int = 0

    while True:
        # --- Human activity gate ---
        try:
            human_activity_gate(config["human_activity_timeout_s"])
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("human_activity_gate error: %s; skipping gate", exc)

        # --- Connect to Discord ---
        try:
            window = find_discord_window()
        except RuntimeError as exc:
            logger.warning(
                "Discord window unavailable: %s — sleeping 60s before retry", exc
            )
            time.sleep(60)
            continue

        # --- Poll each channel ---
        for channel in config["channels"]:
            try:
                msgs = get_channel_messages(window, channel)
            except Exception as exc:  # pylint: disable=broad-except
                logger.warning("Error reading channel %r: %s", channel, exc)
                continue

            for msg in msgs:
                # Age check
                if msg.get("timestamp"):
                    try:
                        msg_age = _parse_message_age_s(msg["timestamp"])
                        if msg_age > config["max_message_age_s"]:
                            continue
                    except Exception:  # pylint: disable=broad-except
                        pass  # Unparseable timestamp — do not skip

                # Dedup
                key = make_dedup_key(msg)
                if key in seen_keys:
                    continue

                # Same-sender suppression
                if suppress_same_sender(msg["sender"], last_sender_times):
                    logger.debug(
                        "Suppressing repeat sender %r in channel %r",
                        msg["sender"],
                        channel,
                    )
                    continue

                # Submit
                try:
                    ok = submit("R7", "desktop_local", channel, msg["text"])
                    if ok:
                        seen_keys.add(key)
                        last_sender_times[msg["sender"]] = time.time()
                        messages_sent += 1
                        logger.info(
                            "Submitted message from %r in %r (key=%s…)",
                            msg["sender"],
                            channel,
                            key[:8],
                        )
                    else:
                        logger.warning(
                            "submit() returned False for message in %r; will retry next poll",
                            channel,
                        )
                except Exception as exc:  # pylint: disable=broad-except
                    logger.warning("submit() raised: %s", exc)

        # --- Heartbeat ---
        if time.time() - last_heartbeat > config["heartbeat_interval_s"]:
            stats = {
                "channels_polled": len(config["channels"]),
                "messages_sent": messages_sent,
                "seen_keys_count": len(seen_keys),
                "ts": datetime.now(timezone.utc).isoformat(),
            }
            send_heartbeat(stats)
            last_heartbeat = time.time()
            logger.debug("Heartbeat sent: %s", stats)

        # --- Sleep until next poll ---
        jitter = random.uniform(-config["poll_jitter_s"], config["poll_jitter_s"])
        sleep_s = max(30, config["poll_interval_s"] + jitter)
        logger.debug("Sleeping %.0fs until next poll", sleep_s)
        time.sleep(sleep_s)


# ---------------------------------------------------------------------------
# Timestamp parsing helper
# ---------------------------------------------------------------------------


def _parse_message_age_s(timestamp_str: str) -> float:
    """
    Best-effort parse of a Discord timestamp string to age in seconds.

    Discord shows times like "Today at 2:34 PM", "Yesterday at …", or
    full ISO-8601 strings from the automation_id.  We try ISO-8601 first,
    then fall back to treating anything unparseable as age=0 (do not filter).
    """
    now = time.time()
    # Try ISO-8601
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            dt = datetime.strptime(timestamp_str, fmt)
            return now - dt.timestamp()
        except ValueError:
            continue
    # Unparseable — return 0 so the message is NOT filtered
    return 0.0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    main_loop(load_config())
