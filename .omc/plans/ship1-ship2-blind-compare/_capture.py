"""Phase B helper — invoke !all for a ticker via webhook, wait for the bot's
embed reply in #chat, then dump the reply (title + description + fields) to
<ticker>-bot.txt under .omc/plans/ship1-ship2-blind-compare/.

Usage:
    python3 _capture.py NVDA AMD TSLA
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
import time

import requests  # type: ignore[import-not-found]

WEBHOOK = (
    "https://discord.com/api/webhooks/WEBHOOK_ID_REDACTED/"
    "-npHx4ykAqzyWqsbI_EfsMotKRXb42Cvd1alw3M4znTKEHaLOPYQ9_fdyEq4cSnq-lkG"
)
CHANNEL_ID = "1468890179698692147"  # #chat
BOT_USER_ID = "1468886193054814352"  # API#8079
DISCORD_API = "https://discord.com/api/v10"
HERE = pathlib.Path(__file__).resolve().parent


def _bot_token() -> str:
    tok = os.environ.get("DISCORD_BOT_TOKEN")
    if not tok:
        raise SystemExit("DISCORD_BOT_TOKEN must be in env")
    return tok


def _send(ticker: str) -> float:
    """Post `!all <ticker>` via webhook; return the wall-clock send timestamp."""
    payload = {"content": f"!all {ticker}", "username": "ClaudeCode"}
    r = requests.post(WEBHOOK, json=payload, timeout=10)
    r.raise_for_status()
    return time.time()


def _poll_for_embed(ticker: str, sent_at: float, timeout: float = 220.0) -> dict:
    """Poll the channel's latest messages for an embed from the bot whose title
    matches the cashtag for `ticker`. Returns the embed dict or raises.
    """
    headers = {"Authorization": f"Bot {_bot_token()}"}
    url = f"{DISCORD_API}/channels/{CHANNEL_ID}/messages?limit=20"
    deadline = sent_at + timeout
    expected = f"${ticker.upper()}"
    last_err = "no matching embed yet"
    while time.time() < deadline:
        r = requests.get(url, headers=headers, timeout=15)
        if r.status_code == 429:
            time.sleep(2)
            continue
        if r.status_code != 200:
            last_err = f"http {r.status_code}: {r.text[:200]}"
            time.sleep(3)
            continue
        msgs = r.json()
        for m in msgs:
            ts = m.get("timestamp", "")
            # ISO 8601 → epoch; only consider messages after our send timestamp
            try:
                m_epoch = time.mktime(time.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S"))
            except Exception:
                continue
            if m_epoch + 30 < sent_at:  # 30 s clock skew tolerance
                continue
            if str(m.get("author", {}).get("id")) != BOT_USER_ID:
                continue
            for emb in m.get("embeds", []) or []:
                title = emb.get("title", "") or ""
                if title.startswith(expected):
                    return emb
        time.sleep(5)
    raise SystemExit(f"timeout waiting for bot embed for {ticker}: {last_err}")


def _render_embed(emb: dict) -> str:
    out: list[str] = []
    out.append(emb.get("title", ""))
    out.append("")
    desc = emb.get("description", "")
    if desc:
        out.append(desc)
        out.append("")
    for f in emb.get("fields", []) or []:
        out.append(f"--- {f.get('name', '')}")
        out.append(f.get("value", ""))
    footer = (emb.get("footer") or {}).get("text", "")
    if footer:
        out.append("")
        out.append(f"footer: {footer}")
    return "\n".join(out)


def main(args: list[str]) -> int:
    if not args:
        print("usage: _capture.py NVDA AMD TSLA")
        return 1
    score_lines: list[str] = []
    for ticker in args:
        print(f"[{ticker}] sending !all via webhook")
        sent_at = _send(ticker)
        print(f"[{ticker}] sent at {time.strftime('%H:%M:%S')}; polling for bot reply")
        emb = _poll_for_embed(ticker, sent_at)
        text = _render_embed(emb)
        out_path = HERE / f"{ticker.lower()}-bot.txt"
        out_path.write_text(text, encoding="utf-8")
        # Score the 10 sub-changes structurally.
        score = _score(text)
        score_lines.append(f"{ticker}: {sum(score.values())}/10  {json.dumps(score)}")
        print(f"[{ticker}] captured to {out_path}  score {sum(score.values())}/10")
    (HERE / "_scores.txt").write_text("\n".join(score_lines) + "\n", encoding="utf-8")
    print("\n".join(score_lines))
    return 0


def _score(text: str) -> dict:
    """Heuristic 10-point checklist (one per sub-change) against the captured embed."""
    return {
        "N1_cashtag": int(text.startswith("$") or "$" in text.splitlines()[0]),
        "N2_emoji": int(any(e in text for e in ("🟢", "🔴", "⚪"))),
        "N3_compact_money": int(any(s in text for s in ("M\n", "K\n", "B\n", "$2.", "$1.", "M ", "K ", "B "))),
        "N4_arrows": int(any(a in text for a in ("↑", "↓", "⇄"))),
        "N5_oneliner": int(text.count("_") >= 4),  # at least 2 italic phrases (4 underscores)
        "N7_relative_date": int(("in 1 session" in text) or ("in " in text and "sessions" in text) or ("in " in text and " days" in text) or "today" in text),
        "M1_tldr": int("**TL;DR:**" in text or "TL;DR:" in text),
        "M2_bear_case": int("What could go wrong" in text),
        "M3_variant": int("Market view" in text and "Our view" in text),
        "M6_risks_mitigants": int("Risks & mitigants" in text or "Risks &" in text or " → " in text),
    }


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
