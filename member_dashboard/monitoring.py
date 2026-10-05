"""Fixed local observations, never logs, arbitrary probes, or service controls."""
import math
from typing import get_args
from .contracts import FeedSource
from .admin_contracts import AdminHealth,Observation,QueueHealth,UsageHealth,SourceFreshness,FailureCount

CADENCE=5
STALE_AFTER=15


def observe(store,component,instance_id,now,*,state,progress=False):
    if component not in ('supervisor','compute') or state not in ('idle','busy','draining','blocked'):
        raise ValueError('Unknown observation')
    if not isinstance(instance_id,str) or not 1<=len(instance_id)<=128 or not math.isfinite(now): raise ValueError('Invalid observation')
    with store.transaction() as con:
        con.execute('''INSERT INTO health_observations(component,instance_id,observed_at,progress_at,state) VALUES (?,?,?,?,?)
            ON CONFLICT(component) DO UPDATE SET instance_id=excluded.instance_id,observed_at=excluded.observed_at,
            progress_at=CASE WHEN health_observations.instance_id!=excluded.instance_id THEN excluded.progress_at
            ELSE coalesce(excluded.progress_at,health_observations.progress_at) END,state=excluded.state''',
            (component,instance_id,now,now if progress else None,state))


def snapshot(con,now):
    def observation(component):
        row=con.execute('SELECT observed_at,progress_at,state FROM health_observations WHERE component=?',(component,)).fetchone()
        if not row or row[0]>now: return Observation(status='unavailable')
        return Observation(status='responsive' if now-row[0]<STALE_AFTER else 'stale',observed_at=row[0],progress_at=row[1],state=row[2])
    queued=running=draining=0;oldest=None
    for table in ('web_jobs','assistant_runs'):
        for status,count,created in con.execute(f"SELECT status,count(*),min(created_at) FROM {table} WHERE status IN ('queued','running','draining') GROUP BY status"):
            if status=='queued': queued+=count;oldest=created if oldest is None else min(oldest,created)
            elif status=='running': running+=count
            else: draining+=count
    sources=[]
    for name in get_args(FeedSource):
        row=con.execute('SELECT checked_at,succeeded_at,available FROM feed_source_status WHERE source_id=?',(name,)).fetchone()
        sources.append(SourceFreshness(source=name,checked_at=row[0] if row else None,succeeded_at=row[1] if row else None,
            stale=not row or not row[2] or row[1] is None or not 0<=now-row[1]<30))
    failures={}
    for table in ('web_jobs','assistant_runs'):
        for code,count in con.execute(f"SELECT error_code,count(*) FROM {table} WHERE error_code IS NOT NULL AND created_at>=? GROUP BY error_code",(now-86400,)):
            safe=code if code in ('deadline','unavailable','unsupported','provider_failed') else 'unavailable'
            failures[safe]=failures.get(safe,0)+count
    row=con.execute('''SELECT count(*),count(actual_input_tokens),count(actual_output_tokens),count(cost),sum(actual_input_tokens),sum(actual_output_tokens),sum(cost),sum(CASE WHEN actual_input_tokens IS NOT NULL AND actual_output_tokens IS NOT NULL THEN 1 ELSE 0 END)
        FROM assistant_runs WHERE created_at>=?''',(now-86400,)).fetchone()
    return AdminHealth(checked_at=now,api=Observation(status='responsive',observed_at=now),frontend=Observation(status='unavailable'),
        supervisor=observation('supervisor'),compute=observation('compute'),
        queue=QueueHealth(queued=queued,running=running,draining=draining,oldest_age_seconds=max(0,now-oldest) if oldest is not None else None),
        sources=sources,failures=[FailureCount(code=k,count=v) for k,v in sorted(failures.items())],
        usage=UsageHealth(runs=row[0],known_usage_runs=row[7] or 0,input_tokens=row[4] if row[0] and row[1]==row[0] else None,
            output_tokens=row[5] if row[0] and row[2]==row[0] else None,cost=row[6] if row[0] and row[3]==row[0] else None))
