#!/usr/bin/env python3
"""Lane B (material company-news reaction) — Stage 2: build the point-in-time
event table from raw Finnhub company-news rows.

Pre-registered method (do not edit in place — see hypotheses-v1.md "Lane B"):

  1. Pull Finnhub /company-news for a small fixed ticker set over a fixed
     2026-06-01..2026-08-22 window, in weekly chunks (Stage-1 audit found
     AAPL's cached monthly pull was silently truncated to the last few days
     of each month near Finnhub's ~250-row response cap -- weekly chunking
     for ALL tickers, not just the one that hit the cap, removes that risk
     uniformly rather than trusting an unverified cache for the others).
  2. Deterministic regex chaff filter -- drops the templated/roundup
     headline shapes the Stage-1 audit's manual spot-check (item 5) actually
     found (Sector Update, Market Wrap, "N Reasons", ValuEngine, Zacks Rank,
     "rises/falls than the market", etc.). This only cuts obvious cost before
     the LLM pass; it is not the event/non-event decision.
  3. Deterministic duplicate clustering: same ticker, normalized-headline
     match, within a 48h window -> one cluster, earliest row is the
     representative timestamp, every row's URL kept as evidence.
  4. One LLM classification call per batch of surviving representative rows
     (house call_with_fallback(role="primary"), temperature=0, JSON output).
     The model may only classify event_type / materiality / novelty /
     direction_implied from the given headline+summary text and must quote
     its evidence -- it may not invent a timestamp, fact, or ticker link.
  5. Frozen retention rule (fixed BEFORE looking at outcomes, per Section 8):
     is_distinct_event=True AND materiality in {high, medium} AND
     novelty=True AND direction_implied in {bullish, bearish}.
  6. Collapse to one retained event per (ticker, Eastern trading day) --
     highest materiality wins ties broken by earliest timestamp.
  7. Tag period: dev = trading_day < 2026-07-01, eval = trading_day >=
     2026-07-01 (untouched until the eval script runs it once).

Read-only against consensus.db (not used here at all -- no DB writes or
reads in this script). Bounded, cached Finnhub calls. No secrets printed.

Usage: python3 scripts/research/lane_b_build_events.py
"""
from __future__ import annotations

import asyncio
import json
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from consensus_engine import config as cfg  # noqa: E402
from consensus_engine.llm_client import call_with_fallback  # noqa: E402

ET = ZoneInfo("America/New_York")
PT = ZoneInfo("America/Los_Angeles")
UTC = timezone.utc

SCRATCH = Path("/tmp/event-reaction-lane-b")
SCRATCH.mkdir(exist_ok=True)

OUT_DIR = ROOT / ".omc" / "research" / "event-reaction-short-duration"

TICKERS = ["AAPL", "MRNA", "ROKU", "GME"]
SECTOR_ETF = {  # AAPL/MRNA from the project's own sector_map.yaml; ROKU/GME
                # are unmapped there (not among its ~63 covered tickers) --
                # assigned here by the closest listed GICS sector.
    "AAPL": "XLK",   # Technology (sector_map.yaml)
    "MRNA": "XLV",   # Health Care (sector_map.yaml)
    "ROKU": "XLC",   # Communication Services -- streaming/media, not mapped upstream
    "GME": "XLY",    # Consumer Discretionary -- specialty retail, not mapped upstream
}

WINDOW_START = "2026-06-01"
WINDOW_END = "2026-08-22"   # yesterday relative to the 2026-08-23 session; avoids a partial in-progress day
DEV_EVAL_SPLIT = "2026-07-01"  # dev = [WINDOW_START, split); eval = [split, WINDOW_END]

FINNHUB_KEY = cfg.get_api_key("finnhub")

# ---------------------------------------------------------------------------
# Step 1: weekly-chunked Finnhub company-news pull (avoids the truncation the
# Stage-1 audit found in AAPL's monthly query).
# ---------------------------------------------------------------------------
def _weekly_chunks(start: str, end: str, days: int = 7) -> list[tuple[str, str]]:
    d0 = datetime.strptime(start, "%Y-%m-%d").date()
    d1 = datetime.strptime(end, "%Y-%m-%d").date()
    chunks = []
    cur = d0
    while cur <= d1:
        chunk_end = min(cur + timedelta(days=days - 1), d1)
        chunks.append((cur.isoformat(), chunk_end.isoformat()))
        cur = chunk_end + timedelta(days=1)
    return chunks


