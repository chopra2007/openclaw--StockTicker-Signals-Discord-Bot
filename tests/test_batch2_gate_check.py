import json
import sqlite3

from scripts.check_batch1_measurement_gate import parse_cutoff
from scripts.check_batch2_trade_gate import evaluate_gate, main


def _database(path):
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE measurement_candidates_v1 (candidate_id TEXT PRIMARY KEY);
        CREATE TABLE measurement_decision_events_v1 (
            decision_id TEXT, candidate_id TEXT);
        CREATE TABLE measurement_outcome_events_v1 (
            outcome_id TEXT, decision_id TEXT);
        CREATE TABLE measurement_delivery_events_v1 (
            delivery_id TEXT, decision_id TEXT, status TEXT, confirmed_at REAL);
        CREATE TABLE measurement_trade_rule_sets_v1 (
            rule_set_id TEXT PRIMARY KEY,
            fee_per_contract_transaction_micros INTEGER,
            max_delivery_entry_delay_seconds REAL);
        CREATE TABLE measurement_trade_plan_events_v1 (
            trade_id TEXT, status TEXT, candidate_id TEXT, decision_id TEXT,
            outcome_id TEXT, delivery_id TEXT, rule_set_id TEXT,
            instrument_type TEXT, confirmed_delivery_at REAL,
            contract_count INTEGER, created_at REAL, plan_json TEXT);
        CREATE TABLE measurement_contract_selection_events_v1 (
            selection_id TEXT, trade_id TEXT, contract_symbol TEXT,
            option_type TEXT, action TEXT, strike_micros INTEGER,
            expiration TEXT, multiplier INTEGER, quote_source TEXT,
            contract_json TEXT);
        CREATE TABLE measurement_market_observations_v1 (
            observation_id TEXT, trade_id TEXT, contract_selection_id TEXT,
            purpose TEXT, status TEXT, usable INTEGER,
            provider_timestamp REAL, received_timestamp REAL,
            delivery_to_quote_seconds REAL, observation_json TEXT,
            bid_micros INTEGER, ask_micros INTEGER,
            executable_price_micros INTEGER, observed_at REAL, quote_source TEXT);
        CREATE TABLE measurement_trade_result_events_v1 (
            trade_id TEXT, outcome_id TEXT, contract_selection_id TEXT,
            status TEXT, is_primary INTEGER,
            gross_micros INTEGER, net_micros INTEGER,
            contract_fees_micros INTEGER, result_json TEXT,
            entry_observation_id TEXT, exit_observation_id TEXT,
            result_rule_version TEXT, resolved_at REAL);
        """
    )
    return conn


def _passing_rows(conn):
    since = parse_cutoff("2026-08-10T00:00:00")
    delivered = parse_cutoff("2026-08-10T07:00:00")
    entry = delivered + 5
    for suffix in ("option", "share"):
        conn.execute(
            "INSERT INTO measurement_candidates_v1 VALUES (?)", (f"c-{suffix}",)
        )
        conn.execute(
            "INSERT INTO measurement_decision_events_v1 VALUES (?,?)",
            (f"d-{suffix}", f"c-{suffix}"),
        )
        conn.execute(
            "INSERT INTO measurement_outcome_events_v1 VALUES (?,?)",
            (f"o-{suffix}", f"d-{suffix}"),
        )
        conn.execute(
            "INSERT INTO measurement_delivery_events_v1 VALUES (?,?,?,?)",
            (f"delivery-{suffix}", f"d-{suffix}", "confirmed_delivered", delivered),
        )
    conn.execute(
        "INSERT INTO measurement_trade_rule_sets_v1 VALUES (?,?,?)",
        ("rules", 450_000, 60),
    )
    for suffix in ("option", "share"):
        conn.execute(
            "INSERT INTO measurement_trade_plan_events_v1 VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                f"trade-{suffix}", "eligible", f"c-{suffix}", f"d-{suffix}",
                f"o-{suffix}", f"delivery-{suffix}", "rules", suffix,
                delivered, 1 if suffix == "option" else None, delivered,
                json.dumps({"exit_due_at": entry + 3600}),
            ),
        )
        if suffix == "option":
            entry_prices = (1_900_000, 2_000_000, 2_000_000)
            exit_prices = (2_500_000, 2_600_000, 2_500_000)
        else:
            entry_prices = (99_900_000, 100_000_000, 100_000_000)
            exit_prices = (103_000_000, 103_100_000, 103_000_000)
        conn.execute(
            "INSERT INTO measurement_market_observations_v1 VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                f"entry-{suffix}", f"trade-{suffix}",
                "selection-option" if suffix == "option" else None,
                "entry", "observed", 1, entry - 1, entry, 5,
                json.dumps({"capture_origin": "live_schwab_api"}),
                *entry_prices, entry, "schwab",
            ),
        )
        conn.execute(
            "INSERT INTO measurement_market_observations_v1 VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                f"exit-{suffix}", f"trade-{suffix}",
                "selection-option" if suffix == "option" else None,
                "exit", "observed", 1, entry + 3599, entry + 3600,
                None, json.dumps({"capture_origin": "live_schwab_api"}),
                *exit_prices, entry + 3600, "schwab",
            ),
        )
    conn.execute(
        "INSERT INTO measurement_contract_selection_events_v1 VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            "selection-option", "trade-option", "NVDA260821C00150000",
            "call", "buy_to_open", 150_000_000, "2026-08-21", 100,
            "schwab", json.dumps({"capture_origin": "live_schwab_api"}),
        ),
    )
    option_result = {
        "entry_ask": 2.0,
        "entry_bid": 1.9,
        "exit_bid": 2.5,
        "exit_ask": 2.6,
        "contract_multiplier": 100,
        "contract_count": 1,
        "buy_contract_fee": 0.45,
        "sell_contract_fee": 0.45,
        "extra_fees_total": 0.0,
    }
    conn.execute(
        "INSERT INTO measurement_trade_result_events_v1 VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "trade-option", "o-option", "selection-option", "resolved", 1,
            50_000_000, 49_100_000, 900_000, json.dumps(option_result),
            "entry-option", "exit-option", "option-result-v1", entry + 3600,
        ),
    )
    share_result = {
        "direction": "long",
        "entry_price": 100.0,
        "exit_price": 103.0,
        "quantity": 1,
        "spread_dollars": 0.20,
        "commission_dollars": 0.0,
        "slippage_dollars": 0.10,
        "planned_risk_dollars": 2.20,
        "fee_rule_version": "share-fees-v1",
        "result_rule_version": "share-result-v1",
    }
    conn.execute(
        "INSERT INTO measurement_trade_result_events_v1 VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "trade-share", "o-share", None, "resolved", 1,
            3_000_000, 3_000_000, 0, json.dumps(share_result),
            "entry-share", "exit-share", "share-result-v1", entry + 3600,
        ),
    )
    conn.commit()
    return since


def test_batch2_gate_passes_with_real_linked_option_and_share_results(tmp_path):
    conn = _database(tmp_path / "gate.db")
    since = _passing_rows(conn)

    result = evaluate_gate(conn, since, parse_cutoff("2026-08-11T14:00:00"))

    conn.close()
    assert result["status"] == "PASS"
    assert result["resolved_option_count"] == 1
    assert result["resolved_share_count"] == 1
    assert result["reproduction_failures"] == 0


def test_batch2_gate_waits_for_missing_exact_contract(tmp_path):
    conn = _database(tmp_path / "gate.db")
    since = _passing_rows(conn)
    conn.execute("DELETE FROM measurement_contract_selection_events_v1")
    conn.commit()

    result = evaluate_gate(conn, since, parse_cutoff("2026-08-11T14:00:00"))

    conn.close()
    assert result["status"] == "WAIT"
    assert result["missing_exact_contract"] == 1


def test_batch2_gate_waits_when_stored_option_result_does_not_reproduce(tmp_path):
    conn = _database(tmp_path / "gate.db")
    since = _passing_rows(conn)
    conn.execute(
        "UPDATE measurement_trade_result_events_v1 SET net_micros=123 "
        "WHERE trade_id='trade-option'"
    )
    conn.commit()

    result = evaluate_gate(conn, since, parse_cutoff("2026-08-11T14:00:00"))

    conn.close()
    assert result["status"] == "WAIT"
    assert result["reproduction_failures"] == 1


def test_batch2_gate_rejects_unapproved_quote_source(tmp_path):
    conn = _database(tmp_path / "gate.db")
    since = _passing_rows(conn)
    conn.execute(
        "UPDATE measurement_market_observations_v1 SET quote_source='synthetic' "
        "WHERE observation_id='entry-option'",
    )
    conn.commit()

    result = evaluate_gate(conn, since, parse_cutoff("2026-08-11T14:00:00"))

    conn.close()
    assert result["status"] == "WAIT"
    assert result["option_entry_count"] == 0


def test_batch2_gate_rejects_source_label_without_live_capture_proof(tmp_path):
    conn = _database(tmp_path / "gate.db")
    since = _passing_rows(conn)
    conn.execute(
        "UPDATE measurement_market_observations_v1 SET observation_json='{}' "
        "WHERE observation_id='entry-option'",
    )
    conn.commit()

    result = evaluate_gate(conn, since, parse_cutoff("2026-08-11T14:00:00"))

    conn.close()
    assert result["status"] == "WAIT"
    assert result["option_entry_count"] == 0


def test_batch2_gate_rejects_contract_without_live_capture_proof(tmp_path):
    conn = _database(tmp_path / "gate.db")
    since = _passing_rows(conn)
    conn.execute(
        "UPDATE measurement_contract_selection_events_v1 SET contract_json='{}' "
        "WHERE selection_id='selection-option'",
    )
    conn.commit()

    result = evaluate_gate(conn, since, parse_cutoff("2026-08-11T14:00:00"))

    conn.close()
    assert result["status"] == "WAIT"
    assert result["missing_exact_contract"] == 1


def test_batch2_gate_rejects_provider_time_after_receipt(tmp_path):
    conn = _database(tmp_path / "gate.db")
    since = _passing_rows(conn)
    conn.execute(
        "UPDATE measurement_market_observations_v1 "
        "SET provider_timestamp=received_timestamp+1 "
        "WHERE observation_id='entry-option'",
    )
    conn.commit()

    result = evaluate_gate(conn, since, parse_cutoff("2026-08-11T14:00:00"))

    conn.close()
    assert result["status"] == "WAIT"
    assert result["bad_entry_timing"] == 1


def test_batch2_gate_rejects_result_quotes_from_another_contract(tmp_path):
    conn = _database(tmp_path / "gate.db")
    since = _passing_rows(conn)
    conn.execute(
        "INSERT INTO measurement_contract_selection_events_v1 VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            "selection-other", "trade-option", "NVDA260821C00155000",
            "call", "buy_to_open", 155_000_000, "2026-08-21", 100,
            "schwab", json.dumps({"capture_origin": "live_schwab_api"}),
        ),
    )
    conn.execute(
        "UPDATE measurement_trade_result_events_v1 "
        "SET contract_selection_id='selection-other' WHERE trade_id='trade-option'",
    )
    conn.commit()

    result = evaluate_gate(conn, since, parse_cutoff("2026-08-11T14:00:00"))

    conn.close()
    assert result["status"] == "WAIT"
    assert result["result_observation_errors"] >= 1


def test_batch2_cli_is_read_only_and_sanitized(tmp_path, capsys):
    path = tmp_path / "gate.db"
    conn = _database(path)
    since = _passing_rows(conn)
    conn.close()
    before = path.read_bytes()

    rc = main([
        "--db", str(path), "--since", str(since),
        "--until", "2026-08-11T14:00:00",
    ])

    output = capsys.readouterr().out.splitlines()
    payload = json.loads(output[0])
    assert rc == 0
    assert payload["status"] == "PASS"
    assert path.read_bytes() == before
    assert "NVDA" not in "\n".join(output)
