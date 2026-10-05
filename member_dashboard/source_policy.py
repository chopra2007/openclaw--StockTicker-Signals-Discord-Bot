"""Separate use permissions, complete lineage and web-only deletion hooks.

No provider contact or grant inference. Default authority/backups remain closed
until the operator supplies independently verified current-state evidence.
"""
from dataclasses import dataclass
import hashlib
import html
import json
import math
import sqlite3
from typing import Callable, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from .contracts import ContentLineage, SourceContribution
from .market_reader import safe_url

Use=Literal['display_raw','display_derived','retain','model_input']
_USES=frozenset({'display_raw','display_derived','retain','model_input'})
_CONTENT_TABLES=('assets','publication_changes','publications','messages','report_versions','market_results')


class SourcePermission(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True,allow_inf_nan=False)
    source_id: str=Field(min_length=1,max_length=128)
    product_id: str=Field(min_length=1,max_length=128)
    provider: str=Field(min_length=1,max_length=128)
    private_grant_ref: str | None=Field(default=None,repr=False,max_length=256)
    private_account_ref: str | None=Field(default=None,repr=False,max_length=256)
    policy_version: str=Field(min_length=1,max_length=128)
    audience: str=Field(min_length=1,max_length=128)
    status: Literal['allowed','denied','unverified']='unverified'
    display_raw: bool=False
    display_derived: bool=False
    retain: bool=False
    model_input: bool=False
    attribution: str | None=Field(default=None,max_length=256)
    delay_seconds: float=Field(default=0,ge=0)
    effective_at: float | None=None
    expires_at: float | None=None
    review_at: float | None=None
    retention_deadline: float | None=None
    terms_url: str | None=Field(default=None,max_length=2048)
    evidence_ref: str | None=Field(default=None,repr=False,max_length=256)
    delete_on_expiry: bool=False
    tombstone_allowed: bool=False


@dataclass(frozen=True)
class PermissionDecision:
    status: Literal['allowed','denied','unverified']
    cache_key: str
    retention_deadline: float | None=None
    attributions: tuple[str,...]=()
    delay_seconds: float=0
    reason: str='source_permission_unavailable'

    @property
    def allowed(self): return self.status=='allowed'


@dataclass(frozen=True)
class PurgeOutcome:
    deleted: int
    cursors: dict[str,int]
    more: bool


