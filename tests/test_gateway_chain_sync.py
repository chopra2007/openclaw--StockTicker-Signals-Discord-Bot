"""Bulletproofing the consensus.yaml <-> openclaw.json agent-chain sync.

The `!ask` / `@-mention` handlers run `openclaw agent --local`, whose model
failover walks ``agents.defaults.model`` ({primary, fallbacks}) in
openclaw.json. consensus.yaml owns that chain as ``llm.agent_model`` +
``llm.agent_fallback_models``; scripts/sync_gateway_models.py mirrors it in.
These tests cover every layer that catches a silent divergence (e.g. an
openclaw npm update overwriting openclaw.json):

1. ``_enumerate_gateway_chain_models`` reads ``agents.defaults.model``
   (happy path, bare-string model, missing file, malformed JSON, missing
   model key, prefix-stripping).
2. ``_consensus_agent_chain`` / ``_compute_drift`` distinguish "synced",
   "drifted", and "either-empty".
3. ``boot_drift_check`` posts to Discord only on drift / config error.
4. ``run_chain_check`` surfaces both ❌ config and ❌ drift rows.
5. ``scripts.sync_gateway_models`` derives the chain correctly (dedup,
   prefix, missing-primary fail-loud).
"""
from __future__ import annotations

import asyncio
import importlib
import json
import sys
from pathlib import Path

import pytest

from consensus_engine import health


REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"


def _gateway_json(primary: str, fallbacks: list[str]) -> dict:
    """openclaw.json shape: agents.defaults.model = {primary, fallbacks}."""
    return {
        "agents": {"defaults": {"model": {
            "primary": primary,
            "fallbacks": fallbacks,
        }}},
    }


# ---------------------------------------------------------------------------
# _enumerate_gateway_chain_models
# ---------------------------------------------------------------------------

def test_gateway_enumerator_happy_path(monkeypatch, tmp_path):
    p = tmp_path / "openclaw.json"
    p.write_text(json.dumps(_gateway_json(
        "openrouter/inclusionai/ring-2.6-1t:free",
        ["openrouter/openai/gpt-oss-120b:free"],
    )))
    monkeypatch.setattr(health, "_GATEWAY_CONFIG", p)

    models, err = health._enumerate_gateway_chain_models()
    assert err == ""
    assert models == [
        ("GATEWAY", "primary", "inclusionai/ring-2.6-1t:free"),
        ("GATEWAY", "fallback 1", "openai/gpt-oss-120b:free"),
    ]


def test_gateway_enumerator_strips_openrouter_prefix_only_when_present(
    monkeypatch, tmp_path
):
    p = tmp_path / "openclaw.json"
    p.write_text(json.dumps(_gateway_json(
        "openrouter/foo/bar:free",   # gets stripped
        ["vendor/baz:free"],          # no prefix — left as-is
    )))
    monkeypatch.setattr(health, "_GATEWAY_CONFIG", p)

    models, _ = health._enumerate_gateway_chain_models()
    assert [m for _, _, m in models] == ["foo/bar:free", "vendor/baz:free"]


def test_gateway_enumerator_accepts_bare_string_model(monkeypatch, tmp_path):
    """`model` may be a bare string instead of a {primary, fallbacks} object."""
    p = tmp_path / "openclaw.json"
    p.write_text(json.dumps(
        {"agents": {"defaults": {"model": "openrouter/z-ai/glm-4.5-air:free"}}}
    ))
    monkeypatch.setattr(health, "_GATEWAY_CONFIG", p)

    models, err = health._enumerate_gateway_chain_models()
    assert err == ""
    assert models == [("GATEWAY", "primary", "z-ai/glm-4.5-air:free")]


def test_gateway_enumerator_missing_file(monkeypatch, tmp_path):
    monkeypatch.setattr(health, "_GATEWAY_CONFIG", tmp_path / "nope.json")
    models, err = health._enumerate_gateway_chain_models()
    assert models == []
    assert "missing" in err


