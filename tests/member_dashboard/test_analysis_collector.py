"""Custom Stock Analysis for the web: !all computation on dashboard-reachable data."""
import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

FILTERS={'rvol_threshold':2.0,'rvol_lookback_days':20,'rsi_period':14,'ema_fast':9,'ema_slow':21,
         'price_change_min_pct':2.0,'atr_period':14,'atr_multiplier':1.5}
NOW=datetime(2026,6,25,14,36,tzinfo=ZoneInfo('America/Los_Angeles')).timestamp()


def history(days=60):
    import pandas as pd
    index=pd.date_range('2026-04-01',periods=days,freq='B',tz='America/New_York')
    closes=[100+i*0.5 for i in range(days)]
    return pd.DataFrame({'Open':[c-0.4 for c in closes],'High':[c+1 for c in closes],'Low':[c-1 for c in closes],
                         'Close':closes,'Volume':[1_000_000+i*1000 for i in range(days)]},index=index)


class Client:
    def __init__(self,fail=False): self.fail=fail
    def get_quote(self,ticker):
        if self.fail: raise RuntimeError('synthetic outage')
        return {'c':130.0,'pc':128.0,'o':129.0,'h':131.0,'l':128.5,'t':NOW}
    def get_price_history(self,ticker,**kwargs):
        if self.fail: raise RuntimeError('synthetic outage')
        return history()
    def get_option_chain(self,ticker,nearest):
        if self.fail: raise RuntimeError('synthetic outage')
        from test_sec_outcomes import synthetic_chain
        return synthetic_chain()


def collector(client,synthesis=None):
    from member_dashboard.analysis_collector import AnalysisCollector
    async def default(request): return ''
    return AnalysisCollector(client,source_id='schwab-marketdata',filter_cfg=FILTERS,settings_values={},
                             synthesis=synthesis or default,clock=lambda:NOW)


async def test_collector_builds_typed_inputs_with_the_bots_own_filters():
    from consensus_engine.analysis.technical_filters import run_filters
    from consensus_engine.analysis.research_contracts import ResearchInputs
    inputs=await collector(Client())('NVDA')
    assert type(inputs) is ResearchInputs and inputs.sanity_quote==130.0 and len(inputs.daily_candles)==60
    window=[dict(r) for r in inputs.daily_candles][-22:]
    expected=run_filters({'c':130.0,'pc':128.0},{'o':[c['open'] for c in window],'h':[c['high'] for c in window],
        'l':[c['low'] for c in window],'c':[c['close'] for c in window],'v':[int(c['volume']) for c in window]},'long',FILTERS)
    model=inputs.technical_long.model()
    assert [(f.name,f.value,f.passed) for f in model.filters]==[(f.name,f.value,f.passed) for f in expected]
    assert inputs.options_unusual.model().ticker=='NVDA'
    statuses={s.source_id:s.status for s in inputs.source_statuses}
    assert statuses['news']==statuses['youtube_levels']==statuses['analyst_posts']=='unavailable'
    assert {(e.source_id,e.source_version) for e in inputs.evidence}=={('schwab-marketdata','v1')}


async def test_collector_outage_stays_unavailable_never_fake():
    inputs=await collector(Client(fail=True))('NVDA')
    assert inputs.technical_long is None and inputs.options_unusual is None and inputs.sanity_quote is None
    assert inputs.daily_candles==() and inputs.evidence==()
    assert all(s.status=='unavailable' for s in inputs.source_statuses)


