ALTER TABLE track_alerts ADD COLUMN direction TEXT NOT NULL DEFAULT 'unclear'
    CHECK(direction IN ('bullish','bearish','unclear'));
-- A bounded rolling scan also revisits old alerts repaired by historical catch-up.
CREATE TABLE track_sync_state (id INTEGER PRIMARY KEY CHECK(id=1), last_id INTEGER NOT NULL, new_id INTEGER NOT NULL) STRICT;
INSERT INTO track_sync_state VALUES (1,0,0);
