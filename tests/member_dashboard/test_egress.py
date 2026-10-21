"""Worker outbound allowlist: supported hosts pass, everything else fails closed. No real network."""
import re
import socket
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from member_dashboard import egress

ROOT = Path(__file__).resolve().parents[2]
PUBLIC = '93.184.216.34'  # documentation-style public address; never contacted


@pytest.fixture
def guarded(monkeypatch):
    """Install the guard over fakes so nothing touches the network; always restore."""
    egress.uninstall()
    seen = []
    def fake_getaddrinfo(host, port, *a, **k):
        table = {'169.254.169.254.example': '169.254.169.254', 'internal.test': '10.0.0.5'}
        ip = table.get(str(host), PUBLIC)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (ip, port or 0))]
    monkeypatch.setattr(socket, 'getaddrinfo', fake_getaddrinfo)
    monkeypatch.setattr(socket.socket, 'connect', lambda self, address: seen.append(address))
    monkeypatch.setattr(socket.socket, 'connect_ex', lambda self, address: seen.append(address) or 0)
    guard = egress.install()
    yield guard, seen
    egress.uninstall()


EXPECTED = {'api.schwabapi.com', 'www.sec.gov', 'data.sec.gov', 'openrouter.ai',
            'news.google.com', 'www.bing.com', 'api.nasdaq.com'}


def test_allowlist_is_exactly_the_reviewed_set():
    assert egress.ALLOWED_HOSTS == EXPECTED  # widening needs a deliberate edit here too


def test_every_supported_source_is_listed():
    for host in EXPECTED: assert egress.host_allowed(host), host
    assert egress.host_allowed('NEWS.Google.com.')  # case and trailing dot do not matter


@pytest.mark.parametrize('host', ['evil.example', 'google.com', 'sec.gov', 'www.sec.gov.evil.example',
    'evilwww.sec.gov', 'query1.finance.yahoo.com', 'cdn.finra.org', 'api.telegram.org', '8.8.8.8',
    '169.254.169.254', '10.0.0.5', '::ffff:8.8.8.8'])
def test_unknown_hosts_and_raw_addresses_are_blocked(host):
    assert not egress.host_allowed(host)


def test_loopback_and_local_stay_open():
    for host in (None, '', 'localhost', '127.0.0.1', '::1'): assert egress.host_allowed(host)


def test_lookup_of_unknown_host_is_refused_before_dns(guarded):
    with pytest.raises(egress.EgressDenied):
        socket.getaddrinfo('evil.example', 443)
    assert issubclass(egress.EgressDenied, OSError)  # callers see an ordinary connection error


def test_allowed_host_resolves_then_connects(guarded):
    _, seen = guarded
    [(*_, address)] = socket.getaddrinfo('news.google.com', 443)
    with socket.socket(socket.AF_INET) as sock:
        sock.connect(address[:2])
    assert seen == [(PUBLIC, 443)]


def test_raw_ip_connect_is_refused(guarded):
    _, seen = guarded
    with socket.socket(socket.AF_INET) as sock:
        with pytest.raises(egress.EgressDenied): sock.connect(('8.8.8.8', 443))
        with pytest.raises(egress.EgressDenied): sock.connect_ex(('8.8.8.8', 443))
    assert seen == []


def test_ip_only_allowed_after_listed_name_vouched_for_it(guarded):
    _, seen = guarded
    with socket.socket(socket.AF_INET) as sock:
        with pytest.raises(egress.EgressDenied): sock.connect((PUBLIC, 443))
        socket.getaddrinfo('api.nasdaq.com', 443)
        sock.connect((PUBLIC, 443))
    assert seen == [(PUBLIC, 443)]


def test_listed_name_pointing_at_private_or_metadata_address_is_refused(monkeypatch, guarded):
    guard, _ = guarded
    monkeypatch.setattr(guard, 'lookup_ok', lambda host: True)  # isolate the address check
    for host in ('internal.test', '169.254.169.254.example'):
        with pytest.raises(egress.EgressDenied): socket.getaddrinfo(host, 443)


def test_loopback_and_unix_sockets_are_unaffected(guarded):
    _, seen = guarded
    with socket.socket(socket.AF_INET) as sock: sock.connect(('127.0.0.1', 8080))
    with socket.socket(socket.AF_UNIX) as sock: sock.connect('/run/anything.sock')
    assert len(seen) == 2


def test_memory_of_vouched_addresses_is_bounded(guarded, monkeypatch):
    guard, _ = guarded
    monkeypatch.setattr(egress, '_MAX_REMEMBERED', 5)
    for n in range(20):
        guard.remember('www.sec.gov', [(socket.AF_INET, 1, 6, '', (f'93.184.216.{n}', 443))])
    assert len(guard.vouched) == 5


def test_install_twice_is_harmless_and_uninstall_restores():
    egress.uninstall()
    original = socket.getaddrinfo
    first = egress.install()
    assert egress.install() is first
    egress.uninstall()
    assert socket.getaddrinfo is original


# ---- keep the list in step with the code ----------------------------------------------------

def _hosts_in(path):
    return {urlsplit(u).hostname for u in re.findall(r"""['"](https://[^'"\s{}]+)""", path.read_text())}


def test_urls_the_worker_fetches_are_all_allowed():
    sources = {
        'member_dashboard/news.py': ['FEED', 'BING'],
        'member_dashboard/street.py': ['BASE'],
        'member_dashboard/assistant_transport.py': ['ENDPOINT'],
        'consensus_engine/scanners/schwab_client.py': ['TOKEN_URL', 'MD_BASE'],
        'consensus_engine/scanners/sec_edgar.py': ['map_url', 'submissions_base', 'archives_base'],
    }
    for relative, names in sources.items():
        text = (ROOT / relative).read_text()
        for name in names:
            found = re.search(rf"\b{name}\b\s*(?::\s*str\s*)?=\s*['\"](https://[^'\"]+)", text)
            assert found, f'{name} not found in {relative}'
            assert urlsplit(found.group(1)).hostname in egress.ALLOWED_HOSTS, (relative, name)


def test_provider_budget_routes_are_all_allowed():
    text = (ROOT / 'member_dashboard/operations.py').read_text()
    hosts = set(re.findall(r"Route\('GET','https://([^'/]+)", text))
    assert hosts and hosts <= egress.ALLOWED_HOSTS


def test_no_unreviewed_network_client_appears():
    """A new module that opens its own connection must be added here on purpose, with its host listed."""
    reviewed = {'egress.py', 'analysis_collector.py', 'assistant_transport.py', 'news.py', 'operations.py', 'street.py',
                'runtime.py',  # local 127.0.0.1:3444 health probe only
                'compute_launcher.py', 'quota_broker.py', 'authority_rpc.py', 'exit_control.py', 'launch.py'}  # local sockets only
    client = re.compile(r'^\s*(import|from)\s+(aiohttp|requests|httpx|urllib\.request|http\.client|ftplib|smtplib|websockets)\b', re.M)
    users = {p.name for p in (ROOT / 'member_dashboard').rglob('*.py') if client.search(p.read_text())}
    assert users <= reviewed, f'unreviewed network client in: {sorted(users - reviewed)}'


def test_compute_child_installs_the_guard_before_provider_code():
    text = (ROOT / 'member_dashboard/operations.py').read_text()
    body = text[text.index('async def run_compute'):]
    assert body.index('egress.install()') < body.index('from .providers import')
