"""Synthetic SEC wire responses exercise the real request and parse boundary."""
import asyncio
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest


def test_structured_sec_boundary_exists():
    source = Path('consensus_engine/scanners/sec_edgar.py').read_text(encoding='utf-8')
    assert 'async def fetch_filings_outcome(' in source, 'Structured SEC boundary is missing'


@pytest.fixture
def sec_wire():
    replies = {}
    requests = []
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers.get('Content-Length', 0)))
            self.do_GET()
        def do_GET(self):
            requests.append(self.path)
            status, value, headers = replies.get(self.path, (404, {}, {}))
            delayed_body=status=='timeout'
            if delayed_body: status=200
            if status == 'drop':
                self.connection.close()
                return
            self.send_response(status)
            for key, val in headers.items(): self.send_header(key, str(val))
            self.end_headers()
            if delayed_body:
                # Establish the real request/response before stalling its body.
                # A tiny connect deadline tests scheduler jitter instead.
                self.wfile.flush()
                __import__('time').sleep(1)
            try: self.wfile.write(value if isinstance(value, bytes) else json.dumps(value).encode())
            except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError): pass
        def log_message(self, *args): pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield SimpleNamespace(replies=replies, requests=requests,
                          origin=f'http://127.0.0.1:{server.server_port}')
    server.shutdown()
    server.server_close()
    thread.join(3)


def recent(*forms):
    return {'cik': 1, 'filings': {'recent': {
        'form': list(forms), 'filingDate': ['2026-10-05'] * len(forms),
        'acceptanceDateTime': ['2026-10-05T12:00:00Z'] * len(forms),
        'accessionNumber': [f'0000000001-26-{i:06}' for i in range(len(forms))],
        'primaryDocument': ['form4.xml'] * len(forms)}}}


class Meter:
    def __init__(self): self.reservations, self.finishes = [], []
    def reserve(self, *args):
        from consensus_engine.utils.provider_budget import Admission
        self.reservations.append(args)
        return Admission(True, str(len(self.reservations)))
    def finish(self, *args): self.finishes.append(args)


async def context(wire):
    import aiohttp
    from consensus_engine.scanners.sec_edgar import SecContext
    from consensus_engine.utils.provider_budget import BudgetSession, TransportBudget, Route
    meter = Meter()
    raw = aiohttp.ClientSession()
    session = BudgetSession(raw, TransportBudget(meter, 'dashboard', [Route('GET', wire.origin, '/', 'synthetic_sec', ('synthetic',))]))
    async def admit(*args): return True
    async def no_sleep(*args): pass
    events = []
    ctx = SecContext(session, admit, lambda: datetime(2026, 10, 5, 12, tzinfo=ZoneInfo('America/Los_Angeles')),
                     events.append, map_url=wire.origin + '/map', submissions_base=wire.origin,
                     archives_base=wire.origin, sleep=no_sleep)
    return ctx, session, meter, events


@pytest.mark.asyncio
@pytest.mark.parametrize('status,reason', [(403, 'access_refused'), (429, 'rate_limited'), (500, 'upstream_unavailable'), ('drop', 'transport_unavailable')])
async def test_http_failure_never_clean_empty(sec_wire, status, reason):
    from consensus_engine.scanners.sec_edgar import fetch_filings_outcome
    sec_wire.replies['/map'] = (200, {'0': {'ticker': 'SPY', 'cik_str': 1}}, {})
    sec_wire.replies['/CIK0000000001.json'] = (status, {}, {'Retry-After': '30'})
    ctx, session, meter, events = await context(sec_wire)
    try:
        result = await fetch_filings_outcome('SPY', 72, ctx)
        assert result.status == 'unavailable'
        assert result.data is None
        assert result.reason_code == reason
        if status == 429: assert result.retry_after == 30
        assert len(meter.reservations) == len(sec_wire.requests)
        assert all(set(event) <= {'event', 'reason_code', 'attempt'} for event in events)
    finally: await session.close()


