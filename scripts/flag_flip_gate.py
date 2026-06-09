#!/usr/bin/env python3
"""Item F (deep-dive-2026-06-08): flag-flip-needs-proof gate.

Detect an OFF->ON flip of any boolean flag in config/consensus.yaml between origin/master
and HEAD via a YAML-PARSE diff (NOT grep — grep can't name nested flags, so every nested
`enabled: true` collapsed to one leaf and a single evidence file blanket-satisfied all flips,
letting the nested vision flag the gate exists to catch slip through).

For each flag that went False -> True, require go-live evidence:
  .claude/go-live-evidence/<dotted_path_with_underscores>.md exists, OR the dotted path is
  referenced in an unpushed commit body. Otherwise BLOCK the push (exit 1).

If wolf.vision.enabled is among the flips, additionally require the vision smoke test to pass
(run separately by session_close.sh through item A's real retry path).

Exit 0 = clear to push. Exit 1 = blocked. Exit 2 = internal error (fail-open with a warning;
don't block a push on a parser bug).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

try:
    import yaml
except Exception as e:  # pragma: no cover
    print(f"flag_flip_gate: yaml import failed ({e}) — skipping gate", file=sys.stderr)
    sys.exit(2)

REPO = Path(__file__).resolve().parent.parent
CONFIG = "config/consensus.yaml"
EVIDENCE_DIR = REPO / ".claude" / "go-live-evidence"


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True).stdout


def _load_yaml_blob(ref: str) -> dict:
    blob = _git("show", f"{ref}:{CONFIG}")
    if not blob.strip():
        return {}
    try:
        return yaml.safe_load(blob) or {}
    except Exception:
        return {}


def _flatten_bools(obj, prefix: str = "") -> dict[str, bool]:
    """Flatten a nested dict to {dotted.path: bool} for boolean leaves only."""
    out: dict[str, bool] = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = f"{prefix}.{k}" if prefix else str(k)
            if isinstance(v, bool):
                out[key] = v
            elif isinstance(v, dict):
                out.update(_flatten_bools(v, key))
    return out


def main() -> int:
    # Refresh the remote ref so the diff set isn't stale (L1).
    _git("fetch", "origin", "master")

    base = _flatten_bools(_load_yaml_blob("origin/master"))
    head = _flatten_bools(_load_yaml_blob("HEAD"))

    flips = [k for k, v in head.items() if v is True and base.get(k) is False]
    if not flips:
        print("flag_flip_gate: no OFF->ON flag flips — clear")
        return 0

    commit_bodies = _git("log", "origin/master..HEAD", "--format=%B")
    blocked: list[str] = []
    for dotted in flips:
        ev_name = dotted.replace(".", "_") + ".md"
        ev_path = EVIDENCE_DIR / ev_name
        referenced = ev_name in commit_bodies or f".claude/go-live-evidence/{ev_name}" in commit_bodies
        if ev_path.exists() or referenced:
            print(f"flag_flip_gate: '{dotted}' flipped ON — evidence OK ({ev_name})")
        else:
            blocked.append(dotted)
            print(f"flag_flip_gate: BLOCKED '{dotted}' flipped OFF->ON with no go-live evidence "
                  f"(expected .claude/go-live-evidence/{ev_name})", file=sys.stderr)

    if blocked:
        print(f"flag_flip_gate: PUSH BLOCKED — {len(blocked)} flag(s) flipped ON without evidence: "
              f"{', '.join(blocked)}", file=sys.stderr)
        return 1

    # Signal to the caller whether a vision flip needs the smoke test.
    if "wolf.vision.enabled" in flips:
        print("VISION_FLIP")  # session_close.sh greps for this to run the smoke test
    return 0


if __name__ == "__main__":
    sys.exit(main())
