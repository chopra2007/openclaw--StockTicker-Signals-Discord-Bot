"""Synthetic quota proof: no credentials and no external provider requests."""
import importlib.util
import multiprocessing
import os
from pathlib import Path
import threading
import time
import subprocess
import sys
from types import SimpleNamespace
from uuid import uuid4

import pytest


def test_budget_implementation_exists():
    assert importlib.util.find_spec('member_dashboard.quota_broker') is not None


@pytest.fixture
def quota(tmp_path):
    from member_dashboard.store import WebStore
    from member_dashboard.quota_broker import QuotaBroker, Identity
    store = WebStore(tmp_path / 'quota.db')
    store.migrate()
    now = [1000.0]
    broker = QuotaBroker(store, clock=lambda: now[0])
    broker.configure_scope('account', window_seconds=60, verified_limit=10,
                           bot_reserved=7, dashboard_allocated=2, safety_margin=1,
                           verified=True, expires_at=2000)
    broker.configure_endpoint('quote', ['account'], participation_verified=True)
    return broker, store, now, Identity('bot', 'bot-process'), Identity('dashboard', 'web-process')


def reserve(broker, who, endpoint='quote', scopes=('account',), units=1, attempt=None):
    return broker.reserve(scopes, who, endpoint, units, attempt or str(uuid4()))


def test_dashboard_cannot_spend_bot_reserve(quota):
    b, store, _, bot, web = quota
    assert sum(reserve(b, web).allowed for _ in range(7)) == 2
    assert sum(reserve(b, bot).allowed for _ in range(7)) == 7
    assert not reserve(b, bot).allowed
    with store.transaction() as con:
        assert con.execute('SELECT sum(units) FROM provider_admissions').fetchone()[0] == 9


def test_atomic_intersections_and_endpoint_labels(quota):
    b, store, _, bot, web = quota
    b.configure_scope('key2', window_seconds=1, verified_limit=2, bot_reserved=1,
                      dashboard_allocated=1, safety_margin=0, verified=True, expires_at=2000)
    b.configure_endpoint('history', ['account', 'key2'], participation_verified=True)
    assert reserve(b, web, 'history', ['account', 'key2']).allowed
    assert not reserve(b, web, 'history', ['account', 'key2']).allowed
    assert reserve(b, web).allowed
    assert not reserve(b, web).allowed
    assert not reserve(b, web, 'history', ['key2']).allowed
    with store.transaction() as con:
        assert con.execute('SELECT count(*) FROM provider_admissions').fetchone()[0] == 3


def test_rolling_boundary_and_token_units(quota):
    b, _, now, _, web = quota
    a = reserve(b, web, units=2)
    assert a.allowed
    b.finish(a.admission_id, web, 'completed', None)
    now[0] = 1059.999
    assert not reserve(b, web).allowed
    now[0] = 1060
    assert reserve(b, web, units=2).allowed


def test_duplicate_rpc_and_owner_binding(quota):
    b, store, _, bot, web = quota
    a = reserve(b, web, attempt='same')
    assert reserve(b, web, attempt='same') == a
    assert not reserve(b, bot, attempt='same').allowed
    assert not reserve(b, web, attempt='same', units=2).allowed
    b.finish(a.admission_id, bot, 'completed', None)
    with store.transaction() as con:
        assert con.execute('SELECT finished_at FROM provider_admissions').fetchone()[0] is None


@pytest.mark.parametrize('outcome,retry_after,advance', [('uncertain', None, 0), ('429_uncertain', 5, 6)])
def test_explicit_uncertain_finish_cannot_be_replayed(quota, outcome, retry_after, advance):
    b, store, now, _, web = quota
    admission = reserve(b, web, attempt='uncertain-replay')
    assert admission.allowed
    # Pre-send retries of the admission RPC still return the same permit.
    assert reserve(b, web, attempt='uncertain-replay') == admission
    b.finish(admission.admission_id, web, outcome, retry_after)
    now[0] += advance
    replay = reserve(b, web, attempt='uncertain-replay')
    assert not replay.allowed
    assert replay.reason == 'stale_attempt'
    with store.transaction() as con:
        assert con.execute('SELECT count(*),sum(units),max(finished_at) FROM provider_admissions').fetchone() == (1, 1, None)
    assert reserve(b, web, attempt='actual-new-send').allowed


