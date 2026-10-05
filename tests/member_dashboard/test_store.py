"""Task 1 boundary proofs: paths, transactions, schema and public projection."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import threading
from uuid import uuid4

import pytest


def member(connection, username="synthetic_member", **overrides):
    values = dict(id=str(uuid4()), username=username, password_hash="synthetic-hash",
                  role="member", status="active", created_at=1.0)
    values.update(overrides)
    connection.execute("INSERT INTO members (id,username,password_hash,role,status,created_at) "
                       "VALUES (:id,:username,:password_hash,:role,:status,:created_at)", values)
    return values["id"]


def test_settings_reject_same_path(tmp_path):
    from member_dashboard.settings import Settings
    with pytest.raises(ValueError, match="distinct"):
        Settings(web_path=tmp_path / "same.db", market_path=tmp_path / "same.db")


def test_settings_reject_relative_paths(tmp_path):
    from member_dashboard.settings import Settings
    with pytest.raises(ValueError, match="absolute"):
        Settings(web_path=Path("web.db"), market_path=tmp_path / "market.db")


@pytest.mark.parametrize("link_kind", ["hard", "symbolic"])
def test_settings_reject_same_file_alias(tmp_path, link_kind):
    from member_dashboard.settings import Settings
    market = tmp_path / "market.db"
    market.touch()
    alias = tmp_path / "web.db"
    if link_kind == "hard":
        os.link(market, alias)
    else:
        try:
            alias.symlink_to(market)
        except OSError as exc:
            pytest.skip(f"Host cannot create symbolic links: {exc}")
    with pytest.raises(ValueError, match="distinct"):
        Settings(web_path=alias, market_path=market)


def test_app_revalidates_alias_created_after_settings(tmp_path):
    from member_dashboard.settings import Settings
    from member_dashboard.app import create_app
    market = tmp_path / "market.db"
    market.touch()
    web = tmp_path / "web.db"
    settings = Settings(web_path=web, market_path=market)
    os.link(market, web)
    with pytest.raises(ValueError, match="distinct"):
        create_app(settings)
    assert market.stat().st_size == 0


def test_web_migration_never_creates_market_database(tmp_path):
    from member_dashboard.store import WebStore
    web = tmp_path / "web.sqlite3"
    market = tmp_path / "missing-market.sqlite3"
    WebStore(web).migrate()
    assert web.exists()
    assert not market.exists()


def test_startup_leaves_missing_market_absent(tmp_path):
    from fastapi.testclient import TestClient
    from member_dashboard.app import create_app
    from member_dashboard.settings import Settings
    market = tmp_path / "missing.db"
    with TestClient(create_app(Settings(web_path=tmp_path / "web.db", market_path=market))) as client:
        assert client.get("/healthz").json() == {"status": "ok"}
    assert not market.exists()


def test_migration_is_idempotent(dashboard):
    with dashboard.store.transaction() as connection:
        member_id = member(connection)
    dashboard.store.migrate()
    dashboard.store.migrate()
    with dashboard.store.transaction() as connection:
        assert connection.execute("SELECT id FROM members").fetchone()[0] == member_id
        assert connection.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall() == [(1,), (2,), (3,), (4,), (5,), (6,)]


def test_failed_transaction_rolls_back(dashboard):
    with pytest.raises(RuntimeError):
        with dashboard.store.transaction() as connection:
            member(connection)
            raise RuntimeError("synthetic failure")
    with dashboard.store.transaction() as connection:
        assert connection.execute("SELECT COUNT(*) FROM members").fetchone()[0] == 0


def test_transaction_enforces_foreign_keys(dashboard):
    with dashboard.store.transaction() as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("INSERT INTO sessions(id,member_id,token_digest,csrf_digest,created_at,"
                               "last_seen_at,absolute_expires_at,idle_expires_at) VALUES (?,?,?,?,?,?,?,?)",
                               (str(uuid4()), str(uuid4()), b"x" * 32, b"c" * 32, 1., 1., 2., 2.))


def test_transaction_uses_wal_and_two_second_timeout(dashboard):
    with dashboard.store.transaction() as connection:
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert connection.execute("PRAGMA busy_timeout").fetchone()[0] == 2000


def test_simultaneous_writers_commit_without_lost_rows(dashboard):
    barrier = threading.Barrier(8)
    def write(index):
        barrier.wait(timeout=5)
        with dashboard.store.transaction() as connection:
            return member(connection, username=f"synthetic_{index}")
    with ThreadPoolExecutor(max_workers=8) as pool:
        ids = list(pool.map(write, range(8)))
    with dashboard.store.transaction() as connection:
        assert {row[0] for row in connection.execute("SELECT id FROM members")} == set(ids)


@pytest.mark.parametrize("overrides", [dict(username="UPPER"), dict(username="with-space "),
                                      dict(username="aa"), dict(role="owner"),
                                      dict(status="disabled"), dict(id="guessable")])
def test_member_constraints_reject_invalid_accounts(dashboard, overrides):
    with dashboard.store.transaction() as connection:
        with pytest.raises(sqlite3.IntegrityError):
            member(connection, **overrides)


def test_duplicate_username_rejected(dashboard):
    with dashboard.store.transaction() as connection:
        member(connection)
        with pytest.raises(sqlite3.IntegrityError):
            member(connection)


@pytest.mark.parametrize("table", ["invites", "password_resets", "sessions"])
def test_token_digests_unique_and_only_binary_digests(dashboard, table):
    with dashboard.store.transaction() as connection:
        owner = member(connection)
        if table == "sessions":
            sql = ("INSERT INTO sessions(id,member_id,token_digest,csrf_digest,created_at,last_seen_at,"
                   "absolute_expires_at,idle_expires_at) VALUES (?,?,?,?,?,?,?,?)")
            tail = (owner, b"x" * 32, b"c" * 32, 1., 1., 2., 2.)
        elif table == "password_resets":
            sql = "INSERT INTO password_resets(id,member_id,token_digest,created_at,expires_at) VALUES (?,?,?,?,?)"
            tail = (owner, b"x" * 32, 1., 2.)
        else:
            sql = "INSERT INTO invites(id,token_digest,created_at,expires_at) VALUES (?,?,?,?)"
            tail = (b"x" * 32, 1., 2.)
        connection.execute(sql, (str(uuid4()), *tail))
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(sql, (str(uuid4()), *tail))
        invalid = tuple("raw-token" if value == b"x" * 32 else value for value in tail)
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(sql, (str(uuid4()), *invalid))


def test_active_job_dedupe_allows_new_job_after_completion(dashboard):
    with dashboard.store.transaction() as connection:
        sql = "INSERT INTO web_jobs(id,dedupe_key,ticker,section,status,created_at) VALUES (?,?,?,?,?,?)"
        connection.execute(sql, (str(uuid4()), "key", "SYN", "analysis", "queued", 1.))
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(sql, (str(uuid4()), "key", "SYN", "analysis", "running", 1.))
        connection.execute("UPDATE web_jobs SET status='completed'")
        connection.execute(sql, (str(uuid4()), "key", "SYN", "analysis", "queued", 2.))


def test_results_keep_immutable_lineage_and_unique_fingerprint(dashboard):
    with dashboard.store.transaction() as connection:
        sql = ("INSERT INTO market_results(id,fingerprint,ticker,section,content_json,created_at,"
               "source_lineage_json,required_features_json,retention_deadline) VALUES (?,?,?,?,?,?,?,?,?)")
        lineage = json.dumps([dict(source_id="synthetic", product_id="quotes", source_version="1",
                                   policy_version="1")])
        result = str(uuid4())
        tail = ("unique", "SYN", "analysis", '{"version":1}', 1., lineage, '["analysis"]', 2.)
        connection.execute(sql, (result, *tail))
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(sql, (str(uuid4()), *tail))
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute("UPDATE market_results SET content_json='{}' WHERE id=?", (result,))
        assert connection.execute("SELECT source_lineage_json,required_features_json,retention_deadline "
                                  "FROM market_results WHERE id=?", (result,)).fetchone() == (lineage, '["analysis"]', 2.)


def test_report_owner_pair_is_unique(dashboard):
    with dashboard.store.transaction() as connection:
        owner = member(connection)
        report = str(uuid4())
        connection.execute("INSERT INTO report_versions(id,report_id,version,content_json,created_at) "
                           "VALUES (?,?,?,?,?)", (str(uuid4()), report, 1, '{}', 1.))
        connection.execute("INSERT INTO report_owners(id,report_id,member_id,created_at) VALUES (?,?,?,?)",
                           (str(uuid4()), report, owner, 1.))
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("INSERT INTO report_owners(id,report_id,member_id,created_at) VALUES (?,?,?,?)",
                               (str(uuid4()), report, owner, 1.))


def test_source_card_version_unique(dashboard):
    with dashboard.store.transaction() as connection:
        sql = ("INSERT INTO publications(id,source_post_key,ticker,content_version,feature,content_json,"
               "published_at) VALUES (?,?,?,?,?,?,?)")
        connection.execute(sql, (str(uuid4()), "synthetic-post", "SYN", "v1", "feed", '{}', 1.))
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(sql, (str(uuid4()), "synthetic-post", "SYN", "v1", "feed", '{}', 1.))


def test_staging_features_enabled_without_verified_source_permissions(dashboard):
    with dashboard.store.transaction() as connection:
        assert dict(connection.execute("SELECT name,enabled FROM features")) == {
            "feed": 1, "setups": 1, "analysis": 1, "sec": 1, "options": 1,
            "em_daily": 1, "em_weekly": 1, "assistant": 1}
        assert connection.execute("SELECT COUNT(*) FROM source_permissions").fetchone()[0] == 0


def test_health_response_has_no_operational_data_or_cors(dashboard):
    response = dashboard.client.get("/healthz", headers={"Origin": "https://untrusted.test"})
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert "access-control-allow-origin" not in response.headers
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["cache-control"] == "private, no-store"


def test_startup_cannot_import_bot_or_read_machine_configuration(tmp_path):
    script = '''
import sys, tempfile
from pathlib import Path
def deny(event, args):
    if event == "import" and args[0].startswith(("consensus_engine", "dotenv")):
        raise RuntimeError("forbidden production import")
    if event == "open" and isinstance(args[0], str) and Path(args[0]).name in {".env", "schwab_token.json", "consensus.yaml"}:
        raise RuntimeError("forbidden machine configuration")
sys.addaudithook(deny)
from fastapi.testclient import TestClient
from member_dashboard.app import create_app
from member_dashboard.settings import Settings
with tempfile.TemporaryDirectory() as d:
    p=Path(d)
    with TestClient(create_app(Settings(web_path=p/"web.db", market_path=p/"missing.db"))) as client:
        assert client.get("/healthz").json() == {"status":"ok"}
    assert not (p/"missing.db").exists()
'''
    run = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr


@pytest.mark.parametrize("field,value", [("value", float("nan")), ("value", float("inf")),
                                       ("private_grant_ref", "forbidden")])
def test_public_metrics_reject_nonfinite_and_private_fields(field, value):
    from pydantic import ValidationError
    from member_dashboard.contracts import Metric
    values = dict(value=None, unit="USD", method="synthetic")
    values[field] = value
    with pytest.raises(ValidationError):
        Metric(**values)


def test_public_payload_union_rejects_arbitrary_dictionaries():
    from pydantic import ValidationError
    from member_dashboard.contracts import SectionResult
    with pytest.raises(ValidationError):
        SectionResult(section="analysis", status="completed", job_id=None, result_id=None,
                      observed_at=None, computed_at=None, valid_until=None, stale=False,
                      analysis_version="v1", payload={"raw_bot_row": "private"}, message=None)


def test_public_payload_preserves_missing_metrics_and_rejects_wrong_horizon():
    from pydantic import ValidationError
    from member_dashboard.contracts import SectionResult
    values = dict(section="em_daily", status="completed", job_id=None, result_id=None,
                  observed_at=None, computed_at=1., valid_until=None, stale=False,
                  analysis_version="v1", message=None, payload=dict(kind="move", horizon="daily",
                  spot=None, expiry=None, ranges=[], quote_times=[], chart_asset_id=None))
    result = SectionResult(**values)
    assert result.model_dump()["payload"]["spot"] is None
    values["payload"]["horizon"] = "weekly"
    with pytest.raises(ValidationError):
        SectionResult(**values)


def test_unknown_schema_version_fails_closed(tmp_path):
    from member_dashboard.store import WebStore
    path = tmp_path / "web.db"
    store = WebStore(path)
    store.migrate()
    with store.transaction() as connection:
        connection.execute("INSERT INTO schema_migrations(version,applied_at) VALUES (999,1.0)")
    with pytest.raises(ValueError, match="newer"):
        store.migrate()


def test_typed_internal_lineage_retains_all_policy_and_feature_dependencies():
    from member_dashboard.contracts import ContentLineage
    lineage = ContentLineage(sources=[dict(source_id="source-a", product_id="quotes",
                              source_version="v2", policy_version="p3")],
                              required_features=["analysis", "options"],
                              field_dependencies=[dict(field_path="summary", required_features=["options"])],
                              retention_deadline=2.0)
    assert json.loads(lineage.model_dump_json()) == {
        "sources": [{"source_id": "source-a", "product_id": "quotes", "source_version": "v2", "policy_version": "p3"}],
        "required_features": ["analysis", "options"],
        "field_dependencies": [{"field_path": "summary", "required_features": ["options"]}],
        "retention_deadline": 2.0}


def test_internal_lineage_rejects_unknown_and_missing_contributors():
    from pydantic import ValidationError
    from member_dashboard.contracts import ContentLineage
    with pytest.raises(ValidationError):
        ContentLineage(sources=[], required_features=["analysis"], field_dependencies=[], retention_deadline=None)
    with pytest.raises(ValidationError):
        ContentLineage(sources=[{"source_id": "source-a"}], required_features=["analysis"],
                       field_dependencies=[], retention_deadline=None)


def test_migration_preserves_existing_market_bytes(tmp_path):
    from fastapi.testclient import TestClient
    from member_dashboard.app import create_app
    from member_dashboard.settings import Settings
    market = tmp_path / "market.db"
    original = b"synthetic-market-bytes-do-not-open"
    market.write_bytes(original)
    with TestClient(create_app(Settings(web_path=tmp_path / "web.db", market_path=market))) as client:
        assert client.get("/healthz").status_code == 200
    assert market.read_bytes() == original


def test_authorization_and_work_revisions_start_at_one(dashboard):
    with dashboard.store.transaction() as connection:
        owner = member(connection)
        assert connection.execute("SELECT authorization_version FROM members WHERE id=?", (owner,)).fetchone()[0] == 1
        job = str(uuid4())
        connection.execute("INSERT INTO web_jobs(id,dedupe_key,ticker,section,status,created_at) VALUES (?,?,?,?,?,?)",
                           (job, "synthetic", "SYN", "analysis", "queued", 1.))
        assert connection.execute("SELECT work_version FROM web_jobs WHERE id=?", (job,)).fetchone()[0] == 1


def test_migration_creates_all_planned_domains(dashboard):
    with dashboard.store.transaction() as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert tables >= {"members", "sessions", "invites", "password_resets", "auth_attempts", "features",
                      "audit_events", "web_jobs", "job_subscribers", "research_requests", "request_sections",
                      "market_results", "report_versions", "report_owners", "conversations", "messages",
                      "assistant_runs", "web_usage", "publications", "publication_changes", "source_checkpoints",
                      "assets", "worker_heartbeat", "source_permissions", "provider_quota_policy",
                      "provider_admissions", "provider_cooldowns"}


def test_unexpected_failure_returns_only_safe_envelope(dashboard):
    from fastapi.testclient import TestClient
    @dashboard.app.get("/synthetic-failure")
    def fail():
        raise RuntimeError("private-path-and-provider-detail")
    with TestClient(dashboard.app, raise_server_exceptions=False) as client:
        response = client.get("/synthetic-failure")
    assert response.status_code == 503
    assert response.json() == {"error": "unavailable", "message": "Request unavailable."}
    assert response.headers["cache-control"] == "private, no-store"


def test_not_found_returns_only_safe_envelope(dashboard):
    response = dashboard.client.get("/does-not-exist")
    assert response.status_code == 404
    assert response.json() == {"error": "not_found", "message": "Request unavailable."}


def test_validation_error_never_echoes_input(dashboard):
    from member_dashboard.contracts import Metric
    @dashboard.app.post("/synthetic-input")
    def metric_input(metric: Metric):
        return metric
    response = dashboard.client.post("/synthetic-input", json={"private_grant_ref": "private-input"})
    assert response.status_code == 422
    assert response.json() == {"error": "invalid_request", "message": "Request unavailable."}


def test_field_feature_lineage_survives_result_storage(dashboard):
    with dashboard.store.transaction() as connection:
        result = str(uuid4())
        connection.execute("INSERT INTO market_results(id,fingerprint,ticker,section,content_json,created_at,"
                           "field_dependencies_json) VALUES (?,?,?,?,?,?,?)",
                           (result, "lineage", "SYN", "analysis", '{}', 1.,
                            '[{"field_path":"summary","required_features":["options"]}]'))
        assert json.loads(connection.execute("SELECT field_dependencies_json FROM market_results WHERE id=?",
                                             (result,)).fetchone()[0]) == [{"field_path": "summary", "required_features": ["options"]}]


def test_publication_content_versions_cannot_be_overwritten(dashboard):
    with dashboard.store.transaction() as connection:
        card = str(uuid4())
        connection.execute("INSERT INTO publications(id,source_post_key,ticker,content_version,feature,content_json,"
                           "published_at) VALUES (?,?,?,?,?,?,?)", (card, "post", "SYN", "v1", "feed", '{}', 1.))
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute("UPDATE publications SET content_json=? WHERE id=?", ('{"private":"mutation"}', card))


def test_failed_migration_rolls_back_partial_tables(tmp_path, monkeypatch):
    import member_dashboard.store as module
    from member_dashboard.store import WebStore
    migration = tmp_path / "migrations"
    migration.mkdir()
    (migration / "001_initial.sql").write_text("CREATE TABLE partial(id INTEGER);\nINVALID SQL;\n", encoding="utf-8")
    monkeypatch.setattr(module, "__file__", str(tmp_path / "store.py"))
    path = tmp_path / "web.db"
    with pytest.raises(sqlite3.OperationalError):
        WebStore(path).migrate()
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT name FROM sqlite_master WHERE name IN ('partial','schema_migrations')").fetchall() == []


def test_private_resource_identifiers_reject_non_uuid_strings(dashboard):
    with dashboard.store.transaction() as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("INSERT INTO invites(id,token_digest,created_at,expires_at) VALUES (?,?,?,?)",
                               ("a" * 36, b"z" * 32, 1., 2.))
