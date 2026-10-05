"""Web-only, serialized administrative authority and safe audit projections."""
import json
import sqlite3
import time
from typing import get_args
from uuid import UUID
from .auth import AuthError
from .contracts import Feature
from .features import require_features
from .admin_contracts import FeatureState, MemberState, InviteState, TokenLink, AuditState, MemberPage, InvitePage, AuditPage

ACTIONS={'invite_issued','invite_redeemed','invite_revoked','reset_issued','password_reset','login','logout',
         'local_admin_recovery','local_admin_created','member_suspended','member_reactivated','sessions_revoked','feature_changed'}

class AdminError(Exception):
    def __init__(self,status=403): self.status=status


def opaque(value):
    try: return str(UUID(value)) if str(UUID(value))==value else None
    except (ValueError,TypeError,AttributeError): return None


class AdminService:
    def __init__(self,store,auth,*,clock=time.time): self.store,self.auth,self.clock=store,auth,clock

    def _actor(self,con,actor,now):
        self.auth.revalidate(actor,now,con=con)
        if actor.role!='admin': raise AdminError()

    def require_feature(self,principal,feature):
        with self.store.transaction() as con:
            self.auth.revalidate(principal,self.clock(),con=con)
            if feature not in get_args(Feature) or not require_features(con,[feature]): raise AdminError()

    def features(self,actor):
        with self.store.transaction() as con:
            self._actor(con,actor,self.clock())
            return [FeatureState(name=name,enabled=bool(enabled),version=version)
                    for name,enabled,version in con.execute('SELECT name,enabled,version FROM features ORDER BY name')]

    def set_feature(self,actor,feature,enabled):
        if feature not in get_args(Feature) or type(enabled) is not bool: raise AdminError(422)
        now=self.clock()
        with self.store.transaction() as con:
            self._actor(con,actor,now)
            con.execute('UPDATE features SET enabled=?,version=version+1,updated_at=? WHERE name=? AND enabled!=?',(int(enabled),now,feature,int(enabled)))
            row=con.execute('SELECT enabled,version FROM features WHERE name=?',(feature,)).fetchone()
            self.auth._audit(con,'feature_changed',feature,now,actor.member_id,{'result':'ok'})
            return FeatureState(name=feature,enabled=bool(row[0]),version=row[1])

    def create_invite(self,actor):
        with self.store.transaction() as con:
            now=self.clock(); self._actor(con,actor,now)
            issued=self.auth.issue_invite(actor,now,con=con)
            return TokenLink(id=issued.id,token=issued.token,expires_at=issued.expires_at)

    def revoke_invite(self,actor,invite_id):
        with self.store.transaction() as con:
            now=self.clock(); self._actor(con,actor,now)
            if con.execute('SELECT 1 FROM invites WHERE id=?',(invite_id,)).fetchone() is None: raise AdminError(404)
            con.execute('UPDATE invites SET revoked_at=? WHERE id=? AND consumed_at IS NULL AND revoked_at IS NULL',(now,invite_id))
            self.auth._audit(con,'invite_revoked',invite_id,now,actor.member_id,{'result':'ok'})

    def _member_action(self,actor,member_id,action):
        denied=False; result=None
        with self.store.transaction() as con:
            now=self.clock(); self._actor(con,actor,now)
            row=con.execute('SELECT role,status FROM members WHERE id=?',(member_id,)).fetchone()
            if row is None: raise AdminError(404)
            denied=(member_id==actor.member_id and action in ('member_suspended','sessions_revoked','reset_issued'))
            if action=='member_suspended' and row[0]=='admin' and row[1]=='active':
                denied=denied or con.execute("SELECT count(*) FROM members WHERE role='admin' AND status='active'").fetchone()[0]<=1
            if denied:
                self.auth._audit(con,action,member_id,now,actor.member_id,{'result':'denied'})
            elif action=='member_reactivated' and row[1]=='active':
                self.auth._audit(con,action,member_id,now,actor.member_id,{'result':'ok'})
            elif action=='reset_issued':
                issued=self.auth.issue_reset(actor,member_id,now,con=con)
                result=TokenLink(id=issued.id,token=issued.token,expires_at=issued.expires_at)
            else:
                status='suspended' if action=='member_suspended' else 'active' if action=='member_reactivated' else row[1]
                con.execute('UPDATE members SET status=?,authorization_version=authorization_version+1,updated_at=? WHERE id=?',(status,now,member_id))
                con.execute('DELETE FROM sessions WHERE member_id=?',(member_id,))
                con.execute('UPDATE password_resets SET revoked_at=? WHERE member_id=? AND consumed_at IS NULL AND revoked_at IS NULL',(now,member_id))
                self.auth._audit(con,action,member_id,now,actor.member_id,{'result':'ok'})
        if denied: raise AdminError()
        return result

    def suspend_member(self,actor,member_id): return self._member_action(actor,member_id,'member_suspended')
    def reactivate_member(self,actor,member_id): return self._member_action(actor,member_id,'member_reactivated')
    def revoke_sessions(self,actor,member_id): return self._member_action(actor,member_id,'sessions_revoked')
    def create_reset(self,actor,member_id): return self._member_action(actor,member_id,'reset_issued')

    def page(self,actor,kind,cursor=None):
        table={'members':'members','invites':'invites','audit':'audit_events'}[kind]
        with self.store.transaction() as con:
            con.row_factory=sqlite3.Row
            self._actor(con,actor,self.clock())
            boundary=0
            if cursor:
                row=con.execute(f'SELECT rowid FROM {table} WHERE id=?',(cursor,)).fetchone()
                if row is None: raise AdminError(422)
                boundary=row[0]
            # Fixed table set. Detail/hash/content columns never enter public DTOs.
            rows=con.execute(f'SELECT * FROM {table} WHERE rowid>? ORDER BY rowid LIMIT 101',(boundary,)).fetchall()
            items=[]
            for r in rows[:100]:
                if kind=='members': items.append(MemberState(**{k:r[k] for k in ('id','username','role','status')}))
                elif kind=='invites': items.append(InviteState(id=r['id'],created_at=r['created_at'],expires_at=r['expires_at'],consumed=r['consumed_at'] is not None,revoked=r['revoked_at'] is not None))
                else:
                    action=r['action'] if r['action'] in ACTIONS else 'account_event'
                    target=opaque(r['target_id']) or (r['target_id'] if action=='feature_changed' and r['target_id'] in get_args(Feature) else None)
                    detail=json.loads(r['detail_json'])
                    items.append(AuditState(id=r['id'],actor_id=opaque(r['actor_member_id']),target_id=target,action=action,occurred_at=r['occurred_at'],result='denied' if isinstance(detail,dict) and detail.get('result')=='denied' else 'ok'))
            cls={'members':MemberPage,'invites':InvitePage,'audit':AuditPage}[kind]
            return cls(items=items,next_cursor=rows[99]['id'] if len(rows)>100 else None)

    def health_snapshot(self,actor):
        from .monitoring import snapshot
        with self.store.transaction() as con:
            now=self.clock(); self._actor(con,actor,now)
            return snapshot(con,now)
