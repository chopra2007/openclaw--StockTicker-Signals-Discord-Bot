"""Fixed Linux role composition. Missing external evidence is unavailable.

No provider credentials, imports, shell commands, grant flags or arbitrary URLs
are accepted from configuration. A live denial authority never implies a grant.
"""
import argparse
import asyncio
from contextlib import asynccontextmanager
import os
from pathlib import Path
import time
from .launch import read_private_json,protected

COMMON={'role','uid'}
WEB={'web_path','authority_socket','authority_uid'}
FIELDS={
 'api':COMMON|WEB|{'origin','signing_key','assistant_key_sha256','assistant_verified_until'},
 'supervisor':COMMON|WEB|{'market_path','cgroup_root','compute_uid','compute_gid','compute_config','control_socket','quota_uid'},
 'compute':COMMON|WEB|{'assistant_key','assistant_verified_until','budget_socket','schwab_credentials','schwab_state','analysis_settings'},
 'quota':COMMON|{'quota_path','budget_socket','control_socket','supervisor_uid','compute_uid','bot_uid','cgroup_root','assistant_daily_usd'},
 'authority':COMMON|{'journal_path','anchor_path','checkpoint_path','socket_path','read_uids','write_uids'},
 'archive':COMMON|{'archive_root','key_path','node_path'},
}
# Owner decisions 2026-10-05 (todo/member-dashboard-phaseC-kickoff.md): assistant through
# OpenRouter under a daily dollar cap; the owner holds data-provider permissions personally.
ASSISTANT_REQUEST_SCOPE='openrouter.requests'
ASSISTANT_COST_SCOPE='openrouter.usd'
ASSISTANT_DAILY_REQUESTS=5000
OWNER_GRANT_REF='owner-attested-2026-10-05'
OWNER_POLICY_VERSION='owner-2026-10-05'
BOT_PRODUCT='openclaw-bot-db'
# Research page sources (owner decision 1). Every send passes the quota broker.
SEC_SOURCE,SEC_PRODUCT='sec-edgar','edgar-public'
SCHWAB_SOURCE,SCHWAB_PRODUCT='schwab-marketdata','schwab-market-data'
SEC_SCOPE,SCHWAB_SCOPE='sec.requests','schwab.requests'
SEC_AGENT='OpenClaw Signal Engine (ak@openclaw.dev)'
# (scope, rolling window seconds, dashboard limit). SEC allows 10/s overall; Schwab ~120/min
# shared with the bot, which is not metered here, so the dashboard keeps a third of it.
# Schwab: the bot shares this app login; owner chose 15/min (2026-10-06) so the bot keeps its headroom.
PROVIDER_LIMITS=((SEC_SCOPE,60,300),(SCHWAB_SCOPE,60,15))
SYMBOLS=Path('/etc/member-dashboard/symbols.json')  # Written by provision.sh from SEC ticker lists.


def symbol_catalog(path=SYMBOLS):
    from .providers import SymbolCatalog
    import json
    try: symbols=json.loads(path.read_text(encoding='utf-8'))
    except (OSError,ValueError): return SymbolCatalog(available=False)
    return SymbolCatalog(symbols) if isinstance(symbols,dict) else SymbolCatalog(available=False)


