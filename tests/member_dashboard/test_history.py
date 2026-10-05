"""Owned immutable history, current permission overlays and deletion fences."""
from dataclasses import replace
import json
import sqlite3
from uuid import uuid4

import pytest
from test_jobs import research, finish_all, fixture_result


@pytest.fixture
def history(research, dashboard):
    from member_dashboard.history import HistoryService
    return HistoryService(research[0], signing_key=b'synthetic-history-key-at-least-32', clock=dashboard.clock)


def completed(research, dashboard, both=False):
    jobs, users, *_ = research
    requests = [jobs.request_research(user, 'SPY', False, dashboard.clock()) for user in users[:2 if both else 1]]
    finish_all(jobs, dashboard.clock())
    return requests


def test_history_module_exists():
    import importlib.util
    assert importlib.util.find_spec('member_dashboard.history') is not None


def test_original_survives_refresh_request_removal_and_password_reset(history, research, dashboard):
    jobs, users, *_ = research
    request = completed(research, dashboard)[0]
    original = history.get_report(users[0], request.report_id)
    dashboard.clock.advance(901)
    jobs.request_research(users[0], 'SPY', False, dashboard.clock())
    finish_all(jobs, dashboard.clock())
    with jobs.store.transaction() as con:
        con.execute('DELETE FROM research_cache')
        con.execute('DELETE FROM research_requests WHERE id=?', (request.id,))
        con.execute('UPDATE members SET authorization_version=2 WHERE id=?', (users[0].member_id,))
        con.execute('UPDATE sessions SET authorization_version=2 WHERE id=?', (users[0].session_id,))
    reopened = history.get_report(replace(users[0], authorization_version=2), request.report_id)
    assert reopened.sections == original.sections
    assert reopened.version == original.version
    assert reopened.finalized


def test_delete_only_owned_copy_and_keep_shared_asset(history, research, dashboard):
    from io import BytesIO
    from PIL import Image
    from member_dashboard.assets import AssetService
    jobs, users, *_ = research
    requests = [jobs.request_research(u, 'SPY', False, dashboard.clock()) for u in users[:2]]
    png = BytesIO(); Image.new('RGB', (8, 8)).save(png, format='PNG')
    while job := jobs.claim_job('fixture', dashboard.clock()):
        jobs.complete_job(job.id, job.lease_token, fixture_result(job.kind, dashboard.clock()), dashboard.clock(),
                          png=png.getvalue() if job.kind == 'em_daily' else None)
    original = history.get_report(users[1], requests[1].report_id)
    asset = original.sections['em_daily'].payload.chart_asset_id
    from member_dashboard.history import HistoryError
    with pytest.raises(HistoryError) as error:
        history.delete_report(users[0], requests[1].report_id)
    assert error.value.status == 404
    history.delete_report(users[0], requests[0].report_id)
    assert history.get_report(users[1], requests[1].report_id) == original
    assert AssetService(jobs).read(users[0], asset, dashboard.clock()) is None
    assert AssetService(jobs).read(users[1], asset, dashboard.clock()) == png.getvalue()


def test_pending_delete_fences_running_completion_without_refund(history, research, dashboard):
    jobs, users, *_ = research
    request = jobs.request_research(users[0], 'SPY', False, dashboard.clock())
    assert history.get_report(users[0], request.report_id).availability == 'pending'
    job = jobs.claim_job('fixture', dashboard.clock())
    history.delete_report(users[0], request.report_id)
    jobs.complete_job(job.id, job.lease_token, fixture_result(job.kind, dashboard.clock()), dashboard.clock())
    with jobs.store.transaction() as con:
        assert con.execute('SELECT count(*) FROM report_versions').fetchone()[0] == 0
        assert con.execute("SELECT count(*) FROM web_usage WHERE kind='research_compute'").fetchone()[0] == 1
        assert con.execute('SELECT count(*) FROM job_subscribers WHERE member_id=? AND deleted_at IS NULL', (users[0].member_id,)).fetchone()[0] == 0
    assert not history.list_reports(users[0]).items


