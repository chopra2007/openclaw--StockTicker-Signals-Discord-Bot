"""Centralized model configuration for text + vision model swapping via .env."""

import os
from pathlib import Path

from dotenv import load_dotenv

_ENV_PATH = Path("/root/.openclaw/.env")
if _ENV_PATH.exists():
    load_dotenv(_ENV_PATH, override=False)
else:
    load_dotenv(override=False)

TEXT_MODEL = os.getenv("TEXT_MODEL", "minimax/minimax-m2.5:free")
VISION_MODEL = os.getenv("VISION_MODEL", "google/gemini-2.5-flash-preview")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_URL = os.getenv("OPENROUTER_URL", "https://openrouter.ai/api/v1/chat/completions")
MODEL_TIMEOUT_SECONDS = float(os.getenv("MODEL_TIMEOUT_SECONDS", "25"))
