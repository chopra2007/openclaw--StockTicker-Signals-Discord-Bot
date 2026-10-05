"""Durable card lifecycle, bounded local projection and guarded cursor reads.

Source pruning is not retraction. Polling uses only the web store and trusted
local permission authorities; it never reads bot data or generates content.
"""
from contextlib import contextmanager
from dataclasses import dataclass, replace
import base64
import hashlib
import hmac
import html
import json
import logging
import math
import sqlite3
import time
from uuid import NAMESPACE_URL,uuid5,uuid4

from pydantic import ValidationError
from .contracts import (ContentLineage,Evidence,FeedPage,FeedUpsert,FeedDelete,FeedPayload,
                        SourceFreshness,SourceContribution,RetractionAnnotation)
from .market_reader import MarketPayload,MarketReader,SourceName,SourceRecord,SourceCheckpoint,safe_url,strict_json
from .features import require_features


def card_identity(key: str,ticker: str) -> str:
    return str(uuid5(NAMESPACE_URL,json.dumps([key,ticker],separators=(',',':'))))


def publication_uses(payload: MarketPayload) -> tuple[str,...]:
    """Actual source fields determine use; the UI feature never grants rights.

    Every card carries raw source facts (ticker, observations/quotes/evidence).
    Classifier direction, quality score and computed trade levels additionally
    require derived-display permission. An unavailable direction is no result.
    """
    if (payload.direction!='unclear' or any(value is not None for value in
            (payload.score,payload.entry,payload.target,payload.invalidation))):
        return ('display_raw','display_derived')
    return ('display_raw',)


@dataclass(frozen=True)
class Publication:
    card_id: str
    content_version: str
    required_feature: str
    observed_at: float | None
    published_at: float | None
    payload: MarketPayload
    evidence: tuple[Evidence,...]
    lineage: ContentLineage
    source_post_key: str
    research_only: bool
    stale: bool=False
    source: SourceName | None=None
    source_computed_at: float | None=None


def publishable(row: SourceRecord) -> Publication | None:
    if not isinstance(row,SourceRecord) or row.lineage is None:
        return None
    if row.source in {SourceName.SOURCE_HEALTH,SourceName.ROUTINE_HEALTH,SourceName.OPTIONS}:
        return None
    # A delivery event never proves the current enriched row's rendered content.
    # Existing bot storage has no delivered-payload hash: every setup here is
    # explicitly research-only, with absent published/entry/target/invalidation.
    feature='feed' if row.source in {SourceName.ANALYST,SourceName.SIGNAL,SourceName.TICKER} else 'setups'
    if feature not in row.lineage.required_features: return None
    version=hashlib.sha256(json.dumps([row.version,row.lineage.model_dump()],sort_keys=True,
        separators=(',',':')).encode()).hexdigest()
    payload=row.payload.model_copy(update={'research_only':True,'entry':None,'target':None,'invalidation':None})
    evidence=Evidence(id=card_identity(row.key,row.ticker),source_id=row.lineage.sources[0].source_id,
        source_version=row.version,observed_at=row.observed_at,url=safe_url(row.url),
        excerpt=row.excerpt,research_only=True)
    return Publication(card_identity(row.key,row.ticker),version,feature,row.observed_at,None,payload,
        (evidence,),row.lineage,row.key,True,row.stale,row.source,row.computed_at)


def advance_log_floor(conn, sequence):
    """Every log/interval deletion writer invalidates older cursors durably."""
    conn.execute('UPDATE feed_state SET retained_floor=MAX(retained_floor,?) WHERE singleton=1',(sequence,))


