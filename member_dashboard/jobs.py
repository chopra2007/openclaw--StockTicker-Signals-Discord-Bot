"""Private requests over durable shared market work, with transactional delivery."""
from dataclasses import dataclass
import hashlib
import json
import random
import sqlite3
from uuid import uuid4
from datetime import datetime, time as day_time, timedelta
from zoneinfo import ZoneInfo

from .auth import AuthError, Principal
from .contracts import ContentLineage, ResearchRequest, SectionResult
from .features import SECTIONS, feature_mask, mask_current, require_features
from .providers import SymbolError

TTL = {'analysis': 900, 'sec': 900, 'options': 300, 'em_daily': 300, 'em_weekly': 300}
DEADLINES = {'analysis': 180, 'sec': 90, 'options': 90, 'em_daily': 90, 'em_weekly': 90}


def move_boundary(now, expiry=None):
    """Conservative US session transitions, also valid on non-trading days.

    Early-close/special-session adapters must return an earlier valid_until.
    Calendar gates shorten cache life; they never make an observation fresh.
    """
    zone = ZoneInfo('America/Los_Angeles')
    local = datetime.fromtimestamp(now, zone)
    date = local.date()
    boundaries = [datetime.combine(date, day_time(hour, minute), zone).timestamp()
                  for hour, minute in [(0,0),(6,30),(13,0)]]
    boundaries.append(datetime.combine(date+timedelta(days=1),day_time(),zone).timestamp())
    boundary = min(stamp for stamp in boundaries if stamp > now)
    if expiry:
        try:
            expiry_date = datetime.strptime(expiry, '%Y-%m-%d').date()
            boundary = min(boundary,datetime.combine(expiry_date,day_time(13),zone).timestamp())
        except (TypeError,ValueError):
            # An uninterpretable contract expiry cannot be treated as cacheable.
            boundary = now
    return boundary