def test_gateway_enumerator_malformed_json(monkeypatch, tmp_path):
    p = tmp_path / "openclaw.json"
    p.write_text("{not valid json")
    monkeypatch.setattr(health, "_GATEWAY_CONFIG", p)

    models, err = health._enumerate_gateway_chain_models()
    assert models == []
    assert "unparseable" in err
    assert "JSONDecodeError" in err  # surfacing the root cause aids debugging


def test_gateway_enumerator_handles_missing_model_path(monkeypatch, tmp_path):
    """openclaw.json with no agents.defaults.model returns empty, not crash."""
    p = tmp_path / "openclaw.json"
    p.write_text(json.dumps({"agents": {"defaults": {}}}))
    monkeypatch.setattr(health, "_GATEWAY_CONFIG", p)

    models, err = health._enumerate_gateway_chain_models()
    assert models == []
    assert err == ""  # not-an-error: the gateway just has no model configured


# ---------------------------------------------------------------------------
# _consensus_agent_chain / _compute_drift
# ---------------------------------------------------------------------------

def test_consensus_agent_chain_reads_and_dedupes(monkeypatch):
    cfg_map = {
        "llm.agent_model": "z-ai/glm-4.5-air:free",
        "llm.agent_fallback_models": [
            "nvidia/nemotron-3-nano-30b-a3b:free",
            "z-ai/glm-4.5-air:free",  # dup of primary — dropped
            "auto",
        ],
    }
    monkeypatch.setattr(health.cfg, "get",
                        lambda k, d=None: cfg_map.get(k, d))
    assert health._consensus_agent_chain() == [
        "z-ai/glm-4.5-air:free",
        "nvidia/nemotron-3-nano-30b-a3b:free",
        "auto",
    ]


def test_drift_empty_when_chains_match(monkeypatch):
    monkeypatch.setattr(health, "_consensus_agent_chain", lambda: ["a", "b"])
    gw = [("GATEWAY", "primary", "a"), ("GATEWAY", "fallback 1", "b")]
    assert health._compute_drift(gw) == ""


def test_drift_detected_when_chains_differ(monkeypatch):
    """The original May 8 bug class: consensus has ring, gateway has ling."""
    monkeypatch.setattr(health, "_consensus_agent_chain",
                        lambda: ["inclusionai/ring-2.6-1t:free"])
    gw = [("GATEWAY", "primary", "inclusionai/ling-2.6-1t:free")]
    detail = health._compute_drift(gw)
    assert "ring" in detail
    assert "ling" in detail


def test_drift_skipped_when_gateway_empty(monkeypatch):
    """Empty gateway means missing-file or no-model — a separate config
    error, not a drift. Drift compare needs both chains present."""
    monkeypatch.setattr(health, "_consensus_agent_chain", lambda: ["a"])
    assert health._compute_drift([]) == ""


def test_drift_skipped_when_consensus_empty(monkeypatch):
    monkeypatch.setattr(health, "_consensus_agent_chain", lambda: [])
    gw = [("GATEWAY", "primary", "a")]
    assert health._compute_drift(gw) == ""


# ---------------------------------------------------------------------------
# boot_drift_check
# ---------------------------------------------------------------------------

async def test_boot_check_silent_when_synced(monkeypatch, tmp_path):
    posted: list[str] = []
    monkeypatch.setattr(health, "_DRIFT_STATE_FILE", tmp_path / "drift_state.json")
    monkeypatch.setattr(health.cfg, "get",
                        lambda k, d=None: True if k == "health_check.enabled" else d)
    monkeypatch.setattr(health, "_consensus_agent_chain", lambda: ["a"])
    monkeypatch.setattr(health, "_enumerate_gateway_chain_models",
                        lambda: ([("GATEWAY", "primary", "a")], ""))

    async def _capture(content: str) -> None:
        posted.append(content)
    monkeypatch.setattr(health, "_post_to_discord", _capture)

    await health.boot_drift_check()
    assert posted == []


