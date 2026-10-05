"""Owner-scoped saved bytes with current access overlays; reads never do work."""
import base64
import hashlib
import hmac
import json
import math
import sqlite3

from pydantic import ValidationError

from .auth import AuthError, Principal
from .contracts import (ConversationPage, ConversationRef, MessageContent, ReportPage,
    ReportRef, SavedConversation, SavedEvidenceAnnotation, SavedMessage, SavedReport, SectionResult)
from .features import require_features
from .jobs import empty_result, packed
from .publication import evidence_retraction


class HistoryError(Exception):
    def __init__(self, status=404):
        self.status = status


class HistoryService:
    def __init__(self, jobs, *, signing_key, clock):
        self.jobs, self.clock = jobs, clock
        if signing_key is not None and (type(signing_key) is not bytes or len(signing_key) < 32):
            raise ValueError('History signing key must contain at least 32 bytes')
        self.key = signing_key

    def _cursor(self, principal, resource, position):
        if self.key is None: raise HistoryError(503)
        value = dict(v=1, member=principal.member_id, resource=resource, position=position)
        raw = base64.urlsafe_b64encode(packed(value).encode()).decode().rstrip('=')
        return raw + '.' + hmac.new(self.key, ('history:'+raw).encode(), hashlib.sha256).hexdigest()

    def _position(self, principal, resource, cursor, limit):
        if self.key is None: raise HistoryError(503)
        if type(limit) is not int or not 1 <= limit <= 100: raise HistoryError(422)
        if cursor is None: return None
        try:
            if type(cursor) is not str or not 1 <= len(cursor) <= 4096: raise ValueError()
            raw, signature = cursor.split('.')
            expected = hmac.new(self.key, ('history:'+raw).encode(), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(signature, expected): raise ValueError()
            value = json.loads(base64.urlsafe_b64decode(raw+'='*(-len(raw)%4)))
            if set(value) != {'v','member','resource','position'} or value['v'] != 1 or value['member'] != principal.member_id or value['resource'] != resource: raise ValueError()
            stamp, identity = value['position']
            if type(stamp) not in (int,float) or not math.isfinite(stamp) or type(identity) is not str or len(identity) != 36: raise ValueError()
            return stamp, identity
        except (ValueError, TypeError, KeyError, UnicodeError):
            raise HistoryError(422) from None

    def _page(self, con, principal, resource, cursor, limit):
        position = self._position(principal, resource, cursor, limit)
        # Table/columns are fixed internal choices, never accepted from a client.
        table = {'reports':'report_owners', 'conversations':'conversations'}[resource]
        clause, args = ('', []) if position is None else (' AND (created_at,id)<(?,?)', list(position))
        rows = con.execute(f'SELECT * FROM {table} WHERE member_id=? AND deleted_at IS NULL{clause} ORDER BY created_at DESC,id DESC LIMIT ?',
                           [principal.member_id, *args, limit+1]).fetchall()
        more, rows = len(rows) > limit, rows[:limit]
        cursor = self._cursor(principal, resource, [rows[-1]['created_at'], rows[-1]['id']]) if more else None
        return rows, cursor

    def list_reports(self, principal, cursor=None, limit=50):
        with self.jobs.store.transaction() as con:
            con.row_factory = sqlite3.Row
            self.jobs.auth.revalidate(principal, self.clock(), con=con)
            rows, cursor = self._page(con, principal, 'reports', cursor, limit)
            return ReportPage(items=[self._report_ref(con,principal,r) for r in rows], cursor=cursor)

    @staticmethod
    def _report_ref(con, principal, owner):
        request = con.execute('SELECT ticker FROM research_requests WHERE report_owner_id=? AND member_id=? AND deleted_at IS NULL LIMIT 1',
            (owner['id'],principal.member_id)).fetchone()
        return ReportRef(id=owner['report_id'],created_at=owner['created_at'],ticker=request[0] if request else None)

    def _annotations(self, con, evidence):
        result = []
        for item in evidence:
            annotation = evidence_retraction(con, item, self.jobs.policy)
            if annotation is not None:
                result.append(SavedEvidenceAnnotation(evidence_id=item.id, source_id=item.source_id,
                    source_version=item.source_version, **annotation.model_dump()))
        return result

    def _pending(self, con, principal, owner, now):
        rows = con.execute('SELECT r.*,m.role FROM research_requests r JOIN members m ON m.id=r.member_id WHERE r.report_owner_id=? AND r.member_id=? AND r.deleted_at IS NULL',
                           (owner['id'], principal.member_id)).fetchall()
        values = {}
        for row in rows:
            if row['subscriber_version'] != owner['subscriber_version']: continue
            try:
                self.jobs.auth.revalidate(Principal(principal.member_id,row['role'],row['session_id'],row['authorization_version']),now,con=con)
            except AuthError: continue
            pending = con.execute("SELECT s.section,s.status,s.job_id FROM request_sections s JOIN research_requests r ON r.id=s.request_id JOIN job_subscribers b ON b.request_id=r.id AND b.job_id=s.job_id JOIN web_jobs j ON j.id=s.job_id WHERE r.id=? AND r.member_id=? AND b.member_id=? AND b.deleted_at IS NULL AND b.subscriber_version=r.subscriber_version AND s.status IN ('queued','running') AND j.status IN ('queued','running')",
                                  (row['id'],principal.member_id,principal.member_id)).fetchall()
            for item in pending:
                job = con.execute('SELECT * FROM web_jobs WHERE id=?',(item['job_id'],)).fetchone()
                sub = con.execute('SELECT * FROM job_subscribers WHERE request_id=? AND job_id=? AND member_id=?', (row['id'],item['job_id'],principal.member_id)).fetchone()
                if self.jobs._authorized_subscriber(con,sub,job,now) and self.jobs._prepare(con,row['ticker'],item['section'],now) is not None:
                    values[item['section']] = empty_result(item['section'],item['status'],job_id=item['job_id'])
        return values

    def get_report(self, principal, report_id):
        now = self.clock()
        with self.jobs.store.transaction() as con:
            con.row_factory = sqlite3.Row
            self.jobs.auth.revalidate(principal, now, con=con)
            owner = con.execute('SELECT * FROM report_owners WHERE report_id=? AND member_id=? AND deleted_at IS NULL', (report_id,principal.member_id)).fetchone()
            if owner is None: raise HistoryError()
            reference = self._report_ref(con,principal,owner).model_dump()
            version = con.execute('SELECT v.* FROM report_versions v JOIN report_owners o ON o.current_version_id=v.id AND o.report_id=v.report_id WHERE o.report_id=? AND o.member_id=? AND o.deleted_at IS NULL', (report_id,principal.member_id)).fetchone()
            if version is None:
                pending = self._pending(con,principal,owner,now)
                return SavedReport(**reference,version=None,saved_at=None,finalized=False,
                    availability='pending' if pending else 'unavailable',sections=pending)
            values, annotations = {}, {}
            try:
                raw = json.loads(version['content_json'])
                if not isinstance(raw,dict) or len(raw)>5: raise ValueError()
                for name, item in raw.items():
                    saved = SectionResult.model_validate(item)
                    if name != saved.section: raise ValueError()
                    visible = None
                    if require_features(con,[name]):
                        if saved.result_id is not None:
                            parent = con.execute('SELECT m.* FROM market_results m JOIN report_owners o ON o.report_id=? AND o.member_id=? AND o.current_version_id=? AND o.deleted_at IS NULL WHERE m.id=?',
                                (report_id,principal.member_id,version['id'],saved.result_id)).fetchone()
                            current = self.jobs._read_result(con,parent,now,historical=True) if parent else None
                            if current is not None and current.section == name:
                                # Payload, evidence, timestamps and analysis version stay original.
                                visible = saved.model_copy(update={'attributions':current.attributions,'delay_seconds':current.delay_seconds})
                                notices = self._annotations(con,saved.evidence)
                                if notices:
                                    annotations[name] = notices
                                    visible = empty_result(name).model_copy(update={'message':'Saved evidence was retracted.' if all(x.status=='retracted' for x in notices) else 'Saved evidence is unavailable.'})
                        elif saved.payload is None and not saved.evidence and saved.status in ('failed','unavailable'):
                            visible = empty_result(name,saved.status)
                        elif saved.status in ('queued','running'):
                            visible = self._pending(con,principal,owner,now).get(name)
                    values[name] = visible or empty_result(name)
            except (ValueError,TypeError,ValidationError):
                values, annotations = {}, {}
            available = any(v.status in ('completed','failed') for v in values.values())
            pending = any(v.status in ('queued','running') for v in values.values())
            return SavedReport(**reference,version=version['version'],saved_at=version['created_at'],
                finalized=bool(version['finalized']),availability='pending' if pending else 'available' if available else 'unavailable',sections=values,annotations=annotations)

    def save_report(self, member_id, request_id, section_results, *, con, now):
        """Trusted worker adapter. Inputs are checked against persisted attachments.

        Call only in the completion transaction after current rights/lease checks.
        Never accepts content to insert or creates ownership from member input.
        """
        con.row_factory = sqlite3.Row
        request = con.execute('SELECT r.*,o.report_id,o.created_at AS report_created_at FROM research_requests r JOIN report_owners o ON o.id=r.report_owner_id WHERE r.id=? AND r.member_id=? AND o.member_id=? AND r.deleted_at IS NULL AND o.deleted_at IS NULL', (request_id,member_id,member_id)).fetchone()
        if request is None: return None
        persisted = {r['section']:r['result_id'] for r in con.execute('SELECT s.section,s.result_id FROM request_sections s JOIN research_requests r ON r.id=s.request_id WHERE r.id=? AND r.member_id=?',(request_id,member_id))}
        if any(name not in persisted or value.result_id != persisted[name] for name,value in section_results.items()):
            raise ValueError('Unattached report result')
        return self.jobs._snapshot(con,request_id,now)

    def delete_report(self, principal, report_id):
        now = self.clock()
        with self.jobs.store.transaction() as con:
            self.jobs.auth.revalidate(principal,now,con=con)
            owner = con.execute('SELECT id FROM report_owners WHERE report_id=? AND member_id=? AND deleted_at IS NULL',(report_id,principal.member_id)).fetchone()
            if owner is None: raise HistoryError()
            con.execute('UPDATE job_subscribers SET deleted_at=?,subscriber_version=subscriber_version+1 WHERE member_id=? AND request_id IN (SELECT id FROM research_requests WHERE report_owner_id=? AND member_id=?) AND deleted_at IS NULL',(now,principal.member_id,owner[0],principal.member_id))
            con.execute('UPDATE research_requests SET deleted_at=?,subscriber_version=subscriber_version+1 WHERE report_owner_id=? AND member_id=? AND deleted_at IS NULL',(now,owner[0],principal.member_id))
            con.execute('UPDATE report_owners SET deleted_at=?,subscriber_version=subscriber_version+1 WHERE id=? AND member_id=?',(now,owner[0],principal.member_id))

    def owned_live_conversation(self, con, principal, conversation_id, now, *, expected_version=None):
        """Task 10 must call in the same transaction as message delivery/insertion."""
        self.jobs.auth.revalidate(principal,now,con=con)
        row = con.execute('SELECT * FROM conversations WHERE id=? AND member_id=? AND deleted_at IS NULL',(conversation_id,principal.member_id)).fetchone()
        if row is None or (expected_version is not None and row['version'] != expected_version): return None
        return row

    def list_conversations(self, principal, cursor=None, limit=50):
        with self.jobs.store.transaction() as con:
            con.row_factory = sqlite3.Row
            self.jobs.auth.revalidate(principal,self.clock(),con=con)
            if not require_features(con,['assistant']): raise HistoryError(403)
            rows,cursor = self._page(con,principal,'conversations',cursor,limit)
            return ConversationPage(items=[self._conversation_ref(r) for r in rows],cursor=cursor)

    @staticmethod
    def _conversation_ref(row):
        return ConversationRef(id=row['id'],title=row['title'],created_at=row['created_at'],version=row['version'])

    def get_conversation(self, principal, conversation_id, cursor=None, limit=50, *, tail=False):
        now = self.clock()
        with self.jobs.store.transaction() as con:
            con.row_factory = sqlite3.Row
            row = self.owned_live_conversation(con,principal,conversation_id,now)
            if row is None: raise HistoryError()
            if not require_features(con,['assistant']): raise HistoryError(403)
            resource = ('messages-tail:' if tail else 'messages:')+conversation_id
            position = self._position(principal,resource,cursor,limit)
            clause,args = ('',[]) if position is None else (' AND (m.created_at,m.id)'+('<' if tail else '>')+'(?,?)',list(position))
            order = 'm.created_at DESC,m.id DESC' if tail else 'm.created_at,m.id'
            rows = con.execute('SELECT m.* FROM messages m JOIN conversations c ON c.id=m.conversation_id AND c.member_id=m.member_id WHERE c.id=? AND c.member_id=? AND c.deleted_at IS NULL AND m.member_id=?'+clause+' ORDER BY '+order+' LIMIT ?', (conversation_id,principal.member_id,principal.member_id,*args,limit+1)).fetchall()
            more,rows = len(rows)>limit,rows[:limit]
            cursor = self._cursor(principal,resource,[rows[-1]['created_at'],rows[-1]['id']]) if more else None
            if tail: rows.reverse()
            messages=[]
            for message in rows:
                text, evidence, annotations = None, [], []
                try:
                    content = MessageContent.model_validate_json(message['content_json'])
                    source_free = (message['role']=='user' and message['source_lineage_json']=='[]' and
                        message['required_features_json']=='[]' and message['field_dependencies_json']=='[]' and
                        message['retention_deadline'] is None and not content.evidence)
                    lineage = self.jobs.policy.stored_lineage(message)
                    tracked = {(s.source_id,s.source_version) for s in lineage.sources} if lineage else set()
                    complete = all((e.source_id,e.source_version) in tracked for e in content.evidence)
                    observed_at = message['source_observed_at'] if message['role']=='assistant' else message['created_at']
                    allowed = source_free or (lineage is not None and complete and require_features(con,lineage.required_features) and all(self.jobs.policy._authorize_lineage(con,lineage,use,now,observed_at).allowed for use in ('retain','display_raw','display_derived')))
                    if allowed:
                        annotations = self._annotations(con,content.evidence)
                        if not annotations: text,evidence = content.text,content.evidence
                except (ValueError,TypeError,ValidationError): pass
                messages.append(SavedMessage(id=message['id'],role=message['role'],created_at=message['created_at'],text=text,evidence=evidence,
                    availability='available' if text is not None else 'unavailable',annotations=annotations))
            return SavedConversation(**self._conversation_ref(row).model_dump(),messages=messages,cursor=cursor)

    def delete_conversation(self, principal, conversation_id):
        now = self.clock()
        with self.jobs.store.transaction() as con:
            con.row_factory = sqlite3.Row
            if self.owned_live_conversation(con,principal,conversation_id,now) is None: raise HistoryError()
            con.execute('UPDATE conversations SET deleted_at=?,version=version+1 WHERE id=? AND member_id=?',(now,conversation_id,principal.member_id))
            con.execute("UPDATE assistant_runs SET deleted_at=?,subscriber_version=subscriber_version+1,status=CASE WHEN status='queued' THEN 'cancelled' WHEN status='running' THEN 'draining' ELSE status END,finished_at=CASE WHEN status='queued' THEN ? ELSE finished_at END WHERE conversation_id=? AND member_id=? AND deleted_at IS NULL",(now,now,conversation_id,principal.member_id))