def isolated_schwab(tmp_path, wire, *, expired=False):
    import os
    from consensus_engine.scanners.schwab_client import PrivateTokenStore, SchwabContext, SchwabClient
    from consensus_engine.utils.provider_budget import TransportBudget, Route
    state_dir=tmp_path/'isolated-state'
    state_dir.mkdir(mode=0o700)
    now=datetime(2026,10,5,12,tzinfo=ZoneInfo('America/Los_Angeles'))
    epoch=now.timestamp()
    token=state_dir/'token.json'
    token.write_text(json.dumps({'creation_timestamp':epoch-3600, '_refresh_created':epoch-(8*86400 if expired else 3600),
                               'token':{'access_token':'synthetic-old','refresh_token':'synthetic-refresh','expires_in':1800}}))
    os.chmod(token,0o600)
    meter=Meter()
    budget=TransportBudget(meter,'dashboard',[Route('GET',wire.origin,'/','synthetic_market',('synthetic',)),
                                             Route('POST',wire.origin,'/','synthetic_oauth',('synthetic',))])
    client=SchwabClient(SchwabContext('synthetic-key','synthetic-secret',PrivateTokenStore(state_dir),budget,
                                    lambda:now,wire.origin+'/token',wire.origin))
    return client,meter,state_dir


def test_schwab_refresh_isolated_state_and_each_send_budgeted(tmp_path,sec_wire,monkeypatch):
    import os
    sec_wire.replies['/token']=(200,{'access_token':'synthetic-new','expires_in':1800},{})
    sec_wire.replies['/quotes?symbols=SPY']=(200,{'SPY':{'quote':{'lastPrice':100}}},{})
    client,meter,directory=isolated_schwab(tmp_path,sec_wire)
    monkeypatch.setenv('HTTP_PROXY','http://127.0.0.1:1')
    monkeypatch.setenv('HTTPS_PROXY','http://127.0.0.1:1')
    try:
        assert client.get_quote('SPY')['c'] == 100
        assert sec_wire.requests == ['/token','/quotes?symbols=SPY']
        assert len(meter.reservations) == 2
        document=json.loads((directory/'token.json').read_text())
        assert document['token']['access_token'] == 'synthetic-new'
        assert document['token']['refresh_token'] == 'synthetic-refresh'
        if os.name == 'posix': assert (directory/'token.json').stat().st_mode & 0o777 == 0o600
        assert set(path.name for path in directory.iterdir()) == {'token.json','refresh.lock'}
    finally: client.close()


def test_schwab_expiry_never_uses_default_marker_or_fallback(tmp_path,sec_wire):
    from consensus_engine.scanners.schwab_client import SchwabRefreshTokenExpired
    client,meter,directory=isolated_schwab(tmp_path,sec_wire,expired=True)
    try:
        with pytest.raises(SchwabRefreshTokenExpired,match='refresh_expired'): client.get_quote('SPY')
        assert sec_wire.requests == [] and meter.reservations == []
        assert json.loads((directory/'reauth.json').read_text())['reason_code']=='refresh_expired'
    finally: client.close()


def test_schwab_missing_context_fails_closed():
    from consensus_engine.scanners.schwab_client import SchwabClient
    with pytest.raises(ValueError,match='Explicit isolated credentials'): SchwabClient(None)


def member_context(dashboard, clients, *, delay_seconds=0, **kwargs):
    from member_dashboard.providers import ProviderContext
    from member_dashboard.source_policy import SourcePolicy,SourcePermission
    from member_dashboard.contracts import ContentLineage,SourceContribution
    from consensus_engine.scanners.expected_move import ExpectedMoveSettings
    policy=SourcePolicy(dashboard.store,authority_current=lambda:True,backup_compliant=lambda *_:True)
    source_ids=tuple(clients) or ('synthetic',)
    sources=[]
    for source in source_ids:
        policy.record(SourcePermission(source_id=source,product_id='fixture',provider=source,policy_version='p1',
            audience='invited_members',status='allowed',display_raw=True,display_derived=True,retain=True,
            private_grant_ref='fixture',evidence_ref='fixture',terms_url='https://www.sec.gov/fixture',effective_at=0.0,
            delay_seconds=delay_seconds))
        sources.append(SourceContribution(source_id=source,product_id='fixture',source_version='s1',policy_version='p1'))
    now=datetime(2026,6,25,14,36,tzinfo=ZoneInfo('America/Los_Angeles'))
    lineage={section:ContentLineage(sources=sources,required_features=[section],field_dependencies=[],retention_deadline=None)
             for section in ('sec','options','em_daily','em_weekly','analysis')}
    return ProviderContext(policy,lineage,clients,ExpectedMoveSettings(),lambda:now,object(),object(),object(),
                           lambda event:None,source_ids[0],**kwargs)


