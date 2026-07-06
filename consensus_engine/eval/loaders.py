"""Read-only DB access + feature extraction for the eval module.

Opens `consensus.db` in SQLite read-only URI mode so a bug here can never
mutate the live database. Also extracts the numeric feature set that is
ACTUALLY populated in `decision_snapshots.feature_vector_json` (see the
module docstring in report.py for why the documented 15-key vector is not it).
"""

from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass, field

DEFAULT_DB = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "consensus.db",
)


def connect_ro(db_path: str = DEFAULT_DB) -> sqlite3.Connection:
    """Open the DB strictly read-only (mode=ro). Raises if the file is absent."""
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"DB not found: {db_path}")
    uri = f"file:{os.path.abspath(db_path)}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# Row containers
# ---------------------------------------------------------------------------

@dataclass
class Snapshot:
    ticker: str
    decision: str
    final_score: float
    recorded_at: float
    entry: float | None
    px: dict = field(default_factory=dict)      # horizon -> outcome price
    feats: dict = field(default_factory=dict)   # extracted numeric features
    catalyst_type: str | None = None

    def hit(self, horizon: str) -> int | None:
        """1 if price at `horizon` closed above entry, 0 if not, None if the
        outcome is unresolved (NULL) or entry is invalid. NULL is NOT a 0."""
        p = self.px.get(horizon)
        if self.entry is None or self.entry <= 0 or p is None:
            return None
        return 1 if p > self.entry else 0


_HORIZON_COL = {
    "1h": "outcome_price_1h",
    "24h": "outcome_price_24h",
    "5d": "outcome_price_5d",
    "20d": "outcome_price_20d",
}


def extract_features(fv_json: str | None) -> dict:
    """Pull the numeric features that are genuinely present in the newer
    `feature_vector_json` generation (nested-dict verdicts + shadow fields).

    Returns a flat {name: float} dict. Absent nested values become 0.0.
    The documented flat 15-key vector (total_sources, bull_count, has_news…)
    exists in only 22 legacy rows and is all-zero there, so it is ignored;
    this is the real, populated feature set.
    """
    if not fv_json:
        return {}
    try:
        d = json.loads(fv_json)
    except (ValueError, TypeError):
        return {}
    if not isinstance(d, dict):
        return {}

    def num(v, default=0.0):
        try:
            return float(v)
        except (TypeError, ValueError):
            return default

    feats: dict = {}
    if "shadow_score" in d:
        feats["shadow_score"] = num(d.get("shadow_score"))
    if "n_opposing" in d:
        feats["n_opposing"] = num(d.get("n_opposing"))

    reg = d.get("regime_context")
    if isinstance(reg, dict):
        feats["regime_z"] = num(reg.get("z_score"))
        feats["regime_threshold_shift"] = num(reg.get("threshold_shift"))
        feats["regime_cold_start"] = 1.0 if reg.get("cold_start") else 0.0

    con = d.get("consolidation_result")
    if isinstance(con, dict):
        feats["consol_log_odds"] = num(con.get("combined_log_odds"))
        feats["consol_n_clusters"] = num(con.get("effective_n_clusters"))
        feats["consol_consensus_boost"] = num(con.get("consensus_boost"))
        feats["consol_fired"] = 1.0 if con.get("fired") else 0.0

    sec = d.get("sector_verdict")
    if isinstance(sec, dict):
        feats["sector_aligned"] = 1.0 if sec.get("aligned") else 0.0
        feats["sector_change_pct"] = num(sec.get("sector_change_pct"))

    ctr = d.get("contradiction_verdict")
    if isinstance(ctr, dict):
        feats["contra_penalty"] = 1.0 if ctr.get("apply_penalty") else 0.0

    return feats


def load_snapshots(conn: sqlite3.Connection, with_catalyst: bool = True) -> list[Snapshot]:
    """Load every decision_snapshots row with its outcomes, extracted
    features, and (optionally) the joined catalyst_type from alert_history."""
    rows = conn.execute(
        """
        SELECT ds.ticker, ds.decision, ds.final_score, ds.recorded_at,
               ds.outcome_price_at_alert, ds.outcome_price_1h, ds.outcome_price_24h,
               ds.outcome_price_5d, ds.outcome_price_20d, ds.feature_vector_json,
               ah.catalyst_type AS catalyst_type
        FROM decision_snapshots ds
        LEFT JOIN alert_history ah ON ds.alert_id = ah.id
        """
    ).fetchall()
    out: list[Snapshot] = []
    for r in rows:
        ct = r["catalyst_type"]
        ct = (ct or "").strip() or None if with_catalyst else None
        out.append(
            Snapshot(
                ticker=r["ticker"],
                decision=r["decision"],
                final_score=float(r["final_score"]) if r["final_score"] is not None else float("nan"),
                recorded_at=float(r["recorded_at"]) if r["recorded_at"] is not None else 0.0,
                entry=r["outcome_price_at_alert"],
                px={
                    "1h": r["outcome_price_1h"],
                    "24h": r["outcome_price_24h"],
                    "5d": r["outcome_price_5d"],
                    "20d": r["outcome_price_20d"],
                },
                feats=extract_features(r["feature_vector_json"]),
                catalyst_type=ct,
            )
        )
    return out


@dataclass
class ShadowPred:
    alert_id: int
    predicted_prob: float
    horizon: str
    actual_hit: int
    created_at: int


def load_shadow_predictions(conn: sqlite3.Connection) -> list[ShadowPred]:
    """Resolved shadow_predictions only (actual_hit NOT NULL, prob in [0,1])."""
    rows = conn.execute(
        """
        SELECT alert_id, predicted_prob, horizon, actual_hit, created_at
        FROM shadow_predictions
        WHERE actual_hit IS NOT NULL
          AND predicted_prob IS NOT NULL
        ORDER BY created_at ASC
        """
    ).fetchall()
    out: list[ShadowPred] = []
    for r in rows:
        p = float(r["predicted_prob"])
        if p < 0 or p > 1:
            continue
        out.append(
            ShadowPred(
                alert_id=r["alert_id"],
                predicted_prob=p,
                horizon=r["horizon"],
                actual_hit=int(r["actual_hit"]),
                created_at=int(r["created_at"]) if r["created_at"] is not None else 0,
            )
        )
    return out
