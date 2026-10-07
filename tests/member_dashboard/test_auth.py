"""Account safety proofs using real SQLite and Argon2, with synthetic identities."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import sqlite3
import threading
from uuid import uuid4

import pytest

PASSWORD = 'synthetic long password one'
NEW_PASSWORD = 'synthetic long password two'


def test_me_returns_all_current_feature_versions(auth, dashboard):
    target = member(auth, dashboard)
    response = post(dashboard, '/auth/login', {'username':target.username,'password':PASSWORD})
    assert set(response.json()['member']) == {'id','username','role'}
    with dashboard.store.transaction() as con:
        con.execute("UPDATE features SET enabled=0,version=version+1 WHERE name='sec'")
    response = dashboard.client.get('/api/v1/me')
    assert response.status_code == 200
    features = response.json()['features']
    assert set(features) == {'feed','setups','analysis','sec','options','em_daily','em_weekly','assistant'}
    assert features['sec'] == {'enabled':False,'version':2}
    assert all(type(v['enabled']) is bool and type(v['version']) is int for v in features.values())


def test_me_revalidation_race_is_unauthorized(auth, dashboard, monkeypatch):
    from member_dashboard.auth import AuthError
    target = member(auth, dashboard)
    post(dashboard, '/auth/login', {'username':target.username,'password':PASSWORD})
    def revoked(*args, **kwargs):
        raise AuthError()
    monkeypatch.setattr(dashboard.app.state.auth, 'revalidate', revoked)
    assert dashboard.client.get('/api/v1/me').status_code == 401


@pytest.fixture
def auth(dashboard):
    from member_dashboard.auth import AuthService
    return AuthService(dashboard.store)


def admin(auth, dashboard, username='synthetic_admin'):
    # Synthetic fixture bypasses the host bootstrap, never the HTTP boundary.
    hashed = auth.hash_password(PASSWORD)
    identity = str(uuid4())
    with dashboard.store.transaction() as con:
        con.execute('INSERT INTO members(id,username,password_hash,role,created_at) VALUES (?,?,?,?,?)',
                    (identity, username, hashed, 'admin', dashboard.clock()))
    return identity


def member(auth, dashboard, username='synthetic_member'):
    actor = admin(auth, dashboard)
    token = auth.issue_invite_trusted(actor, dashboard.clock())
    return auth.redeem_invite(token.token, username, PASSWORD, dashboard.clock())


def post(dashboard, path, body, csrf=None, origin=None):
    if csrf is None:
        csrf = dashboard.client.get('/api/v1/auth/csrf').json()['token']
    return dashboard.client.post('/api/v1' + path, json=body,
        headers={'X-CSRF-Token': csrf, 'Origin': origin or dashboard.settings.origin})


def test_five_lowercase_password_signup_login_and_reset(auth, dashboard):
    actor = admin(auth, dashboard)
    invite = auth.issue_invite_trusted(actor, dashboard.clock())
    response = post(dashboard, '/auth/redeem', {'token': invite.token,
        'username': 'short_password_member', 'password': 'abcde'})
    assert response.status_code == 201
    assert post(dashboard, '/auth/login', {'username': 'short_password_member',
        'password': 'abcde'}).status_code == 200
    with dashboard.store.transaction() as con:
        identity = con.execute("SELECT id FROM members WHERE username='short_password_member'").fetchone()[0]
    reset = auth.issue_reset_trusted(actor, identity, dashboard.clock())
    assert post(dashboard, '/auth/reset', {'token': reset.token,
        'password': 'fghij'}).status_code == 204
    assert post(dashboard, '/auth/login', {'username': 'short_password_member',
        'password': 'abcde'}).status_code == 401
    dashboard.clock.advance(10)  # Respect the existing failed-login cooldown.
    assert post(dashboard, '/auth/login', {'username': 'short_password_member',
        'password': 'fghij'}).status_code == 200


@pytest.mark.parametrize('password', ['', 'abcd', 'a' * 129])
def test_outside_password_length_rejected_without_consuming_invite(auth, dashboard, password):
    from member_dashboard.auth import AuthError
    actor = admin(auth, dashboard)
    invite = auth.issue_invite_trusted(actor, dashboard.clock())
    with pytest.raises(AuthError):
        auth.redeem_invite(invite.token, 'short_password_member', password, dashboard.clock())
    assert auth.redeem_invite(invite.token, 'short_password_member', 'abcde', dashboard.clock()).role == 'member'


def test_http_auth_exists(dashboard):
    assert dashboard.client.get('/api/v1/auth/csrf').status_code == 200


def test_invite_has_one_winner(auth, dashboard):
    from member_dashboard.auth import AuthError, AuthService
    actor = admin(auth, dashboard)
    token = auth.issue_invite_trusted(actor, dashboard.clock())
    barrier = threading.Barrier(2)
    def redeem(index):
        service = AuthService(dashboard.store)
        barrier.wait(timeout=5)
        try:
            service.redeem_invite(token.token, f'member_{index}', PASSWORD, dashboard.clock())
            return 201
        except AuthError:
            return 400
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(redeem, (1, 2)))
    assert sorted(responses) == [201, 400]
    with dashboard.store.transaction() as con:
        assert con.execute("SELECT count(*) FROM members WHERE role='member'").fetchone()[0] == 1
        assert con.execute('SELECT consumed_at FROM invites').fetchone()[0] is not None


@pytest.mark.parametrize('state', ['expiry', 'revoked', 'replayed'])
def test_invite_invalid_state(auth, dashboard, state):
    from member_dashboard.auth import AuthError
    actor = admin(auth, dashboard)
    token = auth.issue_invite_trusted(actor, dashboard.clock())
    now = dashboard.clock()
    if state == 'expiry':
        now = token.expires_at
    elif state == 'revoked':
        with dashboard.store.transaction() as con:
            con.execute('UPDATE invites SET revoked_at=?', (now,))
    else:
        auth.redeem_invite(token.token, 'first_member', PASSWORD, now)
    with pytest.raises(AuthError):
        auth.redeem_invite(token.token, 'next_member', PASSWORD, now)


def test_username_collision_keeps_invite_unused(auth, dashboard):
    from member_dashboard.auth import AuthError
    actor = admin(auth, dashboard)
    first = auth.issue_invite_trusted(actor, dashboard.clock())
    auth.redeem_invite(first.token, 'MiXeD_Name', PASSWORD, dashboard.clock())
    second = auth.issue_invite_trusted(actor, dashboard.clock())
    with pytest.raises(AuthError):
        auth.redeem_invite(second.token, 'mixed_NAME', PASSWORD, dashboard.clock())
    result = auth.redeem_invite(second.token, 'other_member', PASSWORD, dashboard.clock())
    assert result.role == 'member'


@pytest.mark.parametrize('password', ['tiny', 'a'*129, 'a'*4])
def test_invalid_password_leaves_invite(auth, dashboard, password):
    from member_dashboard.auth import AuthError
    actor = admin(auth, dashboard)
    token = auth.issue_invite_trusted(actor, dashboard.clock())
    with pytest.raises(AuthError):
        auth.redeem_invite(token.token, 'test_member', password, dashboard.clock())
    assert auth.redeem_invite(token.token, 'test_member', PASSWORD, dashboard.clock()).role == 'member'


@pytest.mark.parametrize('username', ['has space', 'ééé', 'ab', 'a'*33])
def test_invalid_username(auth, dashboard, username):
    from member_dashboard.auth import AuthError
    token = auth.issue_invite_trusted(admin(auth, dashboard), dashboard.clock())
    with pytest.raises(AuthError):
        auth.redeem_invite(token.token, username, PASSWORD, dashboard.clock())


def test_issue_requires_active_admin(auth, dashboard):
    from member_dashboard.auth import AuthError
    target = member(auth, dashboard)
    with pytest.raises(AuthError):
        auth.issue_invite_trusted(target.id, dashboard.clock())
    with dashboard.store.transaction() as con:
        con.execute("UPDATE members SET status='suspended' WHERE role='admin'")
        actor = con.execute("SELECT id FROM members WHERE role='admin'").fetchone()[0]
    with pytest.raises(AuthError):
        auth.issue_reset_trusted(actor, target.id, dashboard.clock())


def test_only_digests_persist(auth, dashboard):
    target = member(auth, dashboard)
    session = auth.login(target.username, PASSWORD, dashboard.clock(), '192.0.2.1')
    with dashboard.store.transaction() as con:
        row = con.execute('SELECT token_digest,csrf_digest FROM sessions').fetchone()
        assert row == (hashlib.sha256(session.token.encode()).digest(), hashlib.sha256(session.csrf_token.encode()).digest())
        audit = str(con.execute('SELECT * FROM audit_events').fetchall())
    assert PASSWORD not in audit and session.token not in audit and session.csrf_token not in audit


def test_login_rotation_and_cookie_attributes(auth, dashboard):
    target = member(auth, dashboard)
    dashboard.client.cookies.set('__Host-member_session', 'attacker-selected')
    response = post(dashboard, '/auth/login', {'username': target.username, 'password': PASSWORD})
    assert response.status_code == 200
    cookie = response.headers['set-cookie']
    assert 'attacker-selected' not in cookie
    for text in ['__Host-member_session=', 'HttpOnly', 'Secure', 'SameSite=lax', 'Path=/']:
        assert text in cookie
    assert 'Domain=' not in cookie
    assert response.json()['member']['role'] == 'member'
    assert dashboard.client.get('/api/v1/me').json()['username'] == target.username
    assert response.headers['cache-control'] == 'private, no-store'


@pytest.mark.parametrize('mode', ['missing', 'wrong', 'foreign', 'no_origin'])
def test_csrf_and_origin_rejected(dashboard, mode):
    csrf = dashboard.client.get('/api/v1/auth/csrf').json()['token']
    headers = {'Origin': dashboard.settings.origin, 'X-CSRF-Token': csrf}
    if mode == 'missing': headers.pop('X-CSRF-Token')
    if mode == 'wrong': headers['X-CSRF-Token'] = 'wrong'
    if mode == 'foreign': headers['Origin'] = 'https://foreign.test'
    if mode == 'no_origin': headers.pop('Origin')
    response = dashboard.client.post('/api/v1/auth/login', json={'username':'unknown', 'password':PASSWORD}, headers=headers)
    assert response.status_code == 403
    assert PASSWORD not in response.text


def test_logout_invalidates_server_session(auth, dashboard):
    target = member(auth, dashboard)
    post(dashboard, '/auth/login', {'username':target.username, 'password':PASSWORD})
    cookie = dashboard.client.cookies.get('__Host-member_session')
    assert post(dashboard, '/auth/logout', {}).status_code == 204
    dashboard.client.cookies.set('__Host-member_session', cookie)
    assert dashboard.client.get('/api/v1/me').status_code == 401


@pytest.mark.parametrize('state', ['idle','absolute','suspended','revision','revoked'])
def test_request_rechecks_session(auth, dashboard, state):
    target = member(auth, dashboard)
    post(dashboard, '/auth/login', {'username':target.username, 'password':PASSWORD})
    if state == 'idle': dashboard.clock.advance(7200)
    if state == 'absolute':
        with dashboard.store.transaction() as con:
            con.execute('UPDATE sessions SET idle_expires_at=absolute_expires_at+1')
        dashboard.clock.advance(43200)
    with dashboard.store.transaction() as con:
        if state == 'suspended': con.execute("UPDATE members SET status='suspended' WHERE id=?", (target.id,))
        if state == 'revision': con.execute('UPDATE members SET authorization_version=authorization_version+1 WHERE id=?', (target.id,))
        if state == 'revoked': con.execute('UPDATE sessions SET revoked_at=?',(dashboard.clock(),))
    assert dashboard.client.get('/api/v1/me').status_code == 401


def test_reset_replaces_tokens_and_revokes_all_sessions(auth, dashboard):
    from member_dashboard.auth import AuthError
    target = member(auth, dashboard)
    actor = admin(auth, dashboard, 'second_admin')
    auth.login(target.username, PASSWORD, dashboard.clock(), '192.0.2.1')
    auth.login(target.username, PASSWORD, dashboard.clock(), '192.0.2.2')
    old = auth.issue_reset_trusted(actor, target.id, dashboard.clock())
    new = auth.issue_reset_trusted(actor, target.id, dashboard.clock())
    with pytest.raises(AuthError): auth.reset_password(old.token, NEW_PASSWORD, dashboard.clock())
    auth.reset_password(new.token, NEW_PASSWORD, dashboard.clock())
    with pytest.raises(AuthError): auth.reset_password(new.token, NEW_PASSWORD, dashboard.clock())
    with dashboard.store.transaction() as con:
        assert con.execute('SELECT count(*) FROM sessions').fetchone()[0] == 0
        assert con.execute('SELECT authorization_version FROM members WHERE id=?',(target.id,)).fetchone()[0] == 2
    assert auth.login(target.username, NEW_PASSWORD, dashboard.clock(), '192.0.2.3').member.id == target.id
    with pytest.raises(AuthError): auth.login(target.username, PASSWORD, dashboard.clock(), '192.0.2.4')


def test_reset_has_one_winner(auth, dashboard):
    from member_dashboard.auth import AuthService, AuthError
    target = member(auth, dashboard)
    actor = admin(auth, dashboard, 'second_admin')
    token = auth.issue_reset_trusted(actor, target.id, dashboard.clock())
    barrier = threading.Barrier(2)
    def reset(index):
        service = AuthService(dashboard.store)
        barrier.wait(timeout=5)
        try:
            service.reset_password(token.token, NEW_PASSWORD+str(index), dashboard.clock())
            return 200
        except AuthError: return 400
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(reset, (1,2))) == [200,400]


def test_login_throttle_and_expiry(auth, dashboard):
    from member_dashboard.auth import AuthError
    target = member(auth, dashboard)
    for _ in range(5):
        with pytest.raises(AuthError): auth.login(target.username, 'wrong password long', dashboard.clock(), '192.0.2.1')
        dashboard.clock.advance(31)
    with pytest.raises(AuthError): auth.login(target.username, PASSWORD, dashboard.clock(), '192.0.2.2')
    dashboard.clock.advance(901)
    assert auth.login(target.username, PASSWORD, dashboard.clock(), '192.0.2.1').member.id == target.id


def test_absent_user_runs_real_password_verification(auth, dashboard, monkeypatch):
    from member_dashboard.auth import AuthError
    original = auth._verify_password
    measured = []
    def observed(hashed, password):
        measured.append(hashed)
        return original(hashed, password)
    monkeypatch.setattr(auth, '_verify_password', observed)
    with pytest.raises(AuthError): auth.login('missing_member', PASSWORD, dashboard.clock(), '192.0.2.1')
    assert len(measured) == 1 and measured[0].startswith('$argon2id$')


def test_recovery_boundary_does_not_trust_supplied_identity(auth, dashboard):
    from member_dashboard.auth import AuthError
    actor = admin(auth, dashboard)
    with pytest.raises(AuthError): auth.recover_admin(actor, NEW_PASSWORD, 'root', dashboard.clock())


def test_http_cannot_bootstrap_or_recover(dashboard):
    for path in ['/auth/create-admin','/auth/recover-admin','/admin/recover-admin']:
        assert post(dashboard, path, {}).status_code == 404


def authorize_local(monkeypatch, dashboard):
    from member_dashboard import local_authority
    # OS verification is doubled only for cross-platform CLI/service tests.
    # Dedicated POSIX tests below exercise actual protected files.
    monkeypatch.setattr(local_authority, 'verify_local_operator', lambda path: 'uid:0:synthetic_operator')


def test_local_recovery_needs_no_admin_session(auth, dashboard, monkeypatch, tmp_path):
    from member_dashboard import manage
    from member_dashboard.auth import AuthError
    actor = admin(auth, dashboard)
    first = auth.login('synthetic_admin',PASSWORD,dashboard.clock(),'192.0.2.1')
    second = auth.login('synthetic_admin',PASSWORD,dashboard.clock(),'192.0.2.2')
    reset = auth.issue_reset_trusted(actor,actor,dashboard.clock())
    with dashboard.store.transaction() as con:
        con.execute('UPDATE sessions SET absolute_expires_at=?',(dashboard.clock(),))
    authorize_local(monkeypatch,dashboard)
    grant = tmp_path/'recovery.json'
    grant.write_text(json.dumps({'web_path':str(dashboard.settings.web_path)}))
    monkeypatch.setattr(manage,'GRANT_PATH',grant)
    monkeypatch.setattr(manage,'verify_local_operator',lambda path:'uid:0:synthetic_operator')
    monkeypatch.setattr(manage.sys.stdin,'isatty',lambda:True)
    monkeypatch.setattr(manage.sys.stderr,'isatty',lambda:True)
    monkeypatch.setattr(manage.getpass,'getpass',lambda prompt:NEW_PASSWORD)
    assert manage.main(['recover-admin','--username','synthetic_admin']) == 0
    assert auth.login('synthetic_admin',NEW_PASSWORD,dashboard.clock(),'192.0.2.3').member.id == actor
    with pytest.raises(AuthError): auth.login('synthetic_admin',PASSWORD,dashboard.clock(),'192.0.2.4')
    with pytest.raises(AuthError): auth.reset_password(reset.token,PASSWORD,dashboard.clock())
    with dashboard.store.transaction() as con:
        assert con.execute('SELECT count(*) FROM sessions WHERE id IN (?,?)',(first.id,second.id)).fetchone()[0] == 0
        audit = con.execute("SELECT detail_json FROM audit_events WHERE action='local_admin_recovery'").fetchall()
        assert audit == [('{"operator_identity": "uid:0:synthetic_operator"}',)]
        assert PASSWORD not in str(audit) and NEW_PASSWORD not in str(audit) and reset.token not in str(audit)


@pytest.mark.parametrize('mode',['nonadmin','unknown','noninteractive','mismatch','weak'])
def test_recovery_cli_rejects_invalid_input(auth,dashboard,monkeypatch,tmp_path,mode):
    from member_dashboard import manage
    actor = admin(auth,dashboard)
    target='synthetic_admin'
    if mode=='nonadmin':
        token=auth.issue_invite_trusted(actor,dashboard.clock())
        target=auth.redeem_invite(token.token,'synthetic_member',PASSWORD,dashboard.clock()).username
    if mode=='unknown': target='missing_admin'
    authorize_local(monkeypatch,dashboard)
    grant=tmp_path/'grant.json'
    grant.write_text(json.dumps({'web_path':str(dashboard.settings.web_path)}))
    monkeypatch.setattr(manage,'GRANT_PATH',grant)
    monkeypatch.setattr(manage,'verify_local_operator',lambda path:'uid:0:synthetic_operator')
    monkeypatch.setattr(manage.sys.stdin,'isatty',lambda:mode!='noninteractive')
    monkeypatch.setattr(manage.sys.stderr,'isatty',lambda:True)
    answers=iter([NEW_PASSWORD, PASSWORD] if mode=='mismatch' else ['weak','weak'] if mode=='weak' else [NEW_PASSWORD,NEW_PASSWORD])
    monkeypatch.setattr(manage.getpass,'getpass',lambda prompt:next(answers))
    assert manage.main(['recover-admin','--username',target]) == 1
    with dashboard.store.transaction() as con:
        assert con.execute("SELECT count(*) FROM audit_events WHERE action='local_admin_recovery'").fetchone()[0] == 0


def test_recovery_does_not_reactivate_or_promote(auth,dashboard,monkeypatch):
    from member_dashboard.auth import AuthError
    target=member(auth,dashboard)
    with dashboard.store.transaction() as con:
        actor=con.execute("SELECT id FROM members WHERE role='admin'").fetchone()[0]
        con.execute("UPDATE members SET status='suspended' WHERE id=?",(actor,))
    authorize_local(monkeypatch,dashboard)
    with pytest.raises(AuthError): auth.recover_admin(target.id,NEW_PASSWORD,'uid:0:synthetic_operator',dashboard.clock())
    with pytest.raises(AuthError): auth.recover_admin(str(uuid4()),NEW_PASSWORD,'uid:0:synthetic_operator',dashboard.clock())
    auth.recover_admin(actor,NEW_PASSWORD,'uid:0:synthetic_operator',dashboard.clock())
    with dashboard.store.transaction() as con:
        assert con.execute('SELECT status FROM members WHERE id=?',(actor,)).fetchone()[0]=='suspended'
    with pytest.raises(AuthError): auth.login('synthetic_admin',NEW_PASSWORD,dashboard.clock(),'192.0.2.1')


@pytest.mark.parametrize('operation',['recover','reset'])
def test_password_change_failure_rolls_back_everything(auth,dashboard,monkeypatch,operation):
    actor=admin(auth,dashboard)
    issued=auth.login('synthetic_admin',PASSWORD,dashboard.clock(),'192.0.2.1')
    reset=auth.issue_reset_trusted(actor,actor,dashboard.clock())
    authorize_local(monkeypatch,dashboard)
    with dashboard.store.transaction() as con:
        before=con.execute('SELECT password_hash,authorization_version FROM members WHERE id=?',(actor,)).fetchone()
        audit_count=con.execute('SELECT count(*) FROM audit_events').fetchone()[0]
        con.execute("CREATE TRIGGER fail_audit BEFORE INSERT ON audit_events BEGIN SELECT RAISE(ABORT,'synthetic audit failure'); END;")
    with pytest.raises(sqlite3.IntegrityError):
        if operation=='recover': auth.recover_admin(actor,NEW_PASSWORD,'uid:0:synthetic_operator',dashboard.clock())
        else: auth.reset_password(reset.token,NEW_PASSWORD,dashboard.clock())
    with dashboard.store.transaction() as con:
        assert con.execute('SELECT password_hash,authorization_version FROM members WHERE id=?',(actor,)).fetchone()==before
        assert con.execute('SELECT id FROM sessions').fetchone()[0]==issued.id
        assert con.execute('SELECT consumed_at,revoked_at FROM password_resets').fetchone()==(None,None)
        assert con.execute('SELECT count(*) FROM audit_events').fetchone()[0]==audit_count


def test_bootstrap_once_and_host_authorized(auth,dashboard,monkeypatch):
    from member_dashboard.auth import AuthError
    with pytest.raises(AuthError): auth.create_admin('synthetic_admin',PASSWORD,dashboard.clock())
    authorize_local(monkeypatch,dashboard)
    assert auth.create_admin('synthetic_admin',PASSWORD,dashboard.clock()).role=='admin'
    with pytest.raises(AuthError): auth.create_admin('other_admin',PASSWORD,dashboard.clock())


def test_work_principal_cannot_survive_password_reset(auth,dashboard):
    from member_dashboard.auth import AuthError
    actor=admin(auth,dashboard)
    issued=auth.login('synthetic_admin',PASSWORD,dashboard.clock(),'192.0.2.1')
    principal=auth.principal(issued.token,dashboard.clock())
    auth.revalidate(principal,dashboard.clock())
    reset=auth.issue_reset_trusted(actor,actor,dashboard.clock())
    auth.reset_password(reset.token,NEW_PASSWORD,dashboard.clock())
    with dashboard.store.transaction() as con:
        with pytest.raises(AuthError): auth.revalidate(principal,dashboard.clock(),con=con)


def test_reset_expiry_boundary_and_weak_password(auth,dashboard):
    from member_dashboard.auth import AuthError
    actor=admin(auth,dashboard)
    token=auth.issue_reset_trusted(actor,actor,dashboard.clock())
    with pytest.raises(AuthError): auth.reset_password(token.token,'weak',dashboard.clock())
    with pytest.raises(AuthError): auth.reset_password(token.token,NEW_PASSWORD,token.expires_at)
    auth.reset_password(token.token,NEW_PASSWORD,token.expires_at-1)


def test_auth_failure_is_generic_and_not_logged(auth,dashboard,caplog):
    member(auth,dashboard)
    first=post(dashboard,'/auth/login',{'username':'missing_user','password':PASSWORD})
    second=post(dashboard,'/auth/login',{'username':'synthetic_member','password':'another wrong long password'})
    assert first.status_code==second.status_code==401
    assert first.json()==second.json()=={'error':'unauthorized','message':'Request unavailable.'}
    assert PASSWORD not in caplog.text and 'another wrong long password' not in caplog.text


def test_forwarded_header_does_not_evade_address_throttle(auth,dashboard):
    from member_dashboard.auth import AuthError
    # Reserve through service without expensive failed password work: budget is real DB state.
    now=dashboard.clock()
    for index in range(50): auth._reserve_login(f'absent_{index}','testclient',now)
    response=dashboard.client.get('/api/v1/auth/csrf')
    csrf=response.json()['token']
    result=dashboard.client.post('/api/v1/auth/login',json={'username':'other_user','password':PASSWORD},headers={'Origin':dashboard.settings.origin,'X-CSRF-Token':csrf,'X-Forwarded-For':'192.0.2.254'})
    assert result.status_code==401
    with pytest.raises(AuthError): auth._reserve_login('new_user','testclient',now)


def test_login_cannot_publish_session_after_concurrent_reset(auth,dashboard,monkeypatch):
    from member_dashboard.auth import AuthError
    actor=admin(auth,dashboard)
    token=auth.issue_reset_trusted(actor,actor,dashboard.clock())
    verified=threading.Event()
    reset_done=threading.Event()
    original=auth._verify_password
    def blocked_verify(hashed,password):
        result=original(hashed,password)
        verified.set()
        assert reset_done.wait(5)
        return result
    monkeypatch.setattr(auth,'_verify_password',blocked_verify)
    def reset():
        assert verified.wait(5)
        auth.reset_password(token.token,NEW_PASSWORD,dashboard.clock())
        reset_done.set()
    with ThreadPoolExecutor(max_workers=2) as pool:
        future=pool.submit(reset)
        with pytest.raises(AuthError): auth.login('synthetic_admin',PASSWORD,dashboard.clock(),'192.0.2.1')
        future.result()
    with dashboard.store.transaction() as con:
        assert con.execute('SELECT count(*) FROM sessions').fetchone()[0]==0


def test_admin_guard_uses_server_role(auth,dashboard):
    from fastapi import Depends
    from member_dashboard.authorization import require_admin
    target=member(auth,dashboard)
    @dashboard.app.get('/synthetic-admin')
    def protected(principal=Depends(require_admin)):
        return {'role':principal.role}
    post(dashboard,'/auth/login',{'username':target.username,'password':PASSWORD})
    assert dashboard.client.get('/synthetic-admin',headers={'X-Role':'admin'}).status_code==403
    with dashboard.store.transaction() as con:
        con.execute("UPDATE members SET role='admin' WHERE id=?",(target.id,))
    assert dashboard.client.get('/synthetic-admin').json()=={'role':'admin'}


def test_anonymous_csrf_cookie_cannot_be_replaced(dashboard):
    csrf=dashboard.client.get('/api/v1/auth/csrf').json()['token']
    dashboard.client.cookies.clear()
    result=dashboard.client.post('/api/v1/auth/login',json={'username':'unknown','password':PASSWORD},headers={'Origin':dashboard.settings.origin,'X-CSRF-Token':csrf})
    assert result.status_code==403


def test_session_csrf_not_anonymous_and_rejects_wrong_token(auth,dashboard):
    target=member(auth,dashboard)
    anon=dashboard.client.get('/api/v1/auth/csrf').json()['token']
    post(dashboard,'/auth/login',{'username':target.username,'password':PASSWORD},csrf=anon)
    assert post(dashboard,'/auth/logout',{},csrf=anon).status_code==403
    assert post(dashboard,'/auth/logout',{},csrf='wrong').status_code==403


@pytest.mark.skipif(__import__('os').name!='posix',reason='real root-owned POSIX permission proof runs in isolated Linux sandbox')
def test_posix_authority_checks_real_root_owned_grant(dashboard,tmp_path,monkeypatch):
    import os
    import pwd
    from member_dashboard import local_authority
    from member_dashboard.auth import AuthError
    if os.geteuid()!=0: pytest.skip('namespace root required')
    folder=tmp_path/'protected'
    folder.mkdir(mode=0o700)
    grant=folder/'recovery.json'
    grant.write_text(json.dumps({'allowed_uids':[0],'service_uid':65534,'web_path':str(dashboard.settings.web_path)}))
    grant.chmod(0o600)
    monkeypatch.setattr(local_authority,'GRANT_PATH',grant)
    monkeypatch.setattr(local_authority.sys.stdin,'isatty',lambda:True)
    monkeypatch.setattr(local_authority.sys.stderr,'isatty',lambda:True)
    assert local_authority.verify_local_operator(dashboard.settings.web_path)==f'uid:0:{pwd.getpwuid(0).pw_name}'
    for mode in [0o622,0o666]:
        grant.chmod(mode)
        with pytest.raises(AuthError): local_authority.verify_local_operator(dashboard.settings.web_path)
    grant.chmod(0o600)
    grant.write_text(json.dumps({'allowed_uids':[0],'service_uid':0,'web_path':str(dashboard.settings.web_path)}))
    with pytest.raises(AuthError): local_authority.verify_local_operator(dashboard.settings.web_path)


@pytest.mark.skipif(__import__('os').name!='posix',reason='actual CLI PTY requires isolated Linux mount namespace')
def test_linux_pty_recovery_and_bootstrap(auth,dashboard):
    import os
    from pathlib import Path
    import pty
    import select
    import subprocess
    import sys
    import termios
    import fcntl
    import time
    from member_dashboard.auth import AuthError
    if os.environ.get('MEMBER_DASHBOARD_RECOVERY_SANDBOX')!='1':
        pytest.skip('explicit private sandbox mount required')
    mounts=Path('/proc/self/mountinfo').read_text()
    assert any(line.split()[4]=='/etc' and ' - tmpfs ' in line for line in mounts.splitlines())
    folder=Path('/etc/member-dashboard')
    folder.mkdir(exist_ok=True,mode=0o700)
    grant=folder/'recovery.json'
    grant.write_text(json.dumps({'allowed_uids':[0],'service_uid':65534,'web_path':str(dashboard.settings.web_path)}))
    grant.chmod(0o600)
    def terminal(command,username,passwords,prefix=()):
        master,slave=pty.openpty()
        def controlling_terminal():
            os.setsid()
            fcntl.ioctl(slave,termios.TIOCSCTTY,0)
        process=subprocess.Popen([*prefix,sys.executable,'-m','member_dashboard.manage',command,'--username',username],stdin=slave,stdout=slave,stderr=slave,preexec_fn=controlling_terminal)
        os.close(slave)
        output=b''
        sent=0
        deadline=time.monotonic()+15
        try:
            while time.monotonic()<deadline:
                if select.select([master],[],[],0.2)[0]:
                    try: output+=os.read(master,4096)
                    except OSError: break
                prompts=[b'New password:',b'Repeat new password:']
                if sent<len(passwords) and prompts[sent] in output:
                    os.write(master,(passwords[sent]+'\n').encode())
                    sent+=1
                if process.poll() is not None:
                    break
            code=process.wait(timeout=2)
            for password in passwords: assert password.encode() not in output
            return code,output.decode(errors='replace')
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            os.close(master)
    assert terminal('create-admin','sole_admin',[PASSWORD,PASSWORD])[0]==0
    with dashboard.store.transaction() as con:
        actor=con.execute("SELECT id FROM members WHERE username='sole_admin'").fetchone()[0]
    session=auth.login('sole_admin',PASSWORD,dashboard.clock(),'192.0.2.1')
    token=auth.issue_reset_trusted(actor,actor,dashboard.clock())
    with dashboard.store.transaction() as con:
        con.execute('UPDATE sessions SET absolute_expires_at=?',(dashboard.clock(),))
    code,output=terminal('recover-admin','sole_admin',[NEW_PASSWORD,NEW_PASSWORD])
    assert code==0,output
    assert auth.login('sole_admin',NEW_PASSWORD,dashboard.clock(),'192.0.2.2').member.id==actor
    with pytest.raises(AuthError): auth.login('sole_admin',PASSWORD,dashboard.clock(),'192.0.2.3')
    with pytest.raises(AuthError): auth.reset_password(token.token,PASSWORD,dashboard.clock())
    with dashboard.store.transaction() as con:
        assert con.execute('SELECT count(*) FROM sessions WHERE id=?',(session.id,)).fetchone()[0]==0
        events=con.execute("SELECT detail_json FROM audit_events WHERE action='local_admin_recovery'").fetchall()
        assert len(events)==1
        assert json.loads(events[0][0])['operator_identity'].startswith('uid:0:')
        assert token.token not in str(events) and NEW_PASSWORD not in str(events)
    assert terminal('create-admin','another_admin',[PASSWORD,PASSWORD])[0]==1
    assert terminal('recover-admin','missing_admin',[PASSWORD,PASSWORD])[0]==1
    assert terminal('recover-admin','sole_admin',[NEW_PASSWORD,PASSWORD])[0]==1
    assert terminal('recover-admin','sole_admin',['weak','weak'])[0]==1
    assert subprocess.run([sys.executable,'-m','member_dashboard.manage','recover-admin','--username','sole_admin'],capture_output=True).returncode==1
    # Readable but protected grant isolates identity denial from permission denial.
    folder.chmod(0o755)
    grant.write_text(json.dumps({'allowed_uids':[0,65534],'service_uid':65534,'web_path':str(dashboard.settings.web_path)}))
    grant.chmod(0o644)
    code,output=terminal('recover-admin','sole_admin',[],prefix=('setpriv','--reuid=65534','--regid=65534','--clear-groups'))
    assert code==1 and 'New password:' not in output


def test_public_token_writes_obey_address_budget(auth,dashboard):
    actor=admin(auth,dashboard)
    token=auth.issue_invite_trusted(actor,dashboard.clock())
    for index in range(50): auth._reserve_login(f'absent_{index}','testclient',dashboard.clock())
    response=post(dashboard,'/auth/redeem',{'token':token.token,'username':'budget_member','password':PASSWORD})
    assert response.status_code==400
    dashboard.clock.advance(901)
    assert post(dashboard,'/auth/redeem',{'token':token.token,'username':'budget_member','password':PASSWORD}).status_code==201


def test_http_invite_reset_session_flow(auth,dashboard):
    actor=admin(auth,dashboard)
    token=auth.issue_invite_trusted(actor,dashboard.clock())
    response=post(dashboard,'/auth/redeem',{'token':token.token,'username':'http_member','password':PASSWORD})
    assert response.status_code==201 and response.json()['role']=='member'
    assert post(dashboard,'/auth/redeem',{'token':token.token,'username':'other_member','password':PASSWORD}).status_code==400
    assert post(dashboard,'/auth/login',{'username':'http_member','password':PASSWORD}).status_code==200
    reset=auth.issue_reset_trusted(actor,response.json()['id'],dashboard.clock())
    assert post(dashboard,'/auth/reset',{'token':reset.token,'password':NEW_PASSWORD}).status_code==204
    assert dashboard.client.get('/api/v1/me').status_code==401
    assert post(dashboard,'/auth/login',{'username':'http_member','password':NEW_PASSWORD}).status_code==200
    assert post(dashboard,'/auth/logout',{}).status_code==204


def test_recovery_wins_against_simultaneous_old_reset(auth,dashboard,monkeypatch):
    from member_dashboard.auth import AuthError
    actor=admin(auth,dashboard)
    token=auth.issue_reset_trusted(actor,actor,dashboard.clock())
    authorize_local(monkeypatch,dashboard)
    original=auth.hash_password
    barrier=threading.Barrier(2)
    def synchronized_hash(password):
        hashed=original(password)
        barrier.wait(timeout=5)
        return hashed
    monkeypatch.setattr(auth,'hash_password',synchronized_hash)
    def recovery():
        auth.recover_admin(actor,NEW_PASSWORD,'uid:0:synthetic_operator',dashboard.clock())
    def reset():
        try: auth.reset_password(token.token,'synthetic reset race password',dashboard.clock())
        except AuthError: pass
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(recovery),pool.submit(reset)]
        for future in futures: future.result()
    with dashboard.store.transaction() as con:
        hashed=con.execute('SELECT password_hash FROM members WHERE id=?',(actor,)).fetchone()[0]
        assert auth._verify_password(hashed,NEW_PASSWORD)
        assert con.execute("SELECT count(*) FROM password_resets WHERE consumed_at IS NULL AND revoked_at IS NULL").fetchone()[0]==0
        assert con.execute("SELECT count(*) FROM audit_events WHERE action='local_admin_recovery'").fetchone()[0]==1


@pytest.mark.parametrize('operation',['invite','reset'])
@pytest.mark.parametrize('state',['revoked','deleted','idle','absolute','reset','recovery','suspended','revision','role'])
def test_public_issuance_rejects_stale_admin_principal(auth,dashboard,monkeypatch,operation,state):
    from member_dashboard.auth import AuthError
    actor=admin(auth,dashboard)
    issued=auth.login('synthetic_admin',PASSWORD,dashboard.clock(),'192.0.2.1')
    principal=auth.principal(issued.token,dashboard.clock())
    old=auth.issue_reset_trusted(actor,actor,dashboard.clock())
    if state=='reset': auth.reset_password(old.token,NEW_PASSWORD,dashboard.clock())
    elif state=='recovery':
        authorize_local(monkeypatch,dashboard)
        auth.recover_admin(actor,NEW_PASSWORD,'uid:0:synthetic_operator',dashboard.clock())
    else:
        with dashboard.store.transaction() as con:
            if state=='revoked': con.execute('UPDATE sessions SET revoked_at=?',(dashboard.clock(),))
            if state=='deleted': con.execute('DELETE FROM sessions')
            if state=='idle': con.execute('UPDATE sessions SET idle_expires_at=?',(dashboard.clock(),))
            if state=='absolute': con.execute('UPDATE sessions SET absolute_expires_at=?',(dashboard.clock(),))
            if state=='suspended': con.execute("UPDATE members SET status='suspended'")
            if state=='revision': con.execute('UPDATE members SET authorization_version=authorization_version+1')
            if state=='role': con.execute("UPDATE members SET role='member'")
    with dashboard.store.transaction() as con:
        before=[con.execute(f'SELECT * FROM {table}').fetchall() for table in ['invites','password_resets','audit_events']]
    with pytest.raises(AuthError):
        if operation=='invite': auth.issue_invite(principal,dashboard.clock())
        else: auth.issue_reset(principal,actor,dashboard.clock())
    with dashboard.store.transaction() as con:
        after=[con.execute(f'SELECT * FROM {table}').fetchall() for table in ['invites','password_resets','audit_events']]
        assert after==before


def test_public_issuance_joins_caller_transaction_and_rolls_back(auth,dashboard):
    actor=admin(auth,dashboard)
    session=auth.login('synthetic_admin',PASSWORD,dashboard.clock(),'192.0.2.1')
    principal=auth.principal(session.token,dashboard.clock())
    with pytest.raises(RuntimeError,match='synthetic action rollback'):
        with dashboard.store.transaction() as con:
            invite=auth.issue_invite(principal,dashboard.clock(),con=con)
            reset=auth.issue_reset(principal,actor,dashboard.clock(),con=con)
            assert con.execute('SELECT id FROM invites').fetchone()[0]==invite.id
            assert con.execute('SELECT id FROM password_resets').fetchone()[0]==reset.id
            assert con.execute("SELECT count(*) FROM audit_events WHERE action IN ('invite_issued','reset_issued')").fetchone()[0]==2
            raise RuntimeError('synthetic action rollback')
    with dashboard.store.transaction() as con:
        assert con.execute('SELECT count(*) FROM invites').fetchone()[0]==0
        assert con.execute('SELECT count(*) FROM password_resets').fetchone()[0]==0
        assert con.execute("SELECT count(*) FROM audit_events WHERE action IN ('invite_issued','reset_issued')").fetchone()[0]==0
    assert auth.issue_invite(principal,dashboard.clock()).id
    assert auth.issue_reset(principal,actor,dashboard.clock()).id


def test_anonymous_csrf_reuses_live_challenge(dashboard):
    first=dashboard.client.get('/api/v1/auth/csrf')
    cookie=dashboard.client.cookies.get('__Host-member_csrf')
    second=dashboard.client.get('/api/v1/auth/csrf')
    assert first.status_code==second.status_code==200
    assert second.json()['token']==first.json()['token']
    assert dashboard.client.cookies.get('__Host-member_csrf')==cookie
    dashboard.clock.advance(900)
    third=dashboard.client.get('/api/v1/auth/csrf')
    assert third.status_code==200 and third.json()['token']!=first.json()['token']


def test_csrf_abusive_address_cannot_exhaust_other_clients(dashboard):
    from fastapi.testclient import TestClient
    rejected=False
    for index in range(80):
        dashboard.client.cookies.clear()
        response=dashboard.client.get('/api/v1/auth/csrf',headers={'X-Forwarded-For':f'192.0.2.{index+1}'})
        if response.status_code!=200:
            rejected=True
            break
    assert rejected, 'one trusted address must hit its own budget before global capacity'
    with TestClient(dashboard.app,base_url=dashboard.settings.origin,client=('192.0.2.254',45000)) as other:
        response=other.get('/api/v1/auth/csrf')
        assert response.status_code==200
        token=response.json()['token']
        assert other.post('/api/v1/auth/login',json={'username':'unknown','password':PASSWORD},headers={'Origin':dashboard.settings.origin,'X-CSRF-Token':token}).status_code==401
    dashboard.clock.advance(901)
    assert dashboard.client.get('/api/v1/auth/csrf').status_code==200



@pytest.mark.parametrize('operation',['invite','reset'])
def test_public_issuance_rejects_autocommit_connection(auth,dashboard,operation):
    from member_dashboard.auth import AuthError
    actor=admin(auth,dashboard)
    session=auth.login('synthetic_admin',PASSWORD,dashboard.clock(),'192.0.2.1')
    principal=auth.principal(session.token,dashboard.clock())
    con=dashboard.store._connect()
    try:
        assert not con.in_transaction
        with pytest.raises(AuthError):
            if operation=='invite': auth.issue_invite(principal,dashboard.clock(),con=con)
            else: auth.issue_reset(principal,actor,dashboard.clock(),con=con)
        assert con.execute('SELECT count(*) FROM invites').fetchone()[0]==0
        assert con.execute('SELECT count(*) FROM password_resets').fetchone()[0]==0
    finally:
        con.close()