@pytest.mark.parametrize('withdraw', ['suspend', 'reset', 'session'])
def test_no_attachment_after_auth_withdrawal(history, research, dashboard, withdraw):
    from member_dashboard.auth import AuthError
    jobs, users, *_ = research
    request = jobs.request_research(users[0], 'SPY', False, dashboard.clock())
    job = jobs.claim_job('fixture', dashboard.clock())
    with jobs.store.transaction() as con:
        if withdraw == 'suspend': con.execute("UPDATE members SET status='suspended' WHERE id=?", (users[0].member_id,))
        if withdraw == 'reset': con.execute('UPDATE members SET authorization_version=2 WHERE id=?', (users[0].member_id,))
        if withdraw == 'session': con.execute('UPDATE sessions SET revoked_at=? WHERE id=?', (dashboard.clock(), users[0].session_id))
    jobs.complete_job(job.id, job.lease_token, fixture_result(job.kind, dashboard.clock()), dashboard.clock())
    with jobs.store.transaction() as con:
        assert con.execute('SELECT current_version_id FROM report_owners WHERE report_id=?', (request.report_id,)).fetchone()[0] is None
    with pytest.raises(AuthError): history.get_report(users[0], request.report_id)


def test_current_features_hide_old_sections_but_do_not_mutate_snapshot(history, research, dashboard):
    jobs, users, *_ = research
    request = completed(research, dashboard)[0]
    with jobs.store.transaction() as con:
        original = con.execute('SELECT content_json FROM report_versions ORDER BY rowid DESC LIMIT 1').fetchone()[0]
        con.execute("UPDATE features SET enabled=0,version=version+1 WHERE name='options'")
    saved = history.get_report(users[0], request.report_id)
    assert saved.sections['options'].payload is None
    assert saved.sections['sec'].status == 'completed'
    with jobs.store.transaction() as con:
        assert con.execute('SELECT content_json FROM report_versions ORDER BY rowid DESC LIMIT 1').fetchone()[0] == original


def test_provider_purge_applies_to_every_copy_and_null_never_falls_back(history, research, dashboard):
    from member_dashboard.source_policy import SourcePermission
    jobs, users, _, policy = research
    requests = completed(research, dashboard, both=True)
    with jobs.store.transaction() as con:
        current = con.execute('SELECT current_version_id FROM report_owners WHERE report_id=?', (requests[0].report_id,)).fetchone()[0]
        con.execute('DELETE FROM report_versions WHERE id=?', (current,))
    assert history.get_report(users[0], requests[0].report_id).availability == 'unavailable'
    assert history.get_report(users[0], requests[0].report_id).sections == {}
    policy.record(SourcePermission(source_id='synthetic', product_id='fixture', provider='fixture', policy_version='p2', audience='invited_members', status='denied'))
    policy.purge(dashboard.clock())
    for user, request in zip(users, requests):
        saved = history.get_report(user, request.report_id)
        assert saved.availability == 'unavailable' and saved.sections == {}


def test_same_time_pages_are_signed_owner_resource_bound(history, research, dashboard):
    from member_dashboard.history import HistoryError
    jobs, users, *_ = research
    completed(research, dashboard)
    for _ in range(5): jobs.request_research(users[0], 'SPY', False, dashboard.clock())
    first = history.list_reports(users[0], limit=2)
    second = history.list_reports(users[0], cursor=first.cursor, limit=2)
    third = history.list_reports(users[0], cursor=second.cursor, limit=2)
    assert len({r.id for p in [first, second, third] for r in p.items}) == 6
    assert third.cursor is None
    for cursor, user, resource in [(first.cursor+'x', users[0], 'reports'), (first.cursor, users[1], 'reports'), (first.cursor, users[0], 'conversations')]:
        with pytest.raises(HistoryError):
            getattr(history, 'list_'+resource)(user, cursor=cursor)
    with pytest.raises(HistoryError): history.list_reports(users[0], limit=101)