async def test_writeup_is_charged_to_the_assistant_dollar_cap(tmp_path,monkeypatch):
    from member_dashboard import analysis_collector as module
    from member_dashboard.store import WebStore
    from member_dashboard.quota_broker import QuotaBroker,Identity
    from member_dashboard.operations import ensure_assistant_policy,ASSISTANT_REQUEST_SCOPE,ASSISTANT_COST_SCOPE
    from consensus_engine.analysis.research_contracts import SynthesisRequest
    store=WebStore(tmp_path/'quota.sqlite3');store.migrate()
    broker=QuotaBroker(store,clock=lambda:NOW)
    who=Identity('dashboard','worker')
    class Budget:
        def reserve(self,scopes,caller,endpoint,units,attempt): return broker.reserve(scopes,who,endpoint,units,attempt)
        def finish(self,identity,outcome): return broker.finish(identity,who,outcome,None)
    sent=[]
    class Response:
        status=200
        def __init__(self):  # OpenRouter sends keep-alive newlines before the body.
            self.content=self
            self.parts=[b'\n\n',json.dumps({'model':module.MODEL,'choices':[{'finish_reason':'stop','message':{'content':'**TL;DR:** x'}}]}).encode()]
        async def read(self,limit): return self.parts.pop(0) if self.parts else b''
        async def __aenter__(self): return self
        async def __aexit__(self,*args): pass
    class Session:
        def __init__(self,**kwargs): assert kwargs['trust_env'] is False
        async def __aenter__(self): return self
        async def __aexit__(self,*args): pass
        def post(self,url,**kwargs): sent.append(kwargs['json']);return Response()
    monkeypatch.setattr(module.aiohttp,'ClientSession',Session)
    synthesis=module.CappedSynthesis('sk-or-synthetic',Budget(),request_scopes=(ASSISTANT_REQUEST_SCOPE,),cost_scopes=(ASSISTANT_COST_SCOPE,))
    request=SynthesisRequest('NVDA','{}','{}',('news',),(),(),30.0)
    per_call=synthesis.units(synthesis.body(request))[ASSISTANT_COST_SCOPE]
    ensure_assistant_policy(broker,per_call*1.5,NOW)  # Room for exactly one write-up.
    assert await synthesis(request)=='**TL;DR:** x'
    assert await synthesis(request)=='' and len(sent)==1  # Cap reached: no second send.
    assert sent[0]['model']==module.MODEL and sent[0]['max_tokens']==module.SYNTHESIS_OUTPUT_BOUND
    with store.transaction() as con:
        assert con.execute('SELECT units FROM provider_admissions WHERE scope_id=?',(ASSISTANT_COST_SCOPE,)).fetchone()[0]==pytest.approx(per_call)


async def test_member_analysis_section_completes_from_collected_inputs(dashboard):
    from member_dashboard.providers import ProviderContext,ProviderRegistry
    from member_dashboard.research import MemberResearchProvider
    from member_dashboard.source_policy import SourcePolicy
    from member_dashboard.operations import research_lineages,owner_permissions,SCHWAB_SOURCE,SCHWAB_PRODUCT,ANALYSIS_INPUTS
    from consensus_engine.scanners.expected_move import ExpectedMoveSettings
    policy=SourcePolicy(dashboard.store,authority_current=lambda:True)
    for permission in owner_permissions([SCHWAB_SOURCE],SCHWAB_PRODUCT,'schwab','https://developer.schwab.com/',0.0):
        policy.record(permission)
    calls=[]
    async def synthesis(request):
        calls.append(request)
        return '**TL;DR:** Synthetic thesis.\n\nBody.\n\n## Risk Considerations\n- Synthetic risk.'
    clock=lambda:datetime.fromtimestamp(NOW,ZoneInfo('America/Los_Angeles'))
    context=ProviderContext(policy,{'analysis':research_lineages()[SCHWAB_SOURCE]['analysis']},{SCHWAB_SOURCE:Client()},
        ExpectedMoveSettings(),clock,object(),object(),object(),lambda event:None,SCHWAB_SOURCE,
        analysis_collector=collector(Client(),synthesis),input_dependencies=dict(ANALYSIS_INPUTS))
    provider=MemberResearchProvider(context);provider.register(ProviderRegistry())
    result=await provider.compute('NVDA','analysis',{'enabled_features':['analysis']})
    assert result.status=='completed', result.message
    assert result.payload.summary and result.payload.direction in ('bullish','bearish','neutral','unclear')
    assert calls and calls[0].ticker=='NVDA'
    assert {e.source_id for e in result.evidence}=={SCHWAB_SOURCE}