def synthetic_chain():
    from consensus_engine.scanners.schwab_client import Chain
    from test_research_parity import _task6_decode
    raw=json.loads((Path(__file__).parent/'fixtures/task6_golden/em_weekly.json').read_text())
    bundle=_task6_decode(raw['inputs']['bundle'])
    calls,puts=bundle['calls'],bundle['puts']
    import pandas as pd
    expirations=raw['inputs']['expirations']
    calls=pd.concat([calls.assign(expiry=expiry) for expiry in expirations],ignore_index=True)
    puts=pd.concat([puts.assign(expiry=expiry) for expiry in expirations],ignore_index=True)
    # Explicit synthetic source observations; old golden inputs remain unchanged.
    observed=datetime(2026,6,25,14,10,tzinfo=ZoneInfo('America/Los_Angeles')).timestamp()
    calls['providerQuoteTime']=observed*1000
    puts['providerQuoteTime']=observed*1000
    return Chain(calls,puts,bundle['spot'],False,expirations,observed)


def test_member_moves_separate_horizons_history_failure_no_fallback(dashboard):
    from member_dashboard.research import MemberResearchProvider
    class Client:
        def __init__(self): self.calls=[]
        def get_option_chain(self,ticker,nearest): self.calls.append(('chain',nearest)); return synthetic_chain()
        def get_price_history(self,ticker,**kwargs): self.calls.append(('history',kwargs)); raise RuntimeError('synthetic failure')
    client=Client()
    provider=MemberResearchProvider(member_context(dashboard,{'synthetic':client}))
    daily=provider.compute_blocking('SPY','em_daily',{}).result
    weekly=provider.compute_blocking('SPY','em_weekly',{}).result
    assert daily.status==weekly.status=='completed'
    assert daily.payload.horizon=='daily' and weekly.payload.horizon=='weekly'
    assert daily.payload.expiry=='2026-06-26' and weekly.payload.expiry=='2026-07-02'
    assert daily.payload.ranges[0].lower.value==728.665
    assert weekly.payload.ranges[1].lower.value==721.1029844781859
    assert daily.payload.chart_asset_id is None
    assert len(client.calls)==8


@pytest.mark.parametrize('failure',['transport','quality','nan','missing_spot'])
def test_member_primary_failure_and_explicit_fallback(dashboard,failure):
    from member_dashboard.research import MemberResearchProvider
    class Client:
        def __init__(self,broken): self.broken=broken; self.calls=0
        def get_option_chain(self,ticker,nearest):
            self.calls+=1
            if self.broken and failure=='transport': raise RuntimeError('synthetic failure')
            chain=synthetic_chain()
            if self.broken and failure=='quality': chain.calls['bid']=0
            if self.broken and failure=='nan': chain.calls['openInterest']=float('nan')
            if self.broken and failure=='missing_spot': chain.underlying_price=None
            return chain
        def get_price_history(self,*args,**kwargs): return None
    primary,fallback=Client(True),Client(False)
    context=member_context(dashboard,{'synthetic':primary,'fallback':fallback})
    denied=MemberResearchProvider(context).compute_blocking('SPY','em_daily',{})
    assert denied.status=='unavailable' and fallback.calls==0
    from dataclasses import replace
    allowed=MemberResearchProvider(replace(context,fallback_allowlist=('fallback',))).compute_blocking('SPY','em_daily',{})
    assert allowed.result.status=='completed' and fallback.calls==1
    assert allowed.result.payload.quote_times[0].source_id=='fallback'


