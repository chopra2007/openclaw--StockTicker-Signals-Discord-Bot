"""Import isolation is checked in a fresh process, never a warm pytest cache."""
import subprocess
import sys
import pytest


def test_task6_provider_modules_import_without_bot_state():
    script = '''
import importlib.abc, sys, os
blocked = {'consensus_engine.config', 'consensus_engine.db', 'dotenv',
           'consensus_engine.utils.http', 'consensus_engine.utils.rate_limiter',
           'consensus_engine.utils.yahoo_limit', 'consensus_engine.alerts.ops_alert'}
attempts=[]
class Trap(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in blocked:
            attempts.append(fullname)
            raise AssertionError('operational import: '+fullname)
sys.meta_path.insert(0,Trap())
from consensus_engine.scanners import sec_edgar, expected_move, options, schwab_client
assert hasattr(schwab_client,'SchwabClient'), 'Isolated Schwab instance is missing'
assert attempts == [], attempts
'''
    result = subprocess.run([sys.executable,'-B','-c',script],text=True,capture_output=True,timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr


def test_task6_runtime_failure_paths_have_no_ambient_effects():
    script = r'''
import sys, os, importlib.abc, pathlib, datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo
attempts=[]
def forbidden(kind):
    attempts.append(kind)
    raise AssertionError(kind)
class Trap(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in {'consensus_engine.config','consensus_engine.db','consensus_engine.alerts.ops_alert','dotenv','yfinance'}:
            forbidden('import:'+fullname)
sys.meta_path.insert(0,Trap())
def audit(event,args):
    if event in {'socket.connect','socket.getaddrinfo','socket.sendto','subprocess.Popen','os.system'}:
        forbidden(event)
    if event=='open' and isinstance(args[0],(str,bytes)):
        value=os.fsdecode(args[0]).lower().replace('\\','/')
        if any(marker in value for marker in ('schwab_token','schwab_reauth','consensus.yaml','/.env','/vault/','/.openclaw/')):
            forbidden('private_file')
sys.addaudithook(audit)
original_getitem=type(os.environ).__getitem__
def environment(self,key):
    if any(marker in key.upper() for marker in ('API_KEY','APP_KEY','APP_SECRET','ACCESS_TOKEN','REFRESH_TOKEN')):
        forbidden('credential_environment')
    return original_getitem(self,key)
type(os.environ).__getitem__=environment
sys.path.insert(0,'tests/member_dashboard')
from test_sec_outcomes import synthetic_chain
from member_dashboard.providers import ProviderContext
from member_dashboard.research import MemberResearchProvider
from member_dashboard.contracts import ContentLineage,SourceContribution
from consensus_engine.scanners.expected_move import ExpectedMoveSettings
from consensus_engine.scanners.schwab_client import SchwabClient,SchwabContext,PrivateTokenStore,SchwabRefreshTokenExpired
source=SourceContribution(source_id='synthetic',product_id='fixture',source_version='s1',policy_version='p1')
class Client:
    mode='good'
    def get_option_chain(self,*args,**kwargs):
        if self.mode=='transport': raise RuntimeError('synthetic')
        value=synthetic_chain()
        if self.mode=='quality': value.calls['bid']=0
        return value
    def get_price_history(self,*args,**kwargs): raise RuntimeError('synthetic missing history')
client=Client()
context=ProviderContext(SimpleNamespace(authorize_lineage=lambda *args,**kwargs:SimpleNamespace(allowed=True)),
    {'em_daily':ContentLineage(sources=[source],required_features=['em_daily'],field_dependencies=[],retention_deadline=None)},
    {'synthetic':client},ExpectedMoveSettings(),lambda:datetime.datetime(2026,6,25,14,36,tzinfo=ZoneInfo('America/Los_Angeles')),
    object(),object(),object(),lambda event:None,'synthetic')
provider=MemberResearchProvider(context)
for mode in ('good','transport','quality'):
    client.mode=mode
    result=provider.compute_blocking('SPY','em_daily',{})
    assert (result.result.status if hasattr(result,'result') else result.status)==('completed' if mode=='good' else 'unavailable')
try: SchwabClient(None)
except ValueError: pass
else: raise AssertionError('missing settings accepted')
import tempfile
from consensus_engine.utils.provider_budget import TransportBudget
with tempfile.TemporaryDirectory() as temporary:
    directory=pathlib.Path(temporary)/'member-state'
    directory.mkdir(mode=0o700)
    state=PrivateTokenStore(directory)
    epoch=context.clock().timestamp()
    state.write({'creation_timestamp':epoch-3600,'_refresh_created':epoch-8*86400,
                 'token':{'access_token':'synthetic','refresh_token':'synthetic','expires_in':1800}})
    isolated=SchwabClient(SchwabContext('synthetic','synthetic',state,TransportBudget(None,'dashboard',[]),
                          context.clock,'https://unlisted.invalid/token','https://unlisted.invalid/market'))
    try:
        try: isolated.get_quote('SPY')
        except SchwabRefreshTokenExpired: pass
        else: raise AssertionError('expired refresh accepted')
        assert {p.name for p in directory.iterdir()}=={'token.json','refresh.lock','reauth.json'}
    finally: isolated.close()
assert attempts==[], attempts
'''
    result=subprocess.run([sys.executable,'-B','-c',script],text=True,capture_output=True,timeout=30)
    assert result.returncode==0,result.stdout+result.stderr


def test_research_import_has_no_operational_dependencies():
    script = '''
import importlib.abc, sys
blocked = ('consensus_engine.config', 'consensus_engine.db',
           'consensus_engine.scanners', 'consensus_engine.llm_client',
           'consensus_engine.alerts.discord', 'consensus_engine.utils.obs_log',
           'consensus_engine.alerts.all_command.aggregator',
           'consensus_engine.alerts.all_command.narrator',
           'consensus_engine.alerts.all_command.vault_writer')
class Trap(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if any(fullname == x or fullname.startswith(x + '.') for x in blocked):
            raise AssertionError('operational import: ' + fullname)
sys.meta_path.insert(0, Trap())
from consensus_engine.analysis.research_compute import compute_research
from consensus_engine.analysis.research_contracts import ResearchInputs, ResearchServices
'''
    result = subprocess.run([sys.executable, '-B', '-c', script], text=True,
                            capture_output=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize('shadow', [False, True])
def test_sparse_technical_ladder_keeps_injected_context_in_fresh_process(shadow):
    script = '''
import importlib.abc, sys, asyncio, runpy, dataclasses
from types import SimpleNamespace
attempts = []
class Trap(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in {'consensus_engine.config', 'consensus_engine.utils.obs_log'}:
            attempts.append(fullname)
            raise AssertionError('operational import: ' + fullname)
sys.meta_path.insert(0, Trap())
helpers = runpy.run_path('tests/member_dashboard/test_research_parity.py')
from consensus_engine.analysis.research_compute import compute_research
from consensus_engine.analysis.research_contracts import ResearchServices, GapFillResult, CalculationSettings, thaw_value
from consensus_engine.alerts.all_command import levels
def wall_clock():
    attempts.append('wall clock')
    raise AssertionError('unexpected wall clock')
levels.time = SimpleNamespace(time=wall_clock)
raw, inputs, settings, clock = helpers['prepared_case']('sparse_levels')
inputs = dataclasses.replace(inputs, youtube_levels=(), daily_candles=())
values = thaw_value(settings.values)
values['all_command']['levels'] = {'technical_engine_enabled': True,
                                  'technical_engine_shadow_mode': SHADOW}
events = []
async def gap(request): return GapFillResult()
async def synthesis(request): return ''
async def run():
    result = await compute_research('NVDA', inputs, ResearchServices(
        CalculationSettings(values), clock, synthesis, gap, events.append))
    assert result.trade_plan['confidence'] == 'low'
    fallback = [event for event in events if event.get('event') == 'sltp_atr_fallback']
    assert len(fallback) >= (2 if SHADOW else 1), events
    assert all(event['ts'] == clock.epoch for event in fallback)
    assert attempts == [], attempts
asyncio.run(run())
'''.replace('SHADOW', repr(shadow))
    result = subprocess.run([sys.executable, '-B', '-c', script], text=True,
                            capture_output=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr


def test_member_compute_fresh_process_traps_every_effect():
    script = '''
import importlib.abc, sys, os, asyncio, runpy, dataclasses
blocked = ('consensus_engine.config', 'consensus_engine.db', 'consensus_engine.scanners',
           'consensus_engine.api_adapters', 'consensus_engine.llm_client',
           'consensus_engine.alerts.discord', 'consensus_engine.utils.obs_log',
           'consensus_engine.utils.http', 'consensus_engine.analysis.technical',
           'consensus_engine.analysis.consolidation', 'consensus_engine.analysis.llm_scorer',
           'consensus_engine.alerts.all_command.aggregator',
           'consensus_engine.alerts.all_command.narrator',
           'consensus_engine.alerts.all_command.vault_writer')
attempts = []
class Trap(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if any(fullname == x or fullname.startswith(x + '.') for x in blocked):
            attempts.append(fullname)
            raise AssertionError('operational import: ' + fullname)
sys.meta_path.insert(0, Trap())
loop = asyncio.new_event_loop()  # Windows creates an internal loopback self-pipe.
def audit(event, args):
    if event in {'socket.connect', 'socket.getaddrinfo', 'socket.sendto',
                 'subprocess.Popen', 'os.system'}:
        attempts.append(event)
        raise AssertionError('forbidden effect: ' + event)
    if event == 'open' and isinstance(args[0], (str, bytes)):
        path = os.fsdecode(args[0]).lower().replace(chr(92), '/')
        mode, flags = args[1], args[2]
        if (mode and any(c in mode for c in 'wax+')) or flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT):
            attempts.append('write ' + path)
            raise AssertionError('forbidden write')
        if path.endswith(('.env', 'consensus.yaml', '.db', '.sqlite3', 'schwab_token.json')):
            attempts.append('private read ' + path)
            raise AssertionError('forbidden private read')
sys.addaudithook(audit)
helpers = runpy.run_path('tests/member_dashboard/test_research_parity.py')
from consensus_engine.analysis.research_compute import MemberResearchProvider
from consensus_engine.analysis.research_contracts import ResearchServices, GapFillResult, CalculationSettings, thaw_value, ConsolidationInput
async def run():
    for case in helpers['CASES']:
        raw, inputs, settings, clock = helpers['prepared_case'](case)
        events = []
        async def gap(request): return GapFillResult()
        async def synthesis(request):
            assert 'Synthetic private bot' not in repr(request)
            return ''
        provider = MemberResearchProvider({'NVDA': inputs}, ResearchServices(settings, clock, synthesis, gap, events.append))
        result = await provider.compute('NVDA')
        assert helpers['clean'](result.structured) == helpers['clean'](raw['capture']['render_inputs'][0]['structured'])
        assert result.evidence == inputs.evidence
        assert events
    raw, inputs, settings, clock = helpers['prepared_case']('bullish')
    values = thaw_value(settings.values)
    values['features'] = {name: {'enabled': True} for name in (
        'analyst_accuracy_weight', 'earnings_magnitude', 'sec_graduated_scoring',
        'options_graduated_scoring', 'cross_source_consolidation', 'manufactured_agreement_gate',
        'contradiction_index_live', 'finra_short_volume', 'short_interest', 'pead',
        'apewisdom_zscore', 'iv_rv_tag', 'vol_squeeze')}
    values['all_command']['levels'] = {'technical_engine_enabled': True, 'technical_engine_shadow_mode': False}
    enhanced = dataclasses.replace(inputs.score, sec_hit=True,
        sec_graduation={'has_form4': True, 'max_buy_dollars': 500000.0,
                        'plan_flag_seen': True, 'txn_date': '2026-10-05'},
        consolidation=ConsolidationInput(consensus_boost=20),
        finra_volume={'short_pct': 0.9, 'finra_published_at': clock.epoch},
        finra_baseline={'sample_days': 30, 'mean': 0.5, 'std': 0.05},
        short_interest={'published_at': clock.epoch, 'days_to_cover': 4.0, 'pct_change': 10},
        pead={'classification': 'drift-consistent', 'direction': 'long',
              'drift_pct': 5.0, 'days_since': 10})
    inputs = dataclasses.replace(inputs, score=enhanced)
    before = helpers['clean'](inputs)
    provider = MemberResearchProvider({'NVDA': inputs}, ResearchServices(CalculationSettings(values), clock, synthesis, gap, events.append))
    result = await provider.compute('NVDA')
    assert result.score_breakdown.finra_short_volume == 5
    assert result.score_breakdown.days_to_cover == 3
    assert result.score_breakdown.pead == 3
    assert helpers['clean'](inputs) == before
    assert attempts == [], attempts
try:
    loop.run_until_complete(run())
finally:
    loop.close()
'''
    result = subprocess.run([sys.executable, '-B', '-c', script], text=True,
                            capture_output=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