def packed(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def hashed(value):
    return hashlib.sha256(packed(value).encode()).hexdigest()


class ResearchError(Exception):
    def __init__(self, code, status=429):
        self.code, self.status = code, status


@dataclass(frozen=True)
class Job:
    id: str
    ticker: str
    kind: str
    input_fingerprint: str
    attempt_count: int
    lease_token: str
    inputs: dict

    @property
    def call_id(self):
        return self.id + ':' + self.lease_token


def empty_result(section, status='unavailable', *, job_id=None):
    return SectionResult(section=section, status=status, job_id=job_id, result_id=None,
        observed_at=None, computed_at=None, valid_until=None, stale=False,
        analysis_version='v1', payload=None, message=None)


class JobService:
    def __init__(self, store, auth, policy, registry, *, jitter=lambda: random.uniform(0, 1)):
        self.store, self.auth, self.policy, self.registry = store, auth, policy, registry
        self.jitter = jitter

    def _prepare(self, con, ticker, section, now):
        spec = self.registry.providers.get(section)
        if spec is None:
            return None
        mask = feature_mask(con)
        declared = ContentLineage.model_validate(spec.lineage.model_dump())
        required = sorted(set(declared.required_features +
                              ([name for name in SECTIONS if mask[name][0]] if section == 'analysis' else [])))
        if not require_features(con, required):
            return None
        lineage = declared.model_copy(update={'required_features': required})
        # Full grant metadata (not only the textual policy version) changes identity.
        grant_rows = []
        for source in lineage.sources:
            row = con.execute('SELECT * FROM source_permissions WHERE source_id=? AND product_id=? ORDER BY rowid DESC LIMIT 1',
                              (source.source_id, source.product_id)).fetchone()
            grant_rows.append(dict(row) if row else None)
        # Delay is enforced against the actual observation at completion/read.
        permitted = all(self.policy._authorize(con, lineage.sources, use, now).allowed
                        for use in ('retain', 'display_raw', 'display_derived'))
        if not permitted:
            return None
        saved_mask = {name: mask[name] for name in sorted(set(required) | (set(SECTIONS) if section == 'analysis' else set()))}
        metadata = {'analysis_version': spec.analysis_version, 'safe_input_version': spec.safe_input_version,
                    'settings_hash': spec.settings_hash, 'policy_stamp': hashed(grant_rows),
                    'provider_spec': spec.descriptor(),
                    'enabled_features': [name for name in (*SECTIONS,'feed','setups','assistant') if name in required],
                    'source_lineage': [source.model_dump() for source in lineage.sources]}
        key = hashed([ticker, section, lineage.model_dump(), metadata, saved_mask])
        return key, lineage, saved_mask, metadata

    def request_research(self, principal, ticker, refresh, now, *, guard=None):
        try:
            ticker = self.registry.catalog.lookup(ticker)
        except SymbolError as error:
            code = str(error)
            raise ResearchError(code, 503 if code == 'symbol_lookup_unavailable' else 422) from None
        with self.store.transaction() as con:
            con.row_factory = sqlite3.Row
            self.auth.revalidate(principal, now, con=con)
            if guard is not None: guard(con)
            self._endpoint_limit(con, principal, now)
            enabled = [name for name in SECTIONS if feature_mask(con)[name][0]]
            active = {r[0] for r in con.execute("SELECT DISTINCT r.ticker FROM research_requests r JOIN request_sections s ON s.request_id=r.id JOIN report_owners o ON o.id=r.report_owner_id WHERE r.member_id=? AND r.deleted_at IS NULL AND o.deleted_at IS NULL AND s.status IN ('queued','running')", (principal.member_id,))}
            if ticker not in active and len(active) >= 2:
                raise ResearchError('member_capacity')
            plans = []
            for section in enabled:
                prep = self._prepare(con, ticker, section, now)
                if prep is None:
                    plans.append((section, None, None, None))
                    continue
                key, lineage, mask, metadata = prep
                job = con.execute("SELECT * FROM web_jobs WHERE dedupe_key=? AND status IN ('queued','running','draining')", (key,)).fetchone()
                cached = None
                if not refresh:
                    candidate = con.execute('SELECT m.* FROM research_cache c JOIN market_results m ON m.id=c.result_id WHERE c.dedupe_key=? AND m.valid_until>?', (key, now)).fetchone()
                    if candidate is not None and self._read_result(con, candidate, now) is not None:
                        cached = candidate
                if refresh:
                    recent = con.execute('SELECT 1 FROM web_jobs WHERE ticker=? AND section=? AND created_at>? LIMIT 1', (ticker, section, now-60)).fetchone()
                    if recent:
                        raise ResearchError('refresh_cooldown')
                plans.append((section, prep, job, cached))
            new_count = sum(prep is not None and job is None and cache is None for _, prep, job, cache in plans)
            if new_count:
                pending = con.execute("SELECT count(*) FROM web_jobs WHERE status IN ('queued','running','draining')").fetchone()[0]
                if pending + new_count > 50:
                    raise ResearchError('global_capacity')
                charged = con.execute("SELECT count(*) FROM web_usage WHERE member_id=? AND kind='research_compute' AND occurred_at>?", (principal.member_id, now-3600)).fetchone()[0]
                if charged >= 10:
                    raise ResearchError('member_hourly_limit')
                con.execute("INSERT INTO web_usage(id,member_id,kind,units,occurred_at) VALUES (?,?,'research_compute',1,?)", (str(uuid4()), principal.member_id, now))
            request_id, owner_id, report_id = str(uuid4()), str(uuid4()), str(uuid4())
            con.execute('INSERT INTO report_owners(id,report_id,member_id,authorization_version,created_at) VALUES (?,?,?,?,?)', (owner_id, report_id, principal.member_id, principal.authorization_version, now))
            con.execute('INSERT INTO research_requests(id,member_id,session_id,report_owner_id,ticker,authorization_version,created_at) VALUES (?,?,?,?,?,?,?)', (request_id, principal.member_id, principal.session_id, owner_id, ticker, principal.authorization_version, now))
            for section, prep, job, cache in plans:
                job_id, result_id, status = None, None, 'unavailable'
                if cache is not None:
                    result_id, status = cache['id'], 'completed'
                elif prep is not None:
                    key, lineage, mask, metadata = prep
                    if job is None:
                        job_id = str(uuid4())
                        con.execute("INSERT INTO web_jobs(id,dedupe_key,ticker,section,status,created_at,policy_version,required_features_json,lineage_json,input_json,feature_mask_json) VALUES (?,?,?,?,'queued',?,?,?,?,?,?)",
                            (job_id, key, ticker, section, now, metadata['safe_input_version'], packed(lineage.required_features), lineage.model_dump_json(), packed(metadata), packed(mask)))
                        status = 'queued'
                    else:
                        job_id = job['id']
                        status = 'unavailable' if job['status'] == 'draining' else job['status']
                    con.execute('INSERT INTO job_subscribers(id,job_id,request_id,member_id,session_id,authorization_version,created_at,role) VALUES (?,?,?,?,?,?,?,?)',
                        (str(uuid4()), job_id, request_id, principal.member_id, principal.session_id, principal.authorization_version, now, principal.role))
                con.execute('INSERT INTO request_sections(request_id,section,status,job_id,result_id) VALUES (?,?,?,?,?)', (request_id, section, status, job_id, result_id))
            self._snapshot(con, request_id, now)
            return self._get_request(con, principal, request_id, now)

    def _endpoint_limit(self, con, principal, now):
        if con.execute("SELECT count(*) FROM web_usage WHERE member_id=? AND kind='research_endpoint' AND occurred_at>?", (principal.member_id, now-60)).fetchone()[0] >= 60:
            raise ResearchError('request_rate_limit')
        con.execute("INSERT INTO web_usage(id,member_id,kind,units,occurred_at) VALUES (?,?,'research_endpoint',1,?)", (str(uuid4()), principal.member_id, now))

    def _read_result(self, con, row, now, *, historical=False):
        """Historical owners need current rights, not original job generations.

        Only owned immutable history/assets opt in. Live request, cache and
        snapshot paths keep the default generation fence.
        """
        lineage = self.policy.stored_lineage(row)
        if lineage is None or not require_features(con, lineage.required_features):
            return None
        result = SectionResult.model_validate_json(row['content_json'])
        if not historical:
            job = con.execute('SELECT feature_mask_json FROM web_jobs WHERE id=?', (result.job_id,)).fetchone()
            if job is None or not mask_current(con, job[0]):
                return None
        decisions = [self.policy._authorize_lineage(con, lineage, use, now, result.observed_at)
                     for use in ('retain', 'display_raw', 'display_derived')]
        if not all(decision.allowed for decision in decisions):
            return None
        return result.model_copy(update={'stale': result.valid_until is None or result.valid_until <= now,
            'attributions': sorted({text for decision in decisions for text in decision.attributions}),
            'delay_seconds': max(decision.delay_seconds for decision in decisions)})

    def _get_request(self, con, principal, request_id, now):
        self.auth.revalidate(principal, now, con=con)
        request = con.execute('SELECT r.*,o.report_id FROM research_requests r JOIN report_owners o ON o.id=r.report_owner_id WHERE r.id=? AND r.member_id=? AND r.deleted_at IS NULL AND o.deleted_at IS NULL AND o.member_id=r.member_id', (request_id, principal.member_id)).fetchone()
        if request is None:
            return None
        sections = {}
        for row in con.execute('SELECT * FROM request_sections WHERE request_id=?', (request_id,)).fetchall():
            section = row['section']
            if not require_features(con, [section]):
                continue
            value = None
            if row['result_id']:
                result = con.execute('SELECT * FROM market_results WHERE id=?', (row['result_id'],)).fetchone()
                if result:
                    value = self._read_result(con, result, now)
            # A revoked session cannot be used by new sessions to recover pending output.
            valid_owner = request['authorization_version'] == principal.authorization_version
            sections[section] = value if value is not None and valid_owner else empty_result(section,
                row['status'] if not row['result_id'] and valid_owner else 'unavailable', job_id=row['job_id'])
        return ResearchRequest(id=request_id, report_id=request['report_id'], ticker=request['ticker'], sections=sections)

    def get_request(self, principal, request_id, now):
        with self.store.transaction() as con:
            con.row_factory = sqlite3.Row
            return self._get_request(con, principal, request_id, now)

    def claim_job(self, worker_id, now):
        with self.store.transaction() as con:
            con.row_factory = sqlite3.Row
            # Exactly one expensive lane across every process, including draining work.
            if con.execute("SELECT 1 FROM web_jobs WHERE status IN ('running','draining') LIMIT 1").fetchone():
                return None
            if con.execute("SELECT 1 FROM assistant_runs WHERE status IN ('running','draining') LIMIT 1").fetchone():
                return None
            rows = con.execute("SELECT * FROM web_jobs WHERE status='queued' AND coalesce(not_before,0)<=? AND attempts<3 ORDER BY created_at,rowid LIMIT 50", (now,)).fetchall()
            row = None
            for candidate in rows:
                lineage = ContentLineage.model_validate_json(candidate['lineage_json'])
                permission = all(self.policy._authorize(con,lineage.sources,use,now).allowed for use in ('retain','display_raw','display_derived'))
                subscribers = con.execute('SELECT * FROM job_subscribers WHERE job_id=? AND deleted_at IS NULL',(candidate['id'],)).fetchall()
                authorized = [sub for sub in subscribers if self._authorized_subscriber(con,sub,candidate,now)]
                prepared = self._prepare(con,candidate['ticker'],candidate['section'],now)
                matches = prepared is not None and prepared[0] == candidate['dedupe_key']
                if permission and authorized and matches:
                    row = candidate
                    break
                con.execute("UPDATE web_jobs SET status='unavailable',finished_at=? WHERE id=?",(now,candidate['id']))
                con.execute("UPDATE request_sections SET status='unavailable' WHERE job_id=?",(candidate['id'],))
                con.execute('UPDATE job_subscribers SET deleted_at=? WHERE job_id=? AND deleted_at IS NULL',(now,candidate['id']))
                for sub in subscribers:
                    if self._authorized_owner(con,sub,now):
                        self._snapshot(con,sub['request_id'],now)
            if row is None:
                return None
            generation = row['work_version'] + 1
            token = str(generation) + ':' + str(uuid4())
            con.execute("UPDATE web_jobs SET status='running',work_version=?,lease_token=?,worker_id=?,lease_until=?,started_at=?,attempts=attempts+1,actual_finished=0 WHERE id=?", (generation, token, worker_id, now+30, now, row['id']))
            con.execute("UPDATE request_sections SET status='running' WHERE job_id=? AND status='queued'", (row['id'],))
            return Job(row['id'], row['ticker'], row['section'], row['dedupe_key'], row['attempts']+1, token, json.loads(row['input_json']))

    def heartbeat(self, job_id, lease_token, now):
        with self.store.transaction() as con:
            return con.execute("UPDATE web_jobs SET lease_until=? WHERE id=? AND lease_token=? AND status IN ('running','draining')", (now+30, job_id, lease_token)).rowcount == 1

    def mark_draining(self, job_id, lease_token, now):
        with self.store.transaction() as con:
            if con.execute("UPDATE web_jobs SET status='draining',error_code='deadline' WHERE id=? AND lease_token=? AND status='running'", (job_id, lease_token)).rowcount:
                con.execute("UPDATE request_sections SET status='unavailable',message_code='deadline' WHERE job_id=?", (job_id,))

    def _authorized_owner(self, con, sub, now):
        owner = con.execute('SELECT r.deleted_at,o.deleted_at,r.subscriber_version,o.subscriber_version FROM research_requests r JOIN report_owners o ON o.id=r.report_owner_id WHERE r.id=? AND o.member_id=?', (sub['request_id'], sub['member_id'])).fetchone()
        if owner is None or owner[0] is not None or owner[1] is not None or owner[2] != sub['subscriber_version'] or owner[3] != sub['subscriber_version']:
            return False
        try:
            self.auth.revalidate(Principal(sub['member_id'], sub['role'], sub['session_id'], sub['authorization_version']), now, con=con)
        except AuthError:
            return False
        return True

    def _authorized_subscriber(self, con, sub, job, now):
        return (self._authorized_owner(con,sub,now) and mask_current(con,job['feature_mask_json'])
                and require_features(con,ContentLineage.model_validate_json(job['lineage_json']).required_features)
                and require_features(con,json.loads(job['required_features_json'])))

    def complete_job(self, job_id, lease_token, result, now, *, png=None):
        result = SectionResult.model_validate(result)
        if png is not None:
            from .assets import validate_png
            validate_png(png)
            if result.section not in ('em_daily','em_weekly') or result.status != 'completed' or result.payload is None:
                raise ValueError('Chart requires completed expected-move parent')
        with self.store.transaction() as con:
            con.row_factory = sqlite3.Row
            job = con.execute("SELECT * FROM web_jobs WHERE id=? AND lease_token=? AND status IN ('running','draining')", (job_id, lease_token)).fetchone()
            if job is None:
                return
            if result.section != job['section'] or result.status not in ('completed', 'unavailable', 'failed'):
                raise ValueError('invalid terminal result')
            if result.status == 'completed' and result.analysis_version != json.loads(job['input_json'])['analysis_version']:
                raise ValueError('result analysis version differs from claimed job')
            lineage = ContentLineage.model_validate_json(job['lineage_json'])
            tracked = {(source.source_id,source.source_version) for source in lineage.sources}
            if any((item.source_id,item.source_version) not in tracked for item in result.evidence):
                raise ValueError('evidence absent from source lineage')
            decisions = [self.policy._authorize_lineage(con, lineage, use, now, result.observed_at) for use in ('retain', 'display_raw', 'display_derived')]
            subscribers = con.execute('SELECT * FROM job_subscribers WHERE job_id=? AND deleted_at IS NULL', (job_id,)).fetchall()
            permitted = all(decision.allowed for decision in decisions) and any(
                self._authorized_subscriber(con, sub, job, now) for sub in subscribers)
            deadlines = [decision.retention_deadline for decision in decisions if decision.retention_deadline is not None]
            if deadlines:
                lineage = lineage.model_copy(update={'retention_deadline':min(deadlines)})
            result_id = None
            status = result.status if permitted else 'unavailable'
            if status == 'completed':
                result_id = str(uuid4())
                asset_id = str(uuid4()) if png is not None else None
                if result.section in ('em_daily','em_weekly') and result.payload is not None:
                    result = result.model_copy(update={'payload': result.payload.model_copy(update={'chart_asset_id':asset_id})})
                result = result.model_copy(update={
                    'attributions':sorted({text for decision in decisions for text in decision.attributions}),
                    'delay_seconds':max(decision.delay_seconds for decision in decisions)})
                limits = [now+TTL[job['section']]]
                if result.valid_until is not None: limits.append(result.valid_until)
                if lineage.retention_deadline is not None: limits.append(lineage.retention_deadline)
                if job['section'] in ('em_daily','em_weekly'):
                    limits.append(move_boundary(now,result.payload.expiry if result.payload else None))
                result = result.model_copy(update={'job_id': job_id, 'result_id': result_id, 'valid_until': min(limits), 'computed_at': now})
                con.execute('INSERT INTO market_results(id,fingerprint,ticker,section,analysis_version,content_json,source_lineage_json,field_dependencies_json,required_features_json,retention_deadline,observed_at,computed_at,valid_until,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    (result_id, hashed([job['dedupe_key'], lease_token]), job['ticker'], job['section'], result.analysis_version, result.model_dump_json(), packed([s.model_dump() for s in lineage.sources]), packed([d.model_dump() for d in lineage.field_dependencies]), packed(lineage.required_features), lineage.retention_deadline, result.observed_at, now, result.valid_until, now))
                con.execute('INSERT INTO research_cache(dedupe_key,result_id) VALUES (?,?) ON CONFLICT(dedupe_key) DO UPDATE SET result_id=excluded.result_id', (job['dedupe_key'], result_id))
                if asset_id is not None:
                    from .assets import store_chart
                    store_chart(result_id, png, con=con, asset_id=asset_id, lineage=lineage, now=now)
            con.execute('UPDATE web_jobs SET status=?,result_id=?,finished_at=?,lease_until=NULL,actual_finished=1 WHERE id=? AND lease_token=?', (status, result_id, now, job_id, lease_token))
            for sub in con.execute('SELECT * FROM job_subscribers WHERE job_id=? AND deleted_at IS NULL', (job_id,)).fetchall():
                if self._authorized_subscriber(con, sub, job, now):
                    con.execute('UPDATE request_sections SET status=?,result_id=? WHERE request_id=? AND job_id=?', (status, result_id, sub['request_id'], job_id))
                    self._snapshot(con, sub['request_id'], now)
                else:
                    con.execute('UPDATE job_subscribers SET deleted_at=? WHERE id=?', (now, sub['id']))
                    con.execute("UPDATE request_sections SET status='unavailable',result_id=NULL WHERE request_id=? AND job_id=?", (sub['request_id'], job_id))
                    if self._authorized_owner(con,sub,now):
                        self._snapshot(con,sub['request_id'],now)

    def _snapshot(self, con, request_id, now):
        owner = con.execute('SELECT o.*,r.session_id,r.authorization_version AS request_authorization_version,m.role FROM report_owners o JOIN research_requests r ON r.report_owner_id=o.id JOIN members m ON m.id=r.member_id WHERE r.id=? AND r.deleted_at IS NULL AND o.deleted_at IS NULL AND o.member_id=r.member_id AND o.subscriber_version=r.subscriber_version', (request_id,)).fetchone()
        if owner is None:
            return
        try:
            self.auth.revalidate(Principal(owner['member_id'],owner['role'],owner['session_id'],owner['request_authorization_version']),now,con=con)
        except AuthError:
            return
        rows = con.execute('SELECT m.* FROM request_sections s JOIN market_results m ON m.id=s.result_id WHERE s.request_id=?', (request_id,)).fetchall()
        values, sources, features, fields, deadlines = {}, {}, set(), [], []
        for row in rows:
            result = self._read_result(con, row, now)
            if result is None:
                continue
            values[row['section']] = result.model_dump()
            lineage = self.policy.stored_lineage(row)
            for source in lineage.sources: sources[packed(source.model_dump())] = source.model_dump()
            features.update(lineage.required_features)
            fields.extend(d.model_dump() for d in lineage.field_dependencies)
            if lineage.retention_deadline is not None: deadlines.append(lineage.retention_deadline)
        sections = con.execute('SELECT section,status,job_id FROM request_sections WHERE request_id=?',(request_id,)).fetchall()
        finalized = not any(section['status'] in ('queued','running') for section in sections)
        content_free = not values
        # An existing authorized report still needs a terminal workflow version
        # after all source content is withdrawn. Empty lineage grants no source
        # access; these envelopes carry neither content nor old observation IDs.
        if content_free and not finalized:
            return
        for section in sections:
            if content_free:
                values[section['section']] = empty_result(section['section'],
                    'failed' if section['status'] == 'failed' else 'unavailable').model_dump()
            elif section['section'] not in values:
                values[section['section']] = empty_result(section['section'],
                    'unavailable' if section['status'] == 'completed' else section['status'],
                    job_id=section['job_id']).model_dump()
        version = con.execute('SELECT coalesce(max(version),0)+1 FROM report_versions WHERE report_id=?', (owner['report_id'],)).fetchone()[0]
        identity = str(uuid4())
        con.execute('INSERT INTO report_versions(id,report_id,version,content_json,source_lineage_json,field_dependencies_json,required_features_json,retention_deadline,created_at,finalized) VALUES (?,?,?,?,?,?,?,?,?,?)',
            (identity, owner['report_id'], version, packed(values), packed(list(sources.values())), packed(fields), packed(sorted(features)), min(deadlines) if deadlines else None, now, int(finalized)))
        con.execute('UPDATE report_owners SET current_version_id=? WHERE id=? AND deleted_at IS NULL', (identity, owner['id']))
        from .contracts import ReportRef
        return ReportRef(id=owner['report_id'],created_at=owner['created_at'])

    def fail_attempt(self, job_id, lease_token, now, *, retryable=True):
        with self.store.transaction() as con:
            con.row_factory = sqlite3.Row
            row = con.execute("SELECT * FROM web_jobs WHERE id=? AND lease_token=? AND status IN ('running','draining')", (job_id, lease_token)).fetchone()
            if row is None:
                return
            active = con.execute("SELECT 1 FROM provider_calls WHERE call_id=? AND status IN ('running','draining','uncertain')", (job_id+':'+lease_token,)).fetchone()
            if active:
                return
            retry = retryable and row['attempts'] < 3
            delay = (5 if row['attempts'] == 1 else 30) + min(1, max(0, self.jitter()))
            con.execute('UPDATE web_jobs SET status=?,not_before=?,lease_until=NULL,actual_finished=1,error_code=? WHERE id=?',
                        ('queued' if retry else 'failed', now+delay, 'provider_failed', job_id))
            con.execute('UPDATE request_sections SET status=? WHERE job_id=? AND result_id IS NULL', ('queued' if retry else 'failed', job_id))
            if not retry:
                for sub in con.execute('SELECT * FROM job_subscribers WHERE job_id=? AND deleted_at IS NULL',(job_id,)).fetchall():
                    if self._authorized_subscriber(con,sub,row,now):
                        self._snapshot(con,sub['request_id'],now)

    def defer_unsubmitted(self, job_id, lease_token, now):
        """Capacity denial is not a provider attempt; leave work in the durable queue."""
        with self.store.transaction() as con:
            if con.execute('SELECT 1 FROM provider_calls WHERE call_id=?', (job_id+':'+lease_token,)).fetchone():
                return False
            changed = con.execute("UPDATE web_jobs SET status='queued',attempts=attempts-1,lease_token=NULL,lease_until=NULL,not_before=? WHERE id=? AND lease_token=? AND status='running'", (now+1,job_id,lease_token)).rowcount
            if changed:
                con.execute("UPDATE request_sections SET status='queued' WHERE job_id=? AND result_id IS NULL", (job_id,))
            return bool(changed)

    def confirm_worker_exit(self, worker_id, now, *, reconciled=False):
        """Trusted supervisor only, after the OS confirms the entire child tree died.

        A broker's explicit reconciliation can authorize retry. Default uncertainty
        is retained; this method is never an HTTP/member operation.
        """
        with self.store.transaction() as con:
            con.execute('INSERT INTO worker_exits(worker_id,confirmed_at,reconciled) VALUES (?,?,?) ON CONFLICT(worker_id) DO UPDATE SET reconciled=max(reconciled,excluded.reconciled)', (worker_id, now, int(reconciled)))
            con.execute("UPDATE provider_calls SET status='uncertain',completed_at=?,reconciled=? WHERE worker_id=? AND status IN ('running','draining')", (now, int(reconciled), worker_id))
            if reconciled:
                # A dead, broker-reconciled owner cannot renew even an unexpired
                # lease (including work claimed before any provider call).
                con.execute("UPDATE web_jobs SET lease_until=min(lease_until,?) WHERE worker_id=? AND status IN ('running','draining')",(now,worker_id))
                con.execute("UPDATE provider_calls SET status='failed',reconciled=1 WHERE worker_id=? AND status='uncertain'", (worker_id,))
                # An uncertain model turn is never automatically replayed.
                con.execute("UPDATE assistant_turns SET status='uncertain' WHERE run_id IN (SELECT id FROM assistant_runs WHERE worker_id=? AND status IN ('running','draining')) AND status='prepared'", (worker_id,))
                con.execute("UPDATE assistant_runs SET status='unavailable',finished_at=?,error_code='unavailable' WHERE worker_id=? AND status IN ('running','draining')", (now,worker_id))
                from .provider_runtime import settle_exited_probes
                settle_exited_probes(con,worker_id,now)

    def recover_expired_leases(self, now):
        recovered = 0
        with self.store.transaction() as con:
            con.row_factory = sqlite3.Row
            rows = con.execute("SELECT j.* FROM web_jobs j LEFT JOIN worker_exits e ON e.worker_id=j.worker_id WHERE j.status IN ('running','draining') AND j.lease_until<=? AND (j.actual_finished=1 OR e.reconciled=1)", (now,)).fetchall()
            for row in rows:
                if row['result_id'] and con.execute('SELECT 1 FROM market_results WHERE id=?', (row['result_id'],)).fetchone():
                    con.execute("UPDATE web_jobs SET status='completed' WHERE id=?", (row['id'],))
                else:
                    retry = row['attempts'] < 3
                    delay = (5 if row['attempts'] == 1 else 30) + min(1, max(0, self.jitter()))
                    con.execute('UPDATE web_jobs SET status=?,lease_token=NULL,not_before=?,actual_finished=1 WHERE id=?', ('queued' if retry else 'failed', now+delay, row['id']))
                    con.execute('UPDATE request_sections SET status=? WHERE job_id=? AND result_id IS NULL', ('queued' if retry else 'failed', row['id']))
                    if not retry:
                        for sub in con.execute('SELECT * FROM job_subscribers WHERE job_id=? AND deleted_at IS NULL',(row['id'],)).fetchall():
                            if self._authorized_subscriber(con,sub,row,now):
                                self._snapshot(con,sub['request_id'],now)
                recovered += 1
        return recovered