def test_old_admission_cannot_authorize_a_send_in_a_new_window(quota):
    b, _, now, _, web = quota
    assert reserve(b, web, attempt='lost-reply').allowed
    now[0] += 60
    assert not reserve(b, web, attempt='lost-reply').allowed


def test_duplicate_rpc_cannot_bypass_new_shared_cooldown(quota):
    b, _, _, bot, web = quota
    assert reserve(b, web, attempt='lost-reply').allowed
    other = reserve(b, bot)
    b.finish(other.admission_id, bot, '429', 900)
    assert reserve(b, web, attempt='lost-reply').not_before == 1900


def test_429_persists_long_cooldown_across_restart(quota):
    from member_dashboard.quota_broker import QuotaBroker
    b, store, now, bot, web = quota
    a = reserve(b, web)
    b.finish(a.admission_id, web, '429', 900)
    b = QuotaBroker(store, clock=lambda: now[0])
    assert reserve(b, bot).not_before == 1900
    now[0] = 1899
    assert not reserve(b, bot).allowed
    now[0] = 1900
    assert reserve(b, bot).allowed


def test_uncertain_crash_never_refunds_or_releases_on_restart(quota):
    from member_dashboard.quota_broker import QuotaBroker
    b, store, now, bot, web = quota
    b.configure_scope('account', window_seconds=60, verified_limit=10, bot_reserved=7,
                      dashboard_allocated=2, safety_margin=1, max_concurrency=1,
                      verified=True, expires_at=2000)
    a = reserve(b, web)
    b.finish(a.admission_id, web, 'uncertain', None)
    b = QuotaBroker(store, clock=lambda: now[0])
    assert not reserve(b, bot).allowed
    assert b.reconcile_exited(web.owner, confirmed_dead=lambda owner: False) == 0
    assert not reserve(b, bot).allowed
    assert b.reconcile_exited(web.owner, confirmed_dead=lambda owner: True) == 1
    assert reserve(b, bot).allowed
    with store.transaction() as con:
        assert con.execute('SELECT sum(units) FROM provider_admissions').fetchone()[0] == 2


def test_unverified_unknown_expired_and_invalid_units_closed(quota):
    b, _, now, _, web = quota
    assert not reserve(b, web, 'sdk').allowed
    for bad in [0, -1, float('nan'), float('inf'), True, 10**400]:
        assert not reserve(b, web, units=bad).allowed
    b.configure_endpoint('sdk', ['account'], participation_verified=False)
    assert not reserve(b, web, 'sdk').allowed
    now[0] = 2000
    assert not reserve(b, web).allowed


def _compete(address, credential, role, output):
    from consensus_engine.utils.provider_budget import BudgetClient
    client = BudgetClient(address, credential=credential)
    count = 0
    for _ in range(7):
        a = client.reserve(['account'], role, 'quote', 1, str(uuid4()))
        count += a.allowed
        if a.allowed:
            client.finish(a.admission_id, 'completed', None)
    output.put(count)


def test_two_real_processes_separate_connections_and_role_auth(quota):
    from member_dashboard.quota_broker import BrokerServer
    from consensus_engine.utils.provider_budget import BudgetClient
    b, store, _, _, _ = quota
    with BrokerServer.for_loopback_tests(b, {'bot-secret': 'bot', 'web-secret': 'dashboard'}) as server:
        context = multiprocessing.get_context('spawn')
        outputs = [context.Queue(), context.Queue()]
        processes = [context.Process(target=_compete, args=(server.address, key, role, q))
                     for key, role, q in zip(['bot-secret', 'web-secret'], ['bot', 'dashboard'], outputs)]
        for process in processes:
            process.start()
        for process in processes:
            process.join(15)
            assert process.exitcode == 0
        assert [q.get(timeout=2) for q in outputs] == [7, 2]
        imposter = BudgetClient(server.address, credential='web-secret')
        assert not imposter.reserve(['account'], 'bot', 'quote', 1, 'spoof').allowed
        unknown = BudgetClient(server.address, credential='wrong')
        assert not unknown.reserve(['account'], 'bot', 'quote', 1, 'unknown').allowed
    with store.transaction() as con:
        assert con.execute('SELECT sum(units) FROM provider_admissions').fetchone()[0] == 9


