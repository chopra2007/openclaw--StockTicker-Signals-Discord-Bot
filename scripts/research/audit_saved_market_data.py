#!/usr/bin/env python3
"""Write the M9.1EP read-only saved-market-data qualification record."""

import json
from hashlib import sha256
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from consensus_engine.saved_market_data_audit import audit_saved_market_data  # noqa: E402


FILES = (
    ROOT / ".omc/research/professional-day-trader-methods/bars-equs-allmin.parquet",
    ROOT / ".omc/research/professional-day-trader-methods/bars-pillar-allmin.parquet",
)
OUTPUT = ROOT / "trade_alerts_build_docs/M9_1EP_SAVED_DATA_QUALIFICATION.json"
CURRENT_STATE = ROOT / ".omc/research/immediate-profitable-share-feature/current-state.json"
DATA_CAPABILITY = ROOT / ".omc/research/professional-day-trader-methods/data-capability.json"
EXTRACTORS = (
    ROOT / "scripts/research/ipsf_extract_full_session.py",
    ROOT / "scripts/research/pdtm_extract_all_minutes.py",
)


def _sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def main() -> None:
    result = audit_saved_market_data(FILES)
    current_state = json.loads(CURRENT_STATE.read_text())
    capability = json.loads(DATA_CAPABILITY.read_text())
    result["provenance"] = {
        "prior_inventory": {
            "path": str(CURRENT_STATE.relative_to(ROOT)),
            "sha256": _sha256(CURRENT_STATE),
            "raw_files": current_state["raw_files"],
        },
        "prior_capability_record": {
            "path": str(DATA_CAPABILITY.relative_to(ROOT)),
            "sha256": _sha256(DATA_CAPABILITY),
            "minute_feeds": capability["minute_feeds"],
        },
        "extraction_scripts": [
            {"path": str(path.relative_to(ROOT)), "sha256": _sha256(path)}
            for path in EXTRACTORS
        ],
        "boundary": (
            "These bindings identify the saved derivatives and their recorded raw sources. "
            "They do not independently prove original availability, corrections, finality, "
            "point-in-time membership, or adjustment handling."
        ),
    }
    OUTPUT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(OUTPUT.relative_to(ROOT))


if __name__ == "__main__":
    main()