def fetch_news_chunked(ticker: str) -> list[dict]:
    cache_path = SCRATCH / f"news_{ticker}_chunked.json"
    if cache_path.exists():
        cached = json.loads(cache_path.read_text())
        print(f"[news] {ticker}: using cached chunked pull ({len(cached)} rows)", file=sys.stderr)
        return cached
    if not FINNHUB_KEY:
        raise RuntimeError("FINNHUB_API_KEY not configured -- cannot pull news")
    rows: list[dict] = []
    seen_ids = set()
    request_log = []
    for frm, to in _weekly_chunks(WINDOW_START, WINDOW_END):
        resp = requests.get(
            "https://finnhub.io/api/v1/company-news",
            params={"symbol": ticker, "from": frm, "to": to, "token": FINNHUB_KEY},
            timeout=15,
        )
        chunk_rows = resp.json() if resp.status_code == 200 else []
        if not isinstance(chunk_rows, list):
            chunk_rows = []
        request_log.append({"from": frm, "to": to, "row_count": len(chunk_rows),
                             "near_cap_flag": len(chunk_rows) >= 245})
        for r in chunk_rows:
            rid = r.get("id")
            if rid is not None and rid in seen_ids:
                continue
            if rid is not None:
                seen_ids.add(rid)
            rows.append(r)
        print(f"[news] {ticker} {frm}..{to}: {len(chunk_rows)} rows "
              f"({'NEAR CAP' if len(chunk_rows) >= 245 else 'ok'})", file=sys.stderr)
        time.sleep(0.5)
    cache_path.write_text(json.dumps(rows))
    (SCRATCH / f"news_{ticker}_request_log.json").write_text(json.dumps(request_log, indent=2))
    return rows


# ---------------------------------------------------------------------------
# Step 2: deterministic chaff/template regex filter.
# ---------------------------------------------------------------------------
CHAFF_PATTERNS = [
    r"\bsector update\b",
    r"\bmarket wrap\b",
    r"\bpost market wrap\b",
    r"\bthings to know before\b",
    r"\btop gainers and losers\b",
    r"\bbest[- ]performing stocks\b",
    r"\bvaluengine\b",
    r"\bzacks rank\b",
    r"\bkey facts\b",
    r"\bstock market today\b",
    r"^\d+ reasons\b",
    r"\brises? higher than (the )?market\b",
    r"\bfalls? lower than (the )?market\b",
    r"\bwall street\b.*\b(gains|losses|higher|lower)\b",
    r"\bdow (jones )?(industrial average )?hits\b",
    r"\d+ best[- ]performing stocks",
    r"^explore the top",
    r"^\d+ (top|best|worst) stocks",
    r"\bweekly market summary\b",
]
_CHAFF_RE = re.compile("|".join(CHAFF_PATTERNS), re.IGNORECASE)


def is_regex_chaff(headline: str) -> bool:
    return bool(_CHAFF_RE.search(headline or ""))


# ---------------------------------------------------------------------------
# Step 3: deterministic duplicate clustering (same ticker, normalized
# headline, within 48h -- earliest row is the cluster representative).
# ---------------------------------------------------------------------------
def _normalize_headline(h: str) -> str:
    words = "".join(c.lower() for c in (h or "") if c.isalnum() or c.isspace()).split()
    return " ".join(words[:8])


def cluster_duplicates(rows: list[dict]) -> list[dict]:
    """Adds dup_cluster_id and dup_cluster_size to every row in place; returns
    the list of cluster-representative rows (earliest datetime per cluster)."""
    rows_sorted = sorted(rows, key=lambda r: r.get("datetime", 0))
    clusters: dict[str, list[dict]] = {}
    cluster_order: list[str] = []
    for r in rows_sorted:
        norm = _normalize_headline(r.get("headline", ""))
        ts = r.get("datetime", 0)
        placed = False
        # look for an existing open cluster with the same normalized headline
        # whose most recent member is within 48h
        for cid in reversed(cluster_order[-50:]):  # bounded lookback, rows are time-sorted
            members = clusters[cid]
            if members[0]["_norm"] == norm and abs(ts - members[-1]["datetime"]) <= 172800:
                members.append({**r, "_norm": norm})
                placed = True
                break
        if not placed:
            cid = f"c{len(cluster_order)}"
            clusters[cid] = [{**r, "_norm": norm}]
            cluster_order.append(cid)
    reps = []
    for cid, members in clusters.items():
        rep = dict(members[0])
        rep.pop("_norm", None)
        rep["dup_cluster_id"] = cid
        rep["dup_cluster_size"] = len(members)
        rep["dup_cluster_urls"] = [m.get("url", "") for m in members]
        rep["dup_cluster_sources"] = sorted({m.get("source", "") for m in members})
        reps.append(rep)
    return reps