@pytest.mark.skipif(os.name != 'posix', reason='Linux peer credentials proof')
def test_unix_peer_identity_permissions_and_live_owner(quota, tmp_path):
    from member_dashboard.quota_broker import BrokerServer, process_identity, confirmed_process_exit
    from consensus_engine.utils.provider_budget import BudgetClient
    b, _, _, _, _ = quota
    directory = tmp_path / 'socket'
    directory.mkdir(mode=0o700)
    path = str(directory / 'broker.sock')
    with BrokerServer(b, path, uid_roles={os.getuid(): 'bot'}) as server:
        client = BudgetClient(server.address)
        assert client.reserve(['account'], 'bot', 'quote', 1, 'unix').allowed
        assert not client.reserve(['account'], 'dashboard', 'quote', 1, 'spoof').allowed
        assert Path(path).stat().st_mode & 0o777 == 0o660
        assert not confirmed_process_exit(process_identity(os.getpid()))
        assert b.reconcile_exited(process_identity(os.getpid()), confirmed_dead=confirmed_process_exit) == 0


@pytest.mark.skipif(os.name != 'posix', reason='Linux real-process death and identity proof')
def test_confirmed_child_exit_reconciles_without_refunding(quota, tmp_path):
    import json
    from member_dashboard.quota_broker import BrokerServer, QuotaBroker, confirmed_process_exit
    b, store, now, bot, _ = quota
    b.configure_scope('account', window_seconds=60, verified_limit=10, bot_reserved=7,
                      dashboard_allocated=2, safety_margin=1, max_concurrency=1,
                      verified=True, expires_at=2000)
    directory = tmp_path / 'socket'
    directory.mkdir(mode=0o700)
    script = '''
import json, os, sys, time
from uuid import uuid4
from consensus_engine.utils.provider_budget import BudgetClient
from member_dashboard.quota_broker import process_identity
admission = BudgetClient(sys.argv[1]).reserve(['account'], 'bot', 'quote', 1, str(uuid4()))
print(json.dumps([admission.allowed, process_identity(os.getpid())]), flush=True)
time.sleep(60)
'''
    with BrokerServer(b, str(directory / 'broker.sock'), uid_roles={os.getuid(): 'bot'}) as server:
        child = subprocess.Popen([sys.executable, '-c', script, server.address], stdout=subprocess.PIPE, text=True)
        try:
            allowed, owner = json.loads(child.stdout.readline())
            assert allowed
            assert b.reconcile_exited(owner, confirmed_dead=confirmed_process_exit) == 0
            child.kill()
            child.wait(timeout=5)
            assert child.returncode is not None
            restarted = QuotaBroker(store, clock=lambda: now[0])
            assert not reserve(restarted, bot).allowed
            # This synthetic child cannot spawn descendants; its confirmed exit
            # is therefore complete tree-exit evidence for this test only.
            assert restarted.reconcile_exited(owner, confirmed_dead=confirmed_process_exit) == 1
            assert reserve(restarted, bot).allowed
            with store.transaction() as con:
                assert con.execute('SELECT sum(units) FROM provider_admissions').fetchone()[0] == 2
        finally:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=5)
            child.stdout.close()


def test_broker_outage_defers_without_emergency_allowance(tmp_path):
    from consensus_engine.utils.provider_budget import BudgetClient
    a = BudgetClient(('127.0.0.1', 1), credential='synthetic', timeout=.1).reserve(
        ['account'], 'bot', 'quote', 1, 'offline')
    assert not a.allowed
    assert a.not_before > 0


def test_client_import_does_not_load_bot_config_or_database():
    code = '''
import sys
class Block:
    def find_spec(self, name, *args):
        if name in ('consensus_engine.config', 'consensus_engine.db', 'member_dashboard.store'):
            raise AssertionError(name)
sys.meta_path.insert(0, Block())
from consensus_engine.utils.provider_budget import BudgetClient
assert BudgetClient
'''
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


