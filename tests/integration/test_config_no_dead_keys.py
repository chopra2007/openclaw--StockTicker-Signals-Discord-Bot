"""PR6 — guard against re-introducing dead config keys.

`llm.text_max_tokens: 32000` shipped in v1 but is read by no caller in the
!all path (narrator hardcodes _BATCH_MAX_TOKENS=512; synthesize hardcodes
max_tokens=8000). Keeping it confused the v2 investigation. Delete and
guard against re-add.
"""
from __future__ import annotations

from pathlib import Path

import yaml


CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "consensus.yaml"


def test_text_max_tokens_removed():
    """`llm.text_max_tokens` is dead config and must not be present."""
    cfg = yaml.safe_load(CONFIG_PATH.read_text())
    assert "text_max_tokens" not in cfg.get("llm", {}), (
        "llm.text_max_tokens is dead config (see investigation Q7); "
        "remove from config/consensus.yaml"
    )