def validate_config(config):
    role=config.get('role')
    if role not in FIELDS or set(config)!=FIELDS[role]: raise ValueError('invalid_fixed_role_config')
    for key,value in config.items():
        if key=='uid' or key.endswith('_uid') or key.endswith('_gid'):
            if type(value) is not int or value<0: raise ValueError('invalid_role_identity')
        if key.endswith(('_path','_root','_socket','_config')) or key in ('signing_key','assistant_key','schwab_credentials','schwab_state','analysis_settings'):
            if not isinstance(value,str) or not Path(value).is_absolute() or '..' in Path(value).parts:
                raise ValueError('explicit_absolute_path_required')
        if key.endswith('_uids'):
            if not isinstance(value,list) or not 1<=len(value)<=8 or any(type(v) is not int or v<0 for v in value):
                raise ValueError('invalid_authority_identities')
    if 'assistant_verified_until' in config and (type(config['assistant_verified_until']) not in (int,float)
            or not 0<config['assistant_verified_until']<1e10):
        raise ValueError('invalid_assistant_verification')
    if 'assistant_key_sha256' in config and (not isinstance(config['assistant_key_sha256'],str)
            or len(config['assistant_key_sha256'])!=64 or set(config['assistant_key_sha256'])-set('0123456789abcdef')):
        raise ValueError('invalid_assistant_key_digest')
    if 'assistant_daily_usd' in config and (type(config['assistant_daily_usd']) not in (int,float)
            or not 0<config['assistant_daily_usd']<=100):
        raise ValueError('invalid_assistant_budget')
    if role=='supervisor' and len({config['uid'],config['compute_uid'],config['quota_uid'],config['authority_uid']})!=4:
        raise ValueError('distinct_runtime_identities_required')
    if role=='quota' and len({config['uid'],config['supervisor_uid'],config['compute_uid'],config['bot_uid']})!=4:
        raise ValueError('distinct_quota_identities_required')
    if role in ('api','compute') and config['uid']==config['authority_uid']: raise ValueError('distinct_authority_identity_required')
    if role=='authority' and config['uid'] in config['read_uids']: raise ValueError('separate_authority_writer_required')
    return config


def load_config(path,role):
    config=validate_config(read_private_json(Path(path)))
    if os.name!='posix' or not hasattr(os,'getuid'): raise ValueError('linux_role_required')
    if config['role']!=role or os.getuid()!=config['uid']: raise ValueError('wrong_role_identity')
    return config


def authority_fresh(authority,*,seconds=5):
    """Positive source use only while the denial authority answers; cached briefly."""
    state={'until':0.0}
    def current():
        now=time.monotonic()
        if now<state['until']: return True
        try: authority.current()
        except Exception: return False
        state['until']=now+seconds
        return True
    return current


def member_feed_sources():
    """Owner request 2026-10-06: the feed shows analyst calls with their reasoning, setups come from
    bot alerts. Other bot tables carry no readable text (or duplicate alerts) and the raw-mention
    table is 1.5M rows whose scanning locked the database."""
    from .market_reader import SourceName
    return (SourceName.ANALYST,SourceName.ALERT)


def bot_feed_lineage(row):
    """Owner-attested lineage for rows read from the bot database (decision 1)."""
    from .contracts import ContentLineage,SourceContribution
    from .market_reader import SourceName
    # Raw mentions (~55k rows/day) are not member cards: 90-day feed retention would need ~12 GB.
    if row.source is SourceName.TICKER: return None
    feature='feed' if row.source in {SourceName.ANALYST,SourceName.SIGNAL,SourceName.TICKER} else 'setups'
    # source_version must equal the evidence version (row.version) or tools treat it as untracked.
    return ContentLineage(sources=[SourceContribution(source_id='bot-'+row.source.value.replace('_','-'),product_id=BOT_PRODUCT,
        source_version=row.version,policy_version=OWNER_POLICY_VERSION)],required_features=[feature],field_dependencies=[],retention_deadline=None)


def owner_permissions(source_ids,product_id,provider,terms_url,now):
    from .source_policy import SourcePermission
    return [SourcePermission(source_id=source,product_id=product_id,provider=provider,private_grant_ref=OWNER_GRANT_REF,
        policy_version=OWNER_POLICY_VERSION,audience='invited_members',status='allowed',display_raw=True,display_derived=True,
        retain=True,model_input=True,terms_url=terms_url,evidence_ref='todo/member-dashboard-phaseC-kickoff.md',
        effective_at=now,tombstone_allowed=True) for source in source_ids]


def ensure_scope(broker,scope,window,limit,now):
    """Owner-set dashboard allocation. Limit changes apply in place, keeping spend history."""
    expires=now+400*86400
    with broker.store.transaction() as con:
        updated=con.execute('UPDATE provider_quota_policy SET verified=1,verified_limit=?,bot_reserved=0,dashboard_allocated=?,'
            'safety_margin=0,expires_at=? WHERE scope_id=? AND window_seconds=?',(limit,limit,expires,scope,window)).rowcount
    if not updated:
        broker.configure_scope(scope,window_seconds=window,verified_limit=limit,bot_reserved=0,dashboard_allocated=limit,
                               safety_margin=0,verified=True,expires_at=expires)