async def test_boot_check_posts_on_drift(monkeypatch, tmp_path):
    posted: list[str] = []
    monkeypatch.setattr(health, "_DRIFT_STATE_FILE", tmp_path / "drift_state.json")
    monkeypatch.setattr(health.cfg, "get",
                        lambda k, d=None: True if k == "health_check.enabled" else d)
    monkeypatch.setattr(health, "_consensus_agent_chain", lambda: ["ring"])
    monkeypatch.setattr(health, "_enumerate_gateway_chain_models",
                        lambda: ([("GATEWAY", "primary", "ling")], ""))

    async def _capture(content: str) -> None:
        posted.append(content)
    monkeypatch.setattr(health, "_post_to_discord", _capture)

    await health.boot_drift_check()
    assert len(posted) == 1
    assert "drift" in posted[0]
    assert "ring" in posted[0]
    assert "ling" in posted[0]
    assert "make sync-models" in posted[0]  # actionable next step


async def test_boot_check_emits_resolution_when_prior_drift_cleared(monkeypatch, tmp_path):
    """If a prior boot recorded drift and current boot finds chains aligned,
    post a ✅ resolution message and clear the state file."""
    posted: list[str] = []
    state_file = tmp_path / "drift_state.json"
    state_file.write_text('{"first_seen": "2026-05-11 16:34 ET", "last_seen": "2026-05-11 16:34 ET"}')
    monkeypatch.setattr(health, "_DRIFT_STATE_FILE", state_file)
    monkeypatch.setattr(health.cfg, "get",
                        lambda k, d=None: True if k == "health_check.enabled" else d)
    monkeypatch.setattr(health, "_consensus_agent_chain", lambda: ["a"])
    monkeypatch.setattr(health, "_enumerate_gateway_chain_models",
                        lambda: ([("GATEWAY", "primary", "a")], ""))

    async def _capture(content: str) -> None:
        posted.append(content)
    monkeypatch.setattr(health, "_post_to_discord", _capture)

    await health.boot_drift_check()

    assert len(posted) == 1
    assert "✅" in posted[0] and "resolved" in posted[0]
    assert "2026-05-11 16:34 ET" in posted[0]  # quotes first-seen timestamp
    assert not state_file.exists()  # state cleared


async def test_boot_check_persists_drift_state_across_boots(monkeypatch, tmp_path):
    """A drifted boot writes state; a second drifted boot keeps first_seen stable."""
    state_file = tmp_path / "drift_state.json"
    monkeypatch.setattr(health, "_DRIFT_STATE_FILE", state_file)
    monkeypatch.setattr(health.cfg, "get",
                        lambda k, d=None: True if k == "health_check.enabled" else d)
    monkeypatch.setattr(health, "_consensus_agent_chain", lambda: ["ring"])
    monkeypatch.setattr(health, "_enumerate_gateway_chain_models",
                        lambda: ([("GATEWAY", "primary", "ling")], ""))

    async def _noop(content: str) -> None: pass
    monkeypatch.setattr(health, "_post_to_discord", _noop)

    await health.boot_drift_check()
    first_state = json.loads(state_file.read_text())
    assert "first_seen" in first_state and first_state["drift_detail"]

    await health.boot_drift_check()
    second_state = json.loads(state_file.read_text())
    assert second_state["first_seen"] == first_state["first_seen"]  # sticky


async def test_boot_check_disabled_via_config(monkeypatch):
    """When health_check.enabled=False, boot check no-ops without reads."""
    monkeypatch.setattr(health.cfg, "get",
                        lambda k, d=None: False if k == "health_check.enabled" else d)

    def _should_not_be_called():
        raise AssertionError("enumerator must not run when disabled")
    monkeypatch.setattr(health, "_enumerate_gateway_chain_models", _should_not_be_called)

    await health.boot_drift_check()  # must not raise


# ---------------------------------------------------------------------------
# run_chain_check drift / config rows
# ---------------------------------------------------------------------------

class _ProbeStub:
    """Minimal aiohttp.ClientSession stub that returns OK for every model."""
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False
    def post(self, *a, **kw):
        class _R:
            status = 200
            async def __aenter__(s): return s
            async def __aexit__(s, *a): return False
            async def json(s): return {"choices": [{"message": {"content": "ok"}}]}
            async def text(s): return ""
        return _R()


