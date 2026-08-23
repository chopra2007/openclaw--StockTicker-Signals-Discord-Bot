#!/usr/bin/env python3
"""Lane A / Lane C fix-check probe for the event-reaction short-duration research.

Bounded, read-only, free-only checks (no paid subscriptions, no secrets
printed) against:
  - yfinance (already used elsewhere in this project, see consensus_engine/
    scanners/earnings_calendar.py) for historical earnings report dates
  - SEC EDGAR full-text search (free, no key) for 8-K filings that pin a
    real public-disclosure timestamp to an earnings print or a biotech event
  - ClinicalTrials.gov v2 API (free, no key) for trial completion/results
    dates and sponsor-name-to-ticker mapping

Does not touch consensus.db, production config, or services. Writes raw
JSON to /tmp/event-reaction-audit/ (gitignored scratch) and prints a summary
to stdout. Total network calls: ~35 (bounded, well under "a few dozen").

Usage: python3 scripts/research/lane_ac_resolvability_probe.py
"""
from __future__ import annotations

import json
import sys
import time
from datetime import date
from pathlib import Path

import requests
import yfinance as yf

SCRATCH = Path("/tmp/event-reaction-audit")
SCRATCH.mkdir(exist_ok=True)

SEC_HEADERS = {"User-Agent": "OpenClaw Research arashchopra@gmail.com"}
TODAY = date.today().isoformat()

# ---------------------------------------------------------------------------
# Lane A tickers: mix of large/liquid and smaller, matching the audit's own
# ticker choices (SPY/AAPL/MU liquid, ROKU/IONQ medium/volatile) so results
# are directly comparable to data-capability-audit.md.
# ---------------------------------------------------------------------------
LANE_A_TICKERS = {
    "AAPL": "0000320193",
    "MSFT": "0000789019",
    "ROKU": "0001428439",
    "IONQ": "0001824920",
    "MRNA": "0001682852",
}

# Lane C: biotech tickers this project doesn't have a dedicated config list
# for (checked config/consensus.yaml, sector_map.yaml, no biotech universe
# found) — using the team lead's suggested seed set plus enough well-known
# public biotech names to reach ~10, matching Finnhub-audit's own MRNA/VRTX
# choices.
LANE_C_TICKERS = {
    "MRNA": ("0001682852", "ModernaTX"),
    "BIIB": ("0000875045", "Biogen"),
    "VRTX": ("0000875320", "Vertex Pharmaceuticals"),
    "SRPT": ("0000873303", "Sarepta Therapeutics"),
    "IONS": ("0000874015", "Ionis Pharmaceuticals"),
    "REGN": ("0000872589", "Regeneron Pharmaceuticals"),
    "GILD": ("0000882095", "Gilead Sciences"),
    "ALNY": ("0001178670", "Alnylam Pharmaceuticals"),
    "BMRN": ("0001048477", "BioMarin Pharmaceutical"),
    "EXEL": ("0000939767", "Exelixis"),
}


def sec_fts(q: str, forms: str, cik: str, startdt: str, enddt: str) -> dict:
    """One bounded SEC EDGAR full-text-search call. Free, no key."""
    url = (
        "https://efts.sec.gov/LATEST/search-index"
        f"?q={requests.utils.quote(q)}&forms={forms}&ciks={cik}"
        f"&dateRange=custom&startdt={startdt}&enddt={enddt}"
    )
    for attempt in range(3):
        r = requests.get(url, headers=SEC_HEADERS, timeout=15)
        if r.status_code == 200:
            return r.json()
        time.sleep(1.5)
    return {"hits": {"total": {"value": 0}, "hits": []}}


# ---------------------------------------------------------------------------
# Lane A item 1: yfinance historical earnings report dates.
# ---------------------------------------------------------------------------
def lane_a_yfinance() -> dict:
    out = {}
    for ticker in LANE_A_TICKERS:
        print(f"[lane A yfinance] {ticker} ...", file=sys.stderr)
        try:
            ed = yf.Ticker(ticker).earnings_dates
        except Exception as e:
            out[ticker] = {"error": f"{type(e).__name__}: {e}"}
            continue
        if ed is None or ed.empty:
            out[ticker] = {"error": "empty"}
            continue
        rows = []
        for ts, row in ed.iterrows():
            rows.append({
                "date": ts.date().isoformat(),
                "time": ts.strftime("%H:%M %z"),
                "eps_estimate": None if row["EPS Estimate"] != row["EPS Estimate"] else float(row["EPS Estimate"]),
                "reported_eps": None if row["Reported EPS"] != row["Reported EPS"] else float(row["Reported EPS"]),
                "surprise_pct": None if row["Surprise(%)"] != row["Surprise(%)"] else float(row["Surprise(%)"]),
            })
        out[ticker] = {
            "n_rows": len(rows),
            "oldest_date": rows[-1]["date"],
            "newest_date": rows[0]["date"],
            "rows": rows,
        }
    return out


