"""Bounded, read-only projections of the fixed bot storage schema.

No bot imports, migration, credentials, network access or delivery handles.
Rows carry no implied product grant. A host-verified manifest may attach typed
lineage later; absent manifests cannot become member publications.
"""
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
import hashlib
import html
import json
import math
from pathlib import Path
import re
import sqlite3
import time
from typing import Annotated, Callable, Literal
from urllib.parse import unquote, urlsplit, urlunsplit

from pydantic import Field
from .contracts import ContentLineage, Evidence, PublicModel


class SourceName(str, Enum):
    ANALYST = 'analyst_views'
    SIGNAL = 'signal_events'
    ALERT = 'alert_history'
    SNAPSHOT = 'decision_snapshots'
    OPTIONS = 'options_flow'
    TICKER = 'ticker_signals'
    RESEARCH = 'research_sections'
    SOURCE_HEALTH = 'source_health'
    ROUTINE_HEALTH = 'routine_health'


@dataclass(frozen=True)
class SourceCheckpoint:
    last_id: str | None = None
    last_observed_at: float | None = None
    reconciliation_cursor: str | None = None


class MarketPayload(PublicModel):
    ticker: str = Field(max_length=16)
    direction: Literal['bullish','bearish','neutral','unclear']
    excerpt: str = Field(max_length=4000)
    score: float | None = None
    price: float | None = None
    research_only: Literal[True] = True
    entry: float | None = None
    target: float | None = None
    invalidation: float | None = None
    attributions: list[Annotated[str,Field(max_length=1536)]]=Field(default_factory=list,max_length=200)
    evidence: list[Evidence]=Field(default_factory=list,max_length=200)


@dataclass(frozen=True)
class SourceRecord:
    source: SourceName
    key: str
    ticker: str
    version: str
    observed_at: float | None
    computed_at: float | None
    url: str | None
    direction: str
    excerpt: str
    payload: MarketPayload
    research_only: bool = True
    lineage: ContentLineage | None = None
    delivery_confirmed_at: float | None = None
    stale: bool = False


@dataclass(frozen=True)
class SourceBatch:
    records: tuple[SourceRecord, ...]
    checkpoint: SourceCheckpoint
    available: bool = True
    unavailable_reason: str | None = None
    blocked_keys: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class DeliveryEvidence:
    confirmed_at: float
    rendered_content_verified: bool=False


@dataclass(frozen=True)
class _Spec:
    table: str
    columns: tuple[str, ...]
    time_column: str | None
    key_columns: tuple[str, ...] = ('id',)


def _spec(table, columns, time_column, keys=('id',)):
    return _Spec(table, tuple(columns.split()), time_column, keys)


_SPECS = {
    SourceName.ANALYST: _spec('analyst_post_views', 'id source_post_key source_url ticker detected_at '
        'raw_text raw_text_sha256 display_direction reason_text reason_start reason_end reason_kind '
        'decision_code parser_version image_evidence_json created_at', 'created_at'),
    SourceName.SIGNAL: _spec('signal_events', 'id source_type ticker direction quality_score recorded_at '
        'source_link analyst_post_view_id', 'recorded_at'),
    SourceName.ALERT: _spec('alert_history', 'id ticker confidence_score catalyst_type consensus_breakdown '
        'technical_data alerted_at price_at_alert', 'alerted_at'),
    SourceName.SNAPSHOT: _spec('decision_snapshots', 'id ticker decision final_score contradiction_index '
        'sources_json recorded_at outcome_price_at_alert alert_id', 'recorded_at'),
    SourceName.OPTIONS: _spec('options_flow', 'id ticker side strike expiry volume open_interest '
        'vol_oi_ratio premium_usd last_trade_ts spot contract_symbol alerted detected_at flow_side bid ask', 'detected_at'),
    SourceName.TICKER: _spec('ticker_signals', 'id ticker source_type sentiment detected_at expires_at', 'detected_at'),
    SourceName.RESEARCH: _spec('research_sections', 'ticker source content last_good_content fetched_at '
        'last_good_at status', 'fetched_at', ('ticker','source')),
    SourceName.SOURCE_HEALTH: _spec('source_health', 'source_id last_heartbeat error_rate '
        'freshness_seconds updated_at', 'updated_at', ('source_id',)),
    SourceName.ROUTINE_HEALTH: _spec('routine_health', 'routine_id last_cycle_started last_success_at '
        'errors_in_cycle paused_until', None, ('routine_id',)),
}
_PUBLIC_HOSTS = frozenset({'x.com','twitter.com','www.twitter.com','www.youtube.com','youtube.com',
    'youtu.be','www.reddit.com','reddit.com','www.sec.gov','sec.gov','www.finnhub.io','finnhub.io',
    'www.schwab.com','schwab.com','developer.schwab.com','legal.yahoo.com','docs.x.com',
    'support.google.com','policies.google.com'})