def test_transport_retries_charge_and_long_date_retry_after(quota):
    from consensus_engine.utils.provider_budget import TransportBudget, Route, BudgetDeferred
    from member_dashboard.quota_broker import BrokerServer
    b, store, now, _, _ = quota
    with BrokerServer.for_loopback_tests(b, {'web': 'dashboard'}) as server:
        from consensus_engine.utils.provider_budget import BudgetClient
        budget = TransportBudget(BudgetClient(server.address, credential='web'), 'dashboard',
                                 [Route('GET', 'https://synthetic.invalid', '/', 'quote', ('account',))])
        sends = []
        def send(url, **kwargs):
            sends.append(url)
            assert kwargs['allow_redirects'] is False
            return SimpleNamespace(status_code=200, headers={})
        for _ in range(2):
            budget.request(send, 'GET', 'https://synthetic.invalid/quote?private=ignored')
        with pytest.raises(BudgetDeferred):
            budget.request(send, 'GET', 'https://synthetic.invalid/history')
        assert len(sends) == 2
        with pytest.raises(BudgetDeferred):
            budget.request(send, 'GET', 'https://unknown.invalid/quote')
    with store.transaction() as con:
        assert con.execute('SELECT count(DISTINCT attempt_id) FROM provider_admissions').fetchone()[0] == 2
        assert con.execute("SELECT count(*) FROM provider_admissions WHERE endpoint LIKE '%private%'").fetchone()[0] == 0
    from consensus_engine.utils.provider_budget import retry_after_seconds
    assert retry_after_seconds('Thu, 01 Jan 1970 00:31:40 GMT', now=1000) == 900
    assert retry_after_seconds('3600', now=1000) == 3600


def test_transport_exception_remains_uncertain_and_sdk_cannot_bypass(quota):
    from consensus_engine.utils.provider_budget import TransportBudget, Route, BudgetClient, BudgetDeferred
    from member_dashboard.quota_broker import BrokerServer
    b, store, _, _, _ = quota
    with BrokerServer.for_loopback_tests(b, {'web': 'dashboard'}) as server:
        budget = TransportBudget(BudgetClient(server.address, credential='web'), 'dashboard',
                                 [Route('GET', 'https://synthetic.invalid', '/', 'quote', ('account',))])
        def timeout(url, **kwargs):
            raise TimeoutError('synthetic transport timeout')
        with pytest.raises(TimeoutError):
            budget.request(timeout, 'GET', 'https://synthetic.invalid/quote')
        with pytest.raises(BudgetDeferred):
            budget.require_sdk('yahoo')
    with store.transaction() as con:
        assert con.execute('SELECT units,uncertain,finished_at FROM provider_admissions').fetchone() == (1, 1, None)


@pytest.mark.parametrize('method', ['GET', 'POST'])
@pytest.mark.parametrize('truncated', [True, False])
def test_real_sync_429_headers_survive_body_handling(quota, method, truncated):
    requests = pytest.importorskip('requests')
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from consensus_engine.utils.provider_budget import TransportBudget, Route, BudgetClient
    from member_dashboard.quota_broker import BrokerServer
    b, store, _, bot, _ = quota
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(429)
            self.send_header('Retry-After', '900')
            self.send_header('Content-Length', '100' if truncated else '1')
            self.end_headers()
            self.wfile.write(b'x')
            self.close_connection = True
        do_POST = do_GET
        def log_message(self, *_):
            pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=.01), daemon=True)
    thread.start()
    origin = f'http://127.0.0.1:{server.server_port}'
    observed = []
    def existing_hook(response, *args, **kwargs):
        with store.transaction() as con:
            observed.append(con.execute('SELECT outcome,finished_at FROM provider_admissions').fetchone())
        return response
    try:
        with BrokerServer.for_loopback_tests(b, {'web': 'dashboard'}) as broker:
            budget = TransportBudget(BudgetClient(broker.address, credential='web'), 'dashboard',
                                     [Route(method, origin, '/', 'quote', ('account',))])
            def send():
                return budget.request(getattr(requests, method.lower()), method, origin+'/',
                                      timeout=2, proxies={'http': '', 'https': ''},
                                      hooks={'response': existing_hook})
            if truncated:
                with pytest.raises(requests.exceptions.ChunkedEncodingError):
                    send()
            else:
                response = send()
                assert response.status_code == 429 and response.content == b'x'
            assert reserve(b, bot).not_before == 1900
            # Headers establish a shared hold before existing response hooks or
            # eager body reading run; concurrency remains owned until completion.
            assert observed == [('429_uncertain', None)]
        with store.transaction() as con:
            assert con.execute('SELECT units,uncertain,finished_at,outcome FROM provider_admissions').fetchone() == (
                (1, 1, None, '429_uncertain') if truncated else (1, 0, 1000, '429'))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)


