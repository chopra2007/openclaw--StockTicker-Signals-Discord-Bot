"""Outbound allowlist for the dashboard worker (the compute child).

The worker may talk to a short, fixed list of outside hosts and nothing else. The list lives
here in code, not in worker.json, because the fixed role config rejects unknown fields and a
reviewed list should change only with a reviewed code change. Anything not listed fails closed.

How it enforces (inside the worker process only):
- Name lookups (socket.getaddrinfo) for a host not on the list are refused. Lookups for a
  listed host are allowed and the public addresses they return are remembered.
- Every network connect (socket.connect / connect_ex) must go to loopback or to an address
  remembered above. A raw IP, or a name the lookup layer never saw, is refused before any
  packet leaves. Unix sockets (broker, authority) are untouched.
Refusals raise EgressDenied, an OSError, so callers see an ordinary connection failure.
"""
import ipaddress
import socket
import threading

# Every outside host the worker legitimately calls (verified from the code, 2026-10-21):
ALLOWED_HOSTS = frozenset({
    'api.schwabapi.com',   # Schwab quotes/chains/history (token refresh is NOT done by the worker)
    'www.sec.gov',         # SEC ticker map + filing documents (/Archives/)
    'data.sec.gov',        # SEC filing lists (/submissions/)
    'openrouter.ai',       # capped AI write-up (analysis_collector, assistant_transport)
    'news.google.com',     # news feed (news.py)
    'www.bing.com',        # news feed, first choice (news.py)
    'api.nasdaq.com',      # analyst targets / earnings date (street.py)
})
# Resolved addresses remembered at once; far above need, bounded so it cannot grow forever.
_MAX_REMEMBERED = 4096


class EgressDenied(OSError):
    """The worker tried to reach a host that is not on the allowlist."""


def _normalise(host):
    if isinstance(host, (bytes, bytearray)): host = bytes(host).decode('ascii', 'replace')
    return str(host).strip().rstrip('.').lower()


def _ip(text):
    try: return ipaddress.ip_address(text.split('%', 1)[0])
    except ValueError: return None


def host_allowed(host):
    """True for a listed name, or loopback (host None/'' means the local machine)."""
    if host is None: return True
    name = _normalise(host)
    if name in ('', 'localhost'): return True
    address = _ip(name)
    if address is not None: return address.is_loopback
    return name in ALLOWED_HOSTS


class _Guard:
    def __init__(self, hosts):
        self.hosts = frozenset(hosts)
        self.lock = threading.Lock()
        self.vouched = {}  # address text -> host name, insertion order = age

    def lookup_ok(self, host):
        if host is None: return True
        name = _normalise(host)
        if name in ('', 'localhost'): return True
        address = _ip(name)
        if address is not None: return address.is_loopback
        return name in self.hosts

    def remember(self, host, results):
        name = _normalise(host) if host is not None else ''
        public = []
        for item in results:
            text = item[4][0]
            address = _ip(text)
            if address is None: continue
            if address.is_loopback: public.append(item); continue
            if not address.is_global: continue  # a listed name must not point at a private/metadata address
            with self.lock:
                self.vouched[text] = name
                while len(self.vouched) > _MAX_REMEMBERED: self.vouched.pop(next(iter(self.vouched)))
            public.append(item)
        if not public: raise EgressDenied(f'egress_denied: {name} resolved to no public address')
        return public

    def connect_ok(self, address):
        text = address[0] if isinstance(address, tuple) else address
        if isinstance(text, bytes): text = text.decode('ascii', 'replace')
        parsed = _ip(str(text))
        if parsed is None: return self.lookup_ok(text)  # a name here still has to be listed
        if parsed.is_loopback: return True
        with self.lock: return str(text) in self.vouched


_installed = None  # (guard, originals)


def install(hosts=ALLOWED_HOSTS):
    """Turn the allowlist on for this process. Safe to call twice; the second call is a no-op."""
    global _installed
    if _installed is not None: return _installed[0]
    guard = _Guard(hosts)
    real_getaddrinfo, real_connect, real_connect_ex = socket.getaddrinfo, socket.socket.connect, socket.socket.connect_ex

    def getaddrinfo(host, *args, **kwargs):
        if not guard.lookup_ok(host): raise EgressDenied(f'egress_denied: {_normalise(host)}')
        return guard.remember(host, real_getaddrinfo(host, *args, **kwargs))

    def _checked(sock, address):
        if sock.family in (socket.AF_INET, socket.AF_INET6) and not guard.connect_ok(address):
            raise EgressDenied(f'egress_denied: {address[0] if isinstance(address, tuple) else address}')

    def connect(self, address):
        _checked(self, address)
        return real_connect(self, address)

    def connect_ex(self, address):
        _checked(self, address)
        return real_connect_ex(self, address)

    socket.getaddrinfo, socket.socket.connect, socket.socket.connect_ex = getaddrinfo, connect, connect_ex
    # aiodns (if present) would resolve names without the lookup above; force the system resolver.
    try:
        import aiohttp.connector, aiohttp.resolver
        real_resolver = aiohttp.connector.DefaultResolver
        aiohttp.connector.DefaultResolver = aiohttp.resolver.ThreadedResolver
    except ImportError: real_resolver = None
    _installed = (guard, (real_getaddrinfo, real_connect, real_connect_ex, real_resolver))
    return guard


def uninstall():
    """Test helper: put the original functions back."""
    global _installed
    if _installed is None: return
    _, (real_getaddrinfo, real_connect, real_connect_ex, real_resolver) = _installed
    socket.getaddrinfo, socket.socket.connect, socket.socket.connect_ex = real_getaddrinfo, real_connect, real_connect_ex
    if real_resolver is not None:
        import aiohttp.connector
        aiohttp.connector.DefaultResolver = real_resolver
    _installed = None
