"""Private durable assistant orchestration in the existing compute child."""
import asyncio
import json
import hashlib
import re
import sqlite3
import time
from uuid import uuid4

from .auth import AuthError, Principal
from .contracts import AssistantRun, ContentLineage, FieldDependency, MessageContent
from .features import feature_mask, mask_current, require_features
from .history import HistoryError
from .jobs import packed, ResearchError
from .assistant_tools import TOOL_SCHEMAS, READ_TOOLS, ToolResult, parse_tool, permitted
from .assistant_transport import ModelTurn, TurnBudget, INPUT_BOUND, OUTPUT_BOUND, wire_body

NOTICE='Market Assistant is unavailable.'
UNSUPPORTED='This request could not be answered with the available market tools.'
SENSITIVE=re.compile(r'https?://|file:|[a-z]:[\\/]|/(?:home|root|etc|proc|tmp)/|\bsk-[a-z0-9-]+|\b(?:host secret|api[_ -]?key|authorization:|bearer |password|private[_ -]?key|openclaw|run_shell|traceback)\b',re.I)


class AssistantService:
    def __init__(self,history,*,transport=None,clock=time.time):
        self.history,self.jobs,self.transport,self.clock=history,history.jobs,transport,clock

    def fingerprint(self):
        return hashlib.sha256(packed([self.transport.fingerprint,TOOL_SCHEMAS,INPUT_BOUND,OUTPUT_BOUND,4000,20,4,90]).encode()).hexdigest()

    def create_conversation(self,principal,title):
        if type(title)is not str or not 1<=len(title.strip())<=256: raise HistoryError(422)
        with self.jobs.store.transaction() as con:
            con.row_factory=sqlite3.Row
            self.jobs.auth.revalidate(principal,self.clock(),con=con)
            if not require_features(con,['assistant']): raise HistoryError(403)
            identity=str(uuid4())
            con.execute('INSERT INTO conversations(id,member_id,title,created_at) VALUES (?,?,?,?)',(identity,principal.member_id,title.strip(),self.clock()))
            return self.history._conversation_ref(con.execute('SELECT * FROM conversations WHERE id=?',(identity,)).fetchone())

    async def run_assistant(self,principal,conversation_id,message,ticker_context):
        return self.submit(principal,conversation_id,message,ticker_context)

    def submit(self,principal,conversation_id,message,ticker_context=None):
        if type(message)is not str or not 1<=len(message.strip())<=4000: raise HistoryError(422)
        if ticker_context is not None:
            try: ticker_context=self.jobs.registry.catalog.lookup(ticker_context)
            except ValueError: raise HistoryError(422) from None
        now=self.clock()
        with self.jobs.store.transaction() as con:
            con.row_factory=sqlite3.Row
            owner=self.history.owned_live_conversation(con,principal,conversation_id,now)
            if owner is None: raise HistoryError()
            if not require_features(con,['assistant']): raise HistoryError(403)
            if con.execute("SELECT 1 FROM assistant_runs WHERE member_id=? AND status IN ('queued','running','draining')",(principal.member_id,)).fetchone(): raise HistoryError(429)
            if con.execute("SELECT count(*) FROM web_usage WHERE member_id=? AND kind='assistant_message' AND occurred_at>?",(principal.member_id,now-3600)).fetchone()[0]>=20: raise HistoryError(429)
            message_id,run_id=str(uuid4()),str(uuid4())
            con.execute("INSERT INTO messages(id,conversation_id,member_id,role,content_json,created_at) VALUES (?,?,?,'user',?,?)",(message_id,conversation_id,principal.member_id,MessageContent(text=message.strip()).model_dump_json(),now))
            available=self.transport is not None and self.transport.available(now)
            con.execute('INSERT INTO assistant_runs(id,conversation_id,member_id,session_id,authorization_version,status,created_at,finished_at,error_code,input_message_id,ticker_context,conversation_version,feature_mask,transport_fingerprint,model_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (run_id,conversation_id,principal.member_id,principal.session_id,principal.authorization_version,'queued' if available else 'unavailable',now,None if available else now,None if available else 'unavailable',message_id,ticker_context,owner['version'],packed({'assistant':feature_mask(con)['assistant']}),self.fingerprint() if available else None,self.transport.model if available else None))
            con.execute("INSERT INTO web_usage(id,member_id,run_id,kind,units,occurred_at) VALUES (?,?,?,'assistant_message',1,?)",(str(uuid4()),principal.member_id,run_id,now))
            return self._dto(con.execute('SELECT * FROM assistant_runs WHERE id=?',(run_id,)).fetchone())

    @staticmethod
    def _dto(row):
        status={'draining':'running','cancelled':'unavailable'}.get(row['status'],row['status'])
        return AssistantRun(id=row['id'],conversation_id=row['conversation_id'],status=status,ticker_context=row['ticker_context'],created_at=row['created_at'],finished_at=row['finished_at'],message=UNSUPPORTED if row['error_code']=='unsupported' else NOTICE if status in ('unavailable','failed') else None,response_message_id=row['response_message_id'],model_id=row['model_id'],input_tokens=row['actual_input_tokens'],output_tokens=row['actual_output_tokens'],cost=row['cost'])

    def get_run(self,principal,conversation_id,run_id):
        with self.jobs.store.transaction() as con:
            con.row_factory=sqlite3.Row
            if self.history.owned_live_conversation(con,principal,conversation_id,self.clock()) is None: raise HistoryError()
            if not require_features(con,['assistant']): raise HistoryError(403)
            if run_id=='latest':
                row=con.execute('SELECT * FROM assistant_runs WHERE conversation_id=? AND member_id=? AND deleted_at IS NULL ORDER BY created_at DESC,rowid DESC LIMIT 1',(conversation_id,principal.member_id)).fetchone()
            else:
                row=con.execute('SELECT * FROM assistant_runs WHERE id=? AND conversation_id=? AND member_id=? AND deleted_at IS NULL',(run_id,conversation_id,principal.member_id)).fetchone()
            if row is None: raise HistoryError()
            return self._dto(row)

    def _guard(self,con,run,now):
        row=con.execute('SELECT * FROM assistant_runs WHERE id=?',(run['id'],)).fetchone()
        if (row is None or row['status']!='running' or row['deleted_at'] is not None or row['subscriber_version']!=run['subscriber_version']
            or row['lease_token']!=run['lease_token'] or row['lease_until']<=now or row['deadline']<=now
            or not mask_current(con,row['feature_mask']) or self.transport is None or not self.transport.available(now)
            or self.fingerprint()!=row['transport_fingerprint']): raise HistoryError()
        member=con.execute('SELECT role FROM members WHERE id=?',(row['member_id'],)).fetchone()
        if member is None: raise HistoryError()
        principal=Principal(row['member_id'],member['role'],row['session_id'],row['authorization_version'])
        if self.history.owned_live_conversation(con,principal,row['conversation_id'],now,expected_version=row['conversation_version']) is None: raise HistoryError()
        return principal

    def claim(self,worker_id):
        now=self.clock()
        with self.jobs.store.transaction() as con:
            con.row_factory=sqlite3.Row
            if (con.execute("SELECT 1 FROM assistant_runs WHERE status IN ('running','draining') LIMIT 1").fetchone()
                or con.execute("SELECT 1 FROM web_jobs WHERE status IN ('running','draining') LIMIT 1").fetchone()): return None
            row=con.execute("SELECT * FROM assistant_runs WHERE status='queued' ORDER BY created_at,id LIMIT 1").fetchone()
            if row is None: return None
            token=str(uuid4())
            con.execute("UPDATE assistant_runs SET status='running',worker_id=?,lease_token=?,lease_until=?,deadline=? WHERE id=?",(worker_id,token,now+30,now+90,row['id']))
            run=dict(con.execute('SELECT * FROM assistant_runs WHERE id=?',(row['id'],)).fetchone())
            try: self._guard(con,run,now)
            except (HistoryError,AuthError):
                con.execute("UPDATE assistant_runs SET status='unavailable',finished_at=?,error_code='unavailable' WHERE id=?",(now,row['id']))
                return None
            return run

    def heartbeat(self,run):
        with self.jobs.store.transaction() as con:
            con.execute("UPDATE assistant_runs SET lease_until=? WHERE id=? AND lease_token=? AND status IN ('running','draining')",(self.clock()+30,run['id'],run['lease_token']))

    def _context(self,run):
        messages=[]; aggregate=ToolResult({})
        with self.jobs.store.transaction() as con:
            con.row_factory=sqlite3.Row
            principal=self._guard(con,run,self.clock())
            rows=con.execute('SELECT * FROM messages WHERE conversation_id=? AND member_id=? ORDER BY created_at DESC,rowid DESC LIMIT 20',(run['conversation_id'],principal.member_id)).fetchall()
            for row in reversed(rows):
                value=MessageContent.model_validate_json(row['content_json'])
                if row['role']=='user' and row['source_lineage_json']=='[]' and row['required_features_json']=='[]' and row['field_dependencies_json']=='[]' and row['retention_deadline'] is None and not value.evidence:
                    messages.append({'role':'user','text':value.text})
                else:
                    lineage=self.jobs.policy.stored_lineage(row)
                    if permitted(self.jobs,con,lineage,value.evidence,self.clock(),row['source_observed_at']):
                        messages.append({'role':'assistant','untrusted_evidence':value.model_dump(mode='json')})
                        aggregate.contributors.append((lineage,value.evidence,row['source_observed_at']))
                        aggregate.evidence.update({e.id:e for e in value.evidence})
                        current=feature_mask(con)
                        aggregate.feature_versions.update({f:current[f] for f in lineage.required_features})
        if run['ticker_context']: messages.append({'selected_ticker':run['ticker_context']})
        return messages,aggregate

    def _recheck(self,con,aggregate):
        if not mask_current(con,aggregate.feature_versions): raise HistoryError()
        if not all(permitted(self.jobs,con,l,e,self.clock(),observed) for l,e,observed in aggregate.contributors): raise HistoryError()

    async def execute_tool(self,principal,call,*,run):
        with self.jobs.store.transaction() as con:
            con.row_factory=sqlite3.Row
            current=self._guard(con,run,self.clock())
            if current!=principal: raise HistoryError()
            if call.name in READ_TOOLS: return READ_TOOLS[call.name](self.jobs,con,principal,call,self.clock())
        if call.name=='request_research':
            value=self.jobs.request_research(principal,call.arguments.ticker,False,self.clock(),guard=lambda con:self._guard(con,run,self.clock()))
            # Enqueue only, no source material or wait on the sole compute worker.
            return ToolResult({'status':'pending','request_id':value.id})
        raise ValueError('unknown tool')

    def _finish(self,run,status='unavailable',*,error='unavailable',turn=None,aggregate=None):
        now=self.clock()
        with self.jobs.store.transaction() as con:
            con.row_factory=sqlite3.Row
            row=con.execute('SELECT * FROM assistant_runs WHERE id=? AND lease_token=?',(run['id'],run['lease_token'])).fetchone()
            if row is None or row['status'] not in ('running','draining'): return
            response_id=None
            if turn is not None:
                try:
                    self._guard(con,run,now); self._recheck(con,aggregate)
                    if not aggregate.contributors or not turn.answer.strip() or SENSITIVE.search(turn.answer) or any(x not in aggregate.evidence for x in turn.citations): raise ValueError()
                    sources={packed(s.model_dump()):s for l,_,_ in aggregate.contributors for s in l.sources}
                    features=sorted({'assistant'}|{f for l,_,_ in aggregate.contributors for f in l.required_features})
                    deadlines=[l.retention_deadline for l,_,_ in aggregate.contributors if l.retention_deadline is not None]
                    lineage=ContentLineage(sources=list(sources.values()),required_features=features,field_dependencies=[FieldDependency(field_path='text',required_features=features)],retention_deadline=min(deadlines) if deadlines else None)
                    # Persist every exact evidence identity, including uncited contributors,
                    # so retraction on reopening covers omitted citations as well.
                    content=MessageContent(text=turn.answer,evidence=list(aggregate.evidence.values()))
                    response_id=str(uuid4())
                    observed=max(o for _,_,o in aggregate.contributors) if all(o is not None for _,_,o in aggregate.contributors) else None
                    con.execute("INSERT INTO messages(id,conversation_id,member_id,role,content_json,source_lineage_json,field_dependencies_json,required_features_json,retention_deadline,created_at,source_observed_at) VALUES (?,?,?,'assistant',?,?,?,?,?,?,?)",(response_id,run['conversation_id'],run['member_id'],content.model_dump_json(),packed([s.model_dump() for s in lineage.sources]),packed([d.model_dump() for d in lineage.field_dependencies]),packed(features),lineage.retention_deadline,now,observed))
                    status,error='completed',None
                except (HistoryError,AuthError,ValueError,TypeError): status,error='unavailable','unavailable'
            con.execute('UPDATE assistant_runs SET status=?,finished_at=?,error_code=?,response_message_id=? WHERE id=? AND lease_token=?',(status,now,error,response_id,run['id'],run['lease_token']))

    async def execute(self,run,runtime):
        try:
            messages,aggregate=self._context(run)
            invalid=0
            for ordinal in range(5):
                now=self.clock()
                with self.jobs.store.transaction() as con:
                    con.row_factory=sqlite3.Row
                    principal=self._guard(con,run,now); self._recheck(con,aggregate)
                    wire_body(messages,TOOL_SCHEMAS)
                    call_id=str(uuid4()); run['current_call_id']=call_id
                    con.execute('INSERT INTO assistant_turns(run_id,ordinal,call_id,input_bound,output_bound,status,created_at) VALUES (?,?,?,?,?,?,?)',(run['id'],ordinal,call_id,INPUT_BOUND,OUTPUT_BOUND,'prepared',now))
                    con.execute('UPDATE assistant_runs SET current_call_id=?,input_tokens=input_tokens+?,output_tokens=output_tokens+? WHERE id=?',(call_id,INPUT_BOUND,OUTPUT_BOUND,run['id']))
                remaining=min(90,run['deadline']-self.clock())
                async def send():
                    # Runtime admission yields: recheck again after that yield,
                    # immediately before the actual transport can send anything.
                    with self.jobs.store.transaction() as con:
                        con.row_factory=sqlite3.Row
                        self._guard(con,run,self.clock()); self._recheck(con,aggregate)
                    return await self.transport.complete(messages,TOOL_SCHEMAS,TurnBudget(call_id,min(remaining,run['deadline']-self.clock())))
                outcome=await runtime.run_async(call_id,send,remaining,provider='web-assistant')
                if not outcome.actual_completed and outcome.status in ('timeout','uncertain'):
                    with self.jobs.store.transaction() as con:
                        con.execute("UPDATE assistant_runs SET status='draining' WHERE id=? AND lease_token=?",(run['id'],run['lease_token']))
                        con.execute("UPDATE assistant_turns SET status='uncertain' WHERE call_id=?",(call_id,))
                    return False
                self._record_turn(run,outcome)
                runtime.forget(call_id)
                if outcome.status!='completed': self._finish(run); return True
                turn=ModelTurn.model_validate(outcome.value)
                if not turn.tool_calls:
                    self._finish(run,turn=turn,aggregate=aggregate); return True
                if turn.answer: self._finish(run); return True
                for raw in turn.tool_calls:
                    with self.jobs.store.transaction() as con:
                        con.row_factory=sqlite3.Row
                        principal=self._guard(con,run,self.clock()); self._recheck(con,aggregate)
                        count=con.execute('SELECT tool_calls FROM assistant_runs WHERE id=?',(run['id'],)).fetchone()[0]
                        if count>=4: raise ValueError('tool limit')
                        con.execute('UPDATE assistant_runs SET tool_calls=tool_calls+1 WHERE id=?',(run['id'],))
                    try:
                        call=parse_tool(raw)
                        result=await self.execute_tool(principal,call,run=run)
                    except (ValueError,ResearchError):
                        invalid+=1
                        if invalid>=2:
                            self._finish(run,'completed',error='unsupported'); return True
                        messages.append({'tool_result':{'status':'unsupported'}}); continue
                    if any(f in aggregate.feature_versions and aggregate.feature_versions[f]!=v for f,v in result.feature_versions.items()): raise HistoryError()
                    aggregate.feature_versions.update(result.feature_versions)
                    aggregate.contributors.extend(result.contributors)
                    for identity,value in result.evidence.items():
                        if identity in aggregate.evidence and aggregate.evidence[identity]!=value: raise ValueError('ambiguous evidence')
                        aggregate.evidence[identity]=value
                    messages.append({'tool':call.name,'untrusted_evidence':result.content})
            self._finish(run)
        except asyncio.CancelledError:
            with self.jobs.store.transaction() as con:
                con.execute("UPDATE assistant_runs SET status='draining' WHERE id=? AND lease_token=?",(run['id'],run['lease_token']))
            raise
        except (HistoryError,AuthError,ValueError,TypeError): self._finish(run)
        return True

    def _record_turn(self,run,outcome):
        turn=outcome.value if isinstance(outcome.value,ModelTurn) else None
        with self.jobs.store.transaction() as con:
            con.execute('UPDATE assistant_turns SET status=?,actual_input_tokens=?,actual_output_tokens=? WHERE call_id=?',('completed' if outcome.status=='completed' else 'failed',turn.input_tokens if turn else None,turn.output_tokens if turn else None,run['current_call_id']))
            values=con.execute('SELECT actual_input_tokens,actual_output_tokens FROM assistant_turns WHERE run_id=?',(run['id'],)).fetchall()
            con.execute('UPDATE assistant_runs SET actual_input_tokens=?,actual_output_tokens=? WHERE id=?',(sum(v[0] for v in values) if all(v[0] is not None for v in values) else None,sum(v[1] for v in values) if all(v[1] is not None for v in values) else None,run['id']))

    def settle(self,run,runtime):
        self.heartbeat(run)
        outcome=runtime.outcome(run['current_call_id'])
        if outcome is None: return False
        self._record_turn(run,outcome)
        self._finish(run)
        runtime.forget(run['current_call_id'])
        return True
