#!/usr/bin/env python3
"""Build and cache every context field for both feeds (TODO #106).

Writes into .omc/research/professional-day-trader-methods/:
  sessions-<feed>.parquet   one row per symbol-date, session facts + prior
                            session's location (POC, value area, high, low)
  ctx-<feed>.npz            minute matrices: ret, mkt, sector, cumvol, relvol

No profit number is computed here.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pdtm_context as C  # noqa: E402
from pdtm_common import RES_DIR, build_panel, session_frame  # noqa: E402


def main(feed):
    p = build_panel(feed)
    sess = session_frame(p)
    print(f"{feed}: {len(sess)} sessions", flush=True)

    prof = C.session_profiles(p, sess)
    sess = pd.concat([sess.reset_index(drop=True), prof.reset_index(drop=True)], axis=1)
    print(f"{feed}: profiles done, poc finite {np.isfinite(sess.poc).mean():.3f}", flush=True)

    g = sess.groupby("symbol", sort=False)
    for src in ("poc", "vah", "val"):
        sess["prev_" + src] = g[src].shift(1)

    ret, mkt, sec, peers = C.composites(p, sess)
    print(f"{feed}: composites done", flush=True)
    cv = C.cum_volume(p)
    rv = C.relative_volume(p, sess, cv)
    print(f"{feed}: relative volume done", flush=True)

    sess.to_parquet(RES_DIR / f"sessions-{feed}.parquet", index=False)
    np.savez(RES_DIR / f"ctx-{feed}.npz", ret=ret, mkt=mkt, sec=sec,
             peers=peers, cumvol=cv, relvol=rv)
    print(f"{feed}: written", flush=True)


if __name__ == "__main__":
    for feed in (sys.argv[1:] or ["equs", "pillar"]):
        main(feed)
