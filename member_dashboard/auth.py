"""Invitation accounts, atomic token consumption and server-side authentication."""
from dataclasses import dataclass, field
import hashlib
import hmac
import json
import re
import secrets
import sqlite3
import threading
from uuid import uuid4

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, InvalidHashError


class AuthError(Exception):
    """Deliberately contains no credentials or account-existence details."""


@dataclass(frozen=True)
class Member:
    id: str
    username: str
    role: str


@dataclass(frozen=True)
class IssuedToken:
    id: str
    token: str = field(repr=False)
    expires_at: float


@dataclass(frozen=True)
class IssuedSession:
    id: str
    token: str = field(repr=False)
    csrf_token: str = field(repr=False)
    expires_at: float
    member: Member


@dataclass(frozen=True)
class Principal:
    member_id: str
    role: str
    session_id: str
    authorization_version: int


def digest(raw):
    return hashlib.sha256(raw.encode('utf-8')).digest()


def normalize_username(raw):
    username = raw.lower()
    if not re.fullmatch(r'[a-z0-9_]{3,32}', username, flags=re.ASCII):
        raise AuthError()
    return username


_HASHER = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=1)
_HASH_SLOTS = threading.BoundedSemaphore(2)
_DUMMY_HASH = None
_DUMMY_LOCK = threading.Lock()


