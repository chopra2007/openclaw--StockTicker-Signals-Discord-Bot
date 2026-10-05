"""Closed tool grammar and private, currently authorized evidence retrieval."""
from dataclasses import dataclass, field
import json
import re
from typing import Annotated, Literal

from pydantic import Field, TypeAdapter
from .contracts import PublicModel, ContentLineage, Evidence, SectionResult
from .features import require_features, feature_mask
from .market_reader import MarketPayload
from .publication import evidence_retraction, Publisher

Ticker = Annotated[str, Field(pattern=r'^[A-Z][A-Z0-9.\-]{0,15}$')]


class LookupArgs(PublicModel):
    ticker: Ticker
    limit: int = Field(default=20, ge=1, le=20)


class ResearchArgs(PublicModel):
    request_id: Annotated[str, Field(pattern=r'^[0-9a-f-]{36}$')]


class RequestArgs(PublicModel):
    ticker: Ticker
    refresh: Literal[False] = False


class Lookup(PublicModel):
    name: Literal['lookup_market']
    arguments: LookupArgs


class GetResearch(PublicModel):
    name: Literal['get_research']
    arguments: ResearchArgs


class RequestResearch(PublicModel):
    name: Literal['request_research']
    arguments: RequestArgs


ToolCall = Annotated[Lookup | GetResearch | RequestResearch, Field(discriminator='name')]
TOOL_ADAPTER = TypeAdapter(ToolCall)
TOOL_SCHEMAS = TOOL_ADAPTER.json_schema()


def parse_tool(value):
    return TOOL_ADAPTER.validate_python(value)


@dataclass
class ToolResult:
    content: dict
    contributors: list = field(default_factory=list)
    evidence: dict = field(default_factory=dict)
    feature_versions: dict = field(default_factory=dict)


def permitted(jobs, con, lineage, evidence, now, observed_at):
    if lineage is None or not require_features(con,lineage.required_features): return False
    tracked = {(s.source_id,s.source_version) for s in lineage.sources}
    return (all((e.source_id,e.source_version) in tracked and evidence_retraction(con,e,jobs.policy) is None for e in evidence)
        and all(jobs.policy._authorize_lineage(con,lineage,use,now,observed_at).allowed
                for use in ('model_input','retain','display_raw','display_derived')))


def add_record(result, jobs, con, row, content, evidence, now, observed_at):
    lineage = jobs.policy.stored_lineage(row)
    observations=[observed_at,*[e.observed_at for e in evidence]]
    observed_at=max(observations) if all(o is not None for o in observations) else None
    if not permitted(jobs,con,lineage,evidence,now,observed_at): return False
    # Whole oversized records are withheld; never cut attribution or lineage.
    if any(len(e.excerpt)>1000 for e in evidence): return False
    if len(json.dumps(content))>12000: return False
    for item in evidence:
        existing=result.evidence.get(item.id)
        if existing is not None and existing != item: return False
    result.contributors.append((lineage,evidence,observed_at))
    result.evidence.update({e.id:e for e in evidence})
    current=feature_mask(con)
    result.feature_versions.update({f:current[f] for f in lineage.required_features})
    return True


def lookup_market(jobs, con, principal, call, now):
    result=ToolResult({'status':'available','records':[]})
    rows=con.execute('SELECT p.* FROM publications p JOIN publication_heads h ON h.publication_id=p.id WHERE h.active=1 AND p.ticker=? ORDER BY p.observed_at DESC LIMIT ?',
                     (call.arguments.ticker,call.arguments.limit)).fetchall()
    for row in rows:
        try:
            loaded=Publisher(jobs.store,jobs.policy)._load(con,row,now,feed_guard=True)
            if loaded is None: continue
            payload=loaded[0]
            data=payload.model_dump(mode='json')
            if len(payload.excerpt)>1000: continue
            if add_record(result,jobs,con,row,data,payload.evidence,now,row['observed_at']):
                result.content['records'].append(data)
        except (ValueError,TypeError): continue
    return result


def get_research(jobs, con, principal, call, now):
    result=ToolResult({'status':'unavailable','sections':[]})
    rows=con.execute('SELECT m.* FROM market_results m JOIN request_sections s ON s.result_id=m.id JOIN research_requests r ON r.id=s.request_id JOIN report_owners o ON o.id=r.report_owner_id WHERE r.id=? AND r.member_id=? AND o.member_id=? AND r.deleted_at IS NULL AND o.deleted_at IS NULL',
                     (call.arguments.request_id,principal.member_id,principal.member_id)).fetchall()
    for row in rows:
        value=jobs._read_result(con,row,now)
        if value is not None and add_record(result,jobs,con,row,value.model_dump(mode='json'),value.evidence,now,row['observed_at']):
            result.content['sections'].append(value.model_dump(mode='json'))
            result.content['status']='available'
    return result


READ_TOOLS={'lookup_market':lookup_market,'get_research':get_research}
