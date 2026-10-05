"""Restricted quota RPC client. No web-store imports, secrets or DB access.

Trusted process bootstrap may opt into transport admission. The legacy bot is
unchanged unless configured. A missing broker always defers participating work.
"""
from contextlib import asynccontextmanager
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
import json
import math
import socket
import struct
import time
from urllib.parse import urlsplit
from uuid import uuid4


@dataclass(frozen=True)
class Admission:
    allowed: bool
    admission_id: str | None = None
    not_before: float | None = None
    reason: str | None = None


def receive_frame(connection):
    deadline = time.monotonic() + 2
    def exact(size):
        data = b''
        while len(data) < size:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('quota frame deadline')
            connection.settimeout(min(connection.gettimeout() or 2, remaining))
            chunk = connection.recv(size - len(data))
            if not chunk:
                raise OSError('incomplete quota frame')
            data += chunk
        return data
    size = struct.unpack('!I', exact(4))[0]
    if not 0 < size <= 16384:
        raise ValueError('quota frame limit')
    return json.loads(exact(size))


def send_frame(connection, value):
    data = json.dumps(value, allow_nan=False, separators=(',', ':')).encode()
    if len(data) > 16384:
        raise ValueError('quota frame limit')
    connection.sendall(struct.pack('!I', len(data)) + data)


class BudgetClient:
    def __init__(self, address, *, credential=None, timeout=2):
        if not 0 < timeout <= 5:
            raise ValueError('bounded RPC timeout required')
        if isinstance(address, (tuple, list)) and address[0] != '127.0.0.1':
            raise ValueError('only local quota transport is supported')
        self.address, self.credential, self.timeout = address, credential, timeout

    def _rpc(self, payload):
        family = socket.AF_UNIX if isinstance(self.address, str) else socket.AF_INET
        with socket.socket(family, socket.SOCK_STREAM) as connection:
            connection.settimeout(self.timeout)
            connection.connect(self.address)
            send_frame(connection, dict(payload, credential=self.credential))
            return receive_frame(connection)

    def reserve(self, scope_ids, caller, endpoint, units, attempt_id):
        try:
            result = self._rpc(dict(method='reserve', scope_ids=list(scope_ids), caller=caller,
                                    endpoint=endpoint, units=units, attempt_id=attempt_id))
            return Admission(**result)
        except (OSError, ValueError, TypeError, RecursionError):
            return Admission(False, not_before=time.time()+5, reason='broker_unavailable')

    def finish(self, admission_id, outcome, retry_after=None):
        # Lost completion RPC retains uncertain capacity; never opens a bypass.
        try:
            self._rpc(dict(method='finish', admission_id=admission_id,
                           outcome=outcome, retry_after=retry_after))
        except (OSError, ValueError, TypeError, RecursionError):
            pass


class BudgetDeferred(RuntimeError):
    pass


@dataclass(frozen=True)
class Route:
    method: str
    origin: str
    path_prefix: str
    endpoint: str
    scopes: tuple[str, ...]
    units: float = 1


def retry_after_seconds(value, *, now=None):
    now = time.time() if now is None else now
    try:
        result = float(value)
    except (ValueError, TypeError):
        try:
            result = parsedate_to_datetime(value).timestamp() - now
        except (ValueError, TypeError, OverflowError):
            return None
    return result if math.isfinite(result) and result > 0 else None


class TransportBudget:
    """Trusted static route inventory; no model/member supplied scope discovery."""
    def __init__(self, client, caller, routes):
        if caller not in ('bot', 'dashboard'):
            raise ValueError('invalid caller')
        self.client, self.caller, self.routes = client, caller, tuple(routes)

    def admit(self, method, url):
        parsed = urlsplit(str(url))
        if parsed.username or parsed.password or parsed.scheme not in ('http', 'https'):
            raise BudgetDeferred('unmapped transport')
        origin = f'{parsed.scheme}://{parsed.netloc.lower()}'
        routes = [r for r in self.routes if r.method == method.upper() and r.origin == origin
                  and (parsed.path == r.path_prefix.rstrip('/') or parsed.path.startswith(r.path_prefix))]
        if len(routes) != 1:
            raise BudgetDeferred('unmapped or ambiguous transport')
        route = routes[0]
        admission = self.client.reserve(route.scopes, self.caller, route.endpoint, route.units, str(uuid4()))
        if not admission.allowed:
            raise BudgetDeferred(admission.reason or 'provider deferred')
        return admission

    def complete(self, admission, response, *, asynchronous=False):
        status = response.status if asynchronous else response.status_code
        self.client.finish(admission.admission_id, '429' if status == 429 else 'completed',
                           retry_after_seconds(response.headers.get('Retry-After')))

    def request(self, send, method, url, **kwargs):
        # requests' default adapters do not retry. Do not pass custom sessions or
        # streaming responses here: their internal requests are not verified.
        if kwargs.get('stream'):
            raise BudgetDeferred('streaming transport unsupported')
        admission = self.admit(method, url)
        kwargs['allow_redirects'] = False
        try:
            response = send(url, **kwargs)
        except BaseException:
            self.client.finish(admission.admission_id, 'uncertain')
            raise
        self.complete(admission, response)
        return response

    def require_sdk(self, product):
        # No SDK has verified all low-level sends, retries, metadata or fan-out.
        raise BudgetDeferred('unmapped SDK transport')


class BudgetSession:
    """Opt-in async-context transport. Implicit redirects/retries are disabled.

    Callers needing await-response or streaming ownership require separately
    reviewed completion plumbing; this wrapper intentionally exposes no bypass.
    """
    def __init__(self, session, budget):
        if not hasattr(session, '_retry_connection'):
            raise BudgetDeferred('unverified aiohttp retry behavior')
        session._retry_connection = False
        self._session, self._budget = session, budget

    @property
    def closed(self):
        return self._session.closed

    async def close(self):
        await self._session.close()

    @asynccontextmanager
    async def request(self, method, url, **kwargs):
        # RPC is synchronous and bounded; no queued executor work owns permits.
        admission = self._budget.admit(method, url)
        kwargs['allow_redirects'] = False
        response = None
        try:
            async with self._session.request(method, url, **kwargs) as response:
                yield response
        except BaseException:
            throttled = response is not None and response.status == 429
            self._budget.client.finish(admission.admission_id, '429_uncertain' if throttled else 'uncertain',
                                       retry_after_seconds(response.headers.get('Retry-After')) if throttled else None)
            raise
        self._budget.complete(admission, response, asynchronous=True)

    def get(self, url, **kwargs):
        return self.request('GET', url, **kwargs)

    def post(self, url, **kwargs):
        return self.request('POST', url, **kwargs)


_transport_budget = None


def configure_transport_budget(budget):
    """Trusted process bootstrap only; never exposed through member settings.

    Configure before constructing sessions/starting operations. No real endpoint
    inventory is bundled. Unactivated bot processes retain legacy behavior.
    """
    global _transport_budget
    _transport_budget = budget


def wrap_session(session):
    return BudgetSession(session, _transport_budget) if _transport_budget else session


def budgeted_request(send, method, url, **kwargs):
    if _transport_budget is None:
        return send(url, **kwargs)
    return _transport_budget.request(send, method, url, **kwargs)


def require_mapped_sdk(product):
    if _transport_budget is not None:
        _transport_budget.require_sdk(product)