class AuthService:
    def __init__(self, store):
        self.store = store
        global _DUMMY_HASH
        with _DUMMY_LOCK:
            if _DUMMY_HASH is None:
                _DUMMY_HASH = self.hash_password(secrets.token_urlsafe(32))

    def hash_password(self, password):
        if not isinstance(password, str) or not 15 <= len(password) <= 128:
            raise AuthError()
        if not _HASH_SLOTS.acquire(timeout=2):
            raise AuthError()
        try:
            return _HASHER.hash(password)
        finally:
            _HASH_SLOTS.release()

    def _verify_password(self, hashed, password):
        if not _HASH_SLOTS.acquire(timeout=2):
            raise AuthError()
        try:
            try:
                return _HASHER.verify(hashed, password)
            except (VerificationError, InvalidHashError):
                return False
        finally:
            _HASH_SLOTS.release()

    @staticmethod
    def _admin(con, actor_id):
        if con.execute("SELECT 1 FROM members WHERE id=? AND role='admin' AND status='active'",
                       (actor_id,)).fetchone() is None:
            raise AuthError()

    @staticmethod
    def _audit(con, action, target_id, now, actor=None, detail=None):
        con.execute('INSERT INTO audit_events(id,actor_member_id,action,target_id,occurred_at,detail_json) VALUES (?,?,?,?,?,?)',
                    (str(uuid4()), actor, action, target_id, now, json.dumps(detail or {})))

    def issue_invite(self, actor_id, now):
        token = IssuedToken(str(uuid4()), secrets.token_urlsafe(32), now+7*86400)
        with self.store.transaction() as con:
            self._admin(con, actor_id)
            con.execute('INSERT INTO invites(id,token_digest,created_by,created_at,expires_at) VALUES (?,?,?,?,?)',
                        (token.id, digest(token.token), actor_id, now, token.expires_at))
            self._audit(con, 'invite_issued', token.id, now, actor_id)
        return token

    def redeem_invite(self, token, username, password, now):
        username = normalize_username(username)
        hashed = self.hash_password(password)
        member = Member(str(uuid4()), username, 'member')
        try:
            with self.store.transaction() as con:
                row = con.execute('SELECT id FROM invites WHERE token_digest=? AND consumed_at IS NULL AND revoked_at IS NULL AND expires_at>?', (digest(token), now)).fetchone()
                if row is None:
                    raise AuthError()
                con.execute('INSERT INTO members(id,username,password_hash,role,created_at) VALUES (?,?,?,?,?)',
                            (member.id, member.username, hashed, member.role, now))
                changed = con.execute('UPDATE invites SET consumed_at=?,consumed_by=? WHERE id=? AND consumed_at IS NULL AND revoked_at IS NULL AND expires_at>?', (now, member.id, row[0], now))
                if changed.rowcount != 1:
                    raise AuthError()
                self._audit(con, 'invite_redeemed', member.id, now)
        except sqlite3.IntegrityError:
            raise AuthError() from None
        return member

    def _reserve_login(self, username, address, now):
        user_key, address_key = digest(username), digest(address)
        identity = str(uuid4())
        with self.store.transaction() as con:
            con.execute('DELETE FROM auth_attempts WHERE attempted_at<=?', (now-900,))
            user_count, address_count, until = con.execute('SELECT sum(username_digest=?),sum(address_digest=?),max(CASE WHEN username_digest=? OR address_digest=? THEN not_before ELSE 0 END) FROM auth_attempts', (user_key,address_key,user_key,address_key)).fetchone()
            if (user_count or 0) >= 5 or (address_count or 0) >= 50 or (until or 0)>now:
                raise AuthError()
            con.execute('INSERT INTO auth_attempts(id,username_digest,address_digest,attempted_at,success) VALUES (?,?,?,?,0)', (identity,user_key,address_key,now))
        return identity, user_count or 0

    def login(self, username, password, now, address='local'):
        # Invalid usernames still use a digest throttle and the dummy Argon2 path.
        normalized = username.lower()
        attempt, prior = self._reserve_login(normalized, address, now)
        with self.store.transaction() as con:
            row = con.execute('SELECT id,username,role,password_hash,status,authorization_version FROM members WHERE username=?', (normalized,)).fetchone()
        valid = self._verify_password(row[3] if row else _DUMMY_HASH,
                                      password if isinstance(password,str) and len(password)<=128 else '')
        with self.store.transaction() as con:
            current = con.execute('SELECT id,username,role,password_hash,status,authorization_version FROM members WHERE username=?', (normalized,)).fetchone()
            if not valid or not row or current != row or current[4] != 'active':
                con.execute('UPDATE auth_attempts SET not_before=? WHERE id=?', (now+min(2**prior,30), attempt))
            else:
                con.execute('UPDATE auth_attempts SET success=1 WHERE id=?', (attempt,))
                issued = IssuedSession(str(uuid4()),secrets.token_urlsafe(32),secrets.token_urlsafe(32), now+43200,Member(row[0],row[1],row[2]))
                con.execute('INSERT INTO sessions(id,member_id,token_digest,csrf_digest,authorization_version,created_at,last_seen_at,absolute_expires_at,idle_expires_at) VALUES (?,?,?,?,?,?,?,?,?)',
                            (issued.id,row[0],digest(issued.token),digest(issued.csrf_token),row[5],now,now,issued.expires_at,now+7200))
                self._audit(con,'login',row[0],now,row[0])
                return issued
        raise AuthError()

    def reserve_public_write(self, address, now):
        # Anonymous invite/reset traffic shares the login address budget. Its
        # random subject cannot collide with or expose a username/token digest.
        self._reserve_login('anonymous:'+secrets.token_urlsafe(32),address,now)

    def issue_reset(self, actor_id, member_id, now):
        issued = IssuedToken(str(uuid4()),secrets.token_urlsafe(32),now+3600)
        with self.store.transaction() as con:
            self._admin(con,actor_id)
            if con.execute('SELECT 1 FROM members WHERE id=?',(member_id,)).fetchone() is None:
                raise AuthError()
            con.execute('UPDATE password_resets SET revoked_at=? WHERE member_id=? AND consumed_at IS NULL AND revoked_at IS NULL',(now,member_id))
            con.execute('INSERT INTO password_resets(id,member_id,token_digest,created_at,expires_at) VALUES (?,?,?,?,?)',(issued.id,member_id,digest(issued.token),now,issued.expires_at))
            self._audit(con,'reset_issued',member_id,now,actor_id)
        return issued

    def _replace_password(self, con, member_id, hashed, now):
        con.execute('UPDATE members SET password_hash=?,updated_at=?,authorization_version=authorization_version+1 WHERE id=?',(hashed,now,member_id))
        con.execute('DELETE FROM sessions WHERE member_id=?',(member_id,))
        con.execute('UPDATE password_resets SET revoked_at=? WHERE member_id=? AND consumed_at IS NULL AND revoked_at IS NULL',(now,member_id))

    def reset_password(self, token, password, now):
        hashed = self.hash_password(password)
        with self.store.transaction() as con:
            row = con.execute('SELECT id,member_id FROM password_resets WHERE token_digest=? AND consumed_at IS NULL AND revoked_at IS NULL AND expires_at>?',(digest(token),now)).fetchone()
            if row is None:
                raise AuthError()
            changed = con.execute('UPDATE password_resets SET consumed_at=? WHERE id=? AND consumed_at IS NULL AND revoked_at IS NULL AND expires_at>?',(now,row[0],now))
            if changed.rowcount != 1:
                raise AuthError()
            self._replace_password(con,row[1],hashed,now)
            self._audit(con,'password_reset',row[1],now)

    def principal(self, token, now, *, con=None, touch=True):
        if con is None:
            with self.store.transaction() as transaction:
                return self.principal(token,now,con=transaction,touch=touch)
        row = con.execute("SELECT m.id,m.role,s.id,m.authorization_version FROM sessions s JOIN members m ON m.id=s.member_id WHERE s.token_digest=? AND s.revoked_at IS NULL AND s.absolute_expires_at>? AND s.idle_expires_at>? AND m.status='active' AND s.authorization_version=m.authorization_version",(digest(token),now,now)).fetchone()
        if row is None:
            raise AuthError()
        if touch:
            con.execute('UPDATE sessions SET last_seen_at=?,idle_expires_at=min(absolute_expires_at,?) WHERE id=?',(now,now+7200,row[2]))
        return Principal(*row)

    def revalidate(self, principal, now, *, con=None):
        """Use inside the completion/delivery transaction; snapshots never grant authority."""
        if con is None:
            with self.store.transaction() as transaction:
                return self.revalidate(principal,now,con=transaction)
        row = con.execute("SELECT m.role FROM sessions s JOIN members m ON m.id=s.member_id WHERE s.id=? AND m.id=? AND s.revoked_at IS NULL AND s.absolute_expires_at>? AND s.idle_expires_at>? AND m.status='active' AND s.authorization_version=m.authorization_version AND m.authorization_version=?",(principal.session_id,principal.member_id,now,now,principal.authorization_version)).fetchone()
        if row is None or row[0] != principal.role:
            raise AuthError()
        return principal

    def session_csrf(self, token, now):
        raw = secrets.token_urlsafe(32)
        with self.store.transaction() as con:
            principal = self.principal(token,now,con=con)
            con.execute('UPDATE sessions SET csrf_digest=? WHERE id=?',(digest(raw),principal.session_id))
        return raw

    def check_session_csrf(self, token, csrf, now):
        with self.store.transaction() as con:
            principal = self.principal(token,now,con=con)
            expected = con.execute('SELECT csrf_digest FROM sessions WHERE id=?',(principal.session_id,)).fetchone()[0]
            if not hmac.compare_digest(expected,digest(csrf)):
                raise AuthError()
        return principal

    def logout(self, principal, now):
        with self.store.transaction() as con:
            self.revalidate(principal,now,con=con)
            con.execute('DELETE FROM sessions WHERE id=?',(principal.session_id,))
            self._audit(con,'logout',principal.member_id,now,principal.member_id)

    def recover_admin(self, member_id, password, operator_identity, now):
        from .local_authority import verify_local_operator
        verified = verify_local_operator(self.store.path)
        if not hmac.compare_digest(verified,operator_identity):
            raise AuthError()
        hashed = self.hash_password(password)
        # Recheck host authorization after the expensive password operation.
        if verify_local_operator(self.store.path) != verified:
            raise AuthError()
        with self.store.transaction() as con:
            if con.execute("SELECT 1 FROM members WHERE id=? AND role='admin'",(member_id,)).fetchone() is None:
                raise AuthError()
            self._replace_password(con,member_id,hashed,now)
            self._audit(con,'local_admin_recovery',member_id,now,detail={'operator_identity':verified})

    def create_admin(self, username, password, now):
        from .local_authority import verify_local_operator
        verified = verify_local_operator(self.store.path)
        username = normalize_username(username)
        hashed = self.hash_password(password)
        if verify_local_operator(self.store.path) != verified:
            raise AuthError()
        member = Member(str(uuid4()),username,'admin')
        try:
            with self.store.transaction() as con:
                if con.execute("SELECT 1 FROM members WHERE role='admin'").fetchone():
                    raise AuthError()
                con.execute('INSERT INTO members(id,username,password_hash,role,created_at) VALUES (?,?,?,?,?)',(member.id,username,hashed,'admin',now))
                self._audit(con,'local_admin_created',member.id,now,detail={'operator_identity':verified})
        except sqlite3.IntegrityError:
            raise AuthError() from None
        return member