def ensure_assistant_policy(broker,daily_usd,now):
    """Rolling 24-hour caps for the web assistant."""
    from .assistant_transport import QUOTA_ENDPOINT
    for scope,limit in ((ASSISTANT_REQUEST_SCOPE,ASSISTANT_DAILY_REQUESTS),(ASSISTANT_COST_SCOPE,float(daily_usd))):
        ensure_scope(broker,scope,86400,limit,now)
    broker.configure_endpoint(QUOTA_ENDPOINT,[ASSISTANT_REQUEST_SCOPE,ASSISTANT_COST_SCOPE],participation_verified=True,minimum_units=1e-9)


def provider_routes():
    from consensus_engine.utils.provider_budget import Route
    return {'sec':(Route('GET','https://www.sec.gov','/files/','sec.map',(SEC_SCOPE,)),
                   Route('GET','https://data.sec.gov','/submissions/','sec.submissions',(SEC_SCOPE,)),
                   Route('GET','https://www.sec.gov','/Archives/','sec.archives',(SEC_SCOPE,))),
            # No OAuth route: the dashboard never refreshes (see SchwabContext.refresh_allowed).
            'schwab':(Route('GET','https://api.schwabapi.com','/marketdata/v1/','schwab.marketdata',(SCHWAB_SCOPE,)),)}


def ensure_provider_policy(broker,now):
    for scope,window,limit in PROVIDER_LIMITS: ensure_scope(broker,scope,window,limit,now)
    for routes in provider_routes().values():
        for route in routes: broker.configure_endpoint(route.endpoint,list(route.scopes),participation_verified=True)


# The analysis payload mixes the collector's market data and the capped model write-up.
ANALYSIS_INPUTS={'analysis_collector':('analysis',)}


def research_lineages():
    """One definition for API and compute: job identity includes this exact lineage.
    Analysis = the !all computation on Schwab data (see analysis_collector)."""
    from .contracts import ContentLineage,SourceContribution
    def lineage(source,product,section):
        return ContentLineage(sources=[SourceContribution(source_id=source,product_id=product,source_version='v1',
            policy_version=OWNER_POLICY_VERSION)],required_features=[section],field_dependencies=[],retention_deadline=None)
    return {SEC_SOURCE:{'sec':lineage(SEC_SOURCE,SEC_PRODUCT,'sec')},
            SCHWAB_SOURCE:{section:lineage(SCHWAB_SOURCE,SCHWAB_PRODUCT,section) for section in ('options','em_daily','em_weekly','analysis')}}


def register_research_specs(registry):
    """API side: same descriptors as MemberResearchProvider.register, no clients or operations."""
    from .providers import ProviderSpec
    from .contracts import ContentLineage,FieldDependency
    def unavailable(*_): raise ValueError('api_never_computes')
    for source,sections in research_lineages().items():
        for section,lineage in sections.items():
            if section=='analysis':  # Same field dependencies ProviderContext adds on compute.
                value=lineage.model_dump()
                for features in ANALYSIS_INPUTS.values():
                    value['field_dependencies'].append(FieldDependency(field_path='payload',required_features=sorted(set(features))).model_dump())
                lineage=ContentLineage.model_validate(value)
            registry.register(section,ProviderSpec(lineage,unavailable,source,section in ('sec','analysis'),
                                                   analysis_version='member-research-v1'))
    return registry


class _NoSchwabAccess:
    """Credentials not provisioned: sections complete as 'unavailable', never fake data."""
    def get_option_chain(self,*_,**__): raise ValueError('schwab_not_provisioned')
    def get_price_history(self,*_,**__): raise ValueError('schwab_not_provisioned')
    def get_quote(self,*_,**__): raise ValueError('schwab_not_provisioned')


class _NoAnalysisSettings:
    """Exported bot settings missing: analysis completes as 'unavailable'."""
    async def __call__(self,ticker): raise ValueError('analysis_settings_missing')
    def services(self): raise ValueError('analysis_settings_missing')


def _waiting_budget(budget,routes):
    """Schwab calls wait (up to 25 s) for a free slot in the dashboard's per-minute share
    instead of failing a member's section as 'unavailable' (owner report 2026-10-06)."""
    from consensus_engine.utils.provider_budget import BudgetDeferred,TransportBudget
    class Waiting(TransportBudget):
        def admit(self,method,url):
            deadline=time.monotonic()+25
            while True:
                try: return super().admit(method,url)
                except BudgetDeferred as error:
                    if 'unmapped' in str(error) or time.monotonic()>=deadline: raise
                    time.sleep(2)
    return Waiting(budget,'dashboard',routes)