def transition(conn, card_id, row, active, now):
    """One same-transaction visibility writer, also used by policy purging."""
    conn.row_factory=sqlite3.Row
    if row is None: return False
    head=conn.execute('SELECT * FROM publication_heads WHERE card_id=?',(card_id,)).fetchone()
    if head and bool(head['active'])==active and (not active or head['publication_id']==row['id']):
        return False
    fields=('content_json','source_lineage_json','field_dependencies_json','required_features_json','retention_deadline')
    values=tuple(row[name] for name in fields) if active else (None,'[]','[]','[]',None)
    sequence=conn.execute('INSERT INTO publication_changes(card_id,content_version,operation,feature,content_json,'
        'source_lineage_json,field_dependencies_json,required_features_json,retention_deadline,changed_at) '
        'VALUES (?,?,?,?,?,?,?,?,?,?)',(card_id,row['content_version'],'upsert' if active else 'delete',
        row['feature'],*values,now)).lastrowid
    conn.execute('UPDATE feed_state SET high_water=MAX(high_water,?) WHERE singleton=1',(sequence,))
    conn.execute('UPDATE publication_intervals SET end_sequence=?,ended_at=? WHERE card_id=? AND end_sequence IS NULL',
                 (sequence,now,card_id))
    conn.execute('INSERT INTO publication_heads(card_id,publication_id,feature,active,last_sequence,updated_at) '
        'VALUES (?,?,?,?,?,?) ON CONFLICT(card_id) DO UPDATE SET publication_id=excluded.publication_id,'
        'feature=excluded.feature,active=excluded.active,last_sequence=excluded.last_sequence,updated_at=excluded.updated_at',
        (card_id,row['id'],row['feature'],int(active),sequence,now))
    if active:
        conn.execute('INSERT INTO publication_intervals(card_id,publication_id,start_sequence) VALUES (?,?,?)',
                     (card_id,row['id'],sequence))
    return True


def purge_publication(conn, row, now, policy):
    """Do not let deleting an old revision withdraw a newer active revision."""
    card_id=card_identity(row['source_post_key'],row['ticker'])
    try: evidence=MarketPayload.model_validate(strict_json(row['content_json'])).evidence
    except (ValueError,TypeError,RecursionError): evidence=[]
    if not evidence:
        conn.execute('UPDATE feed_state SET retraction_authority_required=1 WHERE singleton=1')
    for item in evidence:
        _retain_marker(conn,policy,'publication_evidence_refs',(card_id,item.id,item.source_id,item.source_version),
                       now,[row['source_lineage_json']])
    head=conn.execute('SELECT publication_id,active FROM publication_heads WHERE card_id=?',(card_id,)).fetchone()
    if head is None or (head[0]==row['object_id'] and head[1]):
        values=dict(row); values['id']=row['object_id']
        transition(conn,card_id,values,False,now)
    intervals=conn.execute('SELECT MAX(COALESCE(end_sequence,start_sequence)) FROM publication_intervals '
                           'WHERE publication_id=?',(row['object_id'],)).fetchone()[0]
    if intervals is not None:
        advance_log_floor(conn,intervals)
    if head is None or head[0]==row['object_id']:
        conn.execute('UPDATE publication_heads SET source_id=NULL,source_key=NULL,ticker=NULL,stale=1 '
                     'WHERE card_id=?',(card_id,))


def evidence_retraction(conn, evidence: Evidence, policy) -> RetractionAnnotation | None:
    """Task 9 applies this exact-identity annotation after its ownership guard."""
    if not isinstance(evidence,Evidence): raise ValueError('typed evidence required')
    if conn.execute('SELECT retraction_authority_required FROM feed_state').fetchone()[0]:
        return RetractionAnnotation(status='unavailable',recorded_at=None)
    row=conn.execute('SELECT recorded_at,source_lineage_json FROM evidence_retractions WHERE evidence_id=? AND source_id=? '
                     'AND source_version=?',(evidence.id,evidence.source_id,evidence.source_version)).fetchone()
    if row:
        if policy._retraction_metadata_allowed(conn,row[1]):
            return RetractionAnnotation(status='retracted',recorded_at=row[0])
        return RetractionAnnotation(status='unavailable',recorded_at=None)
    return None


def _marker_sources(raw_values):
    """Union every contribution, including versions, without truncating proof."""
    sources={}
    for raw in raw_values:
        values=json.loads(raw)
        if not isinstance(values,list) or not 1<=len(values)<=200: raise ValueError('invalid marker lineage')
        for item in values:
            value=SourceContribution.model_validate(item)
            key=(value.source_id,value.product_id,value.source_version,value.policy_version)
            sources[key]=value.model_dump()
            if len(sources)>200: raise ValueError('marker lineage exceeded')
    if not sources: raise ValueError('missing marker lineage')
    return json.dumps([sources[key] for key in sorted(sources)],separators=(',',':'))


