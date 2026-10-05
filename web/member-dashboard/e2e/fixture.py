"""Loopback-only synthetic composition. Never imported by the application."""
import asyncio
import json
from contextlib import asynccontextmanager
from io import BytesIO
from pathlib import Path
import sqlite3
import sys
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from fastapi import Request
from PIL import Image, ImageDraw
import uvicorn
from member_dashboard.app import create_app
from member_dashboard.settings import Settings
from member_dashboard.contracts import ContentLineage, SourceContribution, SectionResult
from member_dashboard.source_policy import SourcePolicy, SourcePermission
from member_dashboard.providers import ProviderRegistry, ProviderSpec, SymbolCatalog, ResearchCompletion
from member_dashboard.jobs import JobService
from member_dashboard.history import HistoryService
from member_dashboard.assistant import AssistantService
from member_dashboard.assistant_transport import ModelTurn
from member_dashboard.provider_runtime import ProviderRuntime
from member_dashboard.worker import ComputeWorker
from member_dashboard.publication import FeedService, Publisher, publishable
from member_dashboard.market_reader import SourceName, SourceRecord, MarketPayload

HOME = Path(__file__).resolve().parents[1] / '.e2e'
HOME.mkdir(exist_ok=True)
# A fresh file per run avoids wiping any existing file or reading machine state.
RUN = HOME / str(uuid4())
RUN.mkdir()
market = RUN / 'synthetic-market.sqlite3'
sqlite3.connect(market).close()
registry = ProviderRegistry(SymbolCatalog({'SPY':'ETF','QQQ':'ETF','AAPL':'equity','MSFT':'equity'}))
app = create_app(Settings(RUN/'synthetic-web.sqlite3', market,
    origin='https://localhost:3443', provider_registry=registry,
    feed_signing_key=b'synthetic-fixture-signing-key-only-32'))
store, auth = app.state.store, app.state.auth
store.migrate()
policy = SourcePolicy(store, authority_current=lambda:True, backup_compliant=lambda *_:True)
sources = [SourceContribution(source_id='synthetic', product_id='fixture', source_version='v1', policy_version='v1')]

def grant(allowed=True):
    policy.record(SourcePermission(source_id='synthetic',product_id='fixture',provider='fixture',
        policy_version='v1',audience='invited_members',status='allowed' if allowed else 'denied',
        display_raw=True,display_derived=True,retain=True,model_input=True,private_grant_ref='synthetic',evidence_ref='synthetic',
        terms_url='https://www.sec.gov/synthetic-terms',effective_at=0.0,
        attribution='Synthetic Exchange · demonstration data',delay_seconds=60.0,tombstone_allowed=True))

grant()
admin = str(uuid4())
with store.transaction() as con:
    con.execute('INSERT INTO members(id,username,password_hash,role,created_at) VALUES (?,?,?,?,?)',
        (admin,'fixture_admin',auth.hash_password('synthetic password only'),'admin',time.time()))

def metric(value, unit='USD', method='Synthetic fixture'):
    return dict(value=value,unit=unit,method=method)

def result(section):
    now = time.time()
    context = [dict(name='net_gamma',metric=metric(None,'USD'),observed_at=None,source_id='synthetic',source_version='v1')]
    payloads = {
      'analysis':dict(kind='analysis',summary='Synthetic breadth is improving, while event risk remains elevated.',direction='bullish',
        score=metric(72,'points'),catalysts=['Synthetic earnings window'],conflicts=['Momentum and valuation disagree'],
        levels=[dict(label='Reference support',price=metric(570))],risk_metrics=[metric(None,'percent')],context_metrics=context),
      'sec':dict(kind='sec',coverage='partial',warning='Some filing detail is unavailable.',filings=[dict(accession='synthetic-10q',form='10-Q',
        filed_at=now-86400,title='Quarterly filing',summary='Synthetic filing summary, not a company statement.',url='https://example.org/filing',detail_status='unavailable')],
        insiders=[dict(accession='synthetic-form4',summary='Synthetic routine transaction',conviction='routine',transaction_value=metric(None))]),
      'options':dict(kind='options',contracts=[dict(symbol='SYNTHETIC CALL',expiry='2026-10-09',side='call',strike=metric(580),volume=metric(0,'contracts'),
        open_interest=metric(None,'contracts'),premium=metric(125000),observed_at=now-130)],call_volume=metric(0,'contracts'),put_volume=None,
        put_call_ratio=metric(None,'ratio'),call_premium=metric(125000),put_premium=None,context_metrics=context),
    }
    if section.startswith('em_'):
        payload=dict(kind='move',horizon='daily' if section=='em_daily' else 'weekly',spot=metric(575),expiry='2026-10-09',
          ranges=[dict(method='ATM straddle',lower=metric(570),upper=metric(580),expected_move=metric(5))],
          quote_times=[dict(source_id='synthetic',input_kind=k,observed_at=now-130-i) for i,k in enumerate(['call','put','underlying','selection'])],
          chart_asset_id=None,context_metrics=context)
    else: payload=payloads[section]
    return SectionResult(section=section,status='completed',job_id=None,result_id=None,observed_at=now-130,computed_at=now,
        valid_until=now+1000,stale=False,analysis_version='fixture-v1',payload=payload,message=None,
        evidence=[dict(id='synthetic-evidence',source_id='synthetic',source_version='v1',observed_at=now-130,url='https://example.org/research',
            excerpt='Synthetic evidence <script>unsafe()</script>',research_only=True)])