async def research_registry(registry,store,policy,runtime,config,*,telemetry=lambda event:None):
    """Compute side: SEC from public EDGAR, options/expected moves from Schwab."""
    import aiohttp,json
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from consensus_engine.scanners.sec_edgar import SecContext
    from consensus_engine.scanners.expected_move import ExpectedMoveSettings,render_chart
    from consensus_engine.utils.provider_budget import BudgetClient,BudgetSession,TransportBudget
    from .providers import ProviderContext
    from .research import MemberResearchProvider
    clock=lambda:datetime.now(ZoneInfo('America/Los_Angeles'))
    budget=BudgetClient(config['budget_socket'])
    routes=provider_routes()
    lineages=research_lineages()
    async def admit(_name): return True  # Pacing is the broker's job (sec.requests scope).
    sec=SecContext(BudgetSession(aiohttp.ClientSession(trust_env=False),TransportBudget(budget,'dashboard',routes['sec'])),
                   admit,clock,telemetry,user_agent=SEC_AGENT)
    contexts=[ProviderContext(policy,lineages[SEC_SOURCE],{},ExpectedMoveSettings(),clock,runtime,
                              budget,store,telemetry,SEC_SOURCE,sec_context=sec)]
    credentials,state=Path(config['schwab_credentials']),Path(config['schwab_state'])
    client=_NoSchwabAccess()
    if credentials.exists() and (state/'token.json').exists():
        from consensus_engine.scanners.schwab_client import PrivateTokenStore,SchwabClient,SchwabContext,TOKEN_URL,MD_BASE
        secret=json.loads(protected(credentials).read_text())
        client=SchwabClient(SchwabContext(secret['key'],secret['secret'],PrivateTokenStore(state),
            _waiting_budget(budget,routes['schwab']),clock,TOKEN_URL,MD_BASE,refresh_allowed=False))
    # Analysis: !all on Schwab data; the write-up shares the assistant's $3/day cap. Without the
    # exported bot settings file there is no collector and the section completes as unavailable.
    from .analysis_collector import AnalysisCollector,CappedSynthesis
    collector=_NoAnalysisSettings()
    settings_file=Path(config['analysis_settings'])
    if settings_file.exists():
        exported=json.loads(settings_file.read_text())
        synthesis=CappedSynthesis(protected(Path(config['assistant_key'])).read_text(encoding='ascii').strip(),budget,
                                  request_scopes=(ASSISTANT_REQUEST_SCOPE,),cost_scopes=(ASSISTANT_COST_SCOPE,))
        collector=AnalysisCollector(client,source_id=SCHWAB_SOURCE,filter_cfg=exported['technical_filters'],
                                    settings_values=exported['calculation'],synthesis=synthesis,telemetry=telemetry)
    contexts.append(ProviderContext(policy,lineages[SCHWAB_SOURCE],{SCHWAB_SOURCE:client},ExpectedMoveSettings(),clock,runtime,
                                    budget,store,telemetry,SCHWAB_SOURCE,chart_renderer=render_chart,
                                    analysis_collector=collector,input_dependencies=dict(ANALYSIS_INPUTS)))
    for context in contexts: MemberResearchProvider(context).register(registry)
    registry.analysis_collector=collector  # Reused for trade setup levels when idle.
    return registry


def web_store(config):
    from .store import WebStore
    from .authority_rpc import AuthorityClient
    store=WebStore(Path(config['web_path']));store.migrate()
    store.bind_authority(AuthorityClient(config['authority_socket'],config['authority_uid']))
    return store


