"""Unified display-scale helper (#46).

The bot shows the user many numbers on many different native scales, so a reader
can't tell at a glance whether a reading is high or low. This module is the
single, display-only place that maps the two genuinely-confusing native
readings onto one human scale: 0-100, where higher always = more of the named
quantity (more market stress, more disagreement).

Scope is deliberately narrow. It does NOT touch scoring math, thresholds, or
stored values, and it is NOT applied to literal quantities (prices, strikes,
counts, % moves, ratios) — those are already self-explanatory in their own
units. The additive headline "Score" family is governed by the separate #I4
reconciliation, not here.

Pure stdlib leaf: imports nothing from consensus_engine so it can be imported
from any alert builder without a circular import.
"""


def regime_stress(z_score: float) -> int:
    """Map the regime EMA volatility z-score onto a 0-100 "market stress"
    reading where higher = more stress.

    The native z-score is unreadable to a human (calm is a *negative* number,
    panic is +1.5). Anchored at the engine's own label cutoffs so the number
    tracks the label: calm cutoff z=-1.0 -> 20, elevated cutoff z=0.5 -> 50,
    panic cutoff z=1.5 -> 85. Clamped to [0, 100].
    """
    if z_score <= 0.5:
        stress = 20.0 * z_score + 40.0           # line through (-1.0, 20) and (0.5, 50)
    else:
        stress = 50.0 + 35.0 * (z_score - 0.5)   # line through (0.5, 50) and (1.5, 85)
    return int(round(max(0.0, min(100.0, stress))))


_REGIME_EMOJI = {
    "calm": "🟢",
    "normal": "🟢",
    "elevated": "🟡",
    "panic": "🔴",
}


def regime_emoji(label: str) -> str:
    """Pick the regime dot from the engine's LABEL, never from the stress
    magnitude, so the colored dot and the word in the line can never disagree.
    Unknown label -> neutral white dot.
    """
    return _REGIME_EMOJI.get(label, "⚪")


def disagreement(contradiction_index: float) -> int:
    """Map the 0.0-1.0 contradiction index onto a 0-100 "disagreement" reading
    where higher = more sources disagree. Clamped to [0, 100].
    """
    return int(round(max(0.0, min(100.0, contradiction_index * 100.0))))
