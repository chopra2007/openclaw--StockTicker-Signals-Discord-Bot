"""Bounded, restartable, cache-aware Yahoo 1-minute option history downloader
(TODO #100, Phase 2).

What it does
------------
* Pulls 1-minute OHLCV bars for named option contracts from
  ``https://query1.finance.yahoo.com/v8/finance/chart/{contract}``.
* Yahoo caps 1-minute granularity at 8 days per request, so the range probe is
  ``1mo`` -> ``7d`` -> ``5d``: the first that returns HTTP 200 with bars wins.
* A normal desktop browser User-Agent, a seeded cookie jar, timeouts, bounded
  retries with exponential backoff, and bounded concurrency (2 in flight).
* No secret is used or stored anywhere. Yahoo needs no key for this endpoint.

Raw storage (OUTSIDE git)
-------------------------
``/home/openclaw/.openclaw/data/put_flow_option_history/yahoo/<CONTRACT>__<range>__<UTCSTAMP>.json``

Idempotence
-----------
Before writing, the new response body is sha256'd and compared against every
existing ``<CONTRACT>__<range>__*.json``. An identical hash is NOT rewritten.
A differing body is saved as a NEW dated revision; nothing is ever overwritten.

Derived artefacts convert timestamps to America/Los_Angeles; raw files keep
Yahoo's own epoch seconds untouched.

    python3 scripts/research/put_flow_option_history_fetch.py --contracts-file <file>
    python3 scripts/research/put_flow_option_history_fetch.py --contract MARA260911P00011500
"""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import hashlib
import json
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

PACIFIC = ZoneInfo("America/Los_Angeles")

DATA_DIR = Path("/home/openclaw/.openclaw/data/put_flow_option_history/yahoo")

CHART_HOSTS = (
    "https://query1.finance.yahoo.com/v8/finance/chart/",
    "https://query2.finance.yahoo.com/v8/finance/chart/",
)
RANGE_PROBE = ("1mo", "7d", "5d")
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)
TIMEOUT = (10, 30)          # (connect, read) seconds
MAX_RETRIES = 4
MAX_IN_FLIGHT = 2


# ---------------------------------------------------------------------------
# time helpers
# ---------------------------------------------------------------------------

def to_pacific_iso(epoch: float) -> str:
    """Yahoo epoch seconds -> ISO-8601 string in America/Los_Angeles."""
    return datetime.fromtimestamp(float(epoch), tz=timezone.utc).astimezone(PACIFIC).isoformat()


def _utcstamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")


# ---------------------------------------------------------------------------
# HTTP session
# ---------------------------------------------------------------------------

def yahoo_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:                                   # seed consent cookies; 404 still sets them
        s.get("https://fc.yahoo.com/", timeout=TIMEOUT)
    except requests.RequestException:
        pass
    return s


def _get_with_retry(session: requests.Session, url: str, params: dict) -> requests.Response:
    last = None
    for attempt in range(MAX_RETRIES):
        try:
            resp = session.get(url, params=params, timeout=TIMEOUT)
        except requests.RequestException as e:
            last = e
            resp = None
        if resp is not None:
            if resp.status_code == 200:
                return resp
            # 422 / 400 mean "range unsupported / no data" -> don't retry, let caller fall back
            if resp.status_code in (400, 404, 422):
                return resp
            last = requests.HTTPError(f"HTTP {resp.status_code}", response=resp)
        sleep_s = (2 ** attempt) + random.uniform(0, 0.75)
        time.sleep(sleep_s)
    if isinstance(last, requests.Response):
        return last
    raise RuntimeError(f"exhausted retries for {url}: {last}")


# ---------------------------------------------------------------------------
# parsing
# ---------------------------------------------------------------------------

def summarize(raw: dict) -> dict:
    """Field inventory + row counts + Pacific span + gap count for one response."""
    chart = raw.get("chart") or {}
    err = chart.get("error")
    results = chart.get("result") or []
    if err or not results:
        return {
            "error": (err or {}).get("description") if err else "no result",
            "rows": 0,
            "positive_volume_rows": 0,
            "fields_present": [],
            "has_bid_ask": False,
            "gap_count": 0,
            "earliest_ts_pacific": None,
            "latest_ts_pacific": None,
            "meta_range": None,
        }
    res = results[0]
    ts = res.get("timestamp") or []
    quote = ((res.get("indicators") or {}).get("quote") or [{}])[0]
    fields = sorted(k for k, v in quote.items() if v is not None)
    has_bid_ask = ("bid" in quote) or ("ask" in quote)

    vols = quote.get("volume") or []
    pos_vol = sum(1 for v in vols if v)

    gap = 0
    for a, b in zip(ts, ts[1:]):
        d = b - a
        if 60 < d <= 3600:               # intraday hole (ignore the overnight jump)
            gap += 1

    return {
        "error": None,
        "rows": len(ts),
        "positive_volume_rows": pos_vol,
        "fields_present": fields,
        "has_bid_ask": has_bid_ask,
        "gap_count": gap,
        "earliest_ts_pacific": to_pacific_iso(ts[0]) if ts else None,
        "latest_ts_pacific": to_pacific_iso(ts[-1]) if ts else None,
        "meta_range": (res.get("meta") or {}).get("range"),
    }


