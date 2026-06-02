"""Fetch the Wolf newsletter excerpt about a ticker, live from Gmail.

The mention/@-ask agent calls this when asked "what does Wolf say about <T>"
or "show me where he mentions it in the email". The raw email body is never
stored locally (only a hash), and the per-ticker snippet capture sometimes
fails (empty), so the only reliable source of the actual quote is the original
email — re-fetched on demand from Gmail by its message id.

Lookup path: macro_theses (scope_key = ticker) -> evidence_log_json[].src is the
Gmail message id -> fetch that email -> print the subject and the paragraph(s)
that mention the ticker.

Usage:
    python3 -m consensus_engine.tools.wolf_email_excerpt --ticker GOOG
"""

import argparse
import json
import re
import sqlite3
import sys

from consensus_engine import config as cfg


def _thesis_for(ticker: str) -> dict | None:
    """Return {direction, stage, srcs:[msg_id...] most-recent-first} for the
    Wolf thesis on `ticker`, or None if there is no such thesis."""
    db_path = cfg.get("database.path", "consensus.db")
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT direction, stage, evidence_log_json FROM macro_theses "
            "WHERE UPPER(scope_key) = ? AND source = 'wolf' AND status = 'active' "
            "ORDER BY last_updated DESC LIMIT 1",
            (ticker.upper(),),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    direction, stage, ev_json = row
    try:
        log = json.loads(ev_json or "[]")
    except (json.JSONDecodeError, TypeError):
        log = []
    # most-recent first, de-duped, skip empties
    srcs: list[str] = []
    stored_snippets: list[str] = []
    for entry in reversed(log):
        src = (entry.get("src") or "").strip()
        if src and src not in srcs:
            srcs.append(src)
        snip = (entry.get("snippet") or "").strip()
        if snip and snip not in stored_snippets:
            stored_snippets.append(snip)
    return {"direction": direction, "stage": stage, "srcs": srcs,
            "stored_snippets": stored_snippets}


def _fetch_email(message_id: str) -> tuple[str, str]:
    """Return (subject, plain_text_body) for a Gmail message id."""
    from bs4 import BeautifulSoup

    from consensus_engine.scanners import gmail_watcher as gw

    svc = gw._build_service()
    msg = svc.users().messages().get(
        userId="me", id=message_id, format="full"
    ).execute()
    payload = msg.get("payload", {})
    subject = ""
    for h in payload.get("headers", []):
        if h.get("name", "").lower() == "subject":
            subject = h.get("value", "")
            break
    text, html = gw._decode_body(payload)
    body = text if (text and text.strip()) else BeautifulSoup(html or "", "lxml").get_text("\n")
    body = re.sub(r"[ \t]+", " ", body)
    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    return subject, body


def _excerpts(body: str, ticker: str) -> list[str]:
    """Pull the paragraph(s) mentioning the ticker (or close aliases)."""
    terms = {ticker.upper()}
    # a couple of common name aliases Wolf uses alongside the symbol
    aliases = {"GOOG": ["alphabet", "google"], "GOOGL": ["alphabet", "google"],
               "META": ["facebook"], "BRK.B": ["berkshire"]}
    patterns = [re.escape(ticker)] + [re.escape(a) for a in aliases.get(ticker.upper(), [])]
    rx = re.compile(r"(?i)\b(" + "|".join(patterns) + r")\b")
    # Collect a context window around each match, then merge overlapping windows
    # so two nearby hits (e.g. "Alphabet" and "GOOG") yield one clean excerpt.
    spans: list[list[int]] = []
    for m in rx.finditer(body):
        start = max(0, m.start() - 220)
        end = min(len(body), m.end() + 220)
        if spans and start <= spans[-1][1]:
            spans[-1][1] = max(spans[-1][1], end)
        else:
            spans.append([start, end])
    out: list[str] = []
    for start, end in spans[:3]:
        out.append(re.sub(r"\s+", " ", body[start:end].strip()))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ticker", required=True, help="e.g. GOOG")
    ap.add_argument("--max-emails", type=int, default=2,
                    help="how many recent source emails to quote (default 2)")
    args = ap.parse_args()
    ticker = args.ticker.strip().upper()

    thesis = _thesis_for(ticker)
    if thesis is None:
        print(f"No Wolf newsletter thesis on {ticker} is stored.")
        return 0
    print(f"TICKER: {ticker} | Wolf thesis: {thesis['direction']} / {thesis['stage']}")
    if not thesis["srcs"]:
        print("No source email id recorded for this thesis — cannot fetch the excerpt.")
        return 0

    shown = 0
    for src in thesis["srcs"][: args.max_emails]:
        try:
            subject, body = _fetch_email(src)
        except Exception as e:  # noqa: BLE001 — surface the failure plainly
            print(f"\nEMAIL {src}: could not fetch from Gmail ({type(e).__name__}: {e}).")
            continue
        print(f'\nEMAIL: "{subject}"')
        excerpts = _excerpts(body, ticker)
        if excerpts:
            for ex in excerpts:
                print(f'EXCERPT: "{ex}"')
            shown += 1
        else:
            print("EXCERPT: no mention of the ticker symbol in this email's text "
                  "(Wolf may refer to it by name, or the read came from chart images).")
    if shown == 0:
        # Live email had no textual symbol match (common for indices Wolf writes
        # out, e.g. "S&P 500" not "SPX"). Fall back to the snippet the parser
        # already captured for this thesis, if any.
        if thesis["stored_snippets"]:
            print("\nCaptured snippet(s) on record for this thesis:")
            for snip in thesis["stored_snippets"][:3]:
                print(f'EXCERPT: "{snip}"')
        else:
            print("\nNo email excerpt could be retrieved and none was captured "
                  "for this thesis.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
