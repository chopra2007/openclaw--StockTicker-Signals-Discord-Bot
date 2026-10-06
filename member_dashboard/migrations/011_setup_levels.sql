-- Trade plan per ticker for the Trade setups page (owner request 2026-10-06): the same
-- buy zone / stop / targets as the ticker research page, computed without the AI write-up.
CREATE TABLE setup_levels (
    ticker TEXT PRIMARY KEY CHECK(length(ticker) BETWEEN 1 AND 16),
    computed_at REAL NOT NULL,
    direction TEXT NOT NULL CHECK(direction IN ('long','short','neutral')),
    price REAL,
    entry_low REAL,
    entry_high REAL,
    stop REAL,
    target1 REAL,
    target2 REAL,
    target3 REAL
) STRICT;