def conversation_fixture(research, dashboard, status='running'):
    jobs, users, *_ = research
    conversation, run = str(uuid4()), str(uuid4())
    with jobs.store.transaction() as con:
        con.execute('INSERT INTO conversations(id,member_id,title,created_at) VALUES (?,?,?,?)', (conversation, users[0].member_id, 'Private discussion', dashboard.clock()))
        con.execute('INSERT INTO assistant_runs(id,conversation_id,member_id,session_id,status,created_at) VALUES (?,?,?,?,?,?)', (run, conversation, users[0].member_id, users[0].session_id, status, dashboard.clock()))
        for user in users[:2]:
            con.execute("INSERT INTO messages(id,conversation_id,member_id,role,content_json,created_at) VALUES (?,?,?,'user',?,?)", (str(uuid4()), conversation, user.member_id, json.dumps({'text': 'My private question' if user == users[0] else 'Wrong owner'}), dashboard.clock()))
    return conversation, run


@pytest.mark.parametrize('status,expected', [('queued','cancelled'), ('running','draining'), ('draining','draining')])
def test_conversation_owner_messages_delete_run_fence(history, research, dashboard, status, expected):
    from member_dashboard.history import HistoryError
    jobs, users, *_ = research
    conversation, run = conversation_fixture(research, dashboard, status)
    assert [m.text for m in history.get_conversation(users[0], conversation).messages] == ['My private question']
    with pytest.raises(HistoryError): history.get_conversation(users[1], conversation)
    history.delete_conversation(users[0], conversation)
    with jobs.store.transaction() as con:
        con.row_factory = sqlite3.Row
        assert history.owned_live_conversation(con, users[0], conversation, dashboard.clock(), expected_version=1) is None
        row = con.execute('SELECT * FROM assistant_runs WHERE id=?', (run,)).fetchone()
        assert row['status'] == expected and row['subscriber_version'] == 2 and row['deleted_at']
        if expected == 'draining':
            with pytest.raises(sqlite3.IntegrityError):
                con.execute("INSERT INTO assistant_runs(id,conversation_id,member_id,status,created_at) VALUES (?,?,?,'queued',?)", (str(uuid4()), conversation, users[0].member_id, dashboard.clock()))


def test_api_owner_csrf_and_no_store(history, research, dashboard):
    from member_dashboard.auth import digest
    jobs, users, *_ = research
    request = completed(research, dashboard)[0]
    dashboard.app.state.history = history
    with jobs.store.transaction() as con:
        con.execute('UPDATE sessions SET token_digest=?,csrf_digest=? WHERE id=?', (digest('history-session'), digest('history-csrf'), users[0].session_id))
    dashboard.client.cookies.set('__Host-member_session', 'history-session')
    response = dashboard.client.get('/api/v1/reports/'+request.report_id)
    assert response.status_code == 200
    assert response.headers['Cache-Control'] == 'private, no-store'
    assert dashboard.client.delete('/api/v1/reports/'+request.report_id).status_code == 403
    assert dashboard.client.delete('/api/v1/reports/'+request.report_id, headers={'Origin':dashboard.settings.origin,'X-CSRF-Token':'history-csrf'}).status_code == 204
    assert dashboard.client.get('/api/v1/reports/'+request.report_id).status_code == 404


def test_all_failed_sections_get_final_snapshot(history, research, dashboard):
    jobs, users, *_ = research
    request = jobs.request_research(users[0], 'SPY', False, dashboard.clock())
    while job := jobs.claim_job('fixture', dashboard.clock()):
        jobs.fail_attempt(job.id, job.lease_token, dashboard.clock(), retryable=False)
    saved = history.get_report(users[0], request.report_id)
    assert saved.finalized and saved.version is not None
    assert {s.status for s in saved.sections.values()} == {'failed'}


