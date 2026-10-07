"""Custom Stock Analysis for the web: !all computation on dashboard-reachable data."""
import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

FILTERS={'rvol_threshold':2.0,'rvol_lookback_days':20,'rsi_period':14,'ema_fast':9,'ema_slow':21,
         'price_change_min_pct':2.0,'atr_period':14,'atr_multiplier':1.5}
NOW=datetime(2026,6,25,14,36,tzinfo=ZoneInfo('America/Los_Angeles')).timestamp()


def history(days=260):
    import pandas as pd
    index=pd.date_range('2025-06-20',periods=days,freq='B',tz='America/New_York')
    closes=[100+i*0.1 for i in range(days)]
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
    def get_expirations(self,ticker):
        if self.fail: raise RuntimeError('synthetic outage')
        from test_sec_outcomes import synthetic_chain
        return synthetic_chain().expirations
    def get_option_chain(self,ticker,**kwargs):
        if self.fail: raise RuntimeError('synthetic outage')
        from test_sec_outcomes import synthetic_chain
        return synthetic_chain()


def collector(client,synthesis=None,news=(),notes=(),street=None):
    from member_dashboard.analysis_collector import AnalysisCollector
    from member_dashboard.street import Street
    async def default(request): return ''
    async def headlines(ticker,name): return list(news)
    async def wall_street(ticker): return street or Street('NVIDIA Corporation Common Stock',160.0,120.0,200.0,30,2,0,'2026-08-26')
    return AnalysisCollector(client,source_id='schwab-marketdata',filter_cfg=FILTERS,settings_values={},
                             synthesis=synthesis or default,clock=lambda:NOW,news=headlines,notes=lambda ticker:list(notes),
                             street=wall_street)


async def test_collector_builds_typed_inputs_with_the_bots_own_filters():
    from consensus_engine.analysis.technical_filters import run_filters
    from consensus_engine.analysis.research_contracts import ResearchInputs
    inputs=await collector(Client())('NVDA')
    assert type(inputs) is ResearchInputs and inputs.sanity_quote==130.0 and len(inputs.daily_candles)==260
    window=[dict(r) for r in inputs.daily_candles][-22:]
    expected=run_filters({'c':130.0,'pc':128.0},{'o':[c['open'] for c in window],'h':[c['high'] for c in window],
        'l':[c['low'] for c in window],'c':[c['close'] for c in window],'v':[int(c['volume']) for c in window]},'long',FILTERS)
    model=inputs.technical_long.model()
    assert [(f.name,f.value,f.passed) for f in model.filters]==[(f.name,f.value,f.passed) for f in expected]
    assert inputs.options_unusual.model().ticker=='NVDA'
    statuses={s.source_id:s.status for s in inputs.source_statuses}
    assert statuses['youtube_levels']==statuses['analyst_posts']=='unavailable'
    assert {(e.source_id,e.source_version) for e in inputs.evidence}=={('schwab-marketdata','v1')}


async def test_news_and_analyst_calls_reach_the_write_up():
    """Owner report 2026-10-06: the write-up was generic price talk with no news or catalysts."""
    from member_dashboard.news import Headline
    from consensus_engine.analysis.research_contracts import GapFillRequest
    made=collector(Client(),news=[Headline('Nvidia wins Stargate order','Reuters',NOW-3600,'https://example.com/a')],
                   notes=[('NVDA long into earnings, target 210',NOW-7200,'https://x.com/a/status/1')])
    inputs=await made('NVDA')
    assert any(e.id=='analyst-0' and 'target 210' in e.excerpt for e in inputs.evidence)
    gap=await made.services().gap_fill(GapFillRequest('NVDA',0,False,'long',NOW+20))
    assert gap.catalyst_research_snippets[0].startswith('Nvidia wins Stargate order (Reuters, ')
    assert gap.evidence[0].id=='news-0' and gap.evidence[0].url=='https://example.com/a'
    sent=[]
    async def write(request): sent.append(json.loads(request.structured_json)); return ''
    study=await made.study('NVDA',write=write)
    facts=sent[0]
    assert facts['news'][0]['title']=='Nvidia wins Stargate order' and 'target 210' in facts['analyst_calls'][0]['text']
    assert facts['wall_street']['target_average']==160.0 and facts['next_earnings']=='Aug 26, 2026' and facts['company']=='NVIDIA'
    assert len(sent)==2 and '## Outlook' in study.note  # Empty drafts twice: the plain note from facts.


class DetailClient(Client):
    """Schwab client with the richer quote the ticker report header reads (get_quote_details)."""
    def __init__(self,**extra): super().__init__(); self.extra=extra; self.bars=[]
    def get_quote_details(self,ticker):
        return {**self.get_quote(ticker),'v':5_000_000.0,'quote_time':NOW,'hi52':150.0,'lo52':90.0,'pe':31.26,'shares':2_000_000_000.0,
                'reg_change':2.0,'reg_time':NOW-3600,'ext_price':130.5,'ext_time':NOW-60,'name':'NVIDIA CORP',**self.extra}
    def get_price_history(self,ticker,**kwargs):
        self.bars.append(kwargs)
        if kwargs.get('interval')!='15m': return history()
        import pandas as pd
        index=pd.date_range('2026-06-22 09:30',periods=300,freq='15min',tz='America/New_York')
        return pd.DataFrame({'Open':1.0,'High':1.0,'Low':1.0,'Close':[100+i*0.1 for i in range(300)],'Volume':1},index=index)


