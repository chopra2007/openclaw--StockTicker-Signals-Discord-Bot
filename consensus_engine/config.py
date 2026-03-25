"""Central configuration loader with defaults and environment variable support."""

import os
import json
import yaml
from pathlib import Path
from typing import Any

_DEFAULT_CONFIG_PATH = Path(__file__).parent.parent / "config" / "consensus.yaml"
_config: dict | None = None

# Runtime flags (set via CLI, not persisted in YAML)
dry_run: bool = False


def _resolve_value(value: Any) -> Any:
    """Resolve environment variable references (strings starting with $)."""
    if isinstance(value, str) and value.startswith("$"):
        env_var = value[1:]
        return os.environ.get(env_var, "")
    return value


def _resolve_dict(d: dict) -> dict:
    """Recursively resolve env vars in a dict."""
    resolved = {}
    for k, v in d.items():
        if isinstance(v, dict):
            resolved[k] = _resolve_dict(v)
        elif isinstance(v, list):
            resolved[k] = [_resolve_value(item) if isinstance(item, str) else item for item in v]
        else:
            resolved[k] = _resolve_value(v)
    return resolved


def load_config(path: str | Path | None = None) -> dict:
    """Load and cache config from YAML file."""
    global _config
    if _config is not None:
        return _config

    config_path = Path(path) if path else _DEFAULT_CONFIG_PATH
    if not config_path.exists():
        raise FileNotFoundError(f"Config not found: {config_path}")

    with open(config_path) as f:
        raw = yaml.safe_load(f)

    _config = _resolve_dict(raw)
    return _config


def get(key: str, default: Any = None) -> Any:
    """Get a config value by dot-separated key path. e.g. 'technical.filters.rsi_period'"""
    cfg = load_config()
    keys = key.split(".")
    current = cfg
    for k in keys:
        if isinstance(current, dict) and k in current:
            current = current[k]
        else:
            return default
    return current


def get_api_key(name: str) -> str:
    """Get an API key by name, with env var fallback.

    Env var lookup order: config value (may itself reference $ENV_VAR),
    then direct env var with the uppercased name.
    """
    val = get(f"api_keys.{name}", "")
    if not val:
        # Fallback: try uppercased name directly as env var
        val = os.environ.get(name.upper(), "")
    return val


def get_twitter_accounts() -> list[str]:
    """Load the Twitter/X accounts list from sources.json."""
    accounts_file = get("twitter.accounts_file", "/root/.openclaw/sources.json")
    try:
        with open(accounts_file) as f:
            data = json.load(f)
        accounts = data.get("trusted_x_accounts", [])
        return [a.lstrip("@") for a in accounts]
    except Exception:
        return []


def reload():
    """Force config reload."""
    global _config
    _config = None
    return load_config()