@pytest.mark.parametrize('exact,latch', [(True,False),(False,False),(False,True)])
def test_retraction_overlay_hides_dependent_prose_and_direct_asset(history, research, dashboard, exact, latch):
    from member_dashboard.contracts import Evidence
    from member_dashboard.publication import _retain_marker
    from member_dashboard.source_policy import SourcePermission
    from member_dashboard.assets import AssetService
    from io import BytesIO
    from PIL import Image
    jobs, users, _, policy = research
    policy.record(SourcePermission(source_id='synthetic', product_id='fixture', provider='fixture',
        policy_version='p2', audience='invited_members', status='allowed', display_raw=True,display_derived=True,
        retain=True,tombstone_allowed=True,private_grant_ref='fixture',evidence_ref='fixture',terms_url='https://www.sec.gov/fixture',effective_at=0.0))
    for name,spec in list(research[2].providers.items()):
        research[2].providers[name]=replace(spec,lineage=spec.lineage.model_copy(update={'sources':[s.model_copy(update={'policy_version':'p2'}) for s in spec.lineage.sources]}))
    request = jobs.request_research(users[0], 'SPY', False, dashboard.clock())
    evidence = Evidence(id='exact-evidence',source_id='synthetic',source_version='s1',observed_at=dashboard.clock()-100,url=None,excerpt='Original retained evidence',research_only=True)
    png=BytesIO(); Image.new('RGB',(8,8)).save(png,format='PNG')
    while job := jobs.claim_job('fixture',dashboard.clock()):
        value=fixture_result(job.kind,dashboard.clock()).model_copy(update={'evidence':[evidence]})
        jobs.complete_job(job.id,job.lease_token,value,dashboard.clock(),png=png.getvalue() if job.kind=='em_daily' else None)
    original=history.get_report(users[0],request.report_id)
    asset=original.sections['em_daily'].payload.chart_asset_id
    with jobs.store.transaction() as con:
        before=con.execute('SELECT content_json FROM report_versions ORDER BY rowid DESC LIMIT 1').fetchone()[0]
        _retain_marker(con,policy,'evidence_retractions',('exact-evidence' if exact else 'nearby-evidence','synthetic','s1'),dashboard.clock(),
            [json.dumps([s.model_dump() for s in research[2].providers['analysis'].lineage.sources])])
        if latch: con.execute('UPDATE feed_state SET retraction_authority_required=1')
    result=history.get_report(users[0],request.report_id)
    if exact or latch:
        assert result.sections['analysis'].payload is None
        assert result.annotations['analysis'][0].status == ('unavailable' if latch else 'retracted')
        assert AssetService(jobs).read(users[0],asset,dashboard.clock()) is None
    else:
        assert result.sections == original.sections and result.annotations == {}
    with jobs.store.transaction() as con:
        assert con.execute('SELECT content_json FROM report_versions ORDER BY rowid DESC LIMIT 1').fetchone()[0] == before


def test_missing_signing_key_fails_closed(history,research,dashboard):
    from member_dashboard.history import HistoryService, HistoryError
    service=HistoryService(research[0],signing_key=None,clock=dashboard.clock)
    with pytest.raises(HistoryError) as error: service.list_reports(research[1][0])
    assert error.value.status==503


def test_model_messages_require_lineage_and_current_retention(history,research,dashboard):
    jobs,users,_,policy=research
    conversation,_=conversation_fixture(research,dashboard)
    with jobs.store.transaction() as con:
        con.execute("INSERT INTO messages(id,conversation_id,member_id,role,content_json,created_at) VALUES (?,?,?,'assistant',?,?)",
            (str(uuid4()),conversation,users[0].member_id,'{"text":"Untracked output"}',dashboard.clock()))
    result=history.get_conversation(users[0],conversation)
    assert next(m for m in result.messages if m.role=='assistant').text is None
    policy.purge(dashboard.clock())
    assert [m.text for m in history.get_conversation(users[0],conversation).messages]==['My private question']