_TICKER = re.compile(r'[A-Z][A-Z0-9.\-]{0,15}\Z')
_DIRECTIONS = {'long':'bullish','short':'bearish','neutral':'neutral','unclear':'unclear'}


def safe_url(value: object) -> str | None:
    """Public canonical source links only; never resolve or fetch link targets."""
    if not isinstance(value,str) or not value or len(value)>2048:
        return None
    if any(ord(c)<33 or ord(c)==127 for c in value) or '\\' in value:
        return None
    try:
        parts=urlsplit(value)
        if (parts.scheme.lower() not in {'https','http'} or parts.username is not None
                or parts.password is not None or parts.hostname not in _PUBLIC_HOSTS
                or parts.port not in {None,80 if parts.scheme.lower()=='http' else 443}):
            return None
        # No query/redirect wrappers, including encoded control characters.
        decoded=unquote(parts.path)
        if parts.query or '\\' in decoded or any(ord(c)<32 or ord(c)==127 for c in decoded):
            return None
        if any(piece in {'redirect','redir','out','url','login','intent'} for piece in decoded.lower().split('/')):
            return None
        return urlunsplit((parts.scheme.lower(),parts.hostname,parts.path or '/', '', ''))
    except (ValueError,UnicodeError):
        return None


def strict_json(value: object) -> dict:
    if not isinstance(value,str) or len(value.encode('utf-8'))>32768:
        raise ValueError('invalid structured input')
    def unique(pairs):
        result={}
        for key,item in pairs:
            if key in result: raise ValueError('duplicate JSON key')
            result[key]=item
        return result
    def constant(_): raise ValueError('nonfinite JSON')
    result=json.loads(value,object_pairs_hook=unique,parse_constant=constant)
    if not isinstance(result,dict) or len(result)>50:
        raise ValueError('invalid structured input')
    return result


def _number(value, *, positive=False):
    if value is None: return None
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):
        raise ValueError('invalid number')
    if positive and value<=0: return None
    return float(value)


def _timestamp(value, now, *, optional=False):
    if value is None and optional: return None
    result=_number(value)
    if result is None or result<=0 or result>now+86400:
        raise ValueError('invalid timestamp')
    return result


def _text(value,limit=4000):
    if not isinstance(value,str) or len(value)>limit or any(ord(c)<32 and c not in '\n\t' for c in value):
        raise ValueError('invalid text')
    return html.escape(value,quote=True)


