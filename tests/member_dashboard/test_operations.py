"""Focused fixed-role composition and maintenance regressions."""
import os
from pathlib import Path
import pytest


def test_fixed_role_config_cannot_smuggle_api_compute_privileges(tmp_path):
    from member_dashboard.operations import validate_config
    base={'role':'api','uid':123,'web_path':str(tmp_path/'web'),'origin':'https://dashboard.test',
          'signing_key':str(tmp_path/'signing'),'authority_socket':str(tmp_path/'authority.sock'),'authority_uid':124}
    assert validate_config(base)['role']=='api'
    for extra in ({'market_path':'/private/source'},{'command':['sh']},{'verified':True}):
        with pytest.raises(ValueError): validate_config({**base,**extra})


def test_denial_authority_rpc_has_no_grant_or_untrusted_mutation(tmp_path):
    from member_dashboard.authority_rpc import AuthorityService
    from member_dashboard.authority import DenialJournal,CheckpointStore
    root=tmp_path/'journal';root.mkdir(mode=0o700)
    journal=DenialJournal.create(root/'journal',root/'anchor',checkpoint=CheckpointStore.create(tmp_path/'checkpoint'))
    service=AuthorityService(journal,read_uids=[123,124],write_uids=[123])
    for uid,request in ((124,{'method':'append','kind':'feature_disabled','key':'options'}),
                        (123,{'method':'grant','verified':True}),
                        (999,{'method':'current','offset':0})):
        with pytest.raises(ValueError): service.dispatch(request,peer_uid=uid)
    assert service.dispatch({'method':'append','kind':'feature_disabled','key':'options'},peer_uid=123)=={'revision':1}
    assert service.dispatch({'method':'current','offset':0},peer_uid=124)['rows'][0][1]=='feature_disabled'


def test_archive_maintenance_authenticates_expiry_before_deletion(tmp_path,monkeypatch):
    from member_dashboard.backup import maintain_archives,_crypt
    node=Path(__file__).resolve().parents[2]/'.superpowers/sdd/2026-10-05-member-dashboard/node-v24.21.0-win-x64/node.exe'
    if not node.exists(): pytest.skip('Node archive proof runs on Windows control host')
    import time
    key=tmp_path/'key';key.write_bytes(os.urandom(32));key.chmod(0o600)
    archive=tmp_path/'one.mdb';deadline=int(time.time())+10
    archive.write_bytes(_crypt('seal',deadline.to_bytes(8,'big')+b'synthetic',key,node));archive.chmod(0o600)
    assert maintain_archives(tmp_path,key_path=key,node=node,now=deadline-1)==0
    bad=bytearray(archive.read_bytes());bad[-1]^=1;archive.write_bytes(bad)
    with pytest.raises(ValueError): maintain_archives(tmp_path,key_path=key,node=node,now=deadline+1)
    assert archive.exists()
    archive.write_bytes(_crypt('seal',deadline.to_bytes(8,'big')+b'synthetic',key,node))
    assert maintain_archives(tmp_path,key_path=key,node=node,now=deadline+1)==1
    assert not archive.exists()


def test_feed_transaction_applies_committed_feature_denial(dashboard,tmp_path):
    from member_dashboard.authority import DenialJournal,CheckpointStore
    import time
    root=tmp_path/'journal';root.mkdir(mode=0o700)
    journal=DenialJournal.create(root/'journal',root/'anchor',checkpoint=CheckpointStore.create(tmp_path/'checkpoint'))
    dashboard.store.bind_authority(journal)
    journal.append('feature_disabled','feed')
    from member_dashboard.publication import FeedService
    feed=FeedService(dashboard.store,dashboard.app.state.auth,dashboard.app.state.source_policy,signing_key=b'x'*32)
    with feed._transaction(time.monotonic()+30) as con:
        assert con.execute("SELECT enabled FROM features WHERE name='feed'").fetchone()[0]==0


def test_api_role_constructs_no_market_reader_or_compute(tmp_path,monkeypatch):
    from member_dashboard.operations import api_app
    def forbidden(*args,**kwargs): pytest.fail('API constructed a market reader or child launcher')
    monkeypatch.setattr('member_dashboard.market_reader.MarketReader',forbidden)
    monkeypatch.setattr('member_dashboard.compute_launcher.CgroupLauncher',forbidden)
    key=tmp_path/'key';key.write_bytes(b'x'*32);key.chmod(0o600)
    app=api_app({'web_path':str(tmp_path/'web'),'signing_key':str(key),
        'origin':'https://dashboard.test','authority_socket':str(tmp_path/'rpc'),'authority_uid':124})
    assert app.state.source_policy.authority_current() is False
    assert app.state.providers is None
    assert not hasattr(app.state,'synthetic_supervisor')


def test_checkpoint_cannot_hide_inside_journal_snapshot(tmp_path):
    from member_dashboard.authority import DenialJournal,CheckpointStore
    root=tmp_path/'journal';root.mkdir(mode=0o700)
    nested=root/'nested';nested.mkdir(mode=0o700)
    checkpoint=CheckpointStore.create(nested/'checkpoint')
    with pytest.raises(ValueError,match='outside_journal'):
        DenialJournal.create(root/'journal',root/'anchor',checkpoint=checkpoint)