def test_member_options_undefined_ratio_null(dashboard):
    from member_dashboard.research import MemberResearchProvider
    chain=synthetic_chain()
    chain.calls['volume']=0
    chain.puts['volume']=0
    client=SimpleNamespace(get_option_chain=lambda *args,**kwargs:chain)
    result=MemberResearchProvider(member_context(dashboard,{'synthetic':client})).compute_blocking('SPY','options',{})
    assert result.status=='completed'
    assert result.payload.put_call_ratio.value is None
    assert result.payload.call_volume.value==0
    assert result.payload.contracts==[]


def test_options_fallback_requires_explicit_allowlist(dashboard):
    from dataclasses import replace
    from member_dashboard.research import MemberResearchProvider
    calls=[]
    def failed(*args,**kwargs): raise RuntimeError('synthetic primary failure')
    def fallback(*args,**kwargs): calls.append('fallback'); return synthetic_chain()
    context=member_context(dashboard,{'synthetic':SimpleNamespace(get_option_chain=failed),
                                      'fallback':SimpleNamespace(get_option_chain=fallback)})
    assert MemberResearchProvider(context).compute_blocking('SPY','options',{}).status=='unavailable' and calls==[]
    result=MemberResearchProvider(replace(context,fallback_allowlist=('fallback',))).compute_blocking('SPY','options',{})
    assert result.status=='completed' and calls==['fallback']
    assert result.evidence[0].source_id=='fallback'


@pytest.mark.parametrize('invalid_return',[False,True])
def test_member_chart_failure_preserves_numbers(dashboard,invalid_return):
    from member_dashboard.research import MemberResearchProvider
    def broken(result):
        if invalid_return: return b'not a chart'
        raise RuntimeError('synthetic rendering failure')
    client=SimpleNamespace(get_option_chain=lambda *args,**kwargs:synthetic_chain(),get_price_history=lambda *args,**kwargs:None)
    result=MemberResearchProvider(member_context(dashboard,{'synthetic':client},chart_renderer=broken)).compute_blocking('SPY','em_daily',{})
    assert result.result.status=='completed' and result.png is None


def test_real_chart_renders_with_private_cache(dashboard,tmp_path,monkeypatch):
    import pandas as pd
    from member_dashboard.research import MemberResearchProvider
    from consensus_engine.scanners.expected_move import render_chart
    cache=tmp_path/'mpl-private'; cache.mkdir(mode=0o700)
    monkeypatch.setenv('MPLCONFIGDIR',str(cache))
    history=pd.DataFrame({'Open':[730.,731,732,733,734],'High':[731.,732,733,734,735],
                          'Low':[729.,730,731,732,733],'Close':[730.5,731.5,732.5,733.5,734.5]},
                         index=pd.date_range('2026-06-25',periods=5,freq='5min',tz='America/Los_Angeles'))
    history['sourceObservedAt']=datetime(2026,6,25,14,10,tzinfo=ZoneInfo('America/Los_Angeles')).timestamp()
    client=SimpleNamespace(get_option_chain=lambda *args,**kwargs:synthetic_chain(),get_price_history=lambda *args,**kwargs:history)
    completion=MemberResearchProvider(member_context(dashboard,{'synthetic':client},chart_renderer=render_chart)).compute_blocking('SPY','em_daily',{})
    assert completion.result.status=='completed'
    assert completion.png.startswith(b'\x89PNG\r\n\x1a\n') and len(completion.png)<2_000_000


@pytest.mark.skipif(__import__('os').name!='posix',reason='real Linux state ownership proof')
def test_private_state_rejects_foreign_identity_and_modes(tmp_path):
    import os
    from consensus_engine.scanners.schwab_client import PrivateTokenStore
    folder=tmp_path/'web-private'; folder.mkdir(mode=0o700)
    store=PrivateTokenStore(folder)
    store.write({'token':{}})
    assert (folder/'token.json').stat().st_mode & 0o777==0o600
    (folder/'token.json').chmod(0o644)
    with pytest.raises(ValueError,match='ownership/mode'): store.load()
    (folder/'token.json').chmod(0o600)
    folder.chmod(0o755)
    with pytest.raises(ValueError,match='ownership/mode'): PrivateTokenStore(folder)
    folder.chmod(0o700)
    if os.geteuid()==0:
        os.chown(folder,65534,65534)
        try:
            with pytest.raises(ValueError,match='ownership/mode'): PrivateTokenStore(folder)
        finally: os.chown(folder,0,0)
    else:
        # The namespace/root variant exercises real foreign ownership too.
        assert folder.stat().st_uid==os.geteuid()


