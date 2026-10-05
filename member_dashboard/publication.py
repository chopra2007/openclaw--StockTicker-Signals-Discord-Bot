"""Safe card projections with versioned lineage and current-policy rechecks.

The feed synchronizer and routes are intentionally later work. Source pruning
does not call retract; only a trusted explicit correction/retraction may do so.
"""
from dataclasses import dataclass
import hashlib
import html
import json
import sqlite3
from uuid import NAMESPACE_URL,uuid5,uuid4

from pydantic import ValidationError
from .contracts import ContentLineage,Evidence
from .market_reader import MarketPayload,SourceName,SourceRecord,safe_url,strict_json


def card_identity(key: str,ticker: str) -> str:
    return str(uuid5(NAMESPACE_URL,json.dumps([key,ticker],separators=(',',':'))))


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
        (evidence,),row.lineage,row.key,True,row.stale)


class Publisher:
    def __init__(self,store,policy): self.store=store; self.policy=policy

    def save(self,publication: Publication,now: float) -> bool:
        if not isinstance(publication,Publication): raise ValueError('typed publication required')
        with self.store.transaction() as conn:
            use='display_raw' if publication.required_feature=='feed' else 'display_derived'
            decision=self.policy._authorize_lineage(conn,publication.lineage,use,now,publication.observed_at)
            retain=self.policy._authorize_lineage(conn,publication.lineage,'retain',now)
            if not decision.allowed or not retain.allowed: return False
            payload=publication.payload.model_copy(update={'attributions':list(decision.attributions),
                                                          'evidence':list(publication.evidence)})
            values=(publication.source_post_key,publication.payload.ticker,publication.content_version,
                publication.required_feature,payload.model_dump_json(),
                json.dumps([s.model_dump() for s in publication.lineage.sources]),
                json.dumps([d.model_dump() for d in publication.lineage.field_dependencies]),
                json.dumps(publication.lineage.required_features),decision.retention_deadline,
                publication.observed_at,now)
            inserted=conn.execute('INSERT OR IGNORE INTO publications(id,source_post_key,ticker,content_version,feature,'
                'content_json,source_lineage_json,field_dependencies_json,required_features_json,retention_deadline,'
                'observed_at,published_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',(str(uuid4()),*values)).rowcount
            if inserted:
                conn.execute('INSERT OR IGNORE INTO publication_changes(card_id,content_version,operation,feature,content_json,'
                    'source_lineage_json,field_dependencies_json,required_features_json,retention_deadline,changed_at) '
                    "VALUES (?,?,'upsert',?,?,?,?,?,?,?)",(publication.card_id,publication.content_version,
                    publication.required_feature,values[4],values[5],values[6],values[7],decision.retention_deadline,now))
            return True

    def load(self,publication_id: str,now: float) -> MarketPayload | None:
        """Current source-use guard for saved cards; membership/features are additional guards."""
        with self.store.transaction() as conn:
            conn.row_factory=sqlite3.Row
            row=conn.execute('SELECT content_json,source_lineage_json,required_features_json,field_dependencies_json,'
                'retention_deadline,feature,observed_at,retracted_at FROM publications WHERE id=?',(publication_id,)).fetchone()
            if row is None or row['retracted_at'] is not None: return None
            lineage=self.policy.stored_lineage(row)
            use='display_raw' if row['feature']=='feed' else 'display_derived'
            decision=self.policy._authorize_lineage(conn,lineage,use,now,row['observed_at'])
            if not decision.allowed or row['feature'] not in lineage.required_features: return None
            try:
                payload=MarketPayload.model_validate(strict_json(row['content_json']))
                evidence=[item.model_copy(update={'url':safe_url(item.url),
                    'excerpt':html.escape(html.unescape(item.excerpt),quote=True)}) for item in payload.evidence]
                return payload.model_copy(update={'excerpt':html.escape(html.unescape(payload.excerpt),quote=True),
                                                  'attributions':list(decision.attributions),'evidence':evidence})
            except (ValueError,TypeError,ValidationError,RecursionError): return None

    def retract(self,source_post_key: str,ticker: str,now: float) -> None:
        """Trusted explicit withdrawal, never invoked merely because a row disappeared."""
        with self.store.transaction() as conn:
            rows=conn.execute('SELECT id,content_version,feature FROM publications WHERE source_post_key=? AND ticker=? '
                'AND retracted_at IS NULL',(source_post_key,ticker)).fetchall()
            for id,version,feature in rows:
                conn.execute('UPDATE publications SET retracted_at=? WHERE id=?',(now,id))
                conn.execute('INSERT OR IGNORE INTO publication_changes(card_id,content_version,operation,feature,changed_at) '
                    "VALUES (?,?,'delete',?,?)",(card_identity(source_post_key,ticker),version,feature,now))