def _retain_marker(conn,policy,table,keys,now,raw_values):
    # Lost coverage cannot be repaired by a later partial reference/marker.
    # Existing permanent card markers still prevent republication.
    if conn.execute('SELECT retraction_authority_required FROM feed_state').fetchone()[0]: return False
    columns={
        'publication_retractions':('card_id',),
        'evidence_retractions':('evidence_id','source_id','source_version'),
        'publication_evidence_refs':('card_id','evidence_id','source_id','source_version'),
    }[table]
    where=' AND '.join(name+'=?' for name in columns)
    old=conn.execute(f'SELECT source_lineage_json FROM {table} WHERE {where}',keys).fetchone()
    try:
        sources=_marker_sources([*raw_values,*([old[0]] if old else [])])
        permitted=policy._retraction_metadata_allowed(conn,sources)
    except (ValueError,TypeError,RecursionError): permitted=False
    if not permitted:
        conn.execute('UPDATE feed_state SET retraction_authority_required=1 WHERE singleton=1')
        conn.execute(f'DELETE FROM {table} WHERE {where}',keys)
        return False
    if old:
        conn.execute(f'UPDATE {table} SET source_lineage_json=? WHERE {where}',(sources,*keys))
    else:
        conn.execute(f'INSERT INTO {table} VALUES ('+','.join('?' for _ in range(len(keys)+2))+')',(*keys,now,sources))
    return True


