#!/usr/bin/env python3
"""Sync the OpenClaw gateway agent model chain from consensus.yaml.

consensus.yaml owns ``llm.model`` + ``llm.fallback_models``. The gateway runs
out of /root/.openclaw/openclaw.json, which holds the same chain at
``agents.defaults.models.openrouter/auto.params.models[]`` (with an
``openrouter/`` prefix per the gateway's model-id convention).

This script reads consensus.yaml and writes the array via
``openclaw config patch``, which uses the package's official write path
(schema-validates, creates an automatic ``.bak`` snapshot).

The openclaw npm package may overwrite ``openclaw.json`` on version updates;
re-run this script after any ``omc update`` / ``npm upgrade openclaw``.
``consensus_engine.health.run_chain_check`` independently probes the chain
once per day and posts a Discord alert if the gateway array drifts away from
consensus.yaml.

Usage:
    sudo python3 scripts/sync_gateway_models.py            # write if drift
    python3 scripts/sync_gateway_models.py --check         # exit 1 on drift
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
CONSENSUS_YAML = REPO_ROOT / "config" / "consensus.yaml"
GATEWAY_PATH = "agents.defaults.models.openrouter/auto.params.models"


def _read_chain() -> list[str]:
    cfg = yaml.safe_load(CONSENSUS_YAML.read_text())
    llm = cfg.get("llm", {})
    primary = llm.get("model")
    fallbacks = llm.get("fallback_models") or []
    if not primary:
        sys.exit(f"error: llm.model missing from {CONSENSUS_YAML}")
    chain: list[str] = []
    seen: set[str] = set()
    for m in [primary, *fallbacks]:
        if m and m not in seen:
            chain.append(m)
            seen.add(m)
    return [f"openrouter/{m}" for m in chain]


def _read_gateway_chain() -> list[str]:
    """Resolve the current gateway chain via the openclaw CLI."""
    result = subprocess.run(
        ["openclaw", "config", "get", GATEWAY_PATH],
        capture_output=True, text=True, check=True,
    )
    return json.loads(result.stdout)


def _write_gateway_chain(chain: list[str]) -> None:
    """Patch the gateway chain via the openclaw CLI."""
    body = {
        "agents": {"defaults": {"models": {
            "openrouter/auto": {"params": {"models": chain}},
        }}},
    }
    subprocess.run(
        ["openclaw", "config", "patch", "--stdin",
         "--replace-path", GATEWAY_PATH],
        input=json.dumps(body), capture_output=True, text=True, check=True,
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="diff-only mode; exit 1 if the gateway is out of sync")
    args = ap.parse_args()

    expected = _read_chain()
    try:
        current = _read_gateway_chain()
    except subprocess.CalledProcessError as exc:
        sys.exit(f"error: failed to read gateway chain: {exc.stderr or exc}")

    if expected == current:
        print(f"in sync: {GATEWAY_PATH}\n  chain: {expected}")
        return 0

    if args.check:
        print(f"DRIFT at {GATEWAY_PATH}", file=sys.stderr)
        print(f"  consensus: {expected}", file=sys.stderr)
        print(f"  gateway:   {current}", file=sys.stderr)
        return 1

    _write_gateway_chain(expected)
    print(f"wrote {GATEWAY_PATH}\n  chain: {expected}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
