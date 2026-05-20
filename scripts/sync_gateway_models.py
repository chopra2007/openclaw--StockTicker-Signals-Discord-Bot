#!/usr/bin/env python3
"""Sync the OpenClaw agent model chain from consensus.yaml.

The ``!ask`` / ``@-mention`` Discord handlers shell out to ``openclaw agent
--local``, whose model failover is driven by ``agents.defaults.model`` in
openclaw.json — a ``{"primary": ..., "fallbacks": [...]}`` object that
openclaw's ``runWithModelFallback`` engine walks in order. (openclaw drops a
bare ``params.models`` array, so that is NOT a usable fallback mechanism.)

consensus.yaml owns this chain as ``llm.agent_model`` +
``llm.agent_fallback_models`` (bare ids; the ``openrouter/`` prefix is the
gateway's model-id convention and is added here). This script mirrors it
into openclaw.json via ``openclaw config patch`` — the package's official
write path (schema-validates, creates an automatic ``.bak``).

NOTE: this is a DIFFERENT chain from ``llm.model`` / ``llm.fallback_models``
(the Python ``call_with_fallback`` path used by ``!all``). The agent chain
must avoid models that overflow on the ~6-8K-token agent system prompt or
reject ``tool_choice`` — so the two chains are curated separately.

The openclaw npm package may overwrite openclaw.json on version updates;
re-run this script after any ``omc update`` / ``npm upgrade openclaw``.
``consensus_engine.health`` independently probes the chain and posts a
Discord alert if openclaw.json drifts away from consensus.yaml.

Run as the ``openclaw`` user so the patched openclaw.json keeps its
``openclaw:openclaw`` ownership (``openclaw config patch`` writes the file
as the calling user).

Usage:
    python3 scripts/sync_gateway_models.py            # write if drift
    python3 scripts/sync_gateway_models.py --check    # exit 1 on drift
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
GATEWAY_PATH = "agents.defaults.model"


def _read_chain() -> tuple[str, list[str]]:
    """Return ``(primary, fallbacks)`` for the agent chain, ``openrouter/``-prefixed."""
    cfg = yaml.safe_load(CONSENSUS_YAML.read_text())
    llm = cfg.get("llm", {})
    primary = llm.get("agent_model")
    fallbacks = llm.get("agent_fallback_models") or []
    if not primary:
        sys.exit(f"error: llm.agent_model missing from {CONSENSUS_YAML}")
    chain: list[str] = []
    seen: set[str] = set()
    for m in [primary, *fallbacks]:
        if m and m not in seen:
            chain.append(f"openrouter/{m}")
            seen.add(m)
    return chain[0], chain[1:]


def _read_gateway_chain() -> tuple[str, list[str]]:
    """Resolve the current openclaw.json agent chain via the openclaw CLI."""
    result = subprocess.run(
        ["openclaw", "config", "get", GATEWAY_PATH],
        capture_output=True, text=True, check=True,
    )
    data = json.loads(result.stdout) or {}
    if isinstance(data, str):  # `model` may be a bare string instead of an object
        return data, []
    return data.get("primary", ""), list(data.get("fallbacks") or [])


def _write_gateway_chain(primary: str, fallbacks: list[str]) -> None:
    """Patch ``agents.defaults.model`` via the openclaw CLI."""
    body = {
        "agents": {"defaults": {"model": {
            "primary": primary,
            "fallbacks": fallbacks,
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
                    help="diff-only mode; exit 1 if openclaw.json is out of sync")
    args = ap.parse_args()

    primary, fallbacks = _read_chain()
    try:
        cur_primary, cur_fallbacks = _read_gateway_chain()
    except subprocess.CalledProcessError as exc:
        sys.exit(f"error: failed to read gateway chain: {exc.stderr or exc}")

    if (primary, fallbacks) == (cur_primary, cur_fallbacks):
        print(f"in sync: {GATEWAY_PATH}\n  primary:   {primary}\n  fallbacks: {fallbacks}")
        return 0

    if args.check:
        print(f"DRIFT at {GATEWAY_PATH}", file=sys.stderr)
        print(f"  consensus: {[primary, *fallbacks]}", file=sys.stderr)
        print(f"  gateway:   {[cur_primary, *cur_fallbacks]}", file=sys.stderr)
        return 1

    _write_gateway_chain(primary, fallbacks)
    print(f"wrote {GATEWAY_PATH}\n  primary:   {primary}\n  fallbacks: {fallbacks}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