class Publisher:
    def __init__(self,store,policy, *, retraction_clearance=lambda key,ticker:False):
        self.store=store; self.policy=policy; self.retraction_clearance=retraction_clearance

    def _retracted(self,conn,key,ticker):
        if conn.execute('SELECT 1 FROM publication_retractions WHERE card_id=?',(card_identity(key,ticker),)).fetchone():
            return True
        if conn.execute('SELECT 1 FROM publications WHERE source_post_key=? AND ticker=? AND retracted_at IS NOT NULL LIMIT 1',
                        (key,ticker)).fetchone(): return True
        if conn.execute('SELECT retraction_authority_required FROM feed_state WHERE singleton=1').fetchone()[0]:
            try: return self.retraction_clearance(key,ticker) is not True
            except Exception: return True
        return False

    def save(self,publication: Publication,now: float) -> bool:
        if not isinstance(publication,Publication): raise ValueError('typed publication required')
        with self.store.transaction() as conn:
            return self._save(conn,publication,now)

    def _save(self,conn,publication,now):
        conn.row_factory=sqlite3.Row
        ages=[value for value in (publication.observed_at,publication.source_computed_at) if value is not None]
        if (not ages or any(type(value) not in (int,float) or not math.isfinite(value) or value<=0 or value>now+86400
                            for value in ages) or min(ages)<=now-90*86400): return False
        if self._retracted(conn,publication.source_post_key,publication.payload.ticker): return False
        if not require_features(conn,publication.lineage.required_features): return False
        decisions=[self.policy._authorize_lineage(conn,publication.lineage,use,now,publication.observed_at)
                   for use in publication_uses(publication.payload)]
        retain=self.policy._authorize_lineage(conn,publication.lineage,'retain',now)
        if not all(item.allowed for item in decisions) or not retain.allowed: return False
        decision=decisions[0]
        payload=publication.payload.model_copy(update={'attributions':list(decision.attributions),
                                                      'evidence':list(publication.evidence)})
        values=(publication.source_post_key,publication.payload.ticker,publication.content_version,
            publication.required_feature,payload.model_dump_json(),
            json.dumps([s.model_dump() for s in publication.lineage.sources]),
            json.dumps([d.model_dump() for d in publication.lineage.field_dependencies]),
            json.dumps(publication.lineage.required_features),decision.retention_deadline,
            publication.observed_at,now,publication.source_computed_at)
        conn.execute('INSERT OR IGNORE INTO publications(id,source_post_key,ticker,content_version,feature,'
            'content_json,source_lineage_json,field_dependencies_json,required_features_json,retention_deadline,'
            'observed_at,published_at,source_computed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',(str(uuid4()),*values))
        row=conn.execute('SELECT * FROM publications WHERE source_post_key=? AND ticker=? AND content_version=?',
            (publication.source_post_key,publication.payload.ticker,publication.content_version)).fetchone()
        if row['published_at']+90*86400<=now: return False
        transition(conn,publication.card_id,row,True,now)
        conn.execute('UPDATE publication_heads SET source_id=?,source_key=?,ticker=?,stale=?,authority_blocked=0 '
            'WHERE card_id=?',(publication.source.value if publication.source else None,publication.source_post_key,
            publication.payload.ticker,int(publication.stale),publication.card_id))
        return True

    def load(self,publication_id: str,now: float) -> MarketPayload | None:
        """Current source-use guard for saved cards; membership/features are additional guards."""
        with self.store.transaction() as conn:
            conn.row_factory=sqlite3.Row
            row=conn.execute('SELECT * FROM publications WHERE id=?',(publication_id,)).fetchone()
            result=self._load(conn,row,now)
            return result[0] if result else None

    def _load(self,conn,row,now, *, feed_guard=False):
        if row is None or row['retracted_at'] is not None: return None
        if self._retracted(conn,row['source_post_key'],row['ticker']): return None
        if feed_guard and (row['published_at']+90*86400<=now or
            (row['observed_at'] is not None and row['observed_at']<=now-90*86400) or
            (row['source_computed_at'] is not None and row['source_computed_at']<=now-90*86400)): return None
        lineage=self.policy.stored_lineage(row)
        try:
            payload=MarketPayload.model_validate(strict_json(row['content_json']))
            decisions=[self.policy._authorize_lineage(conn,lineage,use,now,row['observed_at'])
                       for use in publication_uses(payload)]
            if not all(item.allowed for item in decisions) or row['feature'] not in lineage.required_features:
                return None
            if feed_guard and (not require_features(conn,lineage.required_features) or
                not self.policy._authorize_lineage(conn,lineage,'retain',now).allowed): return None
            decision=decisions[0]
            evidence=[item.model_copy(update={'url':safe_url(item.url),
                'excerpt':html.escape(html.unescape(item.excerpt),quote=True)}) for item in payload.evidence]
            return (payload.model_copy(update={'excerpt':html.escape(html.unescape(payload.excerpt),quote=True),
                                              'attributions':list(decision.attributions),'evidence':evidence}),decision)
        except (ValueError,TypeError,ValidationError,RecursionError): return None

    def retract(self,source_post_key: str,ticker: str,now: float) -> None:
        """Trusted explicit withdrawal, never invoked merely because a row disappeared."""
        with self.store.transaction() as conn:
            if self.policy.denial_journal is not None:
                self.policy.denial_journal.append('retraction',source_post_key+'/'+ticker)
            conn.row_factory=sqlite3.Row
            rows=conn.execute('SELECT * FROM publications WHERE source_post_key=? AND ticker=?',
                             (source_post_key,ticker)).fetchall()
            card_id=card_identity(source_post_key,ticker)
            references=conn.execute('SELECT * FROM publication_evidence_refs WHERE card_id=?',(card_id,)).fetchall()
            _retain_marker(conn,self.policy,'publication_retractions',(card_id,),now,
                           [row['source_lineage_json'] for row in [*rows,*references]])
            evidence_sources={}
            for reference in references:
                key=(reference['evidence_id'],reference['source_id'],reference['source_version'])
                evidence_sources.setdefault(key,[]).append(reference['source_lineage_json'])
            for row in rows:
                conn.execute('UPDATE publications SET retracted_at=COALESCE(retracted_at,?) WHERE id=?',(now,row['id']))
                try: evidence=MarketPayload.model_validate(strict_json(row['content_json'])).evidence
                except (ValueError,TypeError,RecursionError): evidence=[]
                for item in evidence:
                    key=(item.id,item.source_id,item.source_version)
                    evidence_sources.setdefault(key,[]).append(row['source_lineage_json'])
            # Assess the whole identity once. A third revision must not recreate
            # a partial marker after an earlier union exceeded the cap.
            for key,raw_sources in evidence_sources.items():
                _retain_marker(conn,self.policy,'evidence_retractions',key,now,raw_sources)
            head=conn.execute('SELECT p.* FROM publication_heads h JOIN publications p ON p.id=h.publication_id '
                              'WHERE h.card_id=?',(card_id,)).fetchone()
            if head: transition(conn,card_id,head,False,now)