# ---------------------------------------------------------------------------
# Step 4: LLM classification (batched, house call_with_fallback pattern --
# see wolf_verifier.py's numbered-candidate / JSON-verdict shape).
# ---------------------------------------------------------------------------
CLASSIFY_SYSTEM = """You classify financial news headlines for a research study on \
whether company-specific news predicts short-term stock price direction.

For EACH numbered item, using ONLY the headline and summary text given, decide:
- is_distinct_event: true if this headline describes ONE specific, dateable thing \
that happened to this company (a contract, guidance change, regulatory action, \
clinical trial result, merger/acquisition, financing, major lawsuit outcome, \
management change, or a concretely described product event). false if it is a \
roundup, opinion/listicle piece, templated recurring feature, analyst-rating \
recap, or commentary about a result that would be independently reported elsewhere \
(e.g. "3 reasons to buy X", generic price-move description, market-wide roundup \
mentioning the ticker only in passing).
- event_type: one short label (e.g. "guidance", "contract", "merger", \
"regulatory", "clinical_trial", "financing", "legal", "management_change", \
"product_event", "other"). Use "none" if is_distinct_event is false.
- materiality: "high", "medium", "low", or "none" -- how much this event could \
reasonably move investor expectations about the company's value, based only on \
what the text says (not on how big the company is).
- novelty: true if this is genuinely new information the market has not already \
had a chance to price in from an earlier identical report; false if it reads as a \
rehash, follow-on commentary, or restatement of something already known.
- direction_implied: "bullish", "bearish", or "unknown" -- the direction a \
reasonable trader would read from the text ALONE. Do not guess a company's future \
stock price; only report what the text itself implies (e.g. "beat estimates" \
implies bullish, "recalls product" implies bearish, "reports quarterly results" \
with no result stated implies unknown).
- evidence_quote: a short (<=25 word) exact quote from the headline or summary \
that supports your materiality/direction call. If is_distinct_event is false, \
still give a short quote showing why it's not a distinct event (e.g. the listicle \
framing).

You must NOT invent any fact, date, or outcome not present in the text. If the \
text is ambiguous, say so via "unknown"/"low"/"none" rather than guessing.

Return ONLY a JSON object: {"classifications": [{"id": <int>, \
"is_distinct_event": <bool>, "event_type": "<str>", "materiality": "<str>", \
"novelty": <bool>, "direction_implied": "<str>", "evidence_quote": "<str>"}, ...]}
One object per numbered item, in any order, covering every id given."""

BATCH_SIZE = 12  # smaller batches -- a 25-item batch's JSON response sometimes
                 # exceeded max_tokens mid-object and came back unparseable
                 # (observed empirically: 2 of the first 5 batches at size 25
                 # failed to parse; retry logic below also splits further)
# Bounded worst-case LLM-classification cost: AAPL's raw news volume turned
# out far larger than MRNA/ROKU/GME even after weekly-chunked pulls (Finnhub
# still hit its ~250-row cap on 9 of 12 AAPL weekly windows -- see
# lane_b_build_summary.json's raw_rows_pulled_per_ticker). Rather than an
# unbounded classification pass, cap candidates sent to the LLM per ticker at
# a fixed number, sampled deterministically (evenly spaced through the
# chronological, chaff-filtered list, not cherry-picked) so both dev and eval
# windows keep proportional representation. This trades some AAPL recall for
# a bounded, predictable run -- named explicitly in the builder verdict.
MAX_LLM_CANDIDATES_PER_TICKER = 220


