#!/usr/bin/env python3
"""Run the three frozen methods over the development dates (or the sealed ones).

    python3 scripts/research/ipsf_run.py --split development
    python3 scripts/research/ipsf_run.py --split later --method M1   # authorised only

The later split refuses to run without `later-period-authorization.json` and a
matching policy fingerprint.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ipsf_engine as eng  # noqa: E402
import ipsf_metrics as met  # noqa: E402
from ipsf_common import RES_DIR, SEALED_DATES  # noqa: E402
from ipsf_daily import (  # noqa: E402
    EARLY_CLOSE_DATES,
    as_of_liquid_daily,
    as_of_liquid_minute,
    load_daily_panel,
    load_spy,
)
from ipsf_predictors import method1_panel  # noqa: E402

CODE_FILES = ["ipsf_common.py", "ipsf_daily.py", "ipsf_engine.py",
              "ipsf_metrics.py", "ipsf_predictors.py", "ipsf_run.py",
              "ipsf_blocks.py", "ipsf_extract_full_session.py"]


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for c in iter(lambda: fh.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def code_fingerprint() -> dict:
    here = Path(__file__).resolve().parent
    return {n: sha256_file(here / n) for n in CODE_FILES if (here / n).exists()}


def peer_groups() -> dict:
    import yaml
    p = Path("/home/openclaw/.openclaw/workspace/consensus_engine/data/"
             "peer_groups.yaml")
    doc = yaml.safe_load(p.read_text()) or {}
    return {k: v.get("members", []) for k, v in (doc.get("groups") or {}).items()}


def group_of(symbol: str, groups: dict) -> str:
    for g, members in groups.items():
        if symbol in members:
            return g
    return "ungrouped"


# --------------------------------------------------------------------------- #
def load_block_minutes(feed: str, keys: pd.DataFrame) -> pd.DataFrame:
    """Every minute bar of every (date, symbol, block) we might trade."""
    want = set(zip(keys["date"], keys["symbol"], keys["block"].astype(int)))
    pf = pq.ParquetFile(RES_DIR / f"bars-{feed}-full.parquet")
    keep = []
    for i in range(pf.num_row_groups):
        c = pf.read_row_group(i).to_pandas()
        c["date"] = c["date"].astype(str)
        c["symbol"] = c["symbol"].astype(str)
        c["block"] = (570 + ((c["minute"] - 570) // 30) * 30).astype(int)
        idx = pd.MultiIndex.from_arrays([c["date"], c["symbol"], c["block"]])
        c = c[idx.isin(want)]
        if len(c):
            keep.append(c)
        del idx
    return (pd.concat(keep, ignore_index=True) if keep
            else pd.DataFrame(columns=["date", "symbol", "block", "minute",
                                       "open", "high", "low", "close",
                                       "volume"]))


def minute_sessions(feed: str) -> pd.DataFrame:
    """Whole-session dollar volume and bar count per (date, symbol)."""
    pf = pq.ParquetFile(RES_DIR / f"bars-{feed}-full.parquet")
    parts = []
    for i in range(pf.num_row_groups):
        c = pf.read_row_group(
            i, columns=["date", "symbol", "minute", "close", "volume"]).to_pandas()
        c["date"] = c["date"].astype(str)
        c["symbol"] = c["symbol"].astype(str)
        c["dv"] = c["close"] * c["volume"]
        parts.append(c.groupby(["date", "symbol"], observed=True).agg(
            session_dollar_volume=("dv", "sum"),
            session_bars=("minute", "size"),
            last_close=("close", "last")).reset_index())
        del c
    df = pd.concat(parts, ignore_index=True)
    return df.groupby(["date", "symbol"], as_index=False).agg(
        session_dollar_volume=("session_dollar_volume", "sum"),
        session_bars=("session_bars", "sum"),
        last_close=("last_close", "last"))


def chrono_slices(taken: pd.DataFrame, dates: list[str], n: int) -> list:
    if taken is None or len(taken) == 0:
        return [None] * n
    out = []
    for e in np.array_split(np.array(dates), n):
        s = taken[taken["date"].isin(set(e))]
        out.append(float(s["net_return"].mean()) if len(s) else None)
    return out


def window_dates(policy, name, all_dates, split):
    """Which dates this method develops on, or the sealed set."""
    sealed = all_dates[len(all_dates) - SEALED_DATES:]
    if split == "later":
        return [d for d in sealed if d not in EARLY_CLOSE_DATES]
    w = policy["development_windows"][name]
    if name == "M1":
        return [d for d in all_dates[: len(all_dates) - SEALED_DATES]
                if d not in EARLY_CLOSE_DATES]
    daily = load_daily_panel()
    ds = sorted(daily["date"].unique())
    return [d for d in ds if w["first"] <= d <= w["last"]
            and d not in EARLY_CLOSE_DATES]


# --------------------------------------------------------------------------- #
def run_m1(policy, dates, feed="equs", signal_feed=None):
    """signal_feed lets the crossover check take the signal from one feed and
    the payoff from the other."""
    sf = signal_feed or feed
    blocks = pd.read_parquet(RES_DIR / f"blocks-{sf}.parquet")
    liq = as_of_liquid_minute(minute_sessions(sf))
    liq = liq[liq["liquid"]]
    panel = method1_panel(blocks, set(dates))
    del blocks
    panel = panel.merge(liq[["date", "symbol", "prior20_median_dollar_volume"]],
                        on=["date", "symbol"], how="inner")
    sig = eng.m1_signals(panel, policy)
    bars = load_block_minutes(feed, sig[["date", "symbol", "block"]])
    priced = eng.m1_price_trades(sig, bars, policy)
    delayed = eng.m1_price_trades(
        sig, bars, policy,
        entry_delay_minutes=policy["methods"]["M1"]["delayed_entry_minutes"])
    return priced, delayed


def run_m2(policy, dates):
    daily = load_daily_panel()
    liq = as_of_liquid_daily(daily)
    spy = load_spy()
    d = daily[daily["date"].isin(set(dates))]
    return (eng.m2_trades(d, liq, spy, policy, dates),
            eng.m2_trades(d, liq, spy, policy, dates, entry_at_close=True))


def run_m3(policy, dates):
    daily = load_daily_panel()
    liq = as_of_liquid_daily(daily)
    groups = peer_groups()
    return (eng.m3_pairs(daily, liq, groups, policy, dates),
            eng.m3_pairs(daily, liq, groups, policy, dates,
                         entry_delay_sessions=1))


def spy_benchmark(dates: list[str]) -> dict:
    """What simply owning the market over the same dates would have done."""
    spy = load_spy()
    s = spy[spy["date"].isin(set(dates))].sort_values("date")
    if len(s) < 2:
        return {}
    total = float(s["close"].iloc[-1] / s["close"].iloc[0] - 1.0)
    years = len(s) / 252.0
    eq = s["close"] / s["close"].iloc[0]
    peak = eq.cummax()
    return {"total_return": total,
            "annualised_return": float((1 + total) ** (1 / years) - 1)
            if years > 0 else None,
            "max_drawdown": float(((peak - eq) / peak).max())}


def score_method(name, priced, delayed, policy, dates, conf, alt_priced=None,
                 cross_priced=None, common_window=None):
    costs = policy["costs"]
    key = "pair" if name == "M3" else "single"
    normal_cost = costs[key]["normal"]
    harsh_cost = costs[key]["harsh"]
    fixed = policy["portfolio"]["fixed_notional_path"]

    taken, eq = eng.simulate(priced, policy, normal_cost)
    m = met.metrics(taken, eq, dates, policy)
    ftaken, feq = eng.simulate(priced, policy, normal_cost, fixed_notional=fixed)
    fm = met.metrics(ftaken, feq, dates, policy)
    boot = met.block_bootstrap(ftaken, dates, conf,
                               policy["statistics"]["resamples"],
                               policy["statistics"]["seed"])
    h_t, h_e = eng.simulate(priced, policy, harsh_cost, fixed_notional=fixed)
    harsh_boot = met.block_bootstrap(h_t, dates, conf,
                                     policy["statistics"]["resamples"],
                                     policy["statistics"]["seed"])
    d_t, d_e = eng.simulate(delayed, policy, normal_cost, fixed_notional=fixed)
    half_t, half_e = eng.simulate(priced, policy, normal_cost, risk_scale=0.5)
    alt = {}
    if alt_priced is not None:
        a_t, a_e = eng.simulate(alt_priced, policy, normal_cost,
                                fixed_notional=fixed)
        alt = met.metrics(a_t, a_e, dates, policy)
    cross = {}
    if cross_priced is not None:
        c_t, c_e = eng.simulate(cross_priced, policy, normal_cost,
                                fixed_notional=fixed)
        cross = met.metrics(c_t, c_e, dates, policy)

    res = {
        "method": name,
        "compounding": m,
        "fixed_notional": fm,
        "harsh": met.metrics(h_t, h_e, dates, policy),
        "delayed": met.metrics(d_t, d_e, dates, policy),
        "half_size": met.metrics(half_t, half_e, dates, policy),
        "independent_feed": alt,
        "crossover_feed": cross,
        "bootstrap": boot,
        "harsh_bootstrap": harsh_boot,
        "void_rate": (float(priced["void"].mean()) if len(priced) else None),
        "buy_and_hold_spy": spy_benchmark(dates),
        "five_blocks_avg_net": chrono_slices(ftaken, dates, 5),
        "halves_avg_net": chrono_slices(ftaken, dates, 2),
        "candidates_priced": int(len(priced)),
        "candidates_voided": int(priced["void"].sum()) if len(priced) else 0,
        "normal_cost": normal_cost, "harsh_cost": harsh_cost,
    }
    if len(ftaken):
        res["entry_slide"] = {
            "share_sliding": float((ftaken["entry_slide_minutes"].fillna(0) > 0).mean())
            if "entry_slide_minutes" in ftaken else None,
        }
        res["random_control"] = met.random_direction_control(
            ftaken, policy["statistics"]["seed"], 10000)
        if name == "M1":
            groups = peer_groups()
            res["peer_group_shares"] = met.group_shares(ftaken, groups, group_of)
        if name in ("M2", "M3"):
            res["dividend_contamination"] = met.dividend_contamination(ftaken)
    if common_window is not None:
        cw_dates = [d for d in dates
                    if common_window[0] <= d <= common_window[1]]
        cw = ftaken[ftaken["date"].isin(set(cw_dates))] if len(ftaken) else ftaken
        res["common_window"] = (met.metrics(cw, feq, cw_dates, policy)
                                if len(cw) else {"trades": 0})
    return res, ftaken, taken


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", choices=["development", "later"],
                    default="development")
    ap.add_argument("--method", default=None)
    ap.add_argument("--only", default=None, help="run one method only")
    args = ap.parse_args()

    policy = eng.load_policy()
    policy_sha = sha256_file(RES_DIR / "frozen-policy.json")
    want = (RES_DIR / "frozen-policy.sha256").read_text().split()[0]
    if policy_sha != want:
        raise SystemExit("FROZEN POLICY FINGERPRINT MISMATCH — refusing to run")

    all_dates = sorted(pd.read_parquet(RES_DIR / "blocks-equs.parquet",
                                       columns=["date"])["date"].astype(str)
                       .unique())

    if args.split == "later":
        auth = RES_DIR / "later-period-authorization.json"
        if not auth.exists():
            raise SystemExit("the later period is sealed: no authorization file")
        a = json.loads(auth.read_text())
        if a.get("frozen_policy_sha256") != policy_sha:
            raise SystemExit("authorization does not match the frozen policy")
        if not args.method or a.get("method") != args.method:
            raise SystemExit("authorization names a different method")
        methods = [args.method]
        conf = policy["statistics"]["later_confidence"]
    else:
        methods = [args.only] if args.only else ["M1", "M2", "M3"]
        conf = policy["statistics"]["development_confidence"]

    results = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "split": args.split,
        "frozen_policy_sha256": policy_sha,
        "code_fingerprint": code_fingerprint(),
        "methods": {},
    }

    for name in methods:
        dates = window_dates(policy, name, all_dates, args.split)
        print(f"[{args.split}] {name}: {len(dates)} dates "
              f"{dates[0]}..{dates[-1]}", flush=True)
        cross = None
        if name == "M1":
            priced, delayed = run_m1(policy, dates, "equs")
            alt, _ = run_m1(policy, dates, "pillar")
            cross, _ = run_m1(policy, dates, feed="equs", signal_feed="pillar")
        elif name == "M2":
            priced, delayed = run_m2(policy, dates)
            alt = None
        else:
            priced, delayed = run_m3(policy, dates)
            alt = None
        cw = (policy["gates"]["development"]
              ["daily_methods_must_also_pass_common_window"]
              if name in ("M2", "M3") and args.split == "development" else None)
        res, ftaken, taken = score_method(name, priced, delayed, policy, dates,
                                          conf, alt_priced=alt,
                                          cross_priced=cross, common_window=cw)
        res["dates"] = {"n": len(dates), "first": dates[0], "last": dates[-1]}
        if args.split == "development":
            res["gates"] = met.development_gates(res, policy)
        else:
            res["gates"] = met.evaluation_gates(res, policy)
        res["passes_all_gates"] = all(g["pass"] for g in res["gates"])
        results["methods"][name] = res
        # The gates are read off the EQUAL-DOLLAR path, so that is the file
        # named after the method; the compounding path is saved beside it.
        for label, frame in (("", ftaken), ("-compounding", taken)):
            if frame is None or len(frame) == 0:
                continue
            out_t = frame.copy()
            for col in ("entry_seq", "exit_seq"):
                if col in out_t:
                    out_t[col] = out_t[col].map(
                        lambda v: "|".join(str(x) for x in v))
            out_t.to_parquet(
                RES_DIR / f"trades-{args.split}-{name}{label}.parquet",
                index=False)
        fm = res["fixed_notional"]
        print(f"  {name}: trades={fm.get('trades')} "
              f"gross={fm.get('avg_gross_return')} "
              f"net={fm.get('avg_net_return')} "
              f"passes={res['passes_all_gates']}", flush=True)

    out = RES_DIR / ("development-results.json" if args.split == "development"
                     else "later-period-results.json")
    if out.exists() and args.only:
        old = json.loads(out.read_text())
        old["methods"].update(results["methods"])
        results = old
    out.write_text(json.dumps(results, indent=2, default=str) + "\n")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
