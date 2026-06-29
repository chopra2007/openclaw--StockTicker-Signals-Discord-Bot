"""C14 (reliability-hardening): the precision-engine HTTP adapters never told
rate_limiter about failures, so a dead direct-caller source (Exa stuck 429,
Firecrawl down) was retried on every call and the failure was buried at debug.
Now adapters feed the SHARED rate_limiter (same source names as the polling
tiers) and raise the log level on a repeat. Flag-gated (adapters.report_failure,
default OFF) since it changes when those sources back off."""
import pytest

from consensus_engine import config, api_adapters


def _flag(monkeypatch, on):
    real = config.get
    monkeypatch.setattr(config, "get",
                        lambda k, d=None: on if k == "adapters.report_failure" else real(k, d))
    # api_adapters imports cfg as the same module object
    monkeypatch.setattr(api_adapters.cfg, "get",
                        lambda k, d=None: on if k == "adapters.report_failure" else real(k, d))


def test_helper_noop_when_flag_off(monkeypatch):
    _flag(monkeypatch, False)
    calls = []
    monkeypatch.setattr(api_adapters.rate_limiter, "report_failure",
                        lambda s, retry_after=None: calls.append(s))
    api_adapters._report_adapter_failure("exa", "down")
    assert calls == [], "flag OFF must not report to rate_limiter"


def test_helper_reports_when_flag_on(monkeypatch):
    _flag(monkeypatch, True)
    calls = []
    monkeypatch.setattr(api_adapters.rate_limiter, "report_failure",
                        lambda s, retry_after=None: calls.append(s))
    api_adapters._report_adapter_failure("exa", "down")
    assert calls == ["exa"]


def test_repeated_failure_warns(monkeypatch, caplog):
    _flag(monkeypatch, True)
    monkeypatch.setattr(api_adapters.rate_limiter, "report_failure",
                        lambda s, retry_after=None: None)
    api_adapters._adapter_fail_counts.pop("serpapi", None)
    with caplog.at_level("WARNING"):
        api_adapters._report_adapter_failure("serpapi", "503")
        api_adapters._report_adapter_failure("serpapi", "503")
    assert any(r.levelname == "WARNING" and "serpapi" in r.message for r in caplog.records), \
        "a repeat failure must surface at WARNING, not stay at debug"


def test_success_resets_count(monkeypatch):
    _flag(monkeypatch, True)
    monkeypatch.setattr(api_adapters.rate_limiter, "report_failure", lambda s, retry_after=None: None)
    successes = []
    monkeypatch.setattr(api_adapters.rate_limiter, "report_success", lambda s: successes.append(s))
    api_adapters._adapter_fail_counts.pop("exa", None)
    api_adapters._report_adapter_failure("exa", "x")
    api_adapters._report_adapter_success("exa")
    assert successes == ["exa"]
    assert "exa" not in api_adapters._adapter_fail_counts


# ---- integration: an adapter failure site actually calls the helper ----

class _Resp:
    def __init__(self, status):
        self.status = status
        self.headers = {}

    async def json(self):
        return {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _Sess:
    def __init__(self, status):
        self._status = status

    def get(self, *a, **k):
        return _Resp(self._status)

    def post(self, *a, **k):
        return _Resp(self._status)


async def test_exa_non200_reports_failure(monkeypatch):
    recorded = []
    monkeypatch.setattr(api_adapters, "_report_adapter_failure",
                        lambda s, detail="": recorded.append(s))
    adapter = api_adapters.ExaAdapter(_Sess(429), api_key="k")
    hits = await adapter.search("nvda")
    assert hits == []
    assert "exa" in recorded


async def test_serpapi_non200_reports_failure(monkeypatch):
    recorded = []
    monkeypatch.setattr(api_adapters, "_report_adapter_failure",
                        lambda s, detail="": recorded.append(s))
    adapter = api_adapters.SerpApiAdapter(_Sess(503), api_key="k")
    hits = await adapter.search("nvda")
    assert hits == []
    assert "serpapi" in recorded