async def test_report_header_gets_quote_stats_and_chart_from_one_richer_quote_and_one_extra_history_call():
    """Design round 2026-10-06: day change, after hours, key stats and a chart; SOUN-style tickers still get a price."""
    client=DetailClient()
    study=await collector(client).study('NVDA',chart=True)
    quote,chart=study.display['quote'],study.display['chart']
    assert quote['price']==130.0 and quote['change']==2.0 and quote['change_pct']==1.56 and quote['previous_close']==128.0
    assert (quote['open'],quote['high'],quote['low'],quote['volume'])==(129.0,131.0,128.5,5_000_000.0)
    assert quote['high_52w']==150.0 and quote['pe']==31.3 and quote['market_cap']==260_000_000_000
    assert quote['ext_label']=='After hours' and quote['ext_price']==130.5 and quote['ext_change']==0.5 and quote['ext_change_pct']==0.38
    assert quote['next_earnings']=='2026-08-26' and quote['avg_volume']>1_000_000
    assert study.display['company']=='NVIDIA'
    assert len(chart['daily'])==252 and len(chart['intraday'])==200 and all(len(p)==2 for p in chart['daily'])
    assert [k.get('interval') for k in client.bars]==['1d','15m']  # exactly one extra Schwab history call
    assert any(e.id=='schwab-quote-details' for e in study.result.evidence)
    # A report without the chart flag (trade setups, the assistant) makes no extra call and builds no display.
    plain=DetailClient()
    assert (await collector(plain).study('NVDA')).display is None and [k.get('interval') for k in plain.bars]==['1d']


async def test_report_header_leaves_out_what_schwab_did_not_give():
    study=await collector(DetailClient(pe=-15.4,ext_price=None,reg_change=None,shares=None,hi52=None,lo52=None)).study('NVDA',chart=True)
    quote=study.display['quote']
    assert quote['change']==2.0 and quote['price']==130.0  # change falls back to price minus previous close
    assert not {'pe','ext_price','ext_label','market_cap'}&set(quote)  # a loss-maker's negative P/E is left out
    assert quote['high_52w']>0 and quote['low_52w']>0  # 52-week range falls back to the daily candles


def test_schwab_quote_details_maps_the_report_fields_in_one_call():
    """Shape copied from a real /quotes?fields=quote,fundamental,extended,regular,reference answer (2026-10-06)."""
    from types import SimpleNamespace
    from consensus_engine.scanners.schwab_client import SchwabClient
    calls=[]
    entry={'quote':{'52WeekHigh':243.37,'52WeekLow':164.27,'closePrice':238.9,'openPrice':242.1,'highPrice':243.37,'lowPrice':238.93,
                    'totalVolume':101701855,'quoteTime':1791331196263,'tradeTime':1791331198060},
           'fundamental':{'peRatio':30.20808,'sharesOutstanding':24147000000},
           'extended':{'lastPrice':240.74,'tradeTime':1791349568000},
           'regular':{'regularMarketLastPrice':239.24,'regularMarketNetChange':0.34,'regularMarketPercentChange':0.14,'regularMarketTradeTime':1791316800444},
           'reference':{'description':'NVIDIA CORP'}}
    stub=SimpleNamespace(_get=lambda path,params:calls.append((path,params)) or {'NVDA':entry})
    got=SchwabClient.get_quote_details(stub,'NVDA')
    assert len(calls)==1 and calls[0][1]['fields']=='quote,fundamental,extended,regular,reference'
    assert got['c']==239.24 and got['pc']==238.9 and got['hi52']==243.37 and got['pe']==30.20808 and got['shares']==24147000000
    assert got['reg_change']==0.34 and got['ext_price']==240.74 and got['ext_time']==1791349568.0 and got['name']=='NVIDIA CORP'
    entry['fundamental']={}
    assert SchwabClient.get_quote_details(stub,'NVDA')['pe'] is None  # missing stays None, never zero


def test_member_report_payload_keeps_old_stored_reports_loadable():
    from member_dashboard.contracts import AnalysisPayload
    old=AnalysisPayload(summary='x',direction='neutral',score=None)
    assert old.quote is None and old.chart is None and old.company is None
    assert AnalysisPayload.model_validate(old.model_dump()).chart is None


def test_news_feed_keeps_recent_unique_headlines():
    from member_dashboard.news import parse
    item=lambda title,day,link='https://news.example/1':(f'<item><title>{title} - Reuters</title><link>{link}</link>'
        f'<pubDate>{day} Oct 2026 12:00:00 GMT</pubDate><source url="https://reuters.com">Reuters</source></item>')
    xml='<rss><channel>'+item('Fresh',5)+item('Fresh',5)+item('Old',1)+item('Bad link',5,'javascript:x')+'</channel></rss>'
    from datetime import datetime,timezone
    now=datetime(2026,10,12,tzinfo=timezone.utc).timestamp()  # Oct 5 is in the 7-day window, Oct 1 is not
    rows=parse(xml,now=now)
    assert [(r.title,r.source) for r in rows]==[('Fresh','Reuters')]


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
    request=SynthesisRequest('NVDA','{"ticker": "NVDA"}','{}',('news',),(),(),30.0)
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
    assert result.payload.quote.price==130.0 and result.payload.quote.change==2.0 and len(result.payload.chart.daily)==252
    assert result.payload.company=='NVIDIA'  # the plain Client has no richer quote: change = price minus previous close
    assert {e.source_id for e in result.evidence}=={SCHWAB_SOURCE}


def test_news_links_are_plain_article_addresses():
    """Owner 2026-10-06: Latest news must open the article; links stay https, no login or tracking query."""
    from member_dashboard.news import article_url
    assert article_url('https://www.barrons.com/articles/micron-x?mod=rss')=='https://www.barrons.com/articles/micron-x'
    assert article_url('javascript:alert(1)') is None and article_url('http://a.com/x') is None
    assert article_url('https://user:pw@a.com/x') is None and article_url('https://a.com:8443/x') is None
