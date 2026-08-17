"""Plain-English display wording for cached NFCI readings."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any


def _date_value(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


def nfci_state(
    row: dict | None,
    as_of: Any,
    max_age_days: int,
    loose_cutoff: float,
    tight_cutoff: float,
) -> str | None:
    """Return ``loose``, ``normal``, or ``tight`` for a usable stored row."""
    if not row or row.get("nfci_index") is None:
        return None
    observation_date = _date_value(row.get("nfci_observation_date"))
    current_date = _date_value(as_of)
    if observation_date is None or current_date is None:
        return None
    age_days = (current_date - observation_date).days
    if age_days < 0 or age_days > int(max_age_days):
        return None
    value = float(row["nfci_index"])
    if value <= float(loose_cutoff):
        return "loose"
    if value >= float(tight_cutoff):
        return "tight"
    return "normal"


def render_nfci_note(
    row: dict | None,
    as_of: Any,
    max_age_days: int,
    loose_cutoff: float,
    tight_cutoff: float,
    *,
    unusual_only: bool,
) -> str | None:
    """Render one cached NFCI line, optionally only for unusual readings."""
    state = nfci_state(
        row, as_of, max_age_days, loose_cutoff, tight_cutoff
    )
    if state is None or (unusual_only and state == "normal"):
        return None
    meaning = {
        "loose": "financial conditions unusually loose: borrowing is easier than normal",
        "normal": "financial conditions normal: borrowing conditions are near their long-run range",
        "tight": "financial conditions unusually tight: borrowing is harder than normal",
    }[state]
    value = float(row["nfci_index"])
    observation_date = row["nfci_observation_date"]
    return f"NFCI {value:+.3f} — {meaning}. Reading for {observation_date}."
