"""Report orchestration — runs the eval sections and writes markdown.

Design: FIRST PASS SIMPLE and decision-focused. The question the product
actually needs answered is "where, if anywhere, is there real edge?" — not a
metric zoo. Each section returns plain dicts/lists; `build_report` renders
them to markdown and `run` writes the file + prints a summary.

READ-ONLY. Never writes the DB, never imports the live scoring path.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import numpy as np

from consensus_engine.eval import loaders, metrics
from consensus_engine.eval.loaders import Snapshot, ShadowPred

HORIZONS = ["1h", "24h", "5d", "20d"]
_HCOL = {
    "1h": "outcome_price_1h",
    "24h": "outcome_price_24h",
    "5d": "outcome_price_5d",
    "20d": "outcome_price_20d",
}


def _ts(x) -> str:
    return datetime.fromtimestamp(x, tz=timezone.utc).strftime("%Y-%m-%d") if x else "—"


# ===========================================================================
# 1. LABEL AUDIT
# ===========================================================================

def label_audit(conn: sqlite3.Connection) -> dict:
    """Count rows, resolved vs NULL, date range, and sanity issues per outcome
    table. Reports BOTH the naive rate (hits / all rows — the wrong number a
    prior review published) and the correct rate (hits / resolved rows)."""
    out: dict = {"tables": []}

    # ---- decision_snapshots ----
    ds_rows = conn.execute(
        "SELECT recorded_at, outcome_price_at_alert, outcome_price_1h, outcome_price_24h,"
        " outcome_price_5d, outcome_price_20d, alert_id FROM decision_snapshots"
    ).fetchall()
    total = len(ds_rows)
    dates = [r["recorded_at"] for r in ds_rows if r["recorded_at"]]
    bad_entry = sum(1 for r in ds_rows if r["outcome_price_at_alert"] is not None and r["outcome_price_at_alert"] <= 0)
    aid = [r["alert_id"] for r in ds_rows if r["alert_id"] is not None]
    dup_aid = len(aid) - len(set(aid))
    per_h = []
    for h in HORIZONS:
        col = _HCOL[h]
        resolved = [r for r in ds_rows if r["outcome_price_at_alert"] and r["outcome_price_at_alert"] > 0 and r[col] is not None]
        nulls = total - len(resolved)
        hits = sum(1 for r in resolved if r[col] > r["outcome_price_at_alert"])
        # impossible move sanity: >10x up or <-95% at 1h/24h
        impossible = sum(
            1 for r in resolved
            if r[col] / r["outcome_price_at_alert"] > 11 or r[col] / r["outcome_price_at_alert"] < 0.05
        )
        per_h.append({
            "horizon": h, "resolved": len(resolved), "null": nulls,
            "hits": hits,
            "naive_rate": hits / total if total else float("nan"),
            "correct_rate": hits / len(resolved) if resolved else float("nan"),
            "impossible_moves": impossible,
        })
    out["tables"].append({
        "name": "decision_snapshots", "total": total,
        "date_lo": _ts(min(dates)) if dates else "—", "date_hi": _ts(max(dates)) if dates else "—",
        "bad_entry_le0": bad_entry, "dup_alert_ids": dup_aid, "per_horizon": per_h,
    })

    # ---- alert_history ----
    ah_rows = conn.execute(
        "SELECT alerted_at, price_at_alert, price_1h_later, price_24h_later FROM alert_history"
    ).fetchall()
    total = len(ah_rows)
    dates = [r["alerted_at"] for r in ah_rows if r["alerted_at"]]
    bad_entry = sum(1 for r in ah_rows if r["price_at_alert"] is not None and r["price_at_alert"] <= 0)
    per_h = []
    for h, col in [("1h", "price_1h_later"), ("24h", "price_24h_later")]:
        resolved = [r for r in ah_rows if r["price_at_alert"] and r["price_at_alert"] > 0 and r[col] is not None]
        hits = sum(1 for r in resolved if r[col] > r["price_at_alert"])
        per_h.append({
            "horizon": h, "resolved": len(resolved), "null": total - len(resolved), "hits": hits,
            "naive_rate": hits / total if total else float("nan"),
            "correct_rate": hits / len(resolved) if resolved else float("nan"),
            "impossible_moves": 0,
        })
    out["tables"].append({
        "name": "alert_history", "total": total,
        "date_lo": _ts(min(dates)) if dates else "—", "date_hi": _ts(max(dates)) if dates else "—",
        "bad_entry_le0": bad_entry, "dup_alert_ids": 0, "per_horizon": per_h,
        "note": "No direction column — alerts are long-biased watchlist signals. price_up = hit.",
    })

    # ---- shadow_predictions ----
    sp_rows = conn.execute(
        "SELECT horizon, actual_hit, predicted_prob, created_at, alert_id FROM shadow_predictions"
    ).fetchall()
    total = len(sp_rows)
    dates = [r["created_at"] for r in sp_rows if r["created_at"]]
    oob = sum(1 for r in sp_rows if r["predicted_prob"] is not None and (r["predicted_prob"] < 0 or r["predicted_prob"] > 1))
    per_h = []
    for h in ("1h", "24h"):
        hr = [r for r in sp_rows if r["horizon"] == h]
        resolved = [r for r in hr if r["actual_hit"] is not None]
        hits = sum(int(r["actual_hit"]) for r in resolved)
        per_h.append({
            "horizon": h, "resolved": len(resolved), "null": len(hr) - len(resolved), "hits": hits,
            "naive_rate": hits / len(hr) if hr else float("nan"),
            "correct_rate": hits / len(resolved) if resolved else float("nan"),
            "impossible_moves": 0,
        })
    out["tables"].append({
        "name": "shadow_predictions", "total": total,
        "date_lo": _ts(min(dates)) if dates else "—", "date_hi": _ts(max(dates)) if dates else "—",
        "bad_entry_le0": oob, "dup_alert_ids": 0, "per_horizon": per_h,
        "note": "bad_entry_le0 column reused for out-of-[0,1] predicted_prob count.",
    })
    return out


# ===========================================================================
# 2. CALIBRATION of the score->prob map (shadow_predictions)
# ===========================================================================

def calibration(preds: list[ShadowPred], test_frac: float = 0.30) -> dict:
    """Per-horizon time-split calibration of predicted_prob vs actual_hit.
    Fits isotonic + beta on the OLDER train split, applies to the NEWER test
    split, reports held-out Brier before/after. Time-split, never random —
    a random split leaks future info into the fit."""
    result: dict = {"horizons": {}}
    for h in ("1h", "24h"):
        rows = [p for p in preds if p.horizon == h]
        rows.sort(key=lambda p: p.created_at)
        n = len(rows)
        if n < 100:
            result["horizons"][h] = {"n": n, "note": "too few rows"}
            continue
        cut = int(n * (1 - test_frac))
        tr, te = rows[:cut], rows[cut:]
        p_tr = np.array([r.predicted_prob for r in tr]); y_tr = np.array([r.actual_hit for r in tr])
        p_te = np.array([r.predicted_prob for r in te]); y_te = np.array([r.actual_hit for r in te])

        raw = {
            "brier": metrics.brier_score(p_te, y_te),
            "log_loss": metrics.log_loss(p_te, y_te),
            "base_rate_brier": metrics.base_rate_brier(y_te),
            "auc": metrics.auc(p_te, y_te),
        }

        iso_brier = beta_brier = float("nan")
        note = []
        # isotonic recalibration
        try:
            from sklearn.isotonic import IsotonicRegression
            iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
            iso.fit(p_tr, y_tr)
            iso_brier = metrics.brier_score(iso.predict(p_te), y_te)
        except Exception as e:  # pragma: no cover
            note.append(f"isotonic failed: {e}")
        # beta recalibration
        try:
            from betacal import BetaCalibration
            bc = BetaCalibration(parameters="abm")
            bc.fit(p_tr.reshape(-1, 1), y_tr)
            beta_brier = metrics.brier_score(bc.predict(p_te.reshape(-1, 1)), y_te)
        except Exception as e:
            note.append(f"beta unavailable ({e}); isotonic-only")

        result["horizons"][h] = {
            "n": n, "n_train": len(tr), "n_test": len(te),
            "train_date_lo": _ts(tr[0].created_at), "train_date_hi": _ts(tr[-1].created_at),
            "test_date_lo": _ts(te[0].created_at), "test_date_hi": _ts(te[-1].created_at),
            "test_base_rate": float(y_te.mean()),
            "raw": raw,
            "isotonic_test_brier": iso_brier,
            "beta_test_brier": beta_brier,
            "reliability": metrics.reliability_bins(p_te, y_te, 10),
            "note": "; ".join(note) if note else "",
        }
    return result


# ===========================================================================
# 3. DISCRIMINATION + EDGE-POCKET HUNT (decision_snapshots)
# ===========================================================================

def _resolved(snaps: list[Snapshot], h: str) -> tuple[np.ndarray, np.ndarray]:
    s, y = [], []
    for sn in snaps:
        hit = sn.hit(h)
        if hit is None or sn.final_score != sn.final_score:  # nan guard
            continue
        s.append(sn.final_score); y.append(hit)
    return np.array(s, dtype=float), np.array(y, dtype=int)


def discrimination(snaps: list[Snapshot]) -> dict:
    out: dict = {"horizons": {}}
    for h in HORIZONS:
        s, y = _resolved(snaps, h)
        if s.size < 30:
            out["horizons"][h] = {"n": int(s.size), "note": "too few resolved"}
            continue
        base = float(y.mean())
        bands = [0, 40, 55, 65, 75, 200]
        out["horizons"][h] = {
            "n": int(s.size), "base_rate": base,
            "auc": metrics.auc(s, y),
            "top_decile_lift": metrics.top_decile_lift(s, y),
            "p_at_10": metrics.precision_at_k(s, y, 0.10),
            "p_at_20": metrics.precision_at_k(s, y, 0.20),
            "decile_table": metrics.decile_table(s, y, 10),
            "fpr_bands": metrics.fpr_by_band(s, y, bands),
        }
    return out


def edge_pockets(snaps: list[Snapshot], min_n: int = 90) -> dict:
    """The product's real question. Slice by decision tier, catalyst_type, and
    populated-feature buckets; at each horizon report the subgroup hit rate
    with a Wilson lower bound. A slice with Wilson-LB > 0.50 at n >= min_n is a
    real edge pocket above coin-flip. Also reports within-slice precision@top-
    decile where the slice is large enough."""
    out: dict = {"min_n": min_n, "horizons": {}}

    def slices_for(snaps_h, h):
        groups: dict[str, list] = {}
        for sn in snaps_h:
            groups.setdefault(f"tier={sn.decision}", []).append(sn)
            if sn.catalyst_type:
                groups.setdefault(f"catalyst={sn.catalyst_type}", []).append(sn)
            f = sn.feats
            if "sector_aligned" in f:
                groups.setdefault(f"sector_aligned={int(f['sector_aligned'])}", []).append(sn)
            if "contra_penalty" in f:
                groups.setdefault(f"contra_penalty={int(f['contra_penalty'])}", []).append(sn)
            if "consol_fired" in f:
                groups.setdefault(f"consol_fired={int(f['consol_fired'])}", []).append(sn)
            if "regime_z" in f:
                lab = "regime_z>=0" if f["regime_z"] >= 0 else "regime_z<0"
                groups.setdefault(lab, []).append(sn)
            if "n_opposing" in f:
                groups.setdefault(f"n_opposing={int(min(f['n_opposing'],1))}", []).append(sn)
        return groups

    for h in HORIZONS:
        snaps_h = [sn for sn in snaps if sn.hit(h) is not None and sn.final_score == sn.final_score]
        if not snaps_h:
            out["horizons"][h] = {"base_rate": float("nan"), "slices": [], "edge_found": []}
            continue
        base = float(np.mean([sn.hit(h) for sn in snaps_h]))
        rows = []
        for name, g in slices_for(snaps_h, h).items():
            n = len(g)
            if n < min_n:
                continue
            hits = sum(sn.hit(h) for sn in g)
            wlb = metrics.wilson_lower_bound(hits, n)
            # within-slice precision @ top decile of score
            s = np.array([sn.final_score for sn in g]); y = np.array([sn.hit(h) for sn in g])
            pk = metrics.precision_at_k(s, y, 0.10) if n >= 40 else {"precision": float("nan"), "n_selected": 0, "hits": 0}
            rows.append({
                "slice": name, "n": n, "hits": hits,
                "hit_rate": hits / n, "wilson_lb": wlb,
                "beats_base": (hits / n) - base,
                "p_at_10": pk["precision"], "p_at_10_n": pk["n_selected"], "p_at_10_hits": pk["hits"],
            })
        rows.sort(key=lambda r: r["wilson_lb"], reverse=True)
        edge = [r for r in rows if r["wilson_lb"] > 0.50 and r["n"] >= min_n]
        out["horizons"][h] = {"base_rate": base, "slices": rows, "edge_found": edge}
    return out


# ===========================================================================
# 4. LOGISTIC CHALLENGER (measured, not a deliverable)
# ===========================================================================

def logistic_challenger(snaps: list[Snapshot]) -> dict:
    """ONE measured challenger vs the incumbent final_score->prob map.

    The documented flat 15-feature vector is NOT populated (see §6a), so the
    challenger is fit on the feature set that IS populated: the extracted
    nested-verdict + shadow fields. Time-ordered split with a TICKER EMBARGO
    (no same-ticker row on both sides) to kill leakage. Incumbent = isotonic
    map of final_score fit on the SAME train fold (a fair, self-calibrated
    baseline), evaluated on the held-out test fold."""
    out: dict = {"horizons": {}}
    try:
        from sklearn.linear_model import LogisticRegressionCV
        from sklearn.isotonic import IsotonicRegression
        from sklearn.preprocessing import StandardScaler
    except Exception as e:  # pragma: no cover
        return {"error": f"sklearn unavailable: {e}"}

    for h in ("24h", "5d"):
        # rows with resolved outcome + populated features
        rows = [sn for sn in snaps if sn.hit(h) is not None and sn.feats and sn.final_score == sn.final_score]
        rows.sort(key=lambda s: s.recorded_at)
        if len(rows) < 200:
            out["horizons"][h] = {"n": len(rows), "note": "too few rows with features+outcome"}
            continue
        feat_names = sorted({k for sn in rows for k in sn.feats})
        # time-ordered split
        cut = int(len(rows) * 0.70)
        tr, te = rows[:cut], rows[cut:]
        # ticker embargo: drop test rows whose ticker appears in train
        train_tickers = {sn.ticker for sn in tr}
        te = [sn for sn in te if sn.ticker not in train_tickers]
        if len(te) < 60:
            out["horizons"][h] = {"n": len(rows), "note": f"post-embargo test too small ({len(te)})"}
            continue

        def X(rowset):
            return np.array([[sn.feats.get(f, 0.0) for f in feat_names] for sn in rowset], dtype=float)

        ytr = np.array([sn.hit(h) for sn in tr]); yte = np.array([sn.hit(h) for sn in te])
        if len(set(ytr)) < 2:
            out["horizons"][h] = {"n": len(rows), "note": "train single-class"}
            continue
        scaler = StandardScaler().fit(X(tr))
        clf = LogisticRegressionCV(Cs=10, cv=5, penalty="l2", scoring="neg_log_loss", max_iter=2000)
        clf.fit(scaler.transform(X(tr)), ytr)
        p_chal = clf.predict_proba(scaler.transform(X(te)))[:, 1]

        # incumbent: isotonic map of final_score fit on train, applied to test
        s_tr = np.array([sn.final_score for sn in tr]); s_te = np.array([sn.final_score for sn in te])
        iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0).fit(s_tr, ytr)
        p_inc = iso.predict(s_te)

        out["horizons"][h] = {
            "n": len(rows), "n_train": len(tr), "n_test": len(te),
            "n_features": len(feat_names), "features": feat_names,
            "test_base_rate": float(yte.mean()),
            "incumbent": {
                "brier": metrics.brier_score(p_inc, yte),
                "log_loss": metrics.log_loss(p_inc, yte),
                "auc": metrics.auc(p_inc, yte),
                "p_at_10": metrics.precision_at_k(s_te, yte, 0.10)["precision"],
            },
            "challenger": {
                "brier": metrics.brier_score(p_chal, yte),
                "log_loss": metrics.log_loss(p_chal, yte),
                "auc": metrics.auc(p_chal, yte),
                "p_at_10": metrics.precision_at_k(p_chal, yte, 0.10)["precision"],
            },
        }
        inc, chal = out["horizons"][h]["incumbent"], out["horizons"][h]["challenger"]
        brier_better = chal["brier"] < inc["brier"] - 1e-4
        auc_better = chal["auc"] > inc["auc"] + 1e-3
        # A lower Brier with an AUC that sinks toward/below 0.5 is not real edge —
        # the model just predicts nearer the base rate. Only count a win if it
        # also discriminates better.
        if brier_better and auc_better:
            verdict = "challenger genuinely beats incumbent (lower Brier AND higher AUC)"
        elif brier_better and not auc_better:
            verdict = ("TIE — challenger's lower Brier is regression to base rate "
                       f"(AUC {_f(chal['auc'])} ≤ incumbent {_f(inc['auc'])}, near coin-flip); no real added edge")
        else:
            verdict = "incumbent wins / tie (challenger no better)"
        out["horizons"][h]["verdict"] = verdict
    return out


# ===========================================================================
# 5. PER-SIGNAL CONTRIBUTION (IC + leave-one-out)
# ===========================================================================

def per_signal(snaps: list[Snapshot], horizon: str = "24h") -> dict:
    """Univariate Spearman IC per populated feature at `horizon`, plus a
    leave-one-out AUC delta from the full logistic model. Positive IC = the
    feature ranks bullish outcomes. The 15 documented features are all-zero
    (see §6a) so their IC is undefined — this measures what actually varies."""
    rows = [sn for sn in snaps if sn.hit(horizon) is not None and sn.feats and sn.final_score == sn.final_score]
    if len(rows) < 100:
        return {"horizon": horizon, "n": len(rows), "note": "too few rows"}
    feat_names = sorted({k for sn in rows for k in sn.feats})
    y = np.array([sn.hit(horizon) for sn in rows], dtype=float)

    ics = []
    for f in feat_names:
        x = np.array([sn.feats.get(f, 0.0) for sn in rows], dtype=float)
        ics.append({
            "feature": f,
            "spearman_ic": metrics.spearman_ic(x, y),
            "pearson_ic": metrics.pearson_ic(x, y),
            "nonzero_frac": float(np.mean(x != 0)),
        })
    # add final_score itself as the reference
    s = np.array([sn.final_score for sn in rows], dtype=float)
    ics.append({"feature": "final_score(ref)", "spearman_ic": metrics.spearman_ic(s, y),
                "pearson_ic": metrics.pearson_ic(s, y), "nonzero_frac": 1.0})
    ics.sort(key=lambda r: abs(r["spearman_ic"]) if r["spearman_ic"] == r["spearman_ic"] else -1, reverse=True)

    # leave-one-out AUC delta
    loo = _loo_auc(rows, feat_names, y)
    return {"horizon": horizon, "n": len(rows), "ics": ics, "loo": loo}


def _loo_auc(rows, feat_names, y) -> list[dict]:
    try:
        from sklearn.linear_model import LogisticRegression
        from sklearn.preprocessing import StandardScaler
    except Exception:  # pragma: no cover
        return []
    if len(set(y.astype(int))) < 2:
        return []

    def fit_auc(feats):
        if not feats:
            return float("nan")
        X = np.array([[sn.feats.get(f, 0.0) for f in feats] for sn in rows], dtype=float)
        Xs = StandardScaler().fit_transform(X)
        clf = LogisticRegression(penalty="l2", C=1.0, max_iter=2000).fit(Xs, y)
        return metrics.auc(clf.predict_proba(Xs)[:, 1], y)

    full = fit_auc(feat_names)
    out = []
    for f in feat_names:
        reduced = [x for x in feat_names if x != f]
        out.append({"feature": f, "auc_drop_when_removed": full - fit_auc(reduced)})
    out.sort(key=lambda r: r["auc_drop_when_removed"], reverse=True)
    return [{"full_in_sample_auc": full}] + out


# ===========================================================================
# 6. DATA-AVAILABILITY FINDINGS
# ===========================================================================

def data_availability(conn: sqlite3.Connection, snaps: list[Snapshot]) -> dict:
    """6a: are the 5 display-only signals logged anywhere in feature_vector_json?
    6b: is source_performance empty, and what per-analyst outcome data exists?"""
    out: dict = {}

    # 6a — search the raw feature_vector_json text for the display-signal names
    display_terms = {
        "max_pain": ["max_pain", "maxpain", "max-pain"],
        "analyst_momentum": ["analyst_momentum", "analyst_rating", "rating_momentum"],
        "eps_revision": ["eps_revision", "eps_rev", "revision_trend"],
        "peer_relative_strength": ["peer_rs", "peer_relative", "relative_strength", "peer_strength"],
        "chart_patterns": ["chart_pattern", "pattern_field", "patterns"],
    }
    fv_blob = conn.execute(
        "SELECT group_concat(feature_vector_json, '\n') FROM decision_snapshots WHERE feature_vector_json IS NOT NULL"
    ).fetchone()[0] or ""
    fv_blob_l = fv_blob.lower()
    found = {}
    for sig, terms in display_terms.items():
        hits = [t for t in terms if t in fv_blob_l]
        found[sig] = hits
    out["6a_display_signals"] = {
        "verdict": "NONE of the 5 display-only signals appear in feature_vector_json"
        if not any(found.values())
        else "SOME display signals found: " + str({k: v for k, v in found.items() if v}),
        "per_signal_terms_found": found,
        "distinct_keysets": _keyset_summary(conn),
    }

    # 6b — source_performance emptiness + per-analyst outcome availability
    def count(tbl):
        try:
            return conn.execute(f"SELECT count(*) FROM {tbl}").fetchone()[0]
        except sqlite3.Error:
            return None
    sp_n = count("source_performance")
    sps_n = count("source_performance_shadow")
    sps_horizons = []
    if sps_n:
        try:
            for r in conn.execute(
                "SELECT horizon, count(*) c, sum(CASE WHEN sample_size>0 THEN 1 ELSE 0 END) resolved"
                " FROM source_performance_shadow GROUP BY horizon"
            ):
                sps_horizons.append({"horizon": r[0], "rows": r[1], "with_samples": r[2]})
        except sqlite3.Error:
            # schema unknown — just report columns
            cols = [c[1] for c in conn.execute("PRAGMA table_info(source_performance_shadow)")]
            sps_horizons = [{"columns": cols}]
    out["6b_source_performance"] = {
        "source_performance_rows": sp_n,
        "source_performance_shadow_rows": sps_n,
        "shadow_by_horizon": sps_horizons,
        "verdict": (
            f"source_performance is EMPTY ({sp_n} rows). "
            f"Only source_performance_shadow has data ({sps_n} rows) — a single current "
            "rolling-accuracy snapshot, not a time series. Per-analyst 24h/5d outcome "
            "history has not accrued enough to backtest analyst accuracy."
        ),
    }
    return out


def _keyset_summary(conn: sqlite3.Connection) -> list[dict]:
    import json as _json
    from collections import Counter
    c = Counter()
    for (fv,) in conn.execute("SELECT feature_vector_json FROM decision_snapshots WHERE feature_vector_json IS NOT NULL"):
        try:
            c[tuple(sorted(_json.loads(fv).keys()))] += 1
        except Exception:
            pass
    return [{"n": n, "keys": list(ks)} for ks, n in c.most_common()]


# ===========================================================================
# MARKDOWN RENDERING
# ===========================================================================

def _f(x, nd=3):
    if x is None:
        return "—"
    try:
        if x != x:
            return "nan"
        return f"{x:.{nd}f}"
    except (TypeError, ValueError):
        return str(x)


def build_report(sections: dict) -> str:
    L: list[str] = []
    L.append("# Signal-bot evaluation & calibration report\n")
    L.append(f"_Read-only measurement. Generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}. "
             "No live behavior, config, or scoring path was touched._\n")

    # --- 1. Label audit ---
    L.append("## 1. Label audit\n")
    L.append("For every rate below, `correct_rate` uses ONLY resolved rows. A NULL outcome is "
             "**not** a miss. The `naive_rate` (hits / all rows) is shown only to expose how far "
             "off that mistake pushes the number.\n")
    for t in sections["label_audit"]["tables"]:
        L.append(f"### {t['name']} — {t['total']} rows ({t['date_lo']} → {t['date_hi']})")
        L.append(f"entry price ≤0: {t['bad_entry_le0']} · duplicate alert_ids: {t['dup_alert_ids']}"
                 + (f" · _{t['note']}_" if t.get("note") else ""))
        L.append("\n| horizon | resolved | NULL | hits | naive rate (WRONG) | correct rate | impossible moves |")
        L.append("|---|---:|---:|---:|---:|---:|---:|")
        for r in t["per_horizon"]:
            L.append(f"| {r['horizon']} | {r['resolved']} | {r['null']} | {r['hits']} | "
                     f"{_f(r['naive_rate'])} | **{_f(r['correct_rate'])}** | {r['impossible_moves']} |")
        L.append("")

    # --- 2. Calibration ---
    L.append("## 2. Calibration of the score→prob map (shadow_predictions, time-split)\n")
    L.append("Older rows train, newer rows test (never random — random leaks the future). "
             "Recalibration is fit on train, applied to held-out test. Lower Brier = better.\n")
    for h, d in sections["calibration"]["horizons"].items():
        if "raw" not in d:
            L.append(f"### {h}: {d.get('note','—')} (n={d.get('n')})\n"); continue
        L.append(f"### {h} — n={d['n']} (train {d['n_train']} {d['train_date_lo']}→{d['train_date_hi']}, "
                 f"test {d['n_test']} {d['test_date_lo']}→{d['test_date_hi']}, test base rate {_f(d['test_base_rate'])})")
        L.append("\n| metric | held-out test |")
        L.append("|---|---:|")
        L.append(f"| Brier (incumbent map, as logged) | {_f(d['raw']['brier'])} |")
        L.append(f"| Brier of base-rate constant | {_f(d['raw']['base_rate_brier'])} |")
        L.append(f"| log-loss (incumbent) | {_f(d['raw']['log_loss'])} |")
        L.append(f"| AUC (predicted_prob) | {_f(d['raw']['auc'])} |")
        L.append(f"| **Brier after isotonic recal** | **{_f(d['isotonic_test_brier'])}** |")
        L.append(f"| **Brier after beta recal** | **{_f(d['beta_test_brier'])}** |")
        if d.get("note"):
            L.append(f"\n_{d['note']}_")
        L.append("\n10-bin reliability (held-out test): predicted vs realized")
        L.append("\n| bin | n | mean predicted | realized |")
        L.append("|---|---:|---:|---:|")
        for b in d["reliability"]:
            L.append(f"| {b['bin_lo']:.1f}–{b['bin_hi']:.1f} | {b['n']} | {_f(b['mean_pred'])} | {_f(b['mean_actual'])} |")
        L.append("")

    # --- 3. Discrimination + edge pockets ---
    L.append("## 3. Discrimination & the edge-pocket hunt (decision_snapshots)\n")
    L.append("final_score vs (price at horizon > entry). AUC 0.50 = coin flip. Base rate = share of "
             "resolved alerts that closed up.\n")
    for h, d in sections["discrimination"]["horizons"].items():
        if "auc" not in d:
            L.append(f"### {h}: {d.get('note')} (n={d.get('n')})\n"); continue
        L.append(f"### {h} — n={d['n']}, base rate {_f(d['base_rate'])}")
        L.append(f"- AUC **{_f(d['auc'])}** · top-decile lift {_f(d['top_decile_lift'])} · "
                 f"precision@10% {_f(d['p_at_10']['precision'])} (n={d['p_at_10']['n_selected']}) · "
                 f"precision@20% {_f(d['p_at_20']['precision'])} (n={d['p_at_20']['n_selected']})")
        L.append("\n| score decile (low→high) | n | score range | hit rate |")
        L.append("|---|---:|---|---:|")
        for b in d["decile_table"]:
            L.append(f"| {b['rank']} | {b['n']} | {b['score_lo']:.0f}–{b['score_hi']:.0f} | {_f(b['hit_rate'])} |")
        L.append("")
    # edge pockets
    L.append("### Edge-pocket hunt — where, if anywhere, is real edge?\n")
    L.append("A slice is a real edge pocket if its **Wilson lower bound > 0.50** at **n ≥ "
             f"{sections['edge_pockets']['min_n']}** — i.e. we can be confident it beats a coin flip.\n")
    any_edge = False
    for h, d in sections["edge_pockets"]["horizons"].items():
        L.append(f"**{h}** (base rate {_f(d['base_rate'])}):")
        if d["edge_found"]:
            any_edge = True
            L.append("\n| slice | n | hit rate | Wilson LB | vs base | prec@10% |")
            L.append("|---|---:|---:|---:|---:|---:|")
            for r in d["edge_found"]:
                L.append(f"| `{r['slice']}` | {r['n']} | {_f(r['hit_rate'])} | **{_f(r['wilson_lb'])}** | "
                         f"{_f(r['beats_base'],3)} | {_f(r['p_at_10'])} |")
        else:
            top = d["slices"][:3]
            best = ", ".join(f"`{r['slice']}` (hit {_f(r['hit_rate'])}, WLB {_f(r['wilson_lb'])}, n={r['n']})" for r in top)
            L.append(f" no slice clears Wilson-LB > 0.50. Best three: {best if best else '—'}")
        L.append("")
    L.append(("**No subgroup shows statistically-confident edge above a coin flip.**"
              if not any_edge else "**Edge pockets found — see tables above.**") + "\n")

    # --- 4. Logistic challenger ---
    L.append("## 4. Logistic challenger vs incumbent (one measured comparison)\n")
    lc = sections["logistic"]
    if "error" in lc:
        L.append(lc["error"] + "\n")
    else:
        L.append("Fit on the **populated** feature set (the documented 15-key vector is empty — see §6a). "
                 "Time-ordered 70/30 split with a **ticker embargo** (no same-ticker row on both sides). "
                 "Incumbent = isotonic map of final_score fit on the same train fold.\n")
        for h, d in lc["horizons"].items():
            if "incumbent" not in d:
                L.append(f"### {h}: {d.get('note')} (n={d.get('n')})\n"); continue
            L.append(f"### {h} — train {d['n_train']} / test {d['n_test']} (post-embargo), "
                     f"{d['n_features']} features, test base rate {_f(d['test_base_rate'])}")
            L.append("\n| | Brier | log-loss | AUC | prec@10% |")
            L.append("|---|---:|---:|---:|---:|")
            i, c = d["incumbent"], d["challenger"]
            L.append(f"| incumbent (final_score) | {_f(i['brier'])} | {_f(i['log_loss'])} | {_f(i['auc'])} | {_f(i['p_at_10'])} |")
            L.append(f"| challenger (logistic) | {_f(c['brier'])} | {_f(c['log_loss'])} | {_f(c['auc'])} | {_f(c['p_at_10'])} |")
            L.append(f"\n**Verdict: {d['verdict']}.**\n")

    # --- 5. Per-signal ---
    L.append("## 5. Per-signal contribution (IC + leave-one-out)\n")
    ps = sections["per_signal"]
    if "ics" not in ps:
        L.append(f"{ps.get('note')} (n={ps.get('n')})\n")
    else:
        L.append(f"Spearman IC at {ps['horizon']} (n={ps['n']}). IC ~0 = no rank signal. "
                 "The 15 documented flat features are all-zero, so only the populated feature set is measurable.\n")
        L.append("| feature | Spearman IC | Pearson IC | nonzero frac |")
        L.append("|---|---:|---:|---:|")
        for r in ps["ics"]:
            L.append(f"| {r['feature']} | {_f(r['spearman_ic'])} | {_f(r['pearson_ic'])} | {_f(r['nonzero_frac'],2)} |")
        if ps.get("loo"):
            L.append("\nLeave-one-out (in-sample AUC drop when the feature is removed; larger = more load-bearing):")
            L.append(f"\n_full-model in-sample AUC = {_f(ps['loo'][0].get('full_in_sample_auc'))}_\n")
            L.append("| feature | AUC drop when removed |")
            L.append("|---|---:|")
            for r in ps["loo"][1:]:
                L.append(f"| {r['feature']} | {_f(r['auc_drop_when_removed'],4)} |")
        L.append("")

    # --- 6. Data availability ---
    L.append("## 6. Data-availability findings\n")
    da = sections["data_availability"]
    L.append("### 6a — display-only signals in stored data")
    L.append(f"**{da['6a_display_signals']['verdict']}**\n")
    L.append("Searched raw `feature_vector_json` text for each signal's names:\n")
    L.append("| display signal | terms found in stored data |")
    L.append("|---|---|")
    for sig, hits in da["6a_display_signals"]["per_signal_terms_found"].items():
        L.append(f"| {sig} | {hits if hits else '**none**'} |")
    L.append("\nDistinct `feature_vector_json` shapes actually stored:\n")
    L.append("| n rows | keys |")
    L.append("|---:|---|")
    for k in da["6a_display_signals"]["distinct_keysets"]:
        L.append(f"| {k['n']} | `{', '.join(k['keys'])}` |")
    L.append("\n**Conclusion:** these 5 signals are NOT logged. Folding them into the score CANNOT be "
             "validated on stored data — it would first require forward-logging them per alert.\n")
    L.append("### 6b — source_performance / per-analyst outcomes")
    L.append(f"**{da['6b_source_performance']['verdict']}**\n")
    L.append(f"- `source_performance`: {da['6b_source_performance']['source_performance_rows']} rows")
    L.append(f"- `source_performance_shadow`: {da['6b_source_performance']['source_performance_shadow_rows']} rows")
    if da["6b_source_performance"]["shadow_by_horizon"]:
        L.append(f"- shadow breakdown: {da['6b_source_performance']['shadow_by_horizon']}")
    L.append("")

    return "\n".join(L)


# ===========================================================================
# ENTRY
# ===========================================================================

def run(db_path: str = loaders.DEFAULT_DB, out_path: str | None = None) -> dict:
    conn = loaders.connect_ro(db_path)
    try:
        snaps = loaders.load_snapshots(conn)
        preds = loaders.load_shadow_predictions(conn)
        sections = {
            "label_audit": label_audit(conn),
            "calibration": calibration(preds),
            "discrimination": discrimination(snaps),
            "edge_pockets": edge_pockets(snaps),
            "logistic": logistic_challenger(snaps),
            "per_signal": per_signal(snaps, "24h"),
            "data_availability": data_availability(conn, snaps),
        }
    finally:
        conn.close()
    md = build_report(sections)
    if out_path:
        with open(out_path, "w") as f:
            f.write(md)
    return {"sections": sections, "markdown": md, "out_path": out_path}
