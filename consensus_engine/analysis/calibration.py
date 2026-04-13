"""Confidence Calibration — maps raw engine scores to calibrated probabilities.

Trains isotonic regression on rolling decision_snapshots with price-move outcomes.
Falls back to Platt scaling (logistic regression) when isotonic fails.
Returns identity mapping when fewer than MIN_SAMPLES labeled samples exist.

Public API
----------
    calibrate(raw_confidence, horizon="1h") -> float
        Synchronous. Returns calibrated probability in [0, 1].
        Identity fallback (score/100) when no model is available.

    async retrain(horizon="1h") -> int
        Async. Retrains on labeled decision_snapshots. Returns sample count used.

    async retrain_all() -> dict[str, int]
        Retrain both "1h" and "24h" horizons. Returns {horizon: sample_count}.

Walk-forward usage
------------------
    Run `await retrain_all()` periodically (e.g., nightly) to keep the
    calibration model up to date as new outcome data accumulates.
"""

from __future__ import annotations

import logging
import os
import pickle
import time
from pathlib import Path
from typing import Optional

from consensus_engine import db

log = logging.getLogger("consensus_engine.analysis.calibration")

MIN_SAMPLES = 50
MODEL_PATH = Path(".omc/state/calibration_model.pkl")

# In-memory cache: {horizon: _IsotonicWrapper | _PlattWrapper}
_models: dict[str, object] = {}
_loaded_at: float = 0.0
_MODEL_TTL_SEC = 3600  # reload from disk at most once per hour


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def calibrate(raw_confidence: float, horizon: str = "1h") -> float:
    """Map raw engine score to calibrated probability.

    Args:
        raw_confidence: Raw score (0–100 scale from the engine).
        horizon: "1h" or "24h".

    Returns:
        Calibrated probability in [0, 1]. Returns score/100 (identity) when no
        trained model is available or fewer than MIN_SAMPLES were used to train.
    """
    _ensure_loaded()
    model = _models.get(horizon)
    if model is None:
        return _identity(raw_confidence)
    try:
        result = float(model.predict([[raw_confidence]])[0])
        return min(max(result, 0.0), 1.0)
    except Exception as e:
        log.debug("calibration: predict error for horizon=%s: %s", horizon, e)
        return _identity(raw_confidence)


async def retrain(horizon: str = "1h") -> int:
    """Retrain calibration model for one horizon.

    Queries decision_snapshots for labeled rows (rows with non-NULL price
    outcomes), fits isotonic regression (Platt scaling fallback), and
    persists the model to MODEL_PATH.

    Args:
        horizon: "1h" or "24h" — selects which outcome column to use as label.

    Returns:
        Number of samples used. 0 if the file failed to load.
        Returns sample count < MIN_SAMPLES when skipped (model unchanged).
    """
    price_col = "outcome_price_1h" if horizon == "1h" else "outcome_price_24h"
    conn = await db.get_db()
    cursor = await conn.execute(
        f"""SELECT final_score, outcome_price_at_alert, {price_col}
            FROM decision_snapshots
            WHERE outcome_price_at_alert IS NOT NULL
              AND outcome_price_at_alert > 0
              AND {price_col} IS NOT NULL
            ORDER BY recorded_at DESC
            LIMIT 2000"""
    )
    rows = await cursor.fetchall()
    n = len(rows)

    if n < MIN_SAMPLES:
        log.info(
            "calibration: only %d labeled samples for horizon=%s (need %d) — identity fallback retained",
            n, horizon, MIN_SAMPLES,
        )
        return n

    X, y = [], []
    for r in rows:
        score = float(r["final_score"])
        entry = float(r["outcome_price_at_alert"])
        exit_p = float(r[price_col])
        X.append([score])
        y.append(1 if exit_p > entry else 0)

    model = _fit_isotonic(X, y) or _fit_platt(X, y)
    if model is None:
        log.warning("calibration: both isotonic and Platt fitting failed for horizon=%s", horizon)
        return n

    _models[horizon] = model
    _save_models()
    log.info("calibration: retrained horizon=%s on %d samples (model saved)", horizon, n)
    return n


async def retrain_all() -> dict[str, int]:
    """Retrain both 1h and 24h horizons. Returns {horizon: sample_count}."""
    results: dict[str, int] = {}
    for h in ("1h", "24h"):
        results[h] = await retrain(h)
    return results


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _identity(raw_confidence: float) -> float:
    """Normalise score to [0, 1] — used as fallback when no model is available."""
    return min(max(raw_confidence / 100.0, 0.0), 1.0)


def _ensure_loaded() -> None:
    """Lazy-load models from disk into _models if cache is stale."""
    global _models, _loaded_at
    now = time.time()
    if _models and (now - _loaded_at) < _MODEL_TTL_SEC:
        return
    _models = _load_models()
    _loaded_at = now


def _load_models() -> dict[str, object]:
    """Load models dict from pickle. Returns {} on any error."""
    path = MODEL_PATH
    if not path.exists():
        return {}
    try:
        with open(path, "rb") as f:
            data = pickle.load(f)
        if isinstance(data, dict):
            log.debug("calibration: loaded models for horizons: %s", list(data.keys()))
            return data
    except Exception as e:
        log.warning("calibration: failed to load model from %s: %s", path, e)
    return {}


def _save_models() -> None:
    """Atomically persist _models dict to MODEL_PATH."""
    path = MODEL_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    try:
        with open(tmp, "wb") as f:
            pickle.dump(_models, f)
        os.replace(tmp, path)
        log.debug("calibration: models saved to %s", path)
    except Exception as e:
        log.warning("calibration: failed to save models: %s", e)


def _fit_isotonic(X: list, y: list) -> Optional[object]:
    """Fit isotonic regression. Returns _IsotonicWrapper or None on error."""
    try:
        from sklearn.isotonic import IsotonicRegression
        import numpy as np
        X_flat = np.array([x[0] for x in X])
        y_arr = np.array(y, dtype=float)
        model = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
        model.fit(X_flat, y_arr)
        return _IsotonicWrapper(model)
    except Exception as e:
        log.debug("calibration: isotonic fit failed: %s", e)
        return None


def _fit_platt(X: list, y: list) -> Optional[object]:
    """Fit Platt scaling (logistic regression). Returns _PlattWrapper or None."""
    try:
        from sklearn.linear_model import LogisticRegression
        import numpy as np
        model = LogisticRegression(C=1.0, max_iter=200, solver="lbfgs")
        model.fit(np.array(X), np.array(y))
        return _PlattWrapper(model)
    except Exception as e:
        log.debug("calibration: Platt fit failed: %s", e)
        return None


class _IsotonicWrapper:
    """Wraps IsotonicRegression to accept 2D [[x]] input."""

    def __init__(self, model):
        self._model = model

    def predict(self, X) -> list:
        import numpy as np
        x_flat = np.array([row[0] for row in X])
        return list(self._model.predict(x_flat))


class _PlattWrapper:
    """Wraps LogisticRegression, returns P(label=1) from predict_proba."""

    def __init__(self, model):
        self._model = model

    def predict(self, X) -> list:
        import numpy as np
        proba = self._model.predict_proba(np.array(X))
        return list(proba[:, 1])