class MarketReader:
    def __init__(self,path: Path, *, clock: Callable[[],float]=time.time, query_seconds: float=0.25):
        self.path=Path(path)
        if not self.path.is_absolute(): raise ValueError('market path must be absolute')
        if not 0<query_seconds<=1: raise ValueError('invalid query deadline')
        self.clock=clock
        self.query_seconds=query_seconds

    @contextmanager
    def connection(self):
        conn=sqlite3.connect(self.path.resolve().as_uri()+'?mode=ro',uri=True,timeout=0.1)
        try:
            conn.row_factory=sqlite3.Row
            conn.execute('PRAGMA query_only=ON')
            deadline=time.monotonic()+self.query_seconds
            conn.set_progress_handler(lambda: int(time.monotonic()>=deadline),1000)
            yield conn
        finally:
            conn.close()

    def read_batch(self,source: SourceName,checkpoint: SourceCheckpoint,limit: int=100) -> SourceBatch:
        if not isinstance(source,SourceName): raise ValueError('source must be a fixed SourceName')
        if not isinstance(checkpoint,SourceCheckpoint) or type(limit) is not int or not 1<=limit<=100:
            raise ValueError('invalid batch bounds')
        spec=_SPECS[source]
        try:
            with self.connection() as conn:
                columns={r['name'] for r in conn.execute(f'PRAGMA table_info({spec.table})')}
                if not set(spec.columns)<=columns:
                    return SourceBatch((),checkpoint,False,'schema_unavailable')
                rows,next_checkpoint=self._page(conn,source,spec,checkpoint,limit)
                records=[]; blocked=[]
                now=self.clock()
                for row in rows:
                    try:
                        records.append(self._project(source,row,now))
                    except (ValueError,TypeError,KeyError,json.JSONDecodeError,RecursionError):
                        key=row['source_post_key'] if source==SourceName.ANALYST else self._key(spec,row)
                        ticker=row['ticker'] if 'ticker' in row.keys() and _TICKER.fullmatch(str(row['ticker'])) else ''
                        if isinstance(key,str) and 0<len(key)<=256:
                            blocked.append((key,ticker))
                return SourceBatch(tuple(records),next_checkpoint,blocked_keys=tuple(blocked))
        except sqlite3.Error:
            return SourceBatch((),checkpoint,False,'source_unavailable')

    def delivery_evidence(self,history_id: int,ticker: str) -> DeliveryEvidence | None:
        """Exact legacy-ID ledger proof, deliberately separate from rendered content.

        Unknown correction semantics, conflicting decision/candidate links,
        incomplete schemas and overlarge chains are unverified. No fuzzy joins.
        """
        if type(history_id) is not int or history_id<=0 or not _TICKER.fullmatch(ticker):
            raise ValueError('invalid delivery key')
        try:
            with self.connection() as conn:
                return self._delivery_evidence(conn,history_id,ticker)
        except (sqlite3.Error,ValueError,TypeError): return None

    def _delivery_evidence(self,conn,history_id,ticker):
        alerts=conn.execute('SELECT event_id,alert_id,decision_id,created_at FROM measurement_alert_events_v1 '
            'WHERE legacy_alert_id=? ORDER BY created_at,event_id LIMIT 101',(history_id,)).fetchall()
        if not alerts or len(alerts)>100 or len({r['decision_id'] for r in alerts})!=1: return None
        decision_id=alerts[0]['decision_id']
        decisions=conn.execute('SELECT event_id,candidate_id,created_at FROM measurement_decision_events_v1 '
            'WHERE decision_id=? ORDER BY created_at,event_id LIMIT 101',(decision_id,)).fetchall()
        if not decisions or len(decisions)>100 or len({r['candidate_id'] for r in decisions})!=1: return None
        candidate_id=decisions[0]['candidate_id']
        candidates=conn.execute('SELECT ticker FROM measurement_candidates_v1 WHERE candidate_id=? LIMIT 2',
            (candidate_id,)).fetchall()
        if len(candidates)!=1 or candidates[0]['ticker']!=ticker: return None
        deliveries=conn.execute('SELECT event_id,delivery_id,attempt_id,status,external_message_id,confirmed_at,created_at '
            'FROM measurement_delivery_events_v1 WHERE decision_id=? ORDER BY created_at,event_id LIMIT 101',
            (decision_id,)).fetchall()
        if not deliveries or len(deliveries)>100: return None
        entities={decision_id,candidate_id,*[r['alert_id'] for r in alerts],
                  *[r['delivery_id'] for r in deliveries],*[r['attempt_id'] for r in deliveries]}
        events={*[r['event_id'] for r in alerts],*[r['event_id'] for r in decisions],
                *[r['event_id'] for r in deliveries]}
        correction=conn.execute('SELECT correction_id FROM measurement_corrections_v1 WHERE entity_id IN ('+
            ','.join('?' for _ in entities)+') OR prior_event_id IN ('+','.join('?' for _ in events)+') LIMIT 1',
            (*entities,*events)).fetchone()
        if correction is not None: return None
        latest={}; now=self.clock()
        for row in [*alerts,*decisions,*deliveries]:
            _timestamp(row['created_at'],now)
        for row in deliveries:
            if not row['delivery_id'] or not row['attempt_id']: return None
            if row['status'] not in {'attempt_created','send_started','confirmed_delivered','rejected_before_send','timed_out','failed'}:
                return None
            latest[(row['delivery_id'],row['attempt_id'])]=row
        confirmations=[]
        for row in latest.values():
            if row['status']!='confirmed_delivered': continue
            message=row['external_message_id']
            if not isinstance(message,str) or not re.fullmatch(r'[0-9]{1,24}',message) or int(message)<=0:
                continue
            confirmations.append(_timestamp(row['confirmed_at'],now))
        return DeliveryEvidence(min(confirmations)) if confirmations else None

    @staticmethod
    def _key(spec,row):
        return json.dumps([row[k] for k in spec.key_columns],separators=(',',':'))

    def _page(self,conn,source,spec,checkpoint,limit):
        select=', '.join('a.'+c for c in spec.columns)
        authority=''
        if source==SourceName.ANALYST:
            authority=' AND NOT EXISTS (SELECT 1 FROM analyst_post_views newer WHERE '
            authority+='newer.source_post_key=a.source_post_key AND newer.ticker=a.ticker AND '
            authority+='(newer.created_at>a.created_at OR (newer.created_at=a.created_at AND newer.id>a.id)))'
        if spec.key_columns==('id',):
            last=int(checkpoint.last_id or 0); cursor=int(checkpoint.reconciliation_cursor or 0)
            if last<0 or cursor<0: raise ValueError('invalid checkpoint')
            # Reserve capacity for both a five-second overlap lane and rotating
            # old IDs. An old in-place edit need not change its ID or timestamp.
            new_limit=limit if last==0 or limit<3 else max(1,limit//2)
            query=f'SELECT {select} FROM {spec.table} a WHERE a.id>?{authority} ORDER BY a.id LIMIT ?'
            new=list(conn.execute(query,(last,new_limit)))
            rows=list(new)
            if last and limit>=3:
                recent_limit=max(1,(limit-new_limit)//2)
                recent=f'SELECT {select} FROM {spec.table} a WHERE a.id<=? AND a.{spec.time_column}>=?'
                recent+=f'{authority} ORDER BY a.{spec.time_column} DESC,a.id DESC LIMIT ?'
                rows.extend(conn.execute(recent,(last,self.clock()-30,recent_limit)))
            remaining=limit-len(rows)
            old=[]
            if last and remaining>0:
                old_query=f'SELECT {select} FROM {spec.table} a WHERE a.id>? AND a.id<=?{authority} ORDER BY a.id LIMIT ?'
                old=list(conn.execute(old_query,(cursor,last,remaining)))
                if not old: old=list(conn.execute(old_query,(0,last,remaining)))
                rows.extend(old)
            seen=set(); unique=[]
            for row in rows:
                if row['id'] not in seen: unique.append(row); seen.add(row['id'])
            next_id=str(max([last]+[r['id'] for r in new]))
            old_cursor=str(old[-1]['id']) if old else checkpoint.reconciliation_cursor
            observed=max([checkpoint.last_observed_at or 0]+[
                float(r[spec.time_column]) for r in new if isinstance(r[spec.time_column],(float,int))
                and math.isfinite(r[spec.time_column]) and 0<r[spec.time_column]<=self.clock()+86400])
            return unique,SourceCheckpoint(next_id,observed or None,old_cursor)
        # Composite/key-only sources have mutable rows: cyclic lexicographic
        # key scan revisits every key without treating pruning as a retraction.
        keys=spec.key_columns
        cursor=json.loads(checkpoint.reconciliation_cursor) if checkpoint.reconciliation_cursor else ['']*len(keys)
        if not isinstance(cursor,list) or len(cursor)!=len(keys) or not all(isinstance(k,str) for k in cursor):
            raise ValueError('invalid checkpoint')
        expression='('+','.join('a.'+k for k in keys)+')' if len(keys)>1 else 'a.'+keys[0]
        placeholders='('+','.join('?' for k in keys)+')' if len(keys)>1 else '?'
        query=f'SELECT {select} FROM {spec.table} a WHERE {expression}>{placeholders} ORDER BY '
        query+=','.join('a.'+k for k in keys)+' LIMIT ?'
        rows=list(conn.execute(query,(*cursor,limit)))
        if not rows: rows=list(conn.execute(query,(*(['']*len(keys)),limit)))
        next_cursor=self._key(spec,rows[-1]) if rows else checkpoint.reconciliation_cursor
        return rows,SourceCheckpoint(checkpoint.last_id,checkpoint.last_observed_at,next_cursor)

    def _project(self,source,row,now):
        if source in {SourceName.SOURCE_HEALTH,SourceName.ROUTINE_HEALTH}:
            # Health is a separate sanitized admin surface, never evidence.
            raise ValueError('operational source is not market content')
        ticker=row['ticker']
        if not isinstance(ticker,str) or not _TICKER.fullmatch(ticker): raise ValueError('invalid ticker')
        key=source.value+':'+self._key(_SPECS[source],row); excerpt=''; url=None; score=None; price=None; direction='unclear'
        computed=None; stale=False
        observed=_timestamp(row[_SPECS[source].time_column],now)
        classification={'source':source.value,'product':'unverified'}
        if source==SourceName.ANALYST:
            key=row['source_post_key']
            if not isinstance(key,str) or not 0<len(key)<=256: raise ValueError('invalid post key')
            raw=row['raw_text']; reason=row['reason_text']; start=row['reason_start']; end=row['reason_end']
            _text(raw,16000)
            if hashlib.sha256(raw.encode()).hexdigest()!=row['raw_text_sha256']: raise ValueError('invalid quote hash')
            kind=row['reason_kind']; code=row['decision_code']
            if code in {'explicit_clause','reason_only'}:
                if (type(start) is not int or type(end) is not int or not 0<=start<end<=len(raw)
                        or raw[start:end]!=reason or kind not in {'position','setup','event_claim'}):
                    raise ValueError('invalid exact text evidence')
                excerpt=_text(reason)
            elif code=='image_evidence':
                if kind!='image' or reason is not None or start is not None or end is not None:
                    raise ValueError('image cannot manufacture text evidence')
            elif code=='direction_only':
                if kind!='none' or reason is not None: raise ValueError('invalid direction-only evidence')
            else:
                raise ValueError('unsupported parser decision')
            if row['display_direction'] not in _DIRECTIONS: raise ValueError('invalid direction')
            direction=_DIRECTIONS[row['display_direction']]
            if code=='reason_only' and direction!='unclear': raise ValueError('unsupported reason direction')
            image=strict_json(row['image_evidence_json']) if row['image_evidence_json'] is not None else {}
            if image:
                allowed={'ticker','sentiment','setup_direction','overall_sentiment','confidence',
                         'direction_basis','direction_evidence','image_url'}
                if set(image)-allowed or image.get('ticker')!=ticker: raise ValueError('invalid image evidence')
                confidence=_number(image.get('confidence'))
                if confidence is None or not .65<=confidence<=1 or safe_url(image.get('image_url')) is None:
                    raise ValueError('invalid image evidence')
                if image.get('direction_basis') not in {'annotated_setup','price_action','fundamental_event'}:
                    raise ValueError('invalid image evidence')
                if image.get('setup_direction')!=row['display_direction']:
                    raise ValueError('conflicting image direction')
                _text(image.get('direction_evidence'))
            elif code=='image_evidence':
                raise ValueError('missing image evidence')
            observed=_timestamp(row['detected_at'],now)
            computed=_timestamp(row['created_at'],now)
            url=safe_url(row['source_url'])
            classification.update(authority_id=row['id'],parser=_text(row['parser_version'],128),
                                  decision=code,reason_kind=kind,image=image,span=[start,end],
                                  source_text_hash=row['raw_text_sha256'])
        elif source==SourceName.SIGNAL:
            classification['source_type']=_text(row['source_type'],64)
            direction=_DIRECTIONS.get(row['direction'],'unclear')
            score=_number(row['quality_score']); url=safe_url(row['source_link'])
        elif source in {SourceName.ALERT,SourceName.SNAPSHOT}:
            score=_number(row['confidence_score'] if source==SourceName.ALERT else row['final_score'])
            values=strict_json(row['consensus_breakdown'] if source==SourceName.ALERT else row['sources_json'])
            allowed={'base','additional_analysts','news_catalyst','sec_filing','social_apewisdom',
                'social_stocktwits','social_reddit','google_trends','technical','llm_boost','youtube','options_flow',
                'total','precision_classification'}
            if set(values)-allowed: raise ValueError('unknown score fields')
            for name,value in values.items():
                if name!='precision_classification': _number(value)
            classification['scores']={name:value for name,value in values.items() if name!='precision_classification'}
            if source==SourceName.ALERT:
                technical=strict_json(row['technical_data'])
                if set(technical)-{'ticker','filters','price','volume','price_change_pct','atr14'}:
                    raise ValueError('unknown technical fields')
                price=_number(technical.get('price'),positive=True)
                classification['technical']={name:_number(technical.get(name),positive=name in {'price','atr14'})
                    for name in ['price','volume','price_change_pct','atr14']}
            else:
                price=_number(row['outcome_price_at_alert'],positive=True)
        elif source==SourceName.OPTIONS:
            # Product fallback and send-success are not persisted. Do not expose
            # these metrics or upgrade alerted=1 to proof of publication.
            _timestamp(row['detected_at'],now)
            observed=_timestamp(row['last_trade_ts'],now,optional=True) if row['last_trade_ts'] else None
            classification['product']='missing_served_product'
        elif source==SourceName.TICKER:
            classification['source_type']=_text(row['source_type'],64)
            if row['source_type'] in {'desktop_auth','desktop_local'}: raise ValueError('private source')
            _timestamp(row['expires_at'],now)
            direction=_DIRECTIONS.get(row['sentiment'],'unclear')
        elif source==SourceName.RESEARCH:
            if row['source'] not in {'analyst','sec','news'}: raise ValueError('unknown research source')
            classification['subsource']=row['source']
            computed=observed; observed=None
            stale=row['status']!='ok'
            if stale: computed=_timestamp(row['last_good_at'],now,optional=True)
            # Stored prose has unknown contributors/model rights: do not project.
        payload=MarketPayload(ticker=ticker,direction=direction,excerpt=excerpt,score=score,price=price)
        normalized={'key':key,'ticker':ticker,'observed_at':observed,'computed_at':computed,
            'url':url,'payload':payload.model_dump(),'classification':classification,'stale':stale}
        version=hashlib.sha256(json.dumps(normalized,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
        return SourceRecord(source,key,ticker,version,observed,computed,url,direction,excerpt,payload,stale=stale)