def operation(ticker, section, inputs):
    time.sleep(1.5 if section=='analysis' else .15)
    if ticker=='QQQ' and section=='options':
        return result(section).model_copy(update={'status':'failed','payload':None,'message':'Section unavailable.'})
    value=result(section)
    if section.startswith('em_'):
        im=Image.new('RGB',(760,170),'#17191c'); draw=ImageDraw.Draw(im)
        draw.line([(45,115),(180,98),(320,112),(440,67),(610,79),(715,40)],fill='#8bd8bc',width=4)
        draw.text((25,15),'Synthetic expected range | text values below',fill='white')
        png=BytesIO(); im.save(png,format='PNG')
        return ResearchCompletion(value,png.getvalue())
    return value

for section in ['sec','analysis','options','em_daily','em_weekly']:
    registry.register(section,ProviderSpec(ContentLineage(sources=sources,required_features=[section],field_dependencies=[],retention_deadline=None),operation,'fixture',analysis_version='fixture-v1'))
app.state.source_policy=policy
app.state.research=JobService(store,auth,policy,registry)
app.state.history=HistoryService(app.state.research,signing_key=b'synthetic-fixture-signing-key-only-32',clock=time.time)
app.state.feed=FeedService(store,auth,policy,signing_key=b'synthetic-fixture-signing-key-only-32')
publisher=Publisher(store,policy)

def publish(version='v1', excerpt='Synthetic research: momentum is improving.', key='feed-one',feature='feed'):
    lineage=ContentLineage(sources=sources,required_features=[feature],field_dependencies=[],retention_deadline=None)
    record=SourceRecord(SourceName.ANALYST if feature=='feed' else SourceName.ALERT,key,'SPY',version,time.time()-130,None,None,'bullish',excerpt,
        MarketPayload(ticker='SPY',direction='bullish',excerpt=excerpt,score=72.0,price=575.0,
            entry=572.0 if feature=='setups' else None,target=582.0 if feature=='setups' else None,invalidation=568.0 if feature=='setups' else None),lineage=lineage)
    publisher.save(publishable(record),time.time())
publish(); publish(key='setup-one',feature='setups',excerpt='Synthetic setup with defined invalidation.')
runtime=ProviderRuntime(store,'browser-fixture')

class SyntheticAssistant:
    model='synthetic-web-only'
    fingerprint='synthetic-web-only-v1'
    enabled=True
    def available(self,now): return self.enabled
    async def complete(self,messages,schemas,budget):
        await asyncio.sleep(.1)
        if any('untrusted_evidence' in m and m.get('tool')=='lookup_market' for m in messages):
            return ModelTurn(answer='Observation: synthetic momentum is improving. Interpretation: more evidence is needed.',input_tokens=40,output_tokens=20)
        return ModelTurn(tool_calls=[{'name':'lookup_market','arguments':{'ticker':'SPY','limit':2}}],input_tokens=30,output_tokens=10)

assistant_transport=SyntheticAssistant()
app.state.assistant=AssistantService(app.state.history,transport=assistant_transport)
worker=ComputeWorker(app.state.research,registry,runtime,assistant=app.state.assistant)

@asynccontextmanager
async def lifespan(_):
    task=asyncio.create_task(worker.serve())
    yield
    task.cancel()
    try: await task
    except asyncio.CancelledError: pass
app.router.lifespan_context=lifespan

# Control exists solely in this test composition, never in production routers.
@app.post('/__fixture/control')
async def control(request:Request):
    command=await request.json()
    action=command['action']
    if action=='assistant': assistant_transport.enabled=command['enabled']
    if action=='invite':
        return {'token':auth.issue_invite_trusted(admin,time.time()).token}
    if action=='reset':
        with store.transaction() as con:
            member=con.execute('SELECT id FROM members WHERE username=?',(command['username'],)).fetchone()[0]
        return {'token':auth.issue_reset_trusted(admin,member,time.time()).token}
    if action=='conversation':
        identity=str(uuid4())
        with store.transaction() as con:
            member=con.execute('SELECT id FROM members WHERE username=?',(command['username'],)).fetchone()[0]
            con.execute('INSERT INTO conversations(id,member_id,title,created_at) VALUES (?,?,?,?)',
                (identity,member,'Synthetic saved conversation',time.time()))
            con.execute("INSERT INTO messages(id,conversation_id,member_id,role,content_json,created_at) VALUES (?,?,?,'user',?,?)",
                (str(uuid4()),identity,member,json.dumps({'text':'My saved question'}),time.time()))
        return {'id':identity}
    if action=='grant': policy.authority_current=lambda:command['allowed']
    if action=='feature':
        with store.transaction() as con:
            con.execute('UPDATE features SET enabled=?,version=version+1 WHERE name=?',(int(command['enabled']),command['feature']))
    if action=='expire':
        with store.transaction() as con: con.execute('UPDATE sessions SET revoked_at=?',(time.time(),))
    if action=='publish': publish(command['version'],command['excerpt'])
    if action=='freshness':
        with store.transaction() as con:
            con.execute('INSERT OR REPLACE INTO feed_source_status(source_id,available,checked_at,succeeded_at) VALUES (?,?,?,?)',('analyst_views',1,time.time(),time.time() if command['fresh'] else time.time()-100))
    if action=='delete': publisher.retract('feed-one','SPY',time.time())
    if action=='refresh_ready':
        with store.transaction() as con:
            con.execute('UPDATE web_jobs SET created_at=created_at-61 WHERE ticker=?',(command['ticker'],))
    if action=='stats':
        with store.transaction() as con:
            return {'jobs':con.execute('SELECT count(*) FROM web_jobs').fetchone()[0],
                    'calls':con.execute('SELECT count(*) FROM provider_calls').fetchone()[0],
                    'compute_charges':con.execute("SELECT count(*) FROM web_usage WHERE kind='research_compute'").fetchone()[0]}
    return {'ok':True}

if __name__=='__main__':
    uvicorn.run(app,host='127.0.0.1',port=3445,access_log=False,log_level='warning')
