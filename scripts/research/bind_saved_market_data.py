#!/usr/bin/env python3
"""Publish the M9.1EQ saved-bar input matrix from the M9.1EP audit."""

from __future__ import annotations

import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from consensus_engine.saved_market_data_binding import bind_saved_bar_inputs


SOURCE = ROOT / "trade_alerts_build_docs/M9_1EP_SAVED_DATA_QUALIFICATION.json"
OUTPUT = ROOT / "trade_alerts_build_docs/M9_1EQ_AUDITED_INPUT_BINDING.json"


def main() -> None:
    record = bind_saved_bar_inputs(json.loads(SOURCE.read_text()))
    OUTPUT.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
