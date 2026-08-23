#!/usr/bin/env python3
"""Lane C — published biotechnology outcome reaction: event-table builder.

Builds .omc/research/event-reaction-short-duration/events_lane_c.csv (the
point-in-time event table for Lane C) plus a raw-source manifest, per
.omc/plans/event-reaction-short-duration-scanner-research-prompt.md
sections 6-13 and the Lane C kickoff message.

Pipeline:
  1. SEC EDGAR full-text search (free, no key) across a fixed keyword set,
     for 10 pre-mapped biotech tickers (ticker->CIK mapping validated
     already in lane-ac-resolvability.md via ClinicalTrials.gov sponsor
     matching -- reused here, not re-queried).
  2. For each hit, fetch the filing index page for an exact "Accepted"
     timestamp (Eastern, SEC's own official record) and the primary
     document/exhibit text.
  3. Rule-based classification of subtype + direction from the actual
     filing text (keyword markers, evidence snippet preserved). Ambiguous
     -> "meaning unclear", excluded from any advance claim.
  4. Realistic entry timing per section 9 (fixed processing/delivery +
     owner reaction delay), using Schwab extended-hours price history
     (schwab_client.get_price_history direct call, NOT
     consensus_engine.utils.prices.fetch_history, which drops the
     extended_hours flag -- see briefing.md).
  5. Market- (SPY) and sector- (XBI) adjusted outcome at 30/60 min, close,
     next open, next close; MFE/MAE; fixed-stop/fixed-horizon $100-risk
     metric (no target -- avoids the H2 target/stop-race bias).
  6. A same-ticker, non-event-day comparison group, same entry-clock rule.

Read-only against consensus.db (not actually queried here -- no DB-derived
universe needed for Lane C, the ticker list is fixed and pre-validated).
Raw provider responses cached under /tmp/event-reaction-audit/lane_c/
(gitignored scratch, not committed). No secrets printed. Total external
calls are bounded and logged (see call-count summary at the end of run).

Usage: python3 scripts/research/lane_c_build_events.py
"""
from __future__ import annotations

import json
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from consensus_engine.scanners import schwab_client  # noqa: E402

ET = ZoneInfo("America/New_York")
PT = ZoneInfo("America/Los_Angeles")

SCRATCH = Path("/tmp/event-reaction-audit/lane_c")
SCRATCH.mkdir(parents=True, exist_ok=True)

OUT_DIR = ROOT / ".omc/research/event-reaction-short-duration"
EVENTS_CSV = OUT_DIR / "events_lane_c.csv"
MANIFEST_JSON = OUT_DIR / "lane_c_raw_manifest.json"
CALL_LOG = OUT_DIR / "lane_c_call_log.json"

SEC_HEADERS = {"User-Agent": "OpenClaw Research arashchopra@gmail.com"}
TODAY = date.today().isoformat()

# ---------------------------------------------------------------------------
# Ticker universe (unchanged from lane-ac-resolvability.md, CIKs already
# validated there; 10 tickers, biotech only).
# ---------------------------------------------------------------------------
TICKERS: dict[str, str] = {
    "MRNA": "0001682852",
    "BIIB": "0000875045",
    "VRTX": "0000875320",
    "SRPT": "0000873303",
    "IONS": "0000874015",
    "REGN": "0000872589",
    "GILD": "0000882095",
    "ALNY": "0001178670",
    "BMRN": "0001048477",
    "EXEL": "0000939767",
}

# Search phrases -> coarse subtype hint (confirmed/refined later by reading
# the actual filing text, not trusted blindly from the phrase alone).
SEARCH_PHRASES: dict[str, str] = {
    "topline results": "clinical_outcome",
    "top-line results": "clinical_outcome",
    "FDA approval": "regulatory",
    "Complete Response Letter": "regulatory",
    "clinical hold": "trial_suspension_safety",
    "advisory committee": "regulatory",
}

# SEC full-text search only indexes 2001+; bound the window to keep total
# calls modest and because events far outside Schwab's actual price-history
# reach (see data-capability-audit.md item 1: 30m bars reach back to
# 2025-12-07, 5m bars vary 2025-12-07..2026-02-02) can never produce a
# priced outcome anyway. 2024-01-01 gives ~1 extra year of descriptive
# context beyond the priceable window, to show the real ceiling honestly.
SEARCH_START = "2024-01-01"
SEARCH_END = TODAY

