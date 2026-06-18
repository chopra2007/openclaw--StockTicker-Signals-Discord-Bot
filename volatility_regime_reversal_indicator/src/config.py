"""Standalone config loader (reuses the consensus_engine get('dot.path', default) pattern).

Loads config.yaml at the project root once (cached), resolves $ENV references.
Kept independent of the bot so this is a standalone research repo.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_CONFIG_PATH = _PROJECT_ROOT / "config.yaml"
_config: dict | None = None


def _resolve(value: Any) -> Any:
    if isinstance(value, str) and value.startswith("$"):
        return os.environ.get(value[1:], "")
    if isinstance(value, dict):
        return {k: _resolve(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve(v) for v in value]
    return value


def load_config(path: str | Path | None = None) -> dict:
    global _config
    if _config is not None and path is None:
        return _config
    p = Path(path) if path else _CONFIG_PATH
    with open(p, "r") as f:
        raw = yaml.safe_load(f) or {}
    resolved = _resolve(raw)
    if path is None:
        _config = resolved
    return resolved


def get(key: str, default: Any = None) -> Any:
    """Get a config value by dot-separated key path, e.g. get('backtest.primary_horizon', 20)."""
    cfg = load_config()
    cur: Any = cfg
    for k in key.split("."):
        if isinstance(cur, dict) and k in cur:
            cur = cur[k]
        else:
            return default
    return cur


def project_root() -> Path:
    return _PROJECT_ROOT