def test_context_metrics_require_explicit_matching_provenance(dashboard):
    from consensus_engine.analysis.research_contracts import DerivedContextMetric
    from member_dashboard.research import MemberResearchProvider
    good=DerivedContextMetric('iv_skew',None,'IV fraction','25-delta put IV minus call IV',None,'synthetic','s1')
    bad=DerivedContextMetric('net_gamma',1.0,'USD per 1% move','native gamma',None,'unknown','s1')
    client=SimpleNamespace(get_option_chain=lambda *args,**kwargs:synthetic_chain(),get_price_history=lambda *args,**kwargs:None)
    context=member_context(dashboard,{'synthetic':client},supplied_metrics={'em_daily':(good,bad,{'total_net_gex':0})},input_dependencies={f'supplied_metrics.em_daily.{i}':['options'] for i in range(3)})
    result=MemberResearchProvider(context).compute_blocking('SPY','em_daily',{}).result
    assert len(result.payload.context_metrics)==1
    row=result.payload.context_metrics[0]
    assert row.metric.value is None and row.observed_at is None
    assert row.metric.method==good.method and row.source_version=='s1'
    with pytest.raises(ValueError,match='Finite context'):
        DerivedContextMetric('risk',float('nan'),'USD','explicit',None,'synthetic','s1')


@pytest.mark.asyncio
async def test_analysis_model_use_requires_distinct_permission(dashboard):
    from dataclasses import replace
    from test_research_parity import prepared_case
    from consensus_engine.analysis.research_contracts import ResearchServices,GapFillResult
    from member_dashboard.research import MemberResearchProvider
    _,record,settings,clock=prepared_case('sparse_levels')
    record=replace(record,evidence=tuple(replace(row,source_id='synthetic',source_version='s1') for row in record.evidence),
                   source_statuses=tuple(replace(row,source_id='synthetic',source_version='s1') for row in record.source_statuses))
    calls=[]
    async def synthesis(request): calls.append('synthesis'); return ''
    async def gap(request): calls.append('gap'); return GapFillResult()
    services=ResearchServices(settings,clock,synthesis,gap,lambda event:None)
    context=member_context(dashboard,{},analysis_records={'NVDA':record},analysis_services=services,input_dependencies={'analysis_records':['analysis'],'analysis_services':['analysis']})
    result=await MemberResearchProvider(context).compute('NVDA','analysis',{'enabled_features':['analysis']})
    assert result.status=='completed' and calls==[]
    assert result.payload.score.value is not None and result.evidence[0].source_id=='synthetic'
    bad=replace(record,evidence=tuple(replace(row,source_id='unlisted') for row in record.evidence))
    result=await MemberResearchProvider(replace(context,analysis_records={'NVDA':bad})).compute('NVDA','analysis',{'enabled_features':['analysis']})
    assert result.status=='unavailable' and calls==[]


def form4(code='P', price='10', shares='100'):
    return f'''<ownershipDocument><reportingOwner><rptOwnerName>Synthetic Owner</rptOwnerName></reportingOwner>
    <nonDerivativeTransaction><transactionDate><value>2026-10-05</value></transactionDate>
    <transactionCode>{code}</transactionCode><transactionShares><value>{shares}</value></transactionShares>
    <transactionPricePerShare><value>{price}</value></transactionPricePerShare>
    <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode>
    </nonDerivativeTransaction></ownershipDocument>'''.encode()


@pytest.mark.asyncio
@pytest.mark.parametrize('body,status', [(b'<bad>', 'unavailable'), (b'<html/>', 'unavailable'),
    (form4(), 'ok'), (form4('A'), 'ok'), (form4(price=''), 'partial'), (form4(price='nan'), 'unavailable')])
