import sqlite3

def test_restore_uses_exact_alert_link_and_rejects_conflicts():
    from consensus_engine.db import ALERT_DIRECTION_RESTORE_SQL
    c=sqlite3.connect(':memory:')
    c.executescript('CREATE TABLE alert_history(id INTEGER,ticker TEXT,direction TEXT);'
        'CREATE TABLE measurement_alert_events_v1(legacy_alert_id INTEGER,decision_id TEXT);'
        'CREATE TABLE measurement_decision_events_v1(decision_id TEXT,candidate_id TEXT);'
        'CREATE TABLE measurement_candidates_v1(candidate_id TEXT,ticker TEXT,direction TEXT);')
    c.executemany('INSERT INTO alert_history VALUES (?,?,?)',[(1,'AAA','unclear'),(2,'AAA','unclear'),(3,'AAA','unclear'),(4,'AAA','long')])
    c.executemany('INSERT INTO measurement_alert_events_v1 VALUES (?,?)',[(1,'d1'),(2,'d1'),(2,'d2'),(3,'d3'),(4,'d1')])
    c.executemany('INSERT INTO measurement_decision_events_v1 VALUES (?,?)',[('d1','c1'),('d2','c2'),('d3','c3')])
    c.executemany('INSERT INTO measurement_candidates_v1 VALUES (?,?,?)',[('c1','AAA','short'),('c2','AAA','long'),('c3','BBB','short')])
    c.execute(ALERT_DIRECTION_RESTORE_SQL)
    assert c.execute('SELECT direction FROM alert_history ORDER BY id').fetchall()==[('short',),('unclear',),('unclear',),('long',)]
