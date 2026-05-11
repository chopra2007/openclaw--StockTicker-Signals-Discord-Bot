"""Centralized model configuration for text + vision model selection.

Model names are not secrets. We support both:
1) YAML defaults in config/consensus.yaml
2) Optional env-var overrides for runtime model swaps
"""

import os
from pathlib import Path

from dotenv import load_dotenv

_ENV_PATH = Path("/root/.openclaw/.env")
try:
    _env_path_ok = _ENV_PATH.exists()
except PermissionError:
    _env_path_ok = False

if _env_path_ok:
    load_dotenv(_ENV_PATH, override=False)
else:
    load_dotenv(override=False)

try:
    from consensus_engine import config as app_cfg
except Exception:  # avoid hard dependency during isolated tests/imports
    app_cfg = None


def _cfg_get(key: str, default: str) -> str:
    if app_cfg is None:
        return default
    try:
        return str(app_cfg.get(key, default))
    except Exception:
        return default


TEXT_MODEL_DEFAULT = _cfg_get("llm.text_model", "")
VISION_MODEL_DEFAULT = _cfg_get("llm.vision_model", "")

# Env vars are runtime overrides, not secret-only fields.
TEXT_MODEL = os.getenv("TEXT_MODEL", TEXT_MODEL_DEFAULT)
VISION_MODEL = os.getenv("VISION_MODEL", VISION_MODEL_DEFAULT)
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_URL = os.getenv("OPENROUTER_URL", "https://openrouter.ai/api/v1/chat/completions")
MODEL_TIMEOUT_SECONDS = float(os.getenv("MODEL_TIMEOUT_SECONDS", "25"))
