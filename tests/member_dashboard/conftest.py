"""Synthetic dashboard fixtures, independent of the bot and machine credentials."""
from dataclasses import dataclass, field
from types import SimpleNamespace
import sqlite3

import pytest


# The parent suite's fixtures initialize bot modules. Dashboard tests instead
# own their databases and providers. These overrides apply only in this folder.
@pytest.fixture(autouse=True)
def no_discord_alerts():
    yield


@pytest.fixture(autouse=True)
def _reset_http_singleton():
    yield


@pytest.fixture(autouse=True)
def _audit_flags_default_off():
    yield


@pytest.fixture(autouse=True)
def _isolate_db():
    yield


@pytest.fixture(autouse=True)
def _isolate_nfci_fred():
    yield


@pytest.fixture(autouse=True)
def _isolate_level_quote():
    yield


@pytest.fixture(autouse=True)
def _flush_narrator_cache():
    yield


@dataclass
class FakeClock:
    now: float = 1_791_225_000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


@dataclass
class FakeProviderRegistry:
    providers: dict = field(default_factory=dict)


@pytest.fixture
def dashboard(tmp_path):
    from fastapi.testclient import TestClient
    from member_dashboard.app import create_app
    from member_dashboard.settings import Settings

    market_path = tmp_path / "market.sqlite3"
    with sqlite3.connect(market_path) as connection:
        connection.execute("CREATE TABLE synthetic_records(id INTEGER PRIMARY KEY)")
    clock = FakeClock()
    providers = FakeProviderRegistry()
    settings = Settings(web_path=tmp_path / "web.sqlite3", market_path=market_path,
                        clock=clock, provider_registry=providers)
    app = create_app(settings)
    with TestClient(app, base_url=settings.origin) as client:
        yield SimpleNamespace(settings=settings, app=app, client=client,
                              clock=clock, providers=providers, store=app.state.store)