# ---------------------------------------------------------------------------
# Lane A item 2: SEC 8-K Item 2.02 filings (earnings release moment) —
# cross-check against yfinance's realized-quarter dates.
# ---------------------------------------------------------------------------
def lane_a_sec_crosscheck(yf_data: dict) -> dict:
    out = {}
    for ticker, cik in LANE_A_TICKERS.items():
        print(f"[lane A SEC 8-K 2.02] {ticker} ...", file=sys.stderr)
        d = sec_fts('"Item 2.02"', "8-K", cik, "2020-01-01", TODAY)
        total = d["hits"]["total"]["value"]
        sec_dates = sorted(h["_source"]["file_date"] for h in d["hits"]["hits"])
        yf_realized_dates = sorted(
            r["date"] for r in yf_data.get(ticker, {}).get("rows", [])
            if r["reported_eps"] is not None
        )
        matches = sum(1 for dt in yf_realized_dates if dt in sec_dates)
        out[ticker] = {
            "sec_8k_2.02_total_hits": total,
            "sec_dates_sample": sec_dates,
            "yf_realized_dates": yf_realized_dates,
            "matches": matches,
            "yf_realized_count": len(yf_realized_dates),
        }
        time.sleep(0.3)
    return out


# ---------------------------------------------------------------------------
# Lane C item 1: ClinicalTrials.gov sponsor-name mapping + date coverage.
# ---------------------------------------------------------------------------
def lane_c_clinicaltrials() -> dict:
    out = {}
    url = "https://clinicaltrials.gov/api/v2/studies"
    for ticker, (_, name_guess) in LANE_C_TICKERS.items():
        print(f"[lane C ClinicalTrials.gov] {ticker} ({name_guess}) ...", file=sys.stderr)
        params = {
            "query.term": f"AREA[LeadSponsorName]{name_guess}",
            "fields": "NCTId,LeadSponsorName,PrimaryCompletionDate,ResultsFirstPostDate,OverallStatus",
            "pageSize": 50,
            "countTotal": "true",
        }
        try:
            r = requests.get(url, params=params, headers=SEC_HEADERS, timeout=15)
            d = r.json()
        except Exception as e:
            out[ticker] = {"error": f"{type(e).__name__}: {e}"}
            continue
        studies = d.get("studies", [])
        total = d.get("totalCount", 0)
        sponsor_names = set()
        n_pcd_any = n_pcd_past = n_results_posted = 0
        for s in studies:
            stat = s["protocolSection"]["statusModule"]
            sp = s["protocolSection"]["sponsorCollaboratorsModule"]["leadSponsor"]["name"]
            sponsor_names.add(sp)
            pcd = stat.get("primaryCompletionDateStruct", {}).get("date")
            rfp = stat.get("resultsFirstPostDateStruct", {}).get("date") if isinstance(stat.get("resultsFirstPostDateStruct"), dict) else None
            if pcd:
                n_pcd_any += 1
                if pcd <= TODAY:
                    n_pcd_past += 1
            if rfp:
                n_results_posted += 1
        out[ticker] = {
            "query_name_guess": name_guess,
            "total_trials_matched": total,
            "sampled": len(studies),
            "resolved_sponsor_names": sorted(sponsor_names),
            "clean_exact_match": sponsor_names == {sponsor_names_expected(name_guess)} if len(sponsor_names) == 1 else False,
            "has_primary_completion_date": n_pcd_any,
            "primary_completion_date_in_past": n_pcd_past,
            "has_results_first_post_date": n_results_posted,
        }
        time.sleep(0.3)
    return out


def sponsor_names_expected(guess: str) -> str:
    # placeholder purity helper — not used for logic, only for the JSON field above
    return guess


# ---------------------------------------------------------------------------
# Lane C item 2: SEC 8-K cross-check for a few biotech tickers (no Item 2.02
# filter — biotech events use varied items, e.g. 8.01/7.01) as a check that
# real public-disclosure timestamps exist independent of Finnhub.
# ---------------------------------------------------------------------------
def lane_c_sec_crosscheck() -> dict:
    out = {}
    probe_tickers = ["MRNA", "SRPT", "VRTX"]
    queries = ['"topline results"', '"FDA approval"']
    for ticker in probe_tickers:
        cik = LANE_C_TICKERS[ticker][0]
        out[ticker] = {}
        for q in queries:
            print(f"[lane C SEC 8-K] {ticker} q={q} ...", file=sys.stderr)
            d = sec_fts(q, "8-K", cik, "2024-01-01", TODAY)
            total = d["hits"]["total"]["value"]
            dates = [h["_source"]["file_date"] for h in d["hits"]["hits"][:5]]
            out[ticker][q] = {"total_hits": total, "sample_dates": dates}
            time.sleep(0.5)
    return out


def main() -> None:
    result = {}
    result["lane_a_yfinance"] = lane_a_yfinance()
    result["lane_a_sec_crosscheck"] = lane_a_sec_crosscheck(result["lane_a_yfinance"])
    result["lane_c_clinicaltrials"] = lane_c_clinicaltrials()
    result["lane_c_sec_crosscheck"] = lane_c_sec_crosscheck()

    out_path = SCRATCH / "lane-ac-resolvability.json"
    out_path.write_text(json.dumps(result, indent=2, default=str))
    print(f"\nWrote {out_path}", file=sys.stderr)
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
