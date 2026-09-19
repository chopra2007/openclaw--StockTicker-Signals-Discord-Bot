"""M0.4 fixtures; the launcher must install protection before collection."""

import pytest


@pytest.fixture(autouse=True)
async def contract_state(tmp_path, monkeypatch, _isolate_db):
    from consensus_engine import config, db

    fixture = tmp_path / "config.yaml"
    fixture.write_text("database:\n  path: " + str(tmp_path / "contract.db") + "\n"
                       "features:\n  schwab_ohlcv:\n    enabled: true\n"
                       "example:\n  nested:\n    value: 7\n  scalar: leaf\n")
    monkeypatch.setattr(config, "_DEFAULT_CONFIG_PATH", fixture)
    monkeypatch.setattr(config, "_config", None)
    monkeypatch.setattr(config, "dry_run", False)
    yield
    # The parent fixture discards _db; close it first to avoid leaking handles.
    await db.close_db()
    config._config = None
