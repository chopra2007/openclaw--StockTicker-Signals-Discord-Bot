"""Display-only squeeze-candidate wording for detailed alert cards."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any


def _as_utc(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, (int, float)):
        try:
            dt = datetime.fromtimestamp(float(value), tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    elif isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def is_squeeze_candidate(
    row: dict | None,
    as_of: Any,
    max_age: timedelta | float | int,
    min_days_to_cover: float,
    require_rising: bool,
) -> bool:
    """Return whether one stored FINRA row qualifies for the display tag."""
    if not row:
        return False
    observed = _as_utc(row.get("published_at"))
    now = _as_utc(as_of)
    if observed is None or now is None:
        return False
    max_age_seconds = (
        max_age.total_seconds() if isinstance(max_age, timedelta) else float(max_age)
    )
    age_seconds = (now - observed).total_seconds()
    if age_seconds < -3600 or age_seconds > max_age_seconds:
        return False
    days_to_cover = row.get("days_to_cover")
    if days_to_cover is None or float(days_to_cover) < float(min_days_to_cover):
        return False
    if require_rising:
        current = row.get("short_interest")
        previous = row.get("prev_short_interest")
        if current is None or previous is None or int(current) <= int(previous):
            return False
    return True


_SMALL_NUMBERS = {
    1: "one", 2: "two", 3: "three", 4: "four", 5: "five",
    6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten",
}


def render_squeeze_candidate(
    row: dict | None,
    as_of: Any,
    max_age: timedelta | float | int,
    min_days_to_cover: float,
    require_rising: bool,
) -> str | None:
    """Return the detailed-card line, or ``None`` when the row is ineligible."""
    if not is_squeeze_candidate(
        row, as_of, max_age, min_days_to_cover, require_rising
    ):
        return None

    days_to_cover = float(row["days_to_cover"])
    rounded_days = max(1, int(round(days_to_cover)))
    plain_days = _SMALL_NUMBERS.get(rounded_days, str(rounded_days))
    line = (
        f"🩳 Squeeze candidate — {days_to_cover:.1f} days to cover "
        f"(about {plain_days} normal trading days for short-sellers to buy back)"
    )
    pct_change = row.get("pct_change")
    if pct_change is not None:
        line += f", short interest up {abs(float(pct_change)):.1f}% from the prior report."
    else:
        line += ", short interest is higher than the prior report."
    settlement_date = row.get("settlement_date")
    if settlement_date:
        line += f" Latest report: {settlement_date}."
    return line
