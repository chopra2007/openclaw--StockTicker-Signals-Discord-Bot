import json
import subprocess
import sys
from pathlib import Path


WORKSPACE = Path(__file__).resolve().parents[2]


def test_independent_e2_reproduction_passes_current_sealed_result():
    completed = subprocess.run(
        [sys.executable, "scripts/research/verify_trading_edge_e2_result.py", "--check-only"],
        cwd=WORKSPACE,
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    result = json.loads(completed.stdout)
    assert result == {
        "decision": "PARK",
        "raw_sample_checks": 12,
        "required_confirmation_weeks": 1028,
        "verification_status": "PASS",
    }