async def test_real_form4_parse(sec_wire, body, status):
    from consensus_engine.scanners.sec_edgar import fetch_form4_outcome
    sec_wire.replies['/1/000000000126000000/form4.xml'] = (200, body, {})
    ctx, session, meter, _ = await context(sec_wire)
    try:
        outcome = await fetch_form4_outcome('0000000001', '0000000001-26-000000', 'xslF345X06/form4.xml', ctx)
        assert outcome.status == status
        if status == 'partial': assert outcome.data[0].price is None
        assert len(meter.reservations) == 1
    finally: await session.close()


@pytest.mark.asyncio
async def test_mixed_details_fetch_every_displayed_form4(sec_wire):
    from consensus_engine.scanners.sec_edgar import fetch_filings_outcome, fetch_form4_outcome
    from consensus_engine.analysis.sec_research import collect_sec
    sec_wire.replies['/map'] = (200, {'0': {'ticker': 'SPY', 'cik_str': 1}}, {})
    sec_wire.replies['/CIK0000000001.json'] = (200, recent(*(['4'] * 10)), {})
    for i in range(10):
        sec_wire.replies[f'/1/000000000126{i:06}/form4.xml'] = (200, form4('A') if i != 2 else b'<bad>', {})
    ctx, session, _, _ = await context(sec_wire)
    try:
        result = await collect_sec('SPY', lambda t,h: fetch_filings_outcome(t,h,ctx),
                                   lambda c,a,d: fetch_form4_outcome(c,a,d,ctx))
        assert result.coverage == 'partial'
        assert len(result.filings.data) == 10
        assert len(result.details) == 10
        assert sum(d.outcome is None for d in result.details) == 0
        assert sum(d.outcome is not None and d.outcome.status == 'ok' for d in result.details) == 9
        assert result.filings.data[0].url == 'https://www.sec.gov/Archives/edgar/data/1/000000000126000000/form4.xml'
    finally: await session.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('body,status', [({'0': {'ticker':'OTHER','cik_str':1}}, 'not_found'),
    ({'0': {'ticker':'SPY','cik_str':'bad'}}, 'unavailable'),
    ({'0': {'ticker':'OTHER','cik_str':1},'1':None}, 'unavailable')])
async def test_map_missing_symbol_and_invalid_cik(sec_wire, body, status):
    from consensus_engine.scanners.sec_edgar import resolve_cik_outcome
    sec_wire.replies['/map'] = (200, body, {})
    ctx, session, _, _ = await context(sec_wire)
    try: assert (await resolve_cik_outcome('SPY', ctx)).status == status
    finally: await session.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('status,expected,attempts',[(403,'access_refused',1),(429,'rate_limited',1),('timeout','transport_unavailable',3)])
async def test_map_wire_failures_are_budgeted(sec_wire,status,expected,attempts):
    from consensus_engine.scanners.sec_edgar import resolve_cik_outcome
    sec_wire.replies['/map']=(status,{'0':{'ticker':'SPY','cik_str':1}},{'Retry-After':'30'})
    ctx,session,meter,_=await context(sec_wire)
    if status=='timeout': ctx.timeout=.25
    try:
        result=await resolve_cik_outcome('SPY',ctx)
        assert result.status=='unavailable' and result.reason_code==expected
        assert len(meter.reservations)==attempts
        assert len(sec_wire.requests)==attempts
    finally: await session.close()


@pytest.mark.asyncio
async def test_invalid_row_survives_as_partial_not_empty(sec_wire):
    from consensus_engine.scanners.sec_edgar import fetch_filings_outcome
    sec_wire.replies['/map'] = (200, {'0': {'ticker': 'SPY', 'cik_str': 1}}, {})
    body = recent('8-K','4')
    body['filings']['recent']['filingDate'][0] = 'nonsense'
    sec_wire.replies['/CIK0000000001.json'] = (200, body, {})
    ctx, session, _, _ = await context(sec_wire)
    try:
        outcome = await fetch_filings_outcome('SPY', 72, ctx)
        assert outcome.status == 'partial' and len(outcome.data) == 1
        assert outcome.exclusions == ('invalid_filing_row',)
    finally: await session.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [b'{bad', {}, {'filings': {'recent': {}}}, {'cik': 'bad', 'filings': {'recent': recent()['filings']['recent']}},
                                    {'filings': {'recent': {'form': '4'}}}])