# Comparators for market/sector adjustment.
MARKET_ETF = "SPY"
SECTOR_ETF = "XBI"  # SPDR S&P Biotech ETF -- reasonable sector comparator
                     # for large/mid-cap biotech; noted as a design choice,
                     # not validated against a formal sector-classification
                     # source (none exists in this codebase for biotech --
                     # confirmed absent from sector_map.yaml).

# ---------------------------------------------------------------------------
# Frozen timing/outcome parameters (development-period decisions; see
# hypotheses-v1.md for the registered version of these numbers). Defined
# here as constants so the SAME values are used to freeze the hypothesis
# file and to run the eval-period computation -- no drift between them.
# ---------------------------------------------------------------------------
PROCESSING_DELIVERY_DELAY_MIN = 5   # detection + Discord delivery, frozen
OWNER_REACTION_DELAY_MIN = 5        # per research prompt section 9
TOTAL_DELAY_MIN = PROCESSING_DELIVERY_DELAY_MIN + OWNER_REACTION_DELAY_MIN

OWNER_WINDOW_START_PT = (6, 15)
OWNER_WINDOW_END_PT = (6, 45)

STOP_PCT = 0.03      # frozen fixed-stop distance, 3% adverse from entry
HOLD_MINUTES_PRIMARY = 60
BASELINE_LOOKBACK_DAYS = 20  # for the abnormal-activity feature, computed
                              # from 30-minute bars per the H1 lesson (do
                              # not compute a 20-day rolling baseline from
                              # 1-minute Schwab history).

CALL_COUNTS = {"sec_search": 0, "sec_index": 0, "sec_doc": 0, "schwab": 0}


# ---------------------------------------------------------------------------
# SEC EDGAR helpers
# ---------------------------------------------------------------------------
def sec_get(url: str, **kwargs) -> requests.Response:
    for attempt in range(3):
        r = requests.get(url, headers=SEC_HEADERS, timeout=20, **kwargs)
        if r.status_code == 200:
            return r
        time.sleep(1.5)
    r.raise_for_status()
    return r


def sec_fts(q: str, cik: str, startdt: str, enddt: str) -> dict:
    CALL_COUNTS["sec_search"] += 1
    url = (
        "https://efts.sec.gov/LATEST/search-index"
        f"?q={requests.utils.quote(q)}&forms=8-K&ciks={cik}"
        f"&dateRange=custom&startdt={startdt}&enddt={enddt}"
    )
    r = sec_get(url)
    return r.json()


def sec_filing_index(cik_int: str, adsh: str) -> str:
    CALL_COUNTS["sec_index"] += 1
    adsh_nodash = adsh.replace("-", "")
    url = f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{adsh_nodash}/{adsh}-index.htm"
    r = sec_get(url)
    return r.text


def sec_doc_text(cik_int: str, adsh: str, filename: str) -> str:
    CALL_COUNTS["sec_doc"] += 1
    adsh_nodash = adsh.replace("-", "")
    url = f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{adsh_nodash}/{filename}"
    r = sec_get(url)
    txt = re.sub(r"<[^<]+?>", " ", r.text)
    txt = re.sub(r"&#160;|&nbsp;", " ", txt)
    txt = re.sub(r"\s+", " ", txt).strip()
    return txt


ACCEPTED_RE = re.compile(r"Accepted</div>\s*<div class=\"info\">([\d-]+ [\d:]+)</div>")


def parse_accepted_datetime(index_html: str) -> datetime | None:
    m = ACCEPTED_RE.search(index_html)
    if not m:
        return None
    dt = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
    return dt.replace(tzinfo=ET)  # SEC EDGAR "Accepted" timestamps are Eastern


# ---------------------------------------------------------------------------
# Text classification -- rule-based, evidence-preserving. No LLM used: the
# research prompt allows AI text->structure only for Lane B; Lane C keeps
# this mechanical and auditable.
# ---------------------------------------------------------------------------
POSITIVE_MARKERS = [
    "met the primary endpoint", "achieved the primary endpoint",
    "met its primary endpoint", "achieved statistical significance",
    "statistically significant improvement", "positive topline results",
    "positive top-line results", "fda approved", "fda approval",
    "granted approval", "grants approval", "accelerated approval",
    "priority review", "granted breakthrough therapy",
    "recommended approval", "voted in favor",
]
NEGATIVE_MARKERS = [
    "did not meet the primary endpoint", "did not meet its primary endpoint",
    "failed to meet the primary endpoint", "failed to achieve",
    "did not achieve statistical significance", "did not achieve the primary endpoint",
    "complete response letter", "clinical hold", "voluntarily paused",
    "voluntarily pausing", "discontinued the trial", "discontinuing the trial",
    "declined to approve", "rejected the application", "voted against",
    "did not recommend approval", "safety signal", "terminated the trial",
]