@pytest.mark.asyncio
async def test_async_context_finishes_only_after_body_and_no_redirect(quota):
    from consensus_engine.utils.provider_budget import BudgetSession, TransportBudget, Route, BudgetClient
    from member_dashboard.quota_broker import BrokerServer
    b, store, _, _, _ = quota
    class Context:
        async def __aenter__(self):
            return SimpleNamespace(status=200, headers={})
        async def __aexit__(self, *args):
            pass
    class Session:
        _retry_connection = True
        def request(self, method, url, **kwargs):
            assert not kwargs['allow_redirects']
            return Context()
    with BrokerServer.for_loopback_tests(b, {'web': 'dashboard'}) as server:
        budget = TransportBudget(BudgetClient(server.address, credential='web'), 'dashboard',
                                 [Route('GET', 'https://synthetic.invalid', '/', 'quote', ('account',))])
        raw = Session()
        session = BudgetSession(raw, budget)
        async with session.get('https://synthetic.invalid/sec'):
            with store.transaction() as con:
                assert con.execute('SELECT finished_at FROM provider_admissions').fetchone()[0] is None
        assert raw._retry_connection is False
    with store.transaction() as con:
        assert con.execute('SELECT finished_at,uncertain FROM provider_admissions').fetchone() == (1000, 0)


def test_distinct_request_and_token_units(quota):
    b, store, _, _, web = quota
    b.configure_scope('tokens', window_seconds=60, verified_limit=100, bot_reserved=70,
                      dashboard_allocated=20, safety_margin=10, verified=True, expires_at=2000)
    b.configure_endpoint('model-synthetic', ['account', 'tokens'], participation_verified=True)
    units = {'account': 1, 'tokens': 15}
    assert reserve(b, web, 'model-synthetic', ['account', 'tokens'], units).allowed
    assert not reserve(b, web, 'model-synthetic', ['account', 'tokens'], units).allowed
    assert reserve(b, web).allowed
    with store.transaction() as con:
        assert con.execute("SELECT sum(units) FROM provider_admissions WHERE scope_id='tokens'").fetchone()[0] == 15


def test_cannot_reallocate_consumed_capacity_mid_window(quota):
    b, _, _, bot, _ = quota
    assert reserve(b, bot).allowed
    with pytest.raises(ValueError, match='active'):
        b.configure_scope('account', window_seconds=60, verified_limit=10, bot_reserved=0,
                          dashboard_allocated=9, safety_margin=1, verified=True, expires_at=2000)


def test_separate_keys_share_account_ip_and_burst_windows(quota):
    b, _, now, _, web = quota
    for name, window, allocation in [('key1', 60, 10), ('key2', 60, 10), ('ip', 60, 2), ('burst', 1, 1)]:
        b.configure_scope(name, window_seconds=window, verified_limit=allocation,
                          bot_reserved=0, dashboard_allocated=allocation, safety_margin=0,
                          verified=True, expires_at=2000)
    for name, key in [('one', 'key1'), ('two', 'key2')]:
        b.configure_endpoint(name, [key, 'account', 'ip', 'burst'], participation_verified=True)
    assert reserve(b, web, 'one', ['key1', 'account', 'ip', 'burst']).allowed
    assert not reserve(b, web, 'two', ['key2', 'account', 'ip', 'burst']).allowed
    now[0] += 1
    assert reserve(b, web, 'two', ['key2', 'account', 'ip', 'burst']).allowed
    now[0] += 1
    assert not reserve(b, web, 'two', ['key2', 'account', 'ip', 'burst']).allowed