async def test_malformed_filings_unavailable(sec_wire, body):
    from consensus_engine.scanners.sec_edgar import fetch_filings_outcome
    sec_wire.replies['/map'] = (200, {'0': {'ticker': 'SPY', 'cik_str': 1}}, {})
    sec_wire.replies['/CIK0000000001.json'] = (200, body, {})
    ctx, session, _, _ = await context(sec_wire)
    try: assert (await fetch_filings_outcome('SPY', 72, ctx)).status == 'unavailable'
    finally: await session.close()


@pytest.mark.asyncio
async def test_successful_empty_and_missing_symbol_differ(sec_wire):
    from consensus_engine.scanners.sec_edgar import fetch_filings_outcome
    sec_wire.replies['/map'] = (200, {'0': {'ticker': 'SPY', 'cik_str': 1}}, {})
    sec_wire.replies['/CIK0000000001.json'] = (200, recent(), {})
    ctx, session, _, _ = await context(sec_wire)
    try:
        empty = await fetch_filings_outcome('SPY', 72, ctx)
        missing = await fetch_filings_outcome('MISSING', 72, ctx)
        assert empty.status == 'ok' and empty.data == ()
        assert missing.status == 'not_found' and missing.data is None
    finally: await session.close()


@pytest.mark.parametrize('missing',['column','value'])
def test_review_missing_option_price_never_asserts_zero(dashboard,missing):
    from member_dashboard.research import MemberResearchProvider
    chain=synthetic_chain()
    for frame in (chain.calls,chain.puts):
        if missing=='column': frame.drop(columns=['lastPrice'],inplace=True)
        else: frame['lastPrice']=None
    client=SimpleNamespace(get_option_chain=lambda *a,**k:chain)
    result=MemberResearchProvider(member_context(dashboard,{'synthetic':client})).compute_blocking('SPY','options',{})
    assert result.status=='unavailable'


@pytest.mark.parametrize('input_kind',['call','put','underlying'])
@pytest.mark.parametrize('timestamp',['fresh','missing','future'])
def test_review_em_delay_uses_each_price_observation(dashboard,input_kind,timestamp):
    from member_dashboard.research import MemberResearchProvider
    chain=synthetic_chain()
    client=SimpleNamespace(get_option_chain=lambda *a,**k:chain,get_price_history=lambda *a,**k:None)
    ctx=member_context(dashboard,{'synthetic':client},delay_seconds=900)
    now=ctx.clock().timestamp()
    for frame in (chain.calls,chain.puts):
        frame['providerQuoteTime']=(now-1200)*1000
        frame['lastTradeDate']=ctx.clock()-__import__('datetime').timedelta(days=1)
    chain.underlying_quote_time=now-1200
    value={'fresh':now,'missing':None,'future':now+1}[timestamp]
    if input_kind=='underlying': chain.underlying_quote_time=value
    else: getattr(chain,'calls' if input_kind=='call' else 'puts')['providerQuoteTime']=None if value is None else value*1000
    result=MemberResearchProvider(ctx).compute_blocking('SPY','em_daily',{})
    assert getattr(result,'result',result).status=='unavailable'


@pytest.mark.asyncio
async def test_review_sec_relevant_51st_filing_is_not_empty(dashboard,sec_wire):
    from dataclasses import replace
    from member_dashboard.research import MemberResearchProvider
    sec_wire.replies['/map']=(200,{'0':{'ticker':'SPY','cik_str':1}},{})
    sec_wire.replies['/CIK0000000001.json']=(200,recent(*(['S-8']*50+['8-K'])),{})
    ctx,session,_,_=await context(sec_wire)
    try:
        provider=MemberResearchProvider(replace(member_context(dashboard,{}),sec_context=ctx,clock=ctx.clock))
        result=await provider.compute('SPY','sec',{})
        assert result.status=='completed'
        assert len(result.payload.filings)==1
        assert result.payload.filings[0].form=='8-K'
        assert result.message is None
    finally: await session.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('code',['','X','J'])
