"""PR6 — cache key auto-invalidation on code-version bump.

The !all cache used to use a static `KEY_PREFIX = "all"`, so a code-only
deploy left old payloads visible for up to 15 minutes per ticker. PR6
derives the prefix from a sha1 of `consensus_engine.__version__` so any
version bump (or hand-roll) auto-invalidates the namespace.
"""
from __future__ import annotations

import importlib
import re

import consensus_engine
from consensus_engine.alerts.all_command import cache as cache_mod


def test_key_prefix_includes_code_hash():
    """KEY_PREFIX must encode a code-version hash, not be a static string."""
    assert re.fullmatch(r"all_v[0-9a-f]{8}", cache_mod.KEY_PREFIX), (
        f"KEY_PREFIX={cache_mod.KEY_PREFIX!r} does not match all_v<sha1[:8]>"
    )


def test_different_versions_produce_different_keys(monkeypatch):
    """Bumping __version__ and reimporting cache must produce a new prefix."""
    monkeypatch.setattr(consensus_engine, "__version__", "test-version-a")
    importlib.reload(cache_mod)
    prefix_a = cache_mod.KEY_PREFIX

    monkeypatch.setattr(consensus_engine, "__version__", "test-version-b")
    importlib.reload(cache_mod)
    prefix_b = cache_mod.KEY_PREFIX

    assert prefix_a != prefix_b
    assert re.fullmatch(r"all_v[0-9a-f]{8}", prefix_a)
    assert re.fullmatch(r"all_v[0-9a-f]{8}", prefix_b)

    # Restore the real version-derived prefix so other tests aren't polluted.
    importlib.reload(consensus_engine)
    importlib.reload(cache_mod)