def test_process_bootstrap_hooks_preserve_legacy_and_block_sdk(monkeypatch):
    from consensus_engine.utils import provider_budget as pb
    sent = []
    def send(url, **kwargs):
        sent.append((url, kwargs))
        return 'legacy'
    assert pb.budgeted_request(send, 'GET', 'synthetic', timeout=1) == 'legacy'
    assert sent == [('synthetic', {'timeout': 1})]
    budget = pb.TransportBudget(None, 'dashboard', [])
    monkeypatch.setattr(pb, '_transport_budget', budget)
    with pytest.raises(pb.BudgetDeferred):
        pb.budgeted_request(send, 'GET', 'https://unmapped.invalid')
    with pytest.raises(pb.BudgetDeferred):
        pb.require_mapped_sdk('yahoo')
    assert len(sent) == 1


def test_logging_retains_configured_behavior_in_fresh_process():
    code = '''
import sys, types, logging
cfg = types.ModuleType('consensus_engine.config')
cfg.get = lambda name, default=None: {'logging.level':'WARNING', 'logging.format':'%(message)s'}.get(name, default)
sys.modules['consensus_engine.config'] = cfg
from consensus_engine.utils import setup_logging
logger = setup_logging()
assert logger.level == logging.WARNING
assert len(logger.handlers) == 1
assert setup_logging() is logger
'''
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


@pytest.mark.asyncio
async def test_shared_http_session_uses_opt_in_budget(monkeypatch):
    pytest.importorskip('yaml')
    pytest.importorskip('aiohttp')
    from consensus_engine.utils import http, provider_budget as pb
    monkeypatch.setattr(pb, '_transport_budget', pb.TransportBudget(None, 'dashboard', []))
    monkeypatch.setattr(http, '_session', None)
    monkeypatch.setattr(http, '_lock', None)
    try:
        session = await http.get_session()
        assert isinstance(session, pb.BudgetSession)
        with pytest.raises(pb.BudgetDeferred):
            async with session.get('https://unmapped.invalid/sec'):
                pytest.fail('unmapped HTTP was sent')
    finally:
        await http.close_session()


def test_yahoo_price_fallback_is_blocked_when_participating(monkeypatch):
    pytest.importorskip('yaml')
    from consensus_engine.utils import prices, provider_budget as pb
    monkeypatch.setattr(pb, '_transport_budget', pb.TransportBudget(None, 'dashboard', []))
    monkeypatch.setattr(prices.config, 'get', lambda *a, **kw: False)
    fake = SimpleNamespace(Ticker=lambda *a: pytest.fail('SDK entered'))
    monkeypatch.setitem(sys.modules, 'yfinance', fake)
    with pytest.raises(pb.BudgetDeferred):
        prices.fetch_history('SYNTHETIC')


@pytest.mark.skipif(os.name != 'posix', reason='Schwab uses fcntl')
def test_schwab_market_and_oauth_actual_sends_are_guarded(monkeypatch, tmp_path):
    pytest.importorskip('requests')
    pytest.importorskip('yaml')
    from consensus_engine.scanners import schwab_client as schwab
    from consensus_engine.utils import provider_budget as pb
    monkeypatch.setattr(pb, '_transport_budget', pb.TransportBudget(None, 'dashboard', []))
    monkeypatch.setattr(schwab, '_bucket', SimpleNamespace(in_cooldown=lambda: False, acquire=lambda: None))
    monkeypatch.setattr(schwab, '_load_token', lambda: {'creation_timestamp': time.time(), 'token': {'access_token': 'synthetic', 'refresh_token': 'synthetic'}})
    monkeypatch.setattr(schwab, '_needs_refresh', lambda doc: False)
    monkeypatch.setattr(schwab.requests, 'get', lambda *a, **kw: pytest.fail('market request escaped'))
    with pytest.raises(pb.BudgetDeferred):
        schwab._get('/quotes')
    monkeypatch.setattr(schwab, '_needs_refresh', lambda doc: True)
    monkeypatch.setattr(schwab, 'LOCK_PATH', str(tmp_path / 'refresh.lock'))
    monkeypatch.setattr(schwab, '_creds', lambda: ('synthetic', 'synthetic'))
    monkeypatch.setattr(schwab.requests, 'post', lambda *a, **kw: pytest.fail('OAuth request escaped'))
    with pytest.raises(pb.BudgetDeferred):
        schwab.get_access_token()