def api_app(config):
    from . import testing_phase
    testing_phase.apply_flag()
    from .app import create_app
    from .settings import Settings
    from .runtime import FrontendObservation
    from .authority_rpc import AuthorityClient
    # API config has no source mount or compute configuration. This sentinel is
    # only the Settings path inequality guard; no MarketReader is constructed.
    web=Path(config['web_path'])
    key_path=protected(Path(config['signing_key']))
    if key_path.stat().st_size!=32: raise ValueError('signing_key_requires_32_bytes')
    key=key_path.read_bytes()
    if len(key)!=32: raise ValueError('signing_key_requires_32_bytes')
    from .assistant_transport import TransportDescriptor
    assistant=TransportDescriptor(config['assistant_key_sha256'],(ASSISTANT_REQUEST_SCOPE,),(),config['assistant_verified_until'],
                                  cost_scopes=(ASSISTANT_COST_SCOPE,))
    from .providers import ProviderRegistry
    app=create_app(Settings(web_path=web,market_path=web.parent/'no-market-access',origin=config['origin'],feed_signing_key=key,
                            assistant_transport=assistant,provider_registry=register_research_specs(ProviderRegistry(symbol_catalog()))))
    authority=AuthorityClient(config['authority_socket'],config['authority_uid'])
    observation=FrontendObservation();app.state.admin.frontend_observation=observation.snapshot
    app.state.source_policy.authority_current=authority_fresh(authority)
    for service in (app.state.admin,app.state.history,app.state.source_policy): service.denial_journal=authority
    @asynccontextmanager
    async def lifespan(_):
        import anyio.to_thread
        anyio.to_thread.current_default_thread_limiter().total_tokens=4
        app.state.store.migrate();app.state.store.bind_authority(authority)
        async def monitor():
            while True:
                await asyncio.to_thread(observation.probe);await asyncio.sleep(5)
        task=asyncio.create_task(monitor())
        try: yield
        finally: task.cancel();await asyncio.gather(task,return_exceptions=True)
    app.router.lifespan_context=lifespan
    app.state.feed.sources=member_feed_sources()
    return app


async def run_compute(config,worker):
    from uuid import UUID
    if str(UUID(worker))!=worker or os.getpid()!=1: raise ValueError('gated_compute_required')
    from .providers import ProviderRegistry
    from .provider_runtime import ProviderRuntime
    from .jobs import JobService
    from .source_policy import SourcePolicy
    from .auth import AuthService
    from .worker import ComputeWorker
    from .assistant import AssistantService
    from .assistant_transport import DirectTransport
    from .history import HistoryService
    from consensus_engine.utils.provider_budget import BudgetClient
    store=web_store(config)
    registry=ProviderRegistry(symbol_catalog())
    policy=SourcePolicy(store);policy.authority_current=authority_fresh(store.authority)
    policy.denial_journal=store.authority
    runtime=ProviderRuntime(store,worker)
    await research_registry(registry,store,policy,runtime,config)
    jobs=JobService(store,AuthService(store),policy,registry)
    history=HistoryService(jobs,signing_key=None,clock=time.time);history.denial_journal=store.authority
    key=protected(Path(config['assistant_key'])).read_text(encoding='ascii').strip()
    transport=DirectTransport(key,BudgetClient(config['budget_socket']),(ASSISTANT_REQUEST_SCOPE,),(),
                              config['assistant_verified_until'],cost_scopes=(ASSISTANT_COST_SCOPE,))
    assistant=AssistantService(history,transport=transport)
    from .setup_levels import refresh_one
    async def setup_levels():
        try: await refresh_one(store,registry.analysis_collector)
        except Exception: pass  # A chore; the next idle minute tries again.
    await ComputeWorker(jobs,registry,runtime,assistant=assistant,idle=setup_levels).serve()


def recover_worker_state(launcher,jobs,now):
    """Repeatable broker-to-web handoff; broker tombstones survive either crash."""
    workers=launcher.recover()
    if workers is None: return False
    for worker in workers: jobs.confirm_worker_exit(worker,now,reconciled=True)
    jobs.recover_expired_leases(now)
    for worker in workers: launcher.control.forget(worker)
    return True