# ---------------------------------------------------------------------------
# cache-aware writer
# ---------------------------------------------------------------------------

def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _store_raw(contract: str, range_: str, body_text: str, out_dir: Path) -> dict:
    """Write a new dated revision unless an identical body is already stored."""
    out_dir.mkdir(parents=True, exist_ok=True)
    digest = _sha256_text(body_text)
    existing = sorted(out_dir.glob(f"{contract}__{range_}__*.json"))
    for p in existing:
        try:
            if _sha256_text(p.read_text()) == digest:
                return {"path": str(p), "sha256": digest, "rewritten": False,
                        "revision_of": len(existing)}
        except OSError:
            continue
    path = out_dir / f"{contract}__{range_}__{_utcstamp()}.json"
    while path.exists():                       # never overwrite a prior revision
        time.sleep(0.001)
        path = out_dir / f"{contract}__{range_}__{_utcstamp()}.json"
    path.write_text(body_text)
    return {"path": str(path), "sha256": digest, "rewritten": True,
            "revision_of": len(existing)}


# ---------------------------------------------------------------------------
# one contract
# ---------------------------------------------------------------------------

def fetch_contract(
    session: requests.Session,
    contract: str,
    out_dir: Path = DATA_DIR,
    ranges: tuple[str, ...] = RANGE_PROBE,
    extra_probe_ranges: tuple[str, ...] = (),
) -> dict:
    """Download one contract, cache-aware. Returns a manifest-ready record."""
    contract = contract.strip().upper()
    attempts: list[dict] = []
    chosen = None

    for rng in ranges:
        resp = _get_with_retry(session, CHART_HOSTS[0] + contract, {"interval": "1m", "range": rng})
        rec = {"range": rng, "http_status": resp.status_code}
        body_text = resp.text
        try:
            raw = json.loads(body_text)
        except ValueError:
            raw = {}
        summ = summarize(raw)
        rec.update({"rows": summ["rows"], "error": summ["error"]})
        attempts.append(rec)
        if resp.status_code == 200 and summ["rows"] > 0:
            store = _store_raw(contract, rng, body_text, out_dir)
            chosen = {"range": rng, "http_status": 200, "raw": raw, "summary": summ, **store}
            break
        if resp.status_code == 200 and summ["error"] is None:
            # 200 but empty -> keep the evidence, keep probing shorter ranges
            store = _store_raw(contract, rng, body_text, out_dir)
            chosen = {"range": rng, "http_status": 200, "raw": raw, "summary": summ, **store}

    # optional deeper probe (step 6): does 1m reach past 30 days?
    probe = []
    for rng in extra_probe_ranges:
        resp = _get_with_retry(session, CHART_HOSTS[0] + contract, {"interval": "1m", "range": rng})
        try:
            raw = json.loads(resp.text)
        except ValueError:
            raw = {}
        s = summarize(raw)
        probe.append({"range": rng, "http_status": resp.status_code,
                      "rows": s["rows"], "error": s["error"]})

    if chosen is None:
        return {
            "contract": contract,
            "ok": False,
            "http_status": attempts[-1]["http_status"] if attempts else None,
            "attempts": attempts,
            "probe": probe,
        }

    s = chosen["summary"]
    return {
        "contract": contract,
        "ok": s["rows"] > 0,
        "requested_range": chosen["range"],
        "http_status": chosen["http_status"],
        "path": chosen["path"],
        "sha256": chosen["sha256"],
        "rewritten": chosen["rewritten"],
        "rows": s["rows"],
        "positive_volume_rows": s["positive_volume_rows"],
        "fields_present": s["fields_present"],
        "has_bid_ask": s["has_bid_ask"],
        "gap_count": s["gap_count"],
        "earliest_ts_pacific": s["earliest_ts_pacific"],
        "latest_ts_pacific": s["latest_ts_pacific"],
        "attempts": attempts,
        "probe": probe,
    }


# ---------------------------------------------------------------------------
# quality tier
# ---------------------------------------------------------------------------

def quality_tier(rec: dict) -> str:
    if not rec.get("ok"):
        return "MISSING"
    if rec.get("has_bid_ask"):
        return "EXACT_BID_ASK"
    if rec.get("positive_volume_rows", 0) == 0:
        return "NO_TRADES"                     # zero-volume bars cannot prove a fill
    if rec.get("gap_count", 0) > 30:
        return "TRADE_BAR_GAPPY"
    return "TRADE_BAR_ONLY"


# ---------------------------------------------------------------------------
# batch runner
# ---------------------------------------------------------------------------