def test_deleted_current_version_does_not_authorize_old_chart(history,research,dashboard):
    from io import BytesIO
    from PIL import Image
    from member_dashboard.assets import AssetService
    jobs,users,*_=research
    request=jobs.request_research(users[0],'SPY',False,dashboard.clock())
    png=BytesIO(); Image.new('RGB',(8,8)).save(png,format='PNG')
    while job:=jobs.claim_job('fixture',dashboard.clock()):
        jobs.complete_job(job.id,job.lease_token,fixture_result(job.kind,dashboard.clock()),dashboard.clock(),png=png.getvalue() if job.kind=='em_daily' else None)
    asset=history.get_report(users[0],request.report_id).sections['em_daily'].payload.chart_asset_id
    with jobs.store.transaction() as con:
        con.execute('DELETE FROM report_versions WHERE id=(SELECT current_version_id FROM report_owners WHERE report_id=?)',(request.report_id,))
        assert con.execute('SELECT count(*) FROM report_versions WHERE report_id=?',(request.report_id,)).fetchone()[0]>0
    assert AssetService(jobs).read(users[0],asset,dashboard.clock()) is None


def test_completion_delete_race_never_resurrects_owned_history(history,research,dashboard):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from member_dashboard.history import HistoryError
    jobs,users,*_=research
    request=jobs.request_research(users[0],'SPY',False,dashboard.clock())
    job=jobs.claim_job('fixture',dashboard.clock())
    gate=Barrier(2)
    def delete():
        gate.wait(); history.delete_report(users[0],request.report_id)
    def complete():
        gate.wait(); jobs.complete_job(job.id,job.lease_token,fixture_result(job.kind,dashboard.clock()),dashboard.clock())
    with ThreadPoolExecutor(2) as pool:
        futures=[pool.submit(delete),pool.submit(complete)]
        for future in futures: future.result()
    with pytest.raises(HistoryError): history.get_report(users[0],request.report_id)
    assert not history.list_reports(users[0]).items


def test_malformed_snapshot_is_content_free(history,research,dashboard):
    jobs,users,*_=research
    request=completed(research,dashboard)[0]
    with jobs.store.transaction() as con:
        version=str(uuid4())
        con.execute('INSERT INTO report_versions(id,report_id,version,content_json,created_at,finalized) VALUES (?,?,999,?,?,1)',
            (version,request.report_id,'{"analysis":{"private":"must not escape"}}',dashboard.clock()))
        con.execute('UPDATE report_owners SET current_version_id=? WHERE report_id=?',(version,request.report_id))
    saved=history.get_report(users[0],request.report_id)
    assert saved.availability=='unavailable' and saved.sections=={} and 'private' not in saved.model_dump_json()


def test_save_adapter_rejects_unattached_results_and_revoked_owner(history,research,dashboard):
    jobs,users,*_=research
    request=completed(research,dashboard)[0]
    saved=history.get_report(users[0],request.report_id)
    with jobs.store.transaction() as con:
        assert history.save_report(users[1].member_id,request.id,saved.sections,con=con,now=dashboard.clock()) is None
        wrong={'analysis':saved.sections['analysis'].model_copy(update={'result_id':str(uuid4())})}
        with pytest.raises(ValueError): history.save_report(users[0].member_id,request.id,wrong,con=con,now=dashboard.clock())
        con.execute('UPDATE sessions SET revoked_at=? WHERE id=?',(dashboard.clock(),users[0].session_id))
        assert history.save_report(users[0].member_id,request.id,saved.sections,con=con,now=dashboard.clock()) is None


def test_assistant_message_evidence_must_belong_to_complete_lineage(history,research,dashboard):
    jobs,users,registry,_=research
    conversation,_=conversation_fixture(research,dashboard)
    source=registry.providers['analysis'].lineage.sources[0]
    content={'text':'Restricted model prose','evidence':[{'id':'unknown','source_id':'untracked','source_version':'v0',
        'observed_at':dashboard.clock(),'url':None,'excerpt':'Restricted evidence','research_only':True}]}
    with jobs.store.transaction() as con:
        con.execute("INSERT INTO messages(id,conversation_id,member_id,role,content_json,source_lineage_json,required_features_json,created_at) VALUES (?,?,?,'assistant',?,?,?,?)",
            (str(uuid4()),conversation,users[0].member_id,json.dumps(content),json.dumps([source.model_dump()]),'["assistant"]',dashboard.clock()))
    value=next(m for m in history.get_conversation(users[0],conversation).messages if m.role=='assistant')
    assert value.text is None and value.evidence==[]