async def test_review_unknown_form4_classification_not_routine(dashboard,sec_wire,code):
    from dataclasses import replace
    from member_dashboard.research import MemberResearchProvider
    sec_wire.replies['/map']=(200,{'0':{'ticker':'SPY','cik_str':1}},{})
    sec_wire.replies['/CIK0000000001.json']=(200,recent('4'),{})
    sec_wire.replies['/1/000000000126000000/form4.xml']=(200,form4(code),{})
    ctx,session,_,_=await context(sec_wire)
    try:
        provider=MemberResearchProvider(replace(member_context(dashboard,{}),sec_context=ctx,clock=ctx.clock))
        result=await provider.compute('SPY','sec',{})
        assert result.status=='completed' and result.payload.coverage=='partial'
        assert result.payload.insiders[0].conviction=='unknown'
        assert 'Routine' not in result.payload.insiders[0].summary
    finally: await session.close()


@pytest.mark.parametrize('history_time',['fresh','missing','partial','future','permitted'])
def test_review_history_observations_gate_chart_inputs(dashboard,history_time):
    import pandas as pd
    from member_dashboard.research import MemberResearchProvider
    chain=synthetic_chain()
    history=pd.DataFrame({name:[730.0]*5 for name in ('Open','High','Low','Close')})
    rendered=[]
    client=SimpleNamespace(get_option_chain=lambda *a,**k:chain,get_price_history=lambda *a,**k:history)
    ctx=member_context(dashboard,{'synthetic':client},delay_seconds=900,chart_renderer=lambda result:rendered.append(result.history.copy()))
    now=ctx.clock().timestamp()
    chain.underlying_quote_time=now-1500
    chain.calls['providerQuoteTime']=(now-1300)*1000
    chain.puts['providerQuoteTime']=(now-1200)*1000
    if history_time!='missing': history['sourceObservedAt']=now-(1000 if history_time=='permitted' else 0)
    if history_time=='partial': history.loc[2,'sourceObservedAt']=None
    if history_time=='future': history['sourceObservedAt']=now+1
    result=MemberResearchProvider(ctx).compute_blocking('SPY','em_daily',{}).result
    assert result.status=='completed'
    assert len(rendered[0])==(5 if history_time=='permitted' else 0)
    assert result.observed_at==now-(1000 if history_time=='permitted' else 1200)
    times={row.input_kind:row.observed_at for row in result.payload.quote_times}
    assert times['call']==now-1300 and times['put']==now-1200 and times['underlying']==now-1500
    assert ('history' in times)==(history_time=='permitted')


@pytest.mark.parametrize('observed',[None,1791223800])
def test_review_schwab_chain_preserves_explicit_spot_observation(tmp_path,sec_wire,observed):
    sec_wire.replies['/token']=(200,{'access_token':'synthetic-new','expires_in':1800},{})
    leg={'symbol':'SYNTHETIC','strikePrice':100,'bid':1,'ask':1.1,'last':1.05,
         'totalVolume':100,'openInterest':500,'volatility':20,'quoteTimeInLong':1791223800000}
    data={'status':'SUCCESS','underlyingPrice':100,'underlying':{'quoteTime':observed*1000 if observed else None},
          'callExpDateMap':{'2026-10-09:4':{'100':[leg]}},'putExpDateMap':{'2026-10-09:4':{'100':[leg]}}}
    sec_wire.replies['/chains?symbol=SPY&contractType=ALL&toDate=2026-10-09&includeUnderlyingQuote=true']=(200,data,{})
    client,meter,_=isolated_schwab(tmp_path,sec_wire)
    try:
        chain=client.get_option_chain('SPY',to_date='2026-10-09')
        assert chain.underlying_quote_time==observed
        assert chain.calls.iloc[0]['providerQuoteTime']==1791223800000
        assert len(sec_wire.requests)==len(meter.reservations)==2
    finally: client.close()


def test_borrowed_schwab_token_never_refreshes(tmp_path,sec_wire):
    from consensus_engine.scanners.schwab_client import SchwabError
    from dataclasses import replace
    client,meter,directory=isolated_schwab(tmp_path,sec_wire)
    client.context=replace(client.context,refresh_allowed=False)
    with pytest.raises(SchwabError,match='borrowed_token_stale'): client.get_quote('SPY')
    assert sec_wire.requests==[] and meter.reservations==[]
