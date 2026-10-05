"""Explicit provider boundary. No credentials, bot imports or network defaults.

The symbol catalogue is an injected bounded metadata snapshot. Refreshing that
snapshot belongs to the worker; a member HTTP request never calls a provider.
Every registered operation runs through the one actual-work runtime. Concrete
transports must implement finite limits and Task4A metering before registration.
"""
from dataclasses import dataclass
import re
from types import MappingProxyType

from .contracts import ContentLineage, SectionResult


class SymbolError(ValueError):
    pass


class ProviderWait(Exception):
    """Safe runtime outcome; a waiter ending is not underlying-work completion."""
    def __init__(self, outcome):
        self.outcome = outcome


class SymbolCatalog:
    def __init__(self, symbols=None, *, available=True):
        symbols = symbols or {}
        if len(symbols) > 100_000:
            raise ValueError('symbol catalogue exceeds bound')
        self.symbols = MappingProxyType(dict(symbols))
        self.available = available

    def lookup(self, ticker):
        if not isinstance(ticker, str) or not 1 <= len(ticker) <= 16 or not re.fullmatch(r'[A-Za-z]{1,12}(?:[.-][A-Za-z]{1,3})?', ticker, re.ASCII):
            raise SymbolError('invalid_ticker')
        canonical = ticker.upper().replace('-', '.')
        if not self.available:
            raise SymbolError('symbol_lookup_unavailable')
        if canonical not in self.symbols:
            raise SymbolError('unknown_ticker')
        return canonical


@dataclass(frozen=True)
class ProviderSpec:
    lineage: ContentLineage
    operation: object
    provider: str
    asynchronous: bool = False
    analysis_version: str = 'v1'
    safe_input_version: str = 'v1'
    settings_hash: str = 'default'

    def descriptor(self):
        """Declared executable/input contract; a deployment must version code changes."""
        return dict(analysis_version=self.analysis_version,safe_input_version=self.safe_input_version,
                    settings_hash=self.settings_hash,provider=self.provider,asynchronous=self.asynchronous,
                    lineage=self.lineage.model_dump())


@dataclass(frozen=True)
class ComputeInputs:
    runtime: object
    call_id: str
    wait_timeout: float
    now: float
    safe_inputs: dict


class ProviderRegistry:
    def __init__(self, catalog=None):
        self.catalog = catalog or SymbolCatalog(available=False)
        self.providers = {}

    def register(self, section, spec):
        from .features import SECTIONS
        if section not in SECTIONS or not isinstance(spec, ProviderSpec) or section not in spec.lineage.required_features:
            raise ValueError('invalid provider specification')
        self.providers[section] = spec

    async def compute(self, ticker, section, inputs) -> SectionResult:
        spec = self.providers[section]
        saved = inputs.safe_inputs.get('provider_spec')
        if saved != spec.descriptor():
            raise ValueError('provider specification changed')
        def operation():
            # Recheck mutable lineage before actual invocation, after runtime admission.
            if saved != spec.descriptor():
                raise ValueError('provider specification changed')
            return spec.operation(ticker,section,inputs.safe_inputs)
        run = inputs.runtime.run_async if spec.asynchronous else inputs.runtime.run_blocking
        outcome = await run(inputs.call_id, operation, inputs.wait_timeout, provider=spec.provider)
        if outcome.status != 'completed':
            raise ProviderWait(outcome)
        return SectionResult.model_validate(outcome.value)