class SourcePolicy:
    def __init__(self,store, *, authority_current: Callable[[],bool]=lambda:False,
                 backup_compliant: Callable[[str,str],bool]=lambda source,product:False):
        self.store=store
        self.authority_current=authority_current
        self.backup_compliant=backup_compliant
        self.denial_journal=None

    def record(self,permission: SourcePermission) -> None:
        """Local trusted grant registry insertion; never exposed as a web route."""
        if not isinstance(permission,SourcePermission): raise ValueError('typed permission required')
        values=permission.model_dump()
        # Fields come exclusively from this fixed DTO, not a caller's mapping.
        names=tuple(SourcePermission.model_fields)
        with self.store.transaction() as conn:
            if permission.status!='allowed' and self.denial_journal is not None:
                self.denial_journal.append('source_denied',permission.source_id+'/'+permission.product_id)
            conn.execute('INSERT INTO source_permissions(id,'+','.join(names)+') VALUES ('+
                ','.join('?' for _ in range(len(names)+1))+')',
                (str(uuid4()),*(values[name] for name in names)))

    def authorize(self,source_ids,use: Use,now: float) -> PermissionDecision:
        with self.store.transaction() as conn:
            return self._authorize(conn,source_ids,use,now)

    def _authorize(self,conn,source_ids,use,now):
        if use not in _USES: raise ValueError('unknown source use')
        if not isinstance(now,(int,float)) or isinstance(now,bool) or not math.isfinite(now):
            raise ValueError('invalid policy time')
        items=list(source_ids) if isinstance(source_ids,(list,tuple)) else []
        if not 1<=len(items)<=200 or not all(isinstance(x,SourceContribution) for x in items):
            return PermissionDecision('unverified','missing-lineage')
        stamps=[]; statuses=[]; deadlines=[]; attributions=[]; delays=[]
        try: authority=self.authority_current() is True
        except Exception: authority=False
        for item in items:
            conn.row_factory=sqlite3.Row
            row=conn.execute('SELECT source_id,product_id,provider,private_grant_ref,private_account_ref,'
                'policy_version,audience,display_raw,display_derived,retain,model_input,status,attribution,'
                'delay_seconds,effective_at,expires_at,review_at,retention_deadline,terms_url,evidence_ref,'
                'delete_on_expiry,tombstone_allowed FROM source_permissions WHERE source_id=? AND product_id=? '
                'ORDER BY rowid DESC LIMIT 1',(item.source_id,item.product_id)).fetchone()
            status='unverified'
            if row:
                if row['status']=='denied' or row['audience']!='invited_members': status='denied'
                elif row['expires_at'] is not None and row['expires_at']<=now: status='denied'
                elif row['retention_deadline'] is not None and row['retention_deadline']<=now: status='denied'
                elif (row['status']=='allowed' and authority and row['private_grant_ref'] and row['evidence_ref']
                    and safe_url(row['terms_url']) and row['effective_at'] is not None and row['effective_at']<=now
                    and (row['review_at'] is None or row['review_at']>now)
                    and row['policy_version']==item.policy_version):
                    obligation=row['delete_on_expiry'] or row['retention_deadline'] is not None
                    try: backups=not obligation or self.backup_compliant(item.source_id,item.product_id) is True
                    except Exception: backups=False
                    if backups: status='allowed' if row[use] else 'denied'
                for name in ['retention_deadline']+(['expires_at'] if row['delete_on_expiry'] else []):
                    if row[name] is not None: deadlines.append(row[name])
                if status=='allowed':
                    if row['attribution']: attributions.append(html.escape(row['attribution'],quote=True))
                    delays.append(row['delay_seconds'] or 0)
            stamps.append((item.source_id,item.product_id,item.source_version,item.policy_version,
                row['policy_version'] if row else None,status))
            statuses.append(status)
        status='denied' if 'denied' in statuses else 'unverified' if 'unverified' in statuses else 'allowed'
        key=hashlib.sha256(json.dumps([use,sorted(stamps)],separators=(',',':')).encode()).hexdigest()
        return PermissionDecision(status,key,min(deadlines) if deadlines else None,
            tuple(sorted(set(attributions))),max(delays,default=0), 'allowed' if status=='allowed' else 'source_permission_unavailable')

    def authorize_lineage(self,lineage: ContentLineage | None,use: Use,now: float,
                          *, observed_at: float | None=None) -> PermissionDecision:
        with self.store.transaction() as conn:
            return self._authorize_lineage(conn,lineage,use,now,observed_at)

    def _authorize_lineage(self,conn,lineage,use,now,observed_at=None):
        if not isinstance(lineage,ContentLineage): return PermissionDecision('unverified','missing-lineage')
        decision=self._authorize(conn,lineage.sources,use,now)
        deadlines=[x for x in (lineage.retention_deadline,decision.retention_deadline) if x is not None]
        earliest=min(deadlines) if deadlines else None
        if earliest is not None and earliest<=now:
            return PermissionDecision('denied',decision.cache_key,earliest)
        if (decision.allowed and use in {'display_raw','display_derived','model_input'} and decision.delay_seconds
                and (observed_at is None or observed_at+decision.delay_seconds>now)):
            return PermissionDecision('denied',decision.cache_key,earliest)
        return PermissionDecision(decision.status,decision.cache_key,earliest,decision.attributions,
                                  decision.delay_seconds,decision.reason)

    @staticmethod
    def stored_lineage(row) -> ContentLineage | None:
        try:
            return ContentLineage.model_validate(dict(sources=json.loads(row['source_lineage_json']),
                required_features=json.loads(row['required_features_json']),
                field_dependencies=json.loads(row['field_dependencies_json']),retention_deadline=row['retention_deadline']))
        except (ValueError,TypeError,ValidationError,RecursionError): return None

    def _tombstone_allowed(self,conn,lineage):
        if lineage is None: return False
        return self._tombstone_sources_allowed(conn,lineage.sources)

    def _tombstone_sources_allowed(self,conn,sources):
        for source in sources:
            row=conn.execute('SELECT tombstone_allowed FROM source_permissions WHERE source_id=? AND product_id=? '
                'ORDER BY rowid DESC LIMIT 1',(source.source_id,source.product_id)).fetchone()
            if row is None or not row[0]: return False
        return True

    def _retraction_metadata_allowed(self,conn,raw_sources):
        """Current non-content retention rights, independent of content grants."""
        try:
            if self.authority_current() is not True: return False
            values=json.loads(raw_sources)
            if not isinstance(values,list) or not 1<=len(values)<=200: return False
            sources=[SourceContribution.model_validate(value) for value in values]
            return self._tombstone_sources_allowed(conn,sources)
        except Exception: return False

    def purge(self,now: float, *, limit: int=100,cursors: dict[str,int] | None=None) -> PurgeOutcome:
        """Bounded deletion of web content; never bot tables/files or backups.

        Call repeatedly with returned cursors until more is false, then reset
        cursors for the next sweep. Admission stays closed unless outside backup
        deletion/current-authority proofs are independently verified.
        """
        if type(limit) is not int or not 1<=limit<=100: raise ValueError('invalid purge bounds')
        cursors=cursors or {}; next_cursors={}; deleted=0; more=False
        with self.store.transaction() as conn:
            conn.row_factory=sqlite3.Row
            for table in _CONTENT_TABLES:
                cursor=cursors.get(table,0)
                if type(cursor) is not int or cursor<0: raise ValueError('invalid purge cursor')
                id_column='sequence' if table=='publication_changes' else 'id'
                extra=',source_post_key,ticker,feature,content_version,content_json' if table=='publications' else ''
                if table=='messages': extra=',role'
                if table=='publication_changes': extra=',operation,content_json'
                rows=conn.execute(f'SELECT rowid AS scan_id,{id_column} AS object_id,source_lineage_json,'
                    f'field_dependencies_json,required_features_json,retention_deadline{extra} FROM {table} '
                    'WHERE rowid>? ORDER BY rowid LIMIT ?',(cursor,limit)).fetchall()
                next_cursors[table]=rows[-1]['scan_id'] if rows else cursor
                more=more or len(rows)==limit
                for row in rows:
                    no_source_metadata=(row['source_lineage_json']=='[]' and row['retention_deadline'] is None
                                        and row['field_dependencies_json']=='[]' and row['required_features_json']=='[]')
                    if table=='messages' and row['role']=='user' and no_source_metadata:
                        continue # A member's own text is not inferred to be source content.
                    if (table=='publication_changes' and row['operation']=='delete' and row['content_json'] is None
                            and no_source_metadata):
                        continue # Non-content delete events must survive.
                    lineage=self.stored_lineage(row)
                    if self._authorize_lineage(conn,lineage,'retain',now).allowed: continue
                    if self._tombstone_allowed(conn,lineage):
                        conn.execute('INSERT OR IGNORE INTO content_tombstones(object_type,object_id,reason,removed_at) '
                            "VALUES (?,?,'source_permission_unavailable',?)",(table,str(row['object_id']),now))
                    if table=='publications':
                        from .publication import purge_publication
                        purge_publication(conn,row,now,self)
                    if table=='publication_changes':
                        from .publication import advance_log_floor
                        advance_log_floor(conn,row['object_id'])
                    conn.execute(f'DELETE FROM {table} WHERE {id_column}=?',(row['object_id'],))
                    deleted+=1
            for table in ('publication_retractions','evidence_retractions','publication_evidence_refs'):
                cursor=cursors.get(table,0)
                if type(cursor) is not int or cursor<0: raise ValueError('invalid purge cursor')
                rows=conn.execute(f'SELECT rowid,source_lineage_json FROM {table} WHERE rowid>? ORDER BY rowid LIMIT ?',
                                  (cursor,limit)).fetchall()
                next_cursors[table]=rows[-1][0] if rows else cursor
                more=more or len(rows)==limit
                for row in rows:
                    if self._retraction_metadata_allowed(conn,row[1]): continue
                    # Erasing the exact identity must never allow it to be
                    # treated as unretracted after restart or reapproval.
                    conn.execute('UPDATE feed_state SET retraction_authority_required=1 WHERE singleton=1')
                    conn.execute(f'DELETE FROM {table} WHERE rowid=?',(row[0],))
                    deleted+=1
        return PurgeOutcome(deleted,next_cursors,more)