class FeedError(Exception):
    def __init__(self,code,status=409):
        self.code=code; self.status=status
        super().__init__(code)


@dataclass(frozen=True)
class SyncStats:
    scanned: int=0
    published: int=0
    reconciled: int=0
    unavailable: int=0
    status: str='ok'


_FEED_SOURCES=(SourceName.ANALYST,SourceName.SIGNAL,SourceName.ALERT,SourceName.SNAPSHOT,
               SourceName.TICKER,SourceName.RESEARCH)
_LOG_RETENTION=7*86400
_CURSOR_TTL=900


class FeedService:
    def __init__(self,store,auth,policy, *, signing_key,clock=time.time,reader=None,
                 lineage_resolver=lambda row:None,retraction_clearance=lambda key,ticker:False):
        if type(signing_key) is not bytes or len(signing_key)<32:
            raise ValueError('feed signing key must contain at least 32 bytes')
        self.store=store; self.auth=auth; self.policy=policy; self.signing_key=signing_key
        self.clock=clock; self.reader=reader; self.lineage_resolver=lineage_resolver
        self.publisher=Publisher(store,policy,retraction_clearance=retraction_clearance)

    @contextmanager
    def _transaction(self,deadline, *, write=False):
        conn=self.store._connect()
        try:
            remaining=deadline-time.monotonic()
            if remaining<=0: raise TimeoutError('feed_deadline')
            conn.execute('PRAGMA busy_timeout='+str(max(1,min(50,int(remaining*1000)))))
            conn.row_factory=sqlite3.Row
            conn.set_progress_handler(lambda:int(time.monotonic()>=deadline),100)
            conn.execute('BEGIN IMMEDIATE' if write or self.store.authority is not None else 'BEGIN')
            if self.store.authority is not None: self.store.authority.reconcile(conn)
            yield conn
            if self.store.authority is not None: self.store.authority.reconcile(conn)
            if time.monotonic()>=deadline: raise TimeoutError('feed_deadline')
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally: conn.close()

    def _sign(self,body):
        raw=base64.urlsafe_b64encode(json.dumps(body,sort_keys=True,separators=(',',':')).encode()).rstrip(b'=')
        signature=hmac.new(self.signing_key,raw,hashlib.sha256).hexdigest()
        return raw.decode()+'.'+signature

    def _decode(self,cursor,feature,version,now):
        try:
            if type(cursor) is not str or not 1<=len(cursor)<=4096: raise ValueError()
            raw,signature=cursor.split('.')
            if not hmac.compare_digest(hmac.new(self.signing_key,raw.encode(),hashlib.sha256).hexdigest(),signature):
                raise ValueError()
            value=strict_json(base64.b64decode(raw+'='*(-len(raw)%4),altchars=b'-_',validate=True).decode())
            if set(value)!={'v','f','fv','mode','high','after','key','expires'}: raise ValueError()
            if (type(value['v']) is not int or value['v']!=1 or value['f']!=feature or
                type(value['fv']) is not int or value['fv']!=version or value['mode'] not in {'snapshot','delta'} or
                type(value['high']) is not int or value['high']<0 or type(value['after']) is not int or value['after']<0 or
                type(value['key']) is not str or len(value['key'])>128 or
                type(value['expires']) not in (float,int) or not now<value['expires']<=now+_CURSOR_TTL):
                raise ValueError()
            return value
        except (ValueError,TypeError,UnicodeError,RecursionError):
            raise FeedError('snapshot_reset') from None

    def _freshness(self,conn,now):
        rows={r['source_id']:r for r in conn.execute('SELECT * FROM feed_source_status')}
        return [SourceFreshness(source=source.value,
            status=('unavailable' if source.value not in rows or not rows[source.value]['available'] else
                    'stale' if rows[source.value]['succeeded_at'] is None or rows[source.value]['succeeded_at']<now-30 else 'available'),
            checked_at=rows[source.value]['checked_at'] if source.value in rows else None,
            succeeded_at=rows[source.value]['succeeded_at'] if source.value in rows else None) for source in _FEED_SOURCES]

    def _record(self,conn,card_id,row,now,sources):
        if row is None: return FeedDelete(id=card_id)
        head=conn.execute('SELECT source_id,stale,authority_blocked FROM publication_heads WHERE card_id=?',(card_id,)).fetchone()
        loaded=None if head and head['authority_blocked'] else self.publisher._load(conn,row,now,feed_guard=True)
        if loaded is None: return FeedDelete(id=card_id)
        payload,decision=loaded
        stale=head is None or bool(head['stale']) or not any(s.source==head['source_id'] and s.status=='available' for s in sources)
        return FeedUpsert(id=card_id,content_version=row['content_version'],summary_version=row['content_version'],
            source=head['source_id'] if head else None,
            payload=FeedPayload.model_validate(payload.model_dump()),observed_at=row['observed_at'],
            projected_at=row['published_at'],stale=stale,delay_seconds=decision.delay_seconds)

    def read_feed(self,principal,feature,cursor=None,limit=50) -> FeedPage:
        if feature not in {'feed','setups'} or type(limit) is not int or not 1<=limit<=100:
            raise FeedError('invalid_request',422)
        now=self.clock()
        with self._transaction(time.monotonic()+1) as conn:
            self.auth.revalidate(principal,now,con=conn)
            feature_row=conn.execute('SELECT enabled,version FROM features WHERE name=?',(feature,)).fetchone()
            if not feature_row or not feature_row[0]: raise FeedError('forbidden',403)
            state=conn.execute('SELECT high_water,retained_floor FROM feed_state WHERE singleton=1').fetchone()
            value=self._decode(cursor,feature,feature_row[1],now) if cursor is not None else dict(
                v=1,f=feature,fv=feature_row[1],mode='snapshot',high=state['high_water'],after=0,key='',expires=now+_CURSOR_TTL)
            position=value['high'] if value['mode']=='snapshot' else value['after']
            if position<state['retained_floor'] or position>state['high_water']:
                raise FeedError('snapshot_reset')
            snapshot=value['mode']=='snapshot'
            sources=self._freshness(conn,now)
            records=[]
            if snapshot:
                rows=conn.execute('SELECT i.card_id,i.publication_id FROM publication_intervals i '
                    'JOIN publications p ON p.id=i.publication_id WHERE p.feature=? AND i.card_id>? '
                    'AND i.start_sequence<=? AND (i.end_sequence IS NULL OR i.end_sequence>?) '
                    'ORDER BY i.card_id LIMIT ?', (feature,value['key'],value['high'],value['high'],limit+1)).fetchall()
                for item in rows[:limit]:
                    row=conn.execute('SELECT * FROM publications WHERE id=?',(item['publication_id'],)).fetchone()
                    records.append(self._record(conn,item['card_id'],row,now,sources))
                more=len(rows)>limit
                if more: value['key']=rows[limit-1]['card_id']
                else:
                    value.update(mode='delta',after=value['high'],key='',expires=now+_CURSOR_TTL)
            else:
                rows=conn.execute('SELECT * FROM publication_changes WHERE feature=? AND sequence>? '
                    'ORDER BY sequence LIMIT ?',(feature,value['after'],limit+1)).fetchall()
                for item in rows[:limit]:
                    if item['operation']=='delete': records.append(FeedDelete(id=item['card_id']))
                    else:
                        # Exact interval reference avoids joining version strings across cards.
                        row=conn.execute('SELECT p.* FROM publication_intervals i JOIN publications p '
                            'ON p.id=i.publication_id WHERE i.start_sequence=?',(item['sequence'],)).fetchone()
                        records.append(self._record(conn,item['card_id'],row,now,sources))
                    value['after']=item['sequence']
                more=len(rows)>limit
                if not more: value['after']=state['high_water']
                value['expires']=now+_CURSOR_TTL
            return FeedPage(records=records,cursor=self._sign(value),snapshot=snapshot,has_more=more,sources=sources)

    def _cleanup(self,conn,now,deadline):
        rows=conn.execute('SELECT sequence FROM publication_changes WHERE changed_at<? ORDER BY changed_at,sequence LIMIT 100',
                          (now-_LOG_RETENTION,)).fetchall()
        if rows:
            advance_log_floor(conn,max(r[0] for r in rows))
            conn.executemany('DELETE FROM publication_changes WHERE sequence=?',[(r[0],) for r in rows])
        intervals=conn.execute('SELECT start_sequence,end_sequence FROM publication_intervals '
            'WHERE ended_at<? ORDER BY ended_at,start_sequence LIMIT 100',(now-_LOG_RETENTION,)).fetchall()
        if intervals:
            advance_log_floor(conn,max(r[1] for r in intervals))
            conn.executemany('DELETE FROM publication_intervals WHERE start_sequence=?',[(r[0],) for r in intervals])
        # This is feed-only retention. Never truncate report versions or messages.
        expired=conn.execute('SELECT *,id AS object_id FROM publications WHERE published_at<=? OR observed_at<=? OR source_computed_at<=? '
            'ORDER BY published_at,id LIMIT 100',(now-90*86400,now-90*86400,now-90*86400)).fetchall()
        for row in expired:
            if deadline-time.monotonic()<.05: break
            purge_publication(conn,row,now,self.policy)
            conn.execute('DELETE FROM publications WHERE id=?',(row['id'],))

    @staticmethod
    def _block_authority(conn,source,key,ticker,now, *, valid_version=None):
        rows=conn.execute('SELECT p.*,h.card_id FROM publication_heads h JOIN publications p ON p.id=h.publication_id '
            'WHERE h.source_id=? AND h.source_key=? AND h.ticker=?',(source.value,key,ticker)).fetchall()
        for row in rows:
            transition(conn,row['card_id'],row,False,now)
            # A valid, unchanged revision denied only by current policy remains
            # reversible even if its operational source is pruned meanwhile.
            blocked=valid_version is None or row['content_version']!=valid_version
            conn.execute('UPDATE publication_heads SET authority_blocked=? WHERE card_id=?',(int(blocked),row['card_id']))

    def sync_publications(self,now: float) -> SyncStats:
        """One turn: <=100 source rows, <=100 heads and one-second deadline.

        Only injected complete lineage is trusted. Read failures leave checkpoints
        unchanged. All successful projections and their checkpoints commit together.
        """
        deadline=time.monotonic()+1
        scanned=published=reconciled=unavailable=0
        try:
            with self._transaction(deadline) as conn:
                state=conn.execute('SELECT source_rotation,head_cursor FROM feed_state WHERE singleton=1').fetchone()
                checkpoints={r['source_id']:SourceCheckpoint(r['last_id'],r['last_observed_at'],r['reconciliation_cursor'])
                    for r in conn.execute('SELECT * FROM source_checkpoints')}
            start=state['source_rotation']%len(_FEED_SOURCES)
            batches=[]; remaining=100
            for offset in range(len(_FEED_SOURCES)):
                if self.reader is None or deadline-time.monotonic()<.45: break
                source=_FEED_SOURCES[(start+offset)%len(_FEED_SOURCES)]
                checkpoint=checkpoints.get(source.value,SourceCheckpoint())
                reader=self.reader
                if isinstance(reader,MarketReader):
                    reader=MarketReader(reader.path,clock=reader.clock,query_seconds=min(.05,deadline-time.monotonic()-.15))
                limit=max(1,remaining//(len(_FEED_SOURCES)-offset))
                try:
                    batch=reader.read_batch(source,checkpoint,limit)
                    if len(batch.records)+len(batch.blocked_keys)>limit: raise ValueError('source_batch_exceeded')
                except (sqlite3.Error,ValueError,TypeError):
                    from .market_reader import SourceBatch
                    batch=SourceBatch((),checkpoint,False,'source_unavailable')
                scanned+=len(batch.records)+len(batch.blocked_keys)
                remaining-=len(batch.records)+len(batch.blocked_keys)
                batches.append((source,batch))
            with self._transaction(deadline,write=True) as conn:
                for source,batch in batches:
                    if not batch.available: unavailable+=1
                    conn.execute('INSERT INTO feed_source_status(source_id,checked_at,succeeded_at,available) '
                        'VALUES (?,?,?,?) ON CONFLICT(source_id) DO UPDATE SET checked_at=excluded.checked_at,'
                        'succeeded_at=COALESCE(excluded.succeeded_at,feed_source_status.succeeded_at),available=excluded.available',
                        (source.value,now,now if batch.available else None,int(batch.available)))
                    if not batch.available: continue
                    completed=True
                    for source_row in batch.records:
                        # Reserve time for head reconciliation and commit. A
                        # partially applied batch keeps its old checkpoint;
                        # immutable versions make its retry harmless.
                        if deadline-time.monotonic()<.2:
                            completed=False
                            break
                        trusted=self.lineage_resolver(source_row)
                        if not isinstance(trusted,ContentLineage):
                            self._block_authority(conn,source,source_row.key,source_row.ticker,now)
                            continue
                        candidate=publishable(replace(source_row,lineage=trusted))
                        if candidate is not None and conn.execute('SELECT 1 FROM publication_heads h JOIN publications p '
                            'ON p.id=h.publication_id WHERE h.card_id=? AND p.content_version=? AND h.active=1 '
                            'AND h.authority_blocked=0',(candidate.card_id,candidate.content_version)).fetchone():
                            # No new authority is granted by this retry. Polls
                            # and the independent rotating head lane recheck it.
                            continue
                        if candidate is not None and self.publisher._save(conn,candidate,now): published+=1
                        else: self._block_authority(conn,source,source_row.key,source_row.ticker,now,
                                                   valid_version=candidate.content_version if candidate else None)
                    for key,ticker in batch.blocked_keys:
                        if deadline-time.monotonic()<.2:
                            completed=False
                            break
                        exact_key=key if source==SourceName.ANALYST else source.value+':'+key
                        self._block_authority(conn,source,exact_key,ticker,now)
                    if not completed: continue
                    cp=batch.checkpoint
                    conn.execute('INSERT INTO source_checkpoints VALUES (?,?,?,?,?) ON CONFLICT(source_id) DO UPDATE SET '
                        'last_id=excluded.last_id,last_observed_at=excluded.last_observed_at,'
                        'reconciliation_cursor=excluded.reconciliation_cursor,updated_at=excluded.updated_at',
                        (source.value,cp.last_id,cp.last_observed_at,cp.reconciliation_cursor,now))
                # Rotate both source-first ordering and card reconciliation, even
                # through unavailable sources. No single busy source owns the turn.
                conn.execute('UPDATE feed_state SET source_rotation=? WHERE singleton=1',((start+1)%len(_FEED_SOURCES),))
                heads=conn.execute('SELECT h.card_id,h.authority_blocked,p.* FROM publication_heads h '
                    'JOIN publications p ON p.id=h.publication_id WHERE h.card_id>? ORDER BY h.card_id LIMIT 100',
                    (state['head_cursor'],)).fetchall()
                for row in heads:
                    if deadline-time.monotonic()<.05: break
                    allowed=not row['authority_blocked'] and self.publisher._load(conn,row,now,feed_guard=True) is not None
                    transition(conn,row['card_id'],row,allowed,now)
                    reconciled+=1
                conn.execute('UPDATE feed_state SET head_cursor=? WHERE singleton=1',
                    (heads[reconciled-1]['card_id'] if reconciled and (reconciled<len(heads) or len(heads)==100)
                     else state['head_cursor'] if heads and not reconciled else '',))
            # Cleanup is independently atomic. A slow maintenance scan must not
            # roll back already committed source/checkpoint/reconciliation work.
            if deadline-time.monotonic()>.03:
                try:
                    with self._transaction(deadline,write=True) as conn: self._cleanup(conn,now,deadline)
                except (sqlite3.Error,TimeoutError):
                    return SyncStats(scanned,published,reconciled,unavailable,'partial')
            return SyncStats(scanned,published,reconciled,unavailable)
        except (sqlite3.Error,TimeoutError):
            return SyncStats(status='unavailable')

    def feed_tick(self,now):
        """Safe WorkerSupervisor callback: feed failures cannot stop child draining."""
        try:
            result=self.sync_publications(now)
            if result.status!='ok': logging.getLogger(__name__).warning('feed_projection_unavailable')
            return result
        except Exception:
            logging.getLogger(__name__).warning('feed_projection_failed')
            return SyncStats(status='failed')