@pytest.mark.asyncio
async def test_actual_thread_holds_runtime_and_quota_until_transport_completes(quota):
    import asyncio
    from member_dashboard.provider_runtime import ProviderRuntime
    from member_dashboard.quota_broker import BrokerServer
    from consensus_engine.utils.provider_budget import BudgetClient, Route, TransportBudget
    b, store, now, _, _ = quota
    release = threading.Event()
    entered = threading.Event()
    runtime = ProviderRuntime(store, 'worker', clock=lambda: now[0])
    def send(url, **kwargs):
        entered.set()
        assert release.wait(3)
        return SimpleNamespace(status_code=200, headers={})
    with BrokerServer.for_loopback_tests(b, {'web': 'dashboard'}) as server:
        budget = TransportBudget(BudgetClient(server.address, credential='web'), 'dashboard',
                                 [Route('GET', 'https://synthetic.invalid', '/', 'quote', ('account',))])
        try:
            result = await runtime.run_blocking('actual', lambda: budget.request(send, 'GET', 'https://synthetic.invalid/'), .05)
            assert entered.is_set() and result.status == 'timeout'
            assert runtime.running_count == 1
            with store.transaction() as con:
                assert con.execute('SELECT finished_at FROM provider_admissions').fetchone()[0] is None
            release.set()
            async with asyncio.timeout(3):
                while runtime.running_count:
                    await asyncio.sleep(.01)
            with store.transaction() as con:
                assert con.execute('SELECT units,finished_at FROM provider_admissions').fetchone() == (1, 1000)
        finally:
            release.set()
            runtime.shutdown()


@pytest.mark.asyncio
async def test_429_body_failure_still_cools_shared_scope(quota):
    from consensus_engine.utils.provider_budget import BudgetSession, TransportBudget, Route, BudgetClient
    from member_dashboard.quota_broker import BrokerServer
    b, _, _, bot, _ = quota
    class Context:
        async def __aenter__(self):
            return SimpleNamespace(status=429, headers={'Retry-After': '900'})
        async def __aexit__(self, *args):
            pass
    raw = SimpleNamespace(_retry_connection=True, request=lambda *a, **kw: Context())
    with BrokerServer.for_loopback_tests(b, {'web': 'dashboard'}) as server:
        budget = TransportBudget(BudgetClient(server.address, credential='web'), 'dashboard',
                                 [Route('GET', 'https://synthetic.invalid', '/', 'quote', ('account',))])
        with pytest.raises(ValueError):
            async with BudgetSession(raw, budget).get('https://synthetic.invalid/'):
                raise ValueError('synthetic body read failed')
        assert reserve(b, bot).not_before == 1900


def test_bad_frame_cannot_kill_broker_or_expose_admin_rpc(quota):
    import socket
    import struct
    from member_dashboard.quota_broker import BrokerServer
    from consensus_engine.utils.provider_budget import BudgetClient, send_frame, receive_frame
    b, _, _, _, _ = quota
    with BrokerServer.for_loopback_tests(b, {'web': 'dashboard'}) as server:
        with socket.create_connection(server.address, timeout=1) as connection:
            data = b'[' * 2000 + b']' * 2000
            connection.sendall(struct.pack('!I', len(data)) + data)
            assert not receive_frame(connection)['allowed']
        client = BudgetClient(server.address, credential='web')
        assert client.reserve(['account'], 'dashboard', 'quote', 1, 'after-bad').allowed
        assert not client._rpc({'method':'reconcile_exited', 'owner':'arbitrary'})['allowed']
