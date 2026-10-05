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


@dataclass(frozen=True)
class ProviderContext:
    """Trusted composition only; member safe_inputs cannot supply clients/state."""
    policy: object
    lineage: object
    clients: object
    settings: object
    clock: object
    runtime: object
    budget_client: object
    state: object
    telemetry: object
    primary_source: str
    fallback_allowlist: tuple[str, ...] = ()
    sec_context: object = None
    analysis_records: object = None
    analysis_services: object = None
    chart_renderer: object = None
    supplied_metrics: object = None
    input_dependencies: object = None

    def __post_init__(self):
        from datetime import datetime
        if any(item is None for item in (self.policy,self.settings,self.runtime,self.budget_client,self.state)):
            raise ValueError('Explicit provider dependencies required')
        instant=self.clock()
        if not isinstance(instant,datetime) or instant.tzinfo is None or instant.utcoffset() is None:
            raise ValueError('Aware provider clock required')
        lineage={key:ContentLineage.model_validate(value).model_copy(deep=True) for key,value in self.lineage.items()}
        # Each trusted mixed unit is indivisible: its declaration covers every
        # contributing field/evidence and every possible service response.
        from .contracts import Feature, FieldDependency
        from typing import get_args
        paths={}
        for name in ('analysis_records','analysis_services'):
            if getattr(self,name) is not None: paths[name]=('analysis','payload')
        for section,rows in (self.supplied_metrics or {}).items():
            if section not in lineage or len(rows)>20: raise ValueError('Invalid input dependencies')
            for index,_ in enumerate(rows): paths[f'supplied_metrics.{section}.{index}']=(section,'payload.context_metrics')
        declarations=dict(self.input_dependencies or {})
        if len(declarations)>102 or set(declarations)!=set(paths): raise ValueError('Complete input dependencies required')
        owned={}
        for path,values in declarations.items():
            if not isinstance(values,(list,tuple)) or not 1<=len(values)<=8 or any(v not in get_args(Feature) for v in values):
                raise ValueError('Invalid input dependencies')
            section,output=paths[path]
            if section not in lineage: raise ValueError('Invalid input dependencies')
            owned[path]=tuple(sorted(set(values)))
            value=lineage[section].model_dump()
            value['field_dependencies'].append(FieldDependency(field_path=output,required_features=list(owned[path])).model_dump())
            lineage[section]=ContentLineage.model_validate(value)
        object.__setattr__(self,'input_dependencies',MappingProxyType(owned))
        if self.analysis_records is not None:
            object.__setattr__(self,'analysis_records',MappingProxyType(dict(self.analysis_records)))
        object.__setattr__(self,'lineage',MappingProxyType(lineage))
        object.__setattr__(self,'clients',MappingProxyType(dict(self.clients)))
        object.__setattr__(self,'fallback_allowlist',tuple(self.fallback_allowlist))
        if self.supplied_metrics is not None:
            object.__setattr__(self,'supplied_metrics',MappingProxyType({key:tuple(values) for key,values in self.supplied_metrics.items()}))
        if any(source not in self.clients for source in self.fallback_allowlist):
            raise ValueError('Explicit fallback clients required')


@dataclass(frozen=True)
class ResearchCompletion:
    """Private worker handoff; bytes never enter a public response."""
    result: SectionResult
    png: bytes | None = None

    def __post_init__(self):
        if not isinstance(self.result,SectionResult): raise ValueError('Typed result required')
        if self.png is not None:
            if not isinstance(self.png,bytes) or not 8 <= len(self.png) <= 2_000_000 or not self.png.startswith(b'\x89PNG\r\n\x1a\n'):
                raise ValueError('Bounded PNG required')
            if self.result.section not in ('em_daily','em_weekly') or self.result.status != 'completed':
                raise ValueError('Chart parent must be completed expected move')


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
            # Re-read immediately before invoking the admitted operation. The
            # claim's feature snapshot is never permission to start later work.
            from .features import require_features
            lineage=ContentLineage.model_validate(spec.lineage.model_dump())
            with inputs.runtime.store.transaction() as con:
                if not require_features(con,lineage.required_features) or not require_features(con,inputs.safe_inputs.get('enabled_features',[])):
                    raise ValueError('feature_unavailable')
            return spec.operation(ticker,section,inputs.safe_inputs)
        run = inputs.runtime.run_async if spec.asynchronous else inputs.runtime.run_blocking
        outcome = await run(inputs.call_id, operation, inputs.wait_timeout, provider=spec.provider)
        if outcome.status != 'completed':
            raise ProviderWait(outcome)
        if isinstance(outcome.value,ResearchCompletion): return outcome.value
        return SectionResult.model_validate(outcome.value)