async def test_run_chain_check_surfaces_drift_row(monkeypatch):
    """Both chains alive but pointing at different models — must alert."""
    from unittest.mock import AsyncMock
    monkeypatch.setattr(health.cfg, "get_api_key", lambda k: "fake")
    monkeypatch.setattr(health, "_consensus_agent_chain", lambda: ["ring"])
    monkeypatch.setattr(health, "_enumerate_chain_models",
                        lambda: [("LLM", "primary", "ring")])
    monkeypatch.setattr(health, "_enumerate_gateway_chain_models",
                        lambda: ([("GATEWAY", "primary", "different-but-alive")], ""))
    monkeypatch.setattr("consensus_engine.health.get_session",
                        AsyncMock(return_value=_ProbeStub()))

    failed, report = await health.run_chain_check()
    assert failed is True
    assert "GATEWAY` `drift`" in report
    assert "ring" in report
    assert "different-but-alive" in report


async def test_run_chain_check_surfaces_gateway_config_error(monkeypatch):
    from unittest.mock import AsyncMock
    monkeypatch.setattr(health.cfg, "get_api_key", lambda k: "fake")
    monkeypatch.setattr(health, "_consensus_agent_chain", lambda: ["ring"])
    monkeypatch.setattr(health, "_enumerate_chain_models",
                        lambda: [("LLM", "primary", "ring")])
    monkeypatch.setattr(health, "_enumerate_gateway_chain_models",
                        lambda: ([], "missing: /nope"))
    monkeypatch.setattr("consensus_engine.health.get_session",
                        AsyncMock(return_value=_ProbeStub()))

    failed, report = await health.run_chain_check()
    assert failed is True
    assert "GATEWAY` `config`" in report
    assert "missing" in report


# ---------------------------------------------------------------------------
# scripts/sync_gateway_models.py — chain derivation
# ---------------------------------------------------------------------------

@pytest.fixture
def sync_module(monkeypatch, tmp_path):
    """Import the sync script with CONSENSUS_YAML pointing at a tmp file."""
    sys.path.insert(0, str(SCRIPTS_DIR))
    import sync_gateway_models  # noqa: WPS433 — script-style module
    importlib.reload(sync_gateway_models)

    yaml_path = tmp_path / "consensus.yaml"
    monkeypatch.setattr(sync_gateway_models, "CONSENSUS_YAML", yaml_path)
    return sync_gateway_models, yaml_path


def test_sync_read_chain_dedupes(sync_module):
    mod, yaml_path = sync_module
    yaml_path.write_text(
        "llm:\n"
        "  agent_model: a\n"
        "  agent_fallback_models: [b, a, c, b]\n"
    )
    primary, fallbacks = mod._read_chain()
    assert primary == "openrouter/a"
    assert fallbacks == ["openrouter/b", "openrouter/c"]


def test_sync_read_chain_prefixes_openrouter(sync_module):
    mod, yaml_path = sync_module
    yaml_path.write_text(
        "llm:\n"
        "  agent_model: z-ai/glm-4.5-air:free\n"
        "  agent_fallback_models: [nvidia/nemotron-3-nano-30b-a3b:free, auto]\n"
    )
    primary, fallbacks = mod._read_chain()
    assert primary == "openrouter/z-ai/glm-4.5-air:free"
    assert fallbacks == [
        "openrouter/nvidia/nemotron-3-nano-30b-a3b:free",
        "openrouter/auto",
    ]


def test_sync_read_chain_fails_loud_when_primary_missing(sync_module):
    mod, yaml_path = sync_module
    yaml_path.write_text("llm:\n  agent_fallback_models: [foo]\n")  # no agent_model
    with pytest.raises(SystemExit) as exc:
        mod._read_chain()
    assert "llm.agent_model missing" in str(exc.value)


def test_sync_read_chain_handles_null_fallbacks(sync_module):
    mod, yaml_path = sync_module
    yaml_path.write_text("llm:\n  agent_model: only\n  agent_fallback_models: null\n")
    primary, fallbacks = mod._read_chain()
    assert primary == "openrouter/only"
    assert fallbacks == []
