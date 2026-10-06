"""Owner decision 2026-10-06: member throttles are lifted while the site is being tested.

Production turns them off at startup when /etc/member-dashboard/testing-phase exists (see
operations.py). Delete that file (and restart) when the owner says the site is ready to ship.
Money and safety caps ($3/day AI spend, the shared Schwab share, global job capacity) are not
member throttles and stay on.
"""
from pathlib import Path

FLAG = Path('/etc/member-dashboard/testing-phase')
THROTTLES_ON = True


def apply_flag():
    global THROTTLES_ON
    THROTTLES_ON = not FLAG.exists()
