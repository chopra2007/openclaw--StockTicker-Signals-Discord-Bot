"""Read-only evaluation & calibration module for the consensus signal bot.

This package MEASURES stored outcome data. It never writes to the DB, never
touches a live config flag, and never imports the live scoring/calibration
path. It opens `consensus.db` read-only (SQLite URI mode=ro).

Entry point: `python -m consensus_engine.eval` — produces a markdown report
and prints a summary. See `report.py` for the section orchestration and
`metrics.py` for the (fully unit-tested) math.
"""

from consensus_engine.eval import metrics  # noqa: F401