def _parse_json(raw: str) -> dict | None:
    if not raw:
        return None
    s = raw.strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\n?", "", s)
        s = re.sub(r"\n?```$", "", s).strip()
    try:
        return json.loads(s)
    except Exception:
        m = re.search(r"\{.*\}", s, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                return None
    return None


async def classify_batch(items: list[dict]) -> dict[int, dict]:
    """items: [{"id": int, "ticker": str, "headline": str, "summary": str}]."""
    lines = []
    for it in items:
        summary = (it["summary"] or "")[:300]
        lines.append(f'{it["id"]}. [{it["ticker"]}] HEADLINE: "{it["headline"]}"\n   SUMMARY: "{summary}"')
    user = "Classify these items:\n\n" + "\n".join(lines)
    messages = [
        {"role": "system", "content": CLASSIFY_SYSTEM},
        {"role": "user", "content": user},
    ]
    raw = await call_with_fallback(
        role="primary", messages=messages, max_tokens=4500, temperature=0.0, timeout=60,
    )
    parsed = _parse_json(raw)
    out: dict[int, dict] = {}
    if not isinstance(parsed, dict):
        print(f"  WARNING: batch classification returned no parseable JSON "
              f"(raw len={len(raw or '')}) -- {len(items)} items unclassified", file=sys.stderr)
        return out
    for c in (parsed.get("classifications") or []):
        if not isinstance(c, dict):
            continue
        try:
            cid = int(c.get("id"))
        except (TypeError, ValueError):
            continue
        out[cid] = {
            "is_distinct_event": bool(c.get("is_distinct_event")),
            "event_type": str(c.get("event_type", "other")),
            "materiality": str(c.get("materiality", "none")).lower(),
            "novelty": bool(c.get("novelty")),
            "direction_implied": str(c.get("direction_implied", "unknown")).lower(),
            "evidence_quote": str(c.get("evidence_quote", ""))[:200],
        }
    return out


async def classify_all(candidates: list[dict]) -> dict[int, dict]:
    results: dict[int, dict] = {}
    by_id = {c["_id"]: c for c in candidates}
    batches = [candidates[i:i + BATCH_SIZE] for i in range(0, len(candidates), BATCH_SIZE)]
    all_missing: set[int] = set()
    for bi, batch in enumerate(batches):
        print(f"[llm] classifying batch {bi+1}/{len(batches)} ({len(batch)} items)...", file=sys.stderr)
        items = [{"id": c["_id"], "ticker": c["related"], "headline": c.get("headline", ""),
                  "summary": c.get("summary", "")} for c in batch]
        got = await classify_batch(items)
        results.update(got)
        missing = {it["id"] for it in items} - set(got)
        if missing:
            print(f"  batch {bi+1}: {len(missing)} ids missing from response: {sorted(missing)}",
                  file=sys.stderr)
            all_missing |= missing

    # One retry round on whatever didn't classify the first time, in smaller
    # sub-batches (4 items) -- a batch that failed once (likely a truncated/
    # malformed JSON response, not a content problem) has a real chance of
    # succeeding at a much smaller size.
    if all_missing:
        retry_ids = sorted(all_missing)
        print(f"[llm] retry round: {len(retry_ids)} items missing after pass 1, "
              f"resending in sub-batches of 4 ...", file=sys.stderr)
        RETRY_SIZE = 4
        for i in range(0, len(retry_ids), RETRY_SIZE):
            sub_ids = retry_ids[i:i + RETRY_SIZE]
            items = [{"id": cid, "ticker": by_id[cid]["related"], "headline": by_id[cid].get("headline", ""),
                      "summary": by_id[cid].get("summary", "")} for cid in sub_ids]
            got = await classify_batch(items)
            results.update(got)
            still_missing = set(sub_ids) - set(got)
            if still_missing:
                print(f"  retry: ids still unclassified after retry: {sorted(still_missing)}", file=sys.stderr)
    return results


# ---------------------------------------------------------------------------
# Main pipeline.
# ---------------------------------------------------------------------------
def trading_day_et(unix_ts: int) -> str:
    return datetime.fromtimestamp(unix_ts, ET).date().isoformat()


def main() -> int:
    all_reps: list[dict] = []
    raw_counts = {}
    for ticker in TICKERS:
        rows = fetch_news_chunked(ticker)
        raw_counts[ticker] = len(rows)
        for r in rows:
            r["related"] = ticker
        reps = cluster_duplicates(rows)
        for r in reps:
            r["regex_chaff"] = is_regex_chaff(r.get("headline", ""))
        all_reps.extend(reps)

    print(f"raw rows pulled: { {t: raw_counts[t] for t in TICKERS} }, "
          f"total={sum(raw_counts.values())}", file=sys.stderr)
    print(f"after dup clustering: {len(all_reps)} cluster-representative rows", file=sys.stderr)

    non_chaff = [r for r in all_reps if not r["regex_chaff"]]
    chaff_dropped = len(all_reps) - len(non_chaff)
    print(f"regex chaff filter dropped {chaff_dropped} of {len(all_reps)} "
          f"({chaff_dropped/len(all_reps)*100:.1f}%)", file=sys.stderr)

    # Deterministic per-ticker cap (see MAX_LLM_CANDIDATES_PER_TICKER comment).
    sent_to_llm: list[dict] = []
    capped_out: list[dict] = []
    for ticker in TICKERS:
        t_rows = sorted([r for r in non_chaff if r["related"] == ticker], key=lambda r: r["datetime"])
        if len(t_rows) <= MAX_LLM_CANDIDATES_PER_TICKER:
            sent_to_llm.extend(t_rows)
            continue
        stride = len(t_rows) / MAX_LLM_CANDIDATES_PER_TICKER
        keep_idx = {int(i * stride) for i in range(MAX_LLM_CANDIDATES_PER_TICKER)}
        for i, r in enumerate(t_rows):
            (sent_to_llm if i in keep_idx else capped_out).append(r)
        print(f"[cap] {ticker}: {len(t_rows)} chaff-filtered candidates -> "
              f"{sum(1 for i in range(len(t_rows)) if i in keep_idx)} sent to LLM "
              f"(evenly-spaced sample), {len(t_rows) - len(keep_idx)} not classified this run",
              file=sys.stderr)
    non_chaff = sent_to_llm

    for i, r in enumerate(non_chaff):
        r["_id"] = i

    classifications = asyncio.run(classify_all(non_chaff))
    capped_ids = {id(r) for r in capped_out}

    # Build the full raw manifest (every cluster-representative row, retained or not).
    manifest_rows = []
    for r in all_reps:
        row = {
            "ticker": r["related"],
            "headline": r.get("headline", ""),
            "summary": (r.get("summary", "") or "")[:400],
            "source": r.get("source", ""),
            "url": r.get("url", ""),
            "finnhub_datetime_utc": r.get("datetime"),
            "dup_cluster_id": r.get("dup_cluster_id"),
            "dup_cluster_size": r.get("dup_cluster_size"),
            "dup_cluster_sources": ";".join(r.get("dup_cluster_sources", [])),
            "regex_chaff": r["regex_chaff"],
        }
        cls = classifications.get(r.get("_id", -1))
        if cls:
            row.update(cls)
        elif r["regex_chaff"]:
            row.update({"is_distinct_event": False, "event_type": "none",
                        "materiality": "none", "novelty": False,
                        "direction_implied": "unknown",
                        "evidence_quote": "(regex chaff filter -- not sent to LLM)"})
        elif id(r) in capped_ids:
            row.update({"is_distinct_event": None, "event_type": None,
                        "materiality": None, "novelty": None,
                        "direction_implied": None,
                        "evidence_quote": "(dropped by MAX_LLM_CANDIDATES_PER_TICKER cap -- not classified this run)"})
        else:
            row.update({"is_distinct_event": None, "event_type": None,
                        "materiality": None, "novelty": None,
                        "direction_implied": None,
                        "evidence_quote": "(LLM classification failed/missing)"})
        manifest_rows.append(row)

    # Frozen retention rule.
    retained_candidates = []
    for r, mrow in zip(all_reps, manifest_rows):
        keep = (
            mrow.get("is_distinct_event") is True
            and mrow.get("materiality") in ("high", "medium")
            and mrow.get("novelty") is True
            and mrow.get("direction_implied") in ("bullish", "bearish")
        )
        mrow["passes_frozen_retention_rule"] = keep
        if keep:
            retained_candidates.append((r, mrow))

    print(f"passed frozen retention rule: {len(retained_candidates)} / {len(all_reps)} "
          f"({len(retained_candidates)/len(all_reps)*100:.1f}%)", file=sys.stderr)

    # Collapse to one event per (ticker, ET trading day) -- highest materiality
    # wins, tie broken by earliest timestamp.
    mat_rank = {"high": 2, "medium": 1, "low": 0, "none": -1, None: -1}
    by_key: dict[tuple[str, str], tuple[dict, dict]] = {}
    for r, mrow in retained_candidates:
        day = trading_day_et(r["datetime"])
        key = (r["related"], day)
        cur = by_key.get(key)
        if cur is None:
            by_key[key] = (r, mrow)
            continue
        cur_r, cur_mrow = cur
        if (mat_rank[mrow["materiality"]], -r["datetime"]) > (mat_rank[cur_mrow["materiality"]], -cur_r["datetime"]):
            by_key[key] = (r, mrow)

    events = []
    eid = 0
    for (ticker, day), (r, mrow) in sorted(by_key.items()):
        eid += 1
        first_public_utc = datetime.fromtimestamp(r["datetime"], UTC)
        first_public_et = first_public_utc.astimezone(ET)
        first_public_pt = first_public_utc.astimezone(PT)
        entry_et = first_public_et + timedelta(minutes=20)  # 15min detect+deliver + 5min owner reaction, frozen per hypotheses-v1.md
        entry_pt = entry_et.astimezone(PT)
        owner_actionable = (
            entry_pt.hour == 6 and 15 <= entry_pt.minute <= 45
        )
        period = "dev" if day < DEV_EVAL_SPLIT else "eval"
        events.append({
            "event_id": f"laneB_{eid:04d}",
            "ticker": ticker,
            "event_family": "lane_b_company_news",
            "event_subtype": mrow["event_type"],
            "trading_day_et": day,
            "period": period,
            "first_public_ts_utc": first_public_utc.isoformat(),
            "first_public_ts_et": first_public_et.isoformat(),
            "first_public_ts_pt": first_public_pt.isoformat(),
            "first_public_source": "Finnhub /company-news `datetime` field "
                                    "(Finnhub's own ingestion/redistribution timestamp, "
                                    "not independently verified against original publisher)",
            "detected_ts_et": first_public_et.isoformat(),  # no separate detection log exists; see hypotheses-v1.md delay note
            "entry_ts_et": entry_et.isoformat(),
            "entry_ts_pt": entry_pt.isoformat(),
            "owner_actionable_window": owner_actionable,
            "direction_implied": mrow["direction_implied"],
            "materiality": mrow["materiality"],
            "novelty": mrow["novelty"],
            "evidence_quote": mrow["evidence_quote"],
            "headline": r.get("headline", ""),
            "source": r.get("source", ""),
            "url": r.get("url", ""),
            "dup_cluster_id": r.get("dup_cluster_id"),
            "dup_cluster_size": r.get("dup_cluster_size"),
            "dup_cluster_sources": ";".join(r.get("dup_cluster_sources", [])),
            "sector_etf": SECTOR_ETF[ticker],
            "missing_data_exclusion_reason": "",
        })

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # events_lane_b.csv
    import csv
    events_path = OUT_DIR / "events_lane_b.csv"
    if events:
        with open(events_path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(events[0].keys()))
            w.writeheader()
            w.writerows(events)
    print(f"wrote {len(events)} retained one-per-ticker-day events to {events_path}", file=sys.stderr)

    # raw manifest
    manifest_path = OUT_DIR / "events_lane_b_raw_manifest.csv"
    with open(manifest_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(manifest_rows[0].keys()))
        w.writeheader()
        w.writerows(manifest_rows)
    print(f"wrote {len(manifest_rows)} raw cluster-representative rows to {manifest_path}", file=sys.stderr)

    dev_events = [e for e in events if e["period"] == "dev"]
    eval_events = [e for e in events if e["period"] == "eval"]
    summary = {
        "generated_at_pacific": datetime.now(PT).isoformat(),
        "window": [WINDOW_START, WINDOW_END],
        "dev_eval_split_et_date": DEV_EVAL_SPLIT,
        "raw_rows_pulled_per_ticker": raw_counts,
        "raw_rows_total": sum(raw_counts.values()),
        "cluster_representative_rows": len(all_reps),
        "regex_chaff_dropped": chaff_dropped,
        "sent_to_llm": len(non_chaff),
        "dropped_by_per_ticker_cap": len(capped_out),
        "llm_classified": len(classifications),
        "passed_frozen_retention_rule": len(retained_candidates),
        "final_events_one_per_ticker_day": len(events),
        "dev_events": len(dev_events),
        "eval_events": len(eval_events),
        "dev_events_by_ticker": {t: sum(1 for e in dev_events if e["ticker"] == t) for t in TICKERS},
        "eval_events_by_ticker": {t: sum(1 for e in eval_events if e["ticker"] == t) for t in TICKERS},
        "owner_actionable_dev": sum(1 for e in dev_events if e["owner_actionable_window"]),
        "owner_actionable_eval": sum(1 for e in eval_events if e["owner_actionable_window"]),
        "direction_split_eval": {
            "bullish": sum(1 for e in eval_events if e["direction_implied"] == "bullish"),
            "bearish": sum(1 for e in eval_events if e["direction_implied"] == "bearish"),
        },
    }
    (OUT_DIR / "lane_b_build_summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