def run_batch(
    jobs: list[dict],
    out_dir: Path = DATA_DIR,
    extra_probe_ranges: tuple[str, ...] = (),
) -> list[dict]:
    """jobs: [{contract, position_id, ticker, structure, leg}, ...]."""
    session = yahoo_session()
    results: list[dict] = []

    def _work(job: dict) -> dict:
        time.sleep(random.uniform(0, 0.4))
        rec = fetch_contract(session, job["contract"], out_dir=out_dir,
                             extra_probe_ranges=extra_probe_ranges)
        rec.update({k: job.get(k) for k in ("position_id", "ticker", "structure", "leg")})
        rec["quality_tier"] = quality_tier(rec)
        return rec

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_IN_FLIGHT) as ex:
        for rec in ex.map(_work, jobs):
            results.append(rec)
            tag = rec.get("quality_tier")
            print(f"  {rec['contract']:<24} {rec.get('http_status')} "
                  f"rows={rec.get('rows', 0):<5} {tag}", file=sys.stderr)
    return results


MANIFEST_COLUMNS = [
    "contract", "position_id", "ticker", "structure", "leg", "requested_range",
    "http_status", "earliest_ts_pacific", "latest_ts_pacific", "rows",
    "positive_volume_rows", "fields_present", "has_bid_ask", "gap_count",
    "sha256", "quality_tier",
]


def write_manifest(results: list[dict], csv_path: Path, summary_path: Path) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=MANIFEST_COLUMNS)
        w.writeheader()
        for r in results:
            w.writerow({
                "contract": r.get("contract"),
                "position_id": r.get("position_id"),
                "ticker": r.get("ticker"),
                "structure": r.get("structure"),
                "leg": r.get("leg"),
                "requested_range": r.get("requested_range"),
                "http_status": r.get("http_status"),
                "earliest_ts_pacific": r.get("earliest_ts_pacific"),
                "latest_ts_pacific": r.get("latest_ts_pacific"),
                "rows": r.get("rows", 0),
                "positive_volume_rows": r.get("positive_volume_rows", 0),
                "fields_present": "|".join(r.get("fields_present", []) or []),
                "has_bid_ask": r.get("has_bid_ask", False),
                "gap_count": r.get("gap_count", 0),
                "sha256": r.get("sha256"),
                "quality_tier": r.get("quality_tier"),
            })

    requested = len(results)
    received = sum(1 for r in results if r.get("ok"))
    summary = {
        "generated_at_pacific": datetime.now(PACIFIC).isoformat(),
        "raw_dir": str(DATA_DIR),
        "contracts_requested": requested,
        "contracts_received": received,
        "contracts_missing": requested - received,
        "any_bid_ask_field": any(r.get("has_bid_ask") for r in results),
        "total_rows": sum(r.get("rows", 0) for r in results),
        "total_positive_volume_rows": sum(r.get("positive_volume_rows", 0) for r in results),
        "by_quality_tier": _count_by(results, "quality_tier"),
        "yahoo_1m_range_probe": _probe_digest(results),
        "missing_contracts": [r["contract"] for r in results if not r.get("ok")],
    }
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")


def _count_by(results: list[dict], key: str) -> dict:
    out: dict[str, int] = {}
    for r in results:
        out[str(r.get(key))] = out.get(str(r.get(key)), 0) + 1
    return out


def _probe_digest(results: list[dict]) -> list[dict]:
    for r in results:
        if r.get("probe"):
            return r["probe"]
    return []


# ---------------------------------------------------------------------------
# cli
# ---------------------------------------------------------------------------

def _load_jobs(path: str) -> list[dict]:
    rows = json.loads(Path(path).read_text())
    if isinstance(rows, dict):
        rows = rows.get("jobs", [])
    return rows


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--contract", action="append", default=[], help="single OCC/Yahoo symbol; repeatable")
    p.add_argument("--contracts-file", default=None,
                   help='JSON list of {"contract","position_id","ticker","structure","leg"}')
    p.add_argument("--out-dir", default=str(DATA_DIR))
    p.add_argument("--manifest", default=".omc/research/put-flow-option-trade-system/download-manifest.csv")
    p.add_argument("--summary", default=".omc/research/put-flow-option-trade-system/download-summary.json")
    p.add_argument("--probe-3mo", action="store_true",
                   help="also request range=3mo/6mo on one contract to record the true 1m limit")
    a = p.parse_args(argv)

    jobs: list[dict] = []
    if a.contracts_file:
        jobs += _load_jobs(a.contracts_file)
    for c in a.contract:
        jobs.append({"contract": c, "position_id": None, "ticker": None,
                     "structure": None, "leg": None})
    if not jobs:
        p.error("no contracts given (use --contract or --contracts-file)")

    probe_ranges = ("3mo", "6mo") if a.probe_3mo else ()
    results = run_batch(jobs, out_dir=Path(a.out_dir), extra_probe_ranges=probe_ranges)
    write_manifest(results, Path(a.manifest), Path(a.summary))
    print(f"\nmanifest -> {a.manifest}\nsummary  -> {a.summary}")
    print(f"requested={len(results)} received={sum(1 for r in results if r.get('ok'))} "
          f"missing={sum(1 for r in results if not r.get('ok'))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
