"""Conviction model for the Wolf macro-brain (TODO #20, phase 1).

Pure functions, no I/O — fully unit-testable. Given already-validated thesis
fields, this computes:

  - a normalized timeframe ladder for one email's thesis (text + chart-coarse),
  - a 0–100 conviction score (DESCRIPTIVE display only — never triggers an alert),
  - a trajectory label (building|stable|cooling|turned) vs prior entries,
  - whether the change vs the prior entry is a MATERIAL STRUCTURAL escalation
    (the only thing that ever fires a `conviction_update`).

R5: triggers + trajectory are driven by STRUCTURAL change only (stage / timeframe
union / position-intent / direction flip). The score's mention-frequency term is a
DISTINCT-DAY count and is excluded from any trigger/trajectory decision.
"""
from __future__ import annotations

import re

# Fixed timeframe ladder (ascending). Index = rung order.
TF_LADDER = ["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "daily", "3d", "weekly"]
_TF_INDEX = {tf: i for i, tf in enumerate(TF_LADDER)}
# Rungs that count as "longer" (a short-only set gaining one of these is material).
_LONG_RUNGS = {"daily", "3d", "weekly"}

STAGE_ORDER = ["forming", "diverging", "imminent", "acting"]
_STAGE_RANK = {s: i for i, s in enumerate(STAGE_ORDER)}
_STAGE_SCORE = {"forming": 15, "diverging": 30, "imminent": 45, "acting": 60}

INTENT_ORDER = ["none", "watching", "looking", "started", "adding"]
_INTENT_RANK = {s: i for i, s in enumerate(INTENT_ORDER)}
_INTENT_SCORE = {"none": 0, "watching": 2, "looking": 4, "started": 8, "adding": 10}

TRAJECTORY_THRESHOLD = 8  # |conv delta| below this is "stable" absent a structural change


def stage_rank(stage: str) -> int:
    return _STAGE_RANK.get(stage, 0)


def intent_rank(intent: str) -> int:
    return _INTENT_RANK.get(intent, 0)


def normalize_timeframes(raw_strings: list[str], chart_coarse: list[str]) -> list[str]:
    """Map raw author timeframe strings + chart coarse labels to the ladder.

    Text rules: "30-minute"/"30m"/"30 min" → 30m; "1M"/"1-minute"/"1 min" → 1m
    (minute, NOT month); "3D" → 3d; "2H" → 2h; "daily"/"weekly" kept.
    Chart coarse: daily/weekly kept; `intraday` dropped (too coarse); unknown dropped.
    Result is deduped and sorted by ladder order.
    """
    rungs: set[str] = set()
    for raw in (raw_strings or []):
        rung = _normalize_one(str(raw))
        if rung:
            rungs.add(rung)
    for c in (chart_coarse or []):
        cl = str(c).strip().lower()
        if cl in ("daily", "weekly"):
            rungs.add(cl)
        # intraday / unknown → dropped
    return sorted(rungs, key=lambda r: _TF_INDEX[r])


def _normalize_one(raw: str) -> str | None:
    s = raw.strip().lower()
    if not s:
        return None
    if s in ("daily", "weekly"):
        return s
    # number + unit (minute/hour/day). Tolerate "30-minute", "30 min", "30m", "2h", "3d".
    m = re.match(r"^(\d+)\s*-?\s*(m|min|minute|minutes|h|hr|hour|hours|d|day|days)\b", s)
    if not m:
        # bare like "1m" "2h" "3d" without trailing word boundary token
        m = re.match(r"^(\d+)\s*-?\s*(m|h|d)$", s)
    if not m:
        return None
    n = m.group(1)
    unit = m.group(2)[0]  # first char: m/h/d
    candidate = f"{n}{unit}"
    return candidate if candidate in _TF_INDEX else None


def tf_width(tf: list[str]) -> int:
    """Distinct ladder rungs in this timeframe set."""
    return len({t for t in (tf or []) if t in _TF_INDEX})


def tf_widened(old_tf: list[str], new_tf: list[str]) -> bool:
    """R5: material widening = +2 or more rungs in the union, OR a short-only set
    gained a longer (daily/3d/weekly) rung."""
    old = {t for t in (old_tf or []) if t in _TF_INDEX}
    new = {t for t in (new_tf or []) if t in _TF_INDEX}
    union = old | new
    if len(union) - len(old) >= 2:
        return True
    gained = new - old
    if gained & _LONG_RUNGS and not (old & _LONG_RUNGS):
        return True
    return False


def conviction_score(
    stage: str,
    tf: list[str],
    intent: str,
    distinct_day_count: int,
    levels: list[dict],
) -> int:
    """0–100 weighted sum of validated fields (§3). DESCRIPTIVE display only.

    Terms: stage rank (0–60) + timeframe width capped 5 ×6 (0–30) + position intent
    (0–10) + mention frequency = distinct-day count capped 4 ×2.5 (0–10) + level
    specificity (0–10). Clamped to 100.
    """
    score = 0.0
    score += _STAGE_SCORE.get(stage, 0)
    score += min(tf_width(tf), 5) * 6
    score += _INTENT_SCORE.get(intent, 0)
    score += min(max(int(distinct_day_count), 0), 4) * 2.5
    if levels:
        score += 5
        if _has_trigger_level(levels):
            score += 5
    return int(max(0, min(100, round(score))))


def _has_trigger_level(levels: list[dict]) -> bool:
    for lv in levels or []:
        if lv.get("role") == "target":
            return True
        label = str(lv.get("label") or "").lower()
        if "gap" in label or "trigger" in label:
            return True
    return False


def trajectory(
    this_conv: int,
    prior_convs: list[int],
    stage_up: bool,
    stage_down: bool,
    intent_up: bool,
    intent_down: bool,
    flipped: bool,
    threshold: int = TRAJECTORY_THRESHOLD,
) -> str:
    """building|stable|cooling|turned vs the mean of up-to-3 prior entries (§3).

    Structural change overrides the score delta. A flip is always 'turned'.
    First entry of a thread (no priors) is 'building' by definition.
    `threshold` is the score-delta band for 'stable' (wired from config).
    """
    if flipped:
        return "turned"
    if stage_up or intent_up:
        return "building"
    if stage_down or intent_down:
        return "cooling"
    if not prior_convs:
        return "building"
    recent = prior_convs[-3:]
    mean_prior = sum(recent) / len(recent)
    delta = this_conv - mean_prior
    if delta >= threshold:
        return "building"
    if delta <= -threshold:
        return "cooling"
    return "stable"


def is_material_escalation(
    stage_up: bool,
    stage_down: bool,
    tf_widened: bool,
    intent_up: bool,
    flipped: bool,
) -> bool:
    """R5: a conviction_update fires iff a STRUCTURAL change occurred — stage up,
    timeframe union widened materially, position intent strengthened a step+, or a
    direction flip. Score/cadence NEVER triggers. A downgrade is not an escalation.
    """
    return bool(stage_up or tf_widened or intent_up or flipped)