def supervisor(config):
    from .compute_launcher import CgroupLauncher,ExitClient
    from .worker import WorkerSupervisor
    from .source_policy import SourcePolicy
    from .auth import AuthService
    from .market_reader import MarketReader
    from .publication import FeedService
    from .jobs import JobService
    from .providers import ProviderRegistry
    store=web_store(config)
    control=ExitClient(config['control_socket'],config['quota_uid'])
    launcher=CgroupLauncher(config['cgroup_root'],compute_uid=config['compute_uid'],compute_gid=config['compute_gid'],
        config=config['compute_config'],control=control)
    policy=SourcePolicy(store);policy.authority_current=authority_fresh(store.authority)
    policy.denial_journal=store.authority
    auth=AuthService(store)
    jobs=JobService(store,auth,policy,register_research_specs(ProviderRegistry(symbol_catalog())))
    feed=FeedService(store,auth,policy,signing_key=b'not-used-for-member-cursors-000000',reader=MarketReader(Path(config['market_path'])),
                     lineage_resolver=bot_feed_lineage,sources=member_feed_sources())
    worker=WorkerSupervisor(store,launcher,feed.feed_tick,jobs=jobs,reconcile=control.reconcile)
    try:
        while True:
            if worker.child is None:
                if not recover_worker_state(launcher,jobs,time.time()):
                    feed.feed_tick(time.time());time.sleep(1);continue
                worker.blocked=False  # tick rechecks any still-unknown web owner.
            # Each tick is an authority-fenced transaction; nothing it watches needs sub-second reaction.
            worker.tick();time.sleep(1)
    finally:
        if worker.child is not None:
            worker.child.kill_tree()
            deadline=time.monotonic()+5
            while not worker.child.is_dead() and time.monotonic()<deadline: time.sleep(.05)
            if worker.child.is_dead():
                jobs.confirm_worker_exit(worker.child.worker_id,time.time(),reconciled=False)
                worker.child.close()


def quota(config):
    from .store import WebStore
    from .quota_broker import QuotaBroker,BrokerServer
    from .exit_control import ExitRegistry,ExitControlServer
    protected(Path(config['quota_path']))  # Never silently replace a lost ledger.
    store=WebStore(Path(config['quota_path']));store.migrate()
    # Historical local booleans are not current account evidence. Keep all
    # accounting, but no allocation can reopen without the missing trusted
    # external account-policy integration.
    with store.transaction() as con:
        con.execute('UPDATE provider_quota_policy SET verified=0')
        con.execute('UPDATE quota_endpoints SET participation_verified=0')
    broker=QuotaBroker(store)
    ensure_assistant_policy(broker,config['assistant_daily_usd'],time.time())
    ensure_provider_policy(broker,time.time())
    registry=ExitRegistry(broker,supervisor_uid=config['supervisor_uid'],compute_uid=config['compute_uid'],cgroup_root=Path(config['cgroup_root']))
    with BrokerServer(broker,config['budget_socket'],uid_roles={config['compute_uid']:'dashboard',config['bot_uid']:'bot'}), ExitControlServer(registry,config['control_socket']):
        while True: time.sleep(1)


def authority(config):
    from .authority import DenialJournal,CheckpointStore
    from .authority_rpc import AuthorityService,AuthorityServer
    journal=DenialJournal(config['journal_path'],config['anchor_path'],checkpoint=CheckpointStore(config['checkpoint_path']))
    journal.restart_renew()  # Never auto-initialize lost authority; an intact chain may resume.
    journal.current()
    service=AuthorityService(journal,read_uids=config['read_uids'],write_uids=config['write_uids'])
    with AuthorityServer(service,config['socket_path']):
        while True:
            time.sleep(60);journal.renew()  # Denial continuity only, no positive rights.


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('role',choices=FIELDS);parser.add_argument('--config',required=True,type=Path)
    args=parser.parse_args();config=load_config(args.config,args.role)
    if args.role=='api':
        import uvicorn
        uvicorn.run(api_app(config),host='127.0.0.1',port=3445,workers=1,access_log=False,log_level='warning')
    elif args.role=='supervisor': supervisor(config)
    elif args.role=='quota': quota(config)
    elif args.role=='authority': authority(config)
    elif args.role=='archive':
        from .backup import maintain_archives,accounts_backup
        maintain_archives(config['archive_root'],key_path=Path(config['key_path']),node=Path(config['node_path']))
        staging=Path(config['archive_root'])/'web-snapshot.sqlite3'  # Written by the unit's root pre-step.
        if staging.exists(): accounts_backup(staging,config['archive_root'],key_path=Path(config['key_path']),node=Path(config['node_path']))
    else: raise ValueError('compute_requires_kernel_gate')


if __name__=='__main__': main()