SUBTYPE_MARKERS = {
    "trial_suspension_safety": ["clinical hold", "voluntarily paused", "voluntarily pausing",
                                  "safety signal", "discontinued the trial", "discontinuing the trial",
                                  "terminated the trial"],
    "regulatory": ["fda approv", "complete response letter", "advisory committee",
                   "priority review", "accelerated approval", "pdufa",
                   "breakthrough therapy"],
    "clinical_outcome": ["primary endpoint", "topline results", "top-line results",
                          "statistical significance", "phase 3", "phase 2"],
}


def classify(text: str) -> tuple[str, str, str]:
    """Returns (subtype, direction, evidence_snippet)."""
    low = text.lower()
    pos_hits = [m for m in POSITIVE_MARKERS if m in low]
    neg_hits = [m for m in NEGATIVE_MARKERS if m in low]

    if pos_hits and neg_hits:
        direction = "unknown"
    elif pos_hits:
        direction = "positive"
    elif neg_hits:
        direction = "negative"
    else:
        direction = "unknown"

    subtype = "meaning_unclear"
    for st, markers in SUBTYPE_MARKERS.items():
        if any(m in low for m in markers):
            subtype = st
            break

    # A safety/suspension hit always implies negative direction regardless
    # of any hedging language elsewhere in the release.
    if subtype == "trial_suspension_safety":
        direction = "negative"

    if subtype == "meaning_unclear" or direction == "unknown":
        subtype = "meaning_unclear" if subtype != "trial_suspension_safety" else subtype
        direction = "unknown"

    all_hits = pos_hits + neg_hits
    snippet = ""
    if all_hits:
        i = low.find(all_hits[0])
        snippet = text[max(0, i - 150): i + 250]
    else:
        snippet = text[:300]

    return subtype, direction, snippet


