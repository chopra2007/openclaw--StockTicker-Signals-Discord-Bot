import json
import sqlite3

from scripts.check_batch1_measurement_gate import (
    _full_regular_sessions_elapsed,
    evaluate_gate,
    main,
    parse_cutoff,
)


def _database(path):
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE alert_history (id INTEGER PRIMARY KEY, alerted_at REAL);
        CREATE TABLE measurement_candidates_v1 (
            candidate_id TEXT PRIMARY KEY, direction TEXT, created_at REAL);
        CREATE TABLE measurement_decision_events_v1 (
            decision_id TEXT, candidate_id TEXT, status TEXT,
            owner_visible_score REAL, created_at REAL);
        CREATE TABLE measurement_alert_events_v1 (
            decision_id TEXT, legacy_alert_id INTEGER, created_at REAL);
        CREATE TABLE measurement_delivery_events_v1 (
            decision_id TEXT, status TEXT, created_at REAL);
        CREATE TABLE measurement_outcome_events_v1 (
            decision_id TEXT, status TEXT, horizon TEXT, created_at REAL);
        """
    )
    return conn


def _passing_rows(conn):
    since = parse_cutoff("2026-08-10T00:00:00")
    created = parse_cutoff("2026-08-10T07:00:00")
    conn.execute("INSERT INTO alert_history VALUES (1, ?)", (created,))
    conn.execute("INSERT INTO measurement_candidates_v1 VALUES ('c1','long',?)", (created,))
    conn.execute(
        "INSERT INTO measurement_decision_events_v1 VALUES ('d1','c1','scored',81,?)",
        (created,),
    )
    conn.execute("INSERT INTO measurement_alert_events_v1 VALUES ('d1',1,?)", (created,))
    conn.execute(
        "INSERT INTO measurement_delivery_events_v1 VALUES ('d1','confirmed_delivered',?)",
        (created,),
    )
    conn.execute(
        "INSERT INTO measurement_outcome_events_v1 VALUES ('d1','pending','primary',?)",
        (created,),
    )
    conn.commit()
    return since


def test_parse_naive_iso_as_pacific():
    assert parse_cutoff("2026-08-10T07:00:00") == parse_cutoff("2026-08-10T07:00:00-07:00")


def test_market_holiday_does_not_count_as_completed_session():
    since = parse_cutoff("2026-12-25T00:00:00")
    until = parse_cutoff("2026-12-25T23:59:59")

    assert _full_regular_sessions_elapsed(since, until) == 0


def test_completed_scheduled_early_close_counts_as_one_session():
    since = parse_cutoff("2026-11-27T06:00:00")
    until = parse_cutoff("2026-11-27T10:01:00")

    assert _full_regular_sessions_elapsed(since, until) == 1


def test_gate_passes_after_complete_session(tmp_path):
    conn = _database(tmp_path / "gate.db")
    since = _passing_rows(conn)
    until = parse_cutoff("2026-08-11T14:00:00")
    result = evaluate_gate(conn, since, until)
    conn.close()
    assert result["status"] == "PASS"
    assert result["full_regular_sessions_elapsed"] >= 1
    assert result["old_confirmed_delivery_count"] == result["new_confirmed_delivery_count"] == 1


def test_gate_waits_for_missing_evidence(tmp_path):
    conn = _database(tmp_path / "gate.db")
    since = parse_cutoff("2026-08-11T12:00:00")
    until = parse_cutoff("2026-08-11T12:30:00")
    result = evaluate_gate(conn, since, until)
    conn.close()
    assert result["status"] == "WAIT"
    assert "one full regular market session has not elapsed" in result["reasons"]
    assert "no trade candidates collected" in result["reasons"]
    assert "no confirmed delivered alerts collected" in result["reasons"]


def test_gate_waits_when_confirmed_delivery_lacks_pending_primary_outcome(tmp_path):
    conn = _database(tmp_path / "gate.db")
    since = _passing_rows(conn)
    conn.execute("DELETE FROM measurement_outcome_events_v1")
    conn.commit()

    result = evaluate_gate(conn, since, parse_cutoff("2026-08-11T14:00:00"))
    conn.close()

    assert result["status"] == "WAIT"
    assert result["missing_pending_outcome"] == 1
    assert "1 confirmed delivery decision(s) lack a pending primary outcome" in result["reasons"]


def test_cli_is_read_only_and_prints_sanitized_json(tmp_path, capsys):
    db_path = tmp_path / "gate.db"
    conn = _database(db_path)
    since = _passing_rows(conn)
    before = db_path.read_bytes()
    conn.close()

    rc = main([
        "--db", str(db_path), "--since", str(since),
        "--until", "2026-08-11T14:00:00",
    ])

    output = capsys.readouterr().out.splitlines()
    payload = json.loads(output[0])
    assert rc == 0
    assert payload["status"] == "PASS"
    assert output[1].startswith("PASS:")
    assert db_path.read_bytes() == before
    assert "NVDA" not in "\n".join(output)