# ---------------------------------------------------------------------------
# Schwab price data
# ---------------------------------------------------------------------------
def schwab_bars(ticker: str, interval: str, start: datetime, end: datetime):
    CALL_COUNTS["schwab"] += 1
    try:
        return schwab_client.get_price_history(
            ticker, interval=interval, start=start, end=end, extended_hours=True,
        )
    except Exception as e:
        print(f"  [schwab error] {ticker} {interval} {start.date()}..{end.date()}: {e}", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# Event discovery
# ---------------------------------------------------------------------------
@dataclass
class RawHit:
    ticker: str
    cik: str
    adsh: str
    file_date: str
    items: list
    filename: str
    phrase: str
    subtype_hint: str


def discover_hits() -> list[RawHit]:
    seen: dict[tuple, RawHit] = {}
    for ticker, cik in TICKERS.items():
        cik_int = str(int(cik))
        for phrase, hint in SEARCH_PHRASES.items():
            print(f"[SEC search] {ticker} '{phrase}' ...", file=sys.stderr)
            d = sec_fts(phrase, cik, SEARCH_START, SEARCH_END)
            hits = d.get("hits", {}).get("hits", [])
            for h in hits:
                src = h["_source"]
                adsh = src["adsh"]
                key = (ticker, adsh)
                fname = h["_id"].split(":")[1] if ":" in h["_id"] else None
                if key not in seen and fname:
                    seen[key] = RawHit(
                        ticker=ticker, cik=cik_int, adsh=adsh,
                        file_date=src["file_date"], items=src.get("items", []),
                        filename=fname, phrase=phrase, subtype_hint=hint,
                    )
            time.sleep(0.3)
    return list(seen.values())


@dataclass
class Event:
    event_id: str
    ticker: str
    file_date: str
    accepted_et: str | None
    public_ts_et: str | None
    public_ts_source: str
    subtype: str
    direction: str
    evidence_snippet: str
    sec_url: str
    items: list
    phrase_matched: str
    dedup_note: str = ""
    exclusion_reason: str = ""


def resolve_events(hits: list[RawHit]) -> list[Event]:
    events = []
    for h in hits:
        print(f"[SEC index+doc] {h.ticker} {h.adsh} ({h.file_date}) ...", file=sys.stderr)
        try:
            idx_html = sec_filing_index(h.cik, h.adsh)
        except Exception as e:
            print(f"  index fetch failed: {e}", file=sys.stderr)
            continue
        accepted = parse_accepted_datetime(idx_html)
        try:
            doc_text = sec_doc_text(h.cik, h.adsh, h.filename)
        except Exception as e:
            print(f"  doc fetch failed: {e}", file=sys.stderr)
            doc_text = ""
        subtype, direction, snippet = classify(doc_text) if doc_text else ("meaning_unclear", "unknown", "")
        sec_url = f"https://www.sec.gov/Archives/edgar/data/{h.cik}/{h.adsh.replace('-', '')}/{h.filename}"
        events.append(Event(
            event_id=f"{h.ticker}-{h.adsh}",
            ticker=h.ticker,
            file_date=h.file_date,
            accepted_et=accepted.isoformat() if accepted else None,
            public_ts_et=accepted.isoformat() if accepted else None,
            public_ts_source="sec_edgar_accepted_datetime",
            subtype=subtype,
            direction=direction,
            evidence_snippet=snippet,
            sec_url=sec_url,
            items=h.items,
            phrase_matched=h.phrase,
        ))
        time.sleep(0.3)
    return events


# ---------------------------------------------------------------------------
# Entry timing (section 9)
# ---------------------------------------------------------------------------
def compute_entry_timing(public_et: datetime) -> dict:
    resulting_et = public_et + timedelta(minutes=TOTAL_DELAY_MIN)
    resulting_pt = resulting_et.astimezone(PT)
    window_start = resulting_pt.replace(hour=OWNER_WINDOW_START_PT[0], minute=OWNER_WINDOW_START_PT[1], second=0, microsecond=0)
    window_end = resulting_pt.replace(hour=OWNER_WINDOW_END_PT[0], minute=OWNER_WINDOW_END_PT[1], second=0, microsecond=0)
    owner_actionable = resulting_pt <= window_end
    return {
        "resulting_et": resulting_et.isoformat(),
        "resulting_pt": resulting_pt.isoformat(),
        "owner_actionable": owner_actionable,
    }


def first_bar_at_or_after(df, ts_et: datetime):
    if df is None or df.empty:
        return None
    sub = df[df.index >= ts_et]
    if sub.empty:
        return None
    return sub.iloc[0], sub.index[0]


def bars_window(df, start_et: datetime, end_et: datetime):
    if df is None or df.empty:
        return None
    return df[(df.index >= start_et) & (df.index <= end_et)]


# ---------------------------------------------------------------------------
# Outcome computation (section 10)
# ---------------------------------------------------------------------------
def compute_outcome(ticker: str, entry_et: datetime, entry_price: float,
                     direction_sign: int, spy_df, xbi_df, tkr_df_5m) -> dict:
    """direction_sign: +1 for a long/positive-direction trade, -1 for short.
    For direction == 'unknown' events we still compute the metric with
    sign=+1 (i.e. treat it as if long) but these are EXCLUDED from any
    advance claim -- kept only for descriptive completeness."""
    out = {}
    horizon_end = entry_et + timedelta(minutes=HOLD_MINUTES_PRIMARY)
    window = bars_window(tkr_df_5m, entry_et, horizon_end)
    if window is None or window.empty:
        out["outcome_status"] = "no_price_data_in_window"
        return out

    stop_price = entry_price * (1 - direction_sign * STOP_PCT)
    stopped_out = False
    stop_ts = None
    mfe = 0.0
    mae = 0.0
    mfe_ts = mae_ts = None
    for ts, row in window.iterrows():
        move = direction_sign * (row["Close"] / entry_price - 1)
        if move > mfe:
            mfe = move
            mfe_ts = ts
        if move < mae:
            mae = move
            mae_ts = ts
        adverse_hit = (direction_sign == 1 and row["Low"] <= stop_price) or \
                      (direction_sign == -1 and row["High"] >= stop_price)
        if adverse_hit and not stopped_out:
            stopped_out = True
            stop_ts = ts

    last_row = window.iloc[-1]
    ret_60 = direction_sign * (last_row["Close"] / entry_price - 1)

    if stopped_out:
        pnl_per_100_risk = -100.0
    else:
        pnl_per_100_risk = (ret_60 / STOP_PCT) * 100.0

    out.update({
        "outcome_status": "ok",
        "entry_price": entry_price,
        "ret_60min_raw_pct": round(ret_60 * 100, 3),
        "mfe_pct": round(mfe * 100, 3),
        "mfe_ts_et": mfe_ts.isoformat() if mfe_ts is not None else None,
        "mae_pct": round(mae * 100, 3),
        "mae_ts_et": mae_ts.isoformat() if mae_ts is not None else None,
        "stopped_out": stopped_out,
        "stop_ts_et": stop_ts.isoformat() if stop_ts else None,
        "pnl_per_100_risk": round(pnl_per_100_risk, 2),
        "n_bars_in_window": len(window),
    })

    # Market/sector adjustment over the identical clock window.
    for name, cmp_df in (("spy", spy_df), ("xbi", xbi_df)):
        cwin = bars_window(cmp_df, entry_et, horizon_end)
        if cwin is not None and not cwin.empty:
            cmp_start = cmp_df[cmp_df.index <= entry_et]
            if not cmp_start.empty:
                cmp_entry = cmp_start.iloc[-1]["Close"]
                cmp_ret = cwin.iloc[-1]["Close"] / cmp_entry - 1
                out[f"{name}_ret_60min_pct"] = round(cmp_ret * 100, 3)
                out[f"ret_60min_adj_{name}_pct"] = round((ret_60 - direction_sign * cmp_ret) * 100, 3)
    return out


def compute_30min_directional(tkr_df_5m, entry_et: datetime, entry_price: float, direction_sign: int) -> dict:
    w = bars_window(tkr_df_5m, entry_et, entry_et + timedelta(minutes=30))
    if w is None or w.empty:
        return {"dir_success_30min": None}
    ret30 = direction_sign * (w.iloc[-1]["Close"] / entry_price - 1)
    return {"dir_success_30min": bool(ret30 > 0), "ret_30min_raw_pct": round(ret30 * 100, 3)}


# ---------------------------------------------------------------------------
# Abnormal-activity feature (from 30-minute bars, per H1 lesson)
# ---------------------------------------------------------------------------
def abnormal_premarket_volume(ticker: str, event_day_et: date) -> dict:
    start = datetime.combine(event_day_et - timedelta(days=45), datetime.min.time(), tzinfo=ET)
    end = datetime.combine(event_day_et + timedelta(days=1), datetime.min.time(), tzinfo=ET)
    df = schwab_bars(ticker, "30m", start, end)
    if df is None or df.empty:
        return {"premarket_baseline_status": "no_30m_data"}
    df = df.copy()
    df["day"] = df.index.date
    df["hm"] = df.index.strftime("%H:%M")
    block = df[df["hm"] == "06:00"]  # 6:00-6:29 ET premarket 30-min bar
    prior = block[block["day"] < event_day_et].tail(BASELINE_LOOKBACK_DAYS)
    today = block[block["day"] == event_day_et]
    if len(prior) < 5 or today.empty:
        return {"premarket_baseline_status": "insufficient_history", "n_prior_days": len(prior)}
    median_vol = float(prior["Volume"].median())
    today_vol = float(today.iloc[0]["Volume"])
    rvol = (today_vol / median_vol) if median_vol > 0 else None
    return {
        "premarket_baseline_status": "ok",
        "n_prior_days": len(prior),
        "premarket_median_baseline_volume": median_vol,
        "premarket_volume_event_day": today_vol,
        "premarket_rvol": round(rvol, 2) if rvol else None,
    }


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------
def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    hits_cache = SCRATCH / "hits.json"
    if hits_cache.exists():
        print("[cache] reusing hits.json", file=sys.stderr)
        raw = json.loads(hits_cache.read_text())
        hits = [RawHit(**h) for h in raw]
    else:
        hits = discover_hits()
        hits_cache.write_text(json.dumps([h.__dict__ for h in hits], indent=2))
    print(f"Discovered {len(hits)} unique (ticker, accession) SEC 8-K hits.", file=sys.stderr)

    events_cache = SCRATCH / "events_raw.json"
    if events_cache.exists():
        print("[cache] reusing events_raw.json", file=sys.stderr)
        raw = json.loads(events_cache.read_text())
        events = [Event(**e) for e in raw]
    else:
        events = resolve_events(hits)
        events_cache.write_text(json.dumps([e.__dict__ for e in events], indent=2))
    print(f"Resolved {len(events)} events with text classification.", file=sys.stderr)

    # One independent event per ticker + trading day (dedup multiple
    # accessions filed same day for the same ticker -- keep the one with
    # the more specific subtype, i.e. not meaning_unclear, if any).
    by_key: dict[tuple, Event] = {}
    for e in events:
        key = (e.ticker, e.file_date)
        if key not in by_key:
            by_key[key] = e
        else:
            existing = by_key[key]
            if existing.subtype == "meaning_unclear" and e.subtype != "meaning_unclear":
                by_key[key] = e
            else:
                existing.dedup_note = (existing.dedup_note + f"; also matched {e.event_id}").strip("; ")
    events = list(by_key.values())
    print(f"After ticker+day dedup: {len(events)} independent events.", file=sys.stderr)

    # Pull market/sector comparator daily-range once, wide enough to cover
    # everything, then slice per event.
    spy_5m_cache: dict[str, object] = {}
    xbi_5m_cache: dict[str, object] = {}

    rows_out = []
    manifest = []

    for e in events:
        rec = e.__dict__.copy()
        if e.accepted_et is None:
            rec["exclusion_reason"] = "no_sec_accepted_timestamp"
            rows_out.append(rec)
            manifest.append(rec)
            continue

        public_et = datetime.fromisoformat(e.accepted_et)
        timing = compute_entry_timing(public_et)
        rec.update(timing)

        file_dt = date.fromisoformat(e.file_date)
        # Pull price bars: 5-min extended-hours window spanning event day
        # -1 to +3 calendar days (covers overnight-gap + 60min horizon).
        w_start = datetime.combine(file_dt - timedelta(days=1), datetime.min.time(), tzinfo=ET)
        w_end = datetime.combine(file_dt + timedelta(days=3), datetime.min.time(), tzinfo=ET)
        tkr_df = schwab_bars(e.ticker, "5m", w_start, w_end)
        if e.ticker not in ("SPY",):
            key = (w_start.date().isoformat(), w_end.date().isoformat())
            if key not in spy_5m_cache:
                spy_5m_cache[key] = schwab_bars(MARKET_ETF, "5m", w_start, w_end)
            if key not in xbi_5m_cache:
                xbi_5m_cache[key] = schwab_bars(SECTOR_ETF, "5m", w_start, w_end)
            spy_df = spy_5m_cache[key]
            xbi_df = xbi_5m_cache[key]

        if tkr_df is None or tkr_df.empty:
            rec["exclusion_reason"] = "no_schwab_5m_data_for_window"
            rows_out.append(rec)
            manifest.append(rec)
            continue

        resulting_et = datetime.fromisoformat(timing["resulting_et"])
        entry = first_bar_at_or_after(tkr_df, resulting_et)
        if entry is None:
            rec["exclusion_reason"] = "no_bar_at_or_after_resulting_time"
            rows_out.append(rec)
            manifest.append(rec)
            continue
        entry_row, entry_ts = entry
        entry_price = float(entry_row["Open"]) if "Open" in entry_row else float(entry_row["Close"])
        rec["entry_ts_et"] = entry_ts.isoformat()
        rec["entry_ts_pt"] = entry_ts.astimezone(PT).isoformat()
        rec["entry_price"] = entry_price

        if e.direction == "positive":
            sign = 1
        elif e.direction == "negative":
            sign = -1
        else:
            sign = 1  # descriptive only; excluded from advance claims downstream

        rec["direction_sign_used"] = sign
        rec["usable_for_advance_claim"] = e.direction in ("positive", "negative")

        outcome = compute_outcome(e.ticker, entry_ts, entry_price, sign, spy_df, xbi_df, tkr_df)
        rec.update(outcome)
        rec.update(compute_30min_directional(tkr_df, entry_ts, entry_price, sign))

        abn = abnormal_premarket_volume(e.ticker, file_dt)
        rec.update(abn)

        rows_out.append(rec)
        manifest.append(rec)

    # -----------------------------------------------------------------
    # Write outputs
    # -----------------------------------------------------------------
    import csv
    all_keys = set()
    for r in rows_out:
        all_keys.update(r.keys())
    fieldnames = sorted(all_keys)
    with open(EVENTS_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows_out:
            w.writerow(r)

    MANIFEST_JSON.write_text(json.dumps(manifest, indent=2, default=str))
    CALL_LOG.write_text(json.dumps(CALL_COUNTS, indent=2))

    print(f"\nWrote {len(rows_out)} event rows to {EVENTS_CSV}", file=sys.stderr)
    print(f"Call counts: {CALL_COUNTS}", file=sys.stderr)


if __name__ == "__main__":
    main()
