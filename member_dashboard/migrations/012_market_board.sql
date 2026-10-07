-- Market strip, watchlist and alert track record (design round 2026-10-06).
-- market_quotes: one Schwab /quotes snapshot (indices + watched + recent alert tickers), written by the compute worker.
CREATE TABLE market_quotes (
    symbol TEXT PRIMARY KEY CHECK(length(symbol) BETWEEN 1 AND 16),
    price REAL,
    prev_close REAL,
    prev_day TEXT,  -- Pacific trading date the previous close belongs to (see market_board.settle).
    quote_time REAL,
    fetched_at REAL NOT NULL
) STRICT;

CREATE TABLE watchlist (
    member_id TEXT NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    ticker TEXT NOT NULL CHECK(length(ticker) BETWEEN 1 AND 16),
    added_at REAL NOT NULL,
    PRIMARY KEY (member_id, ticker)
) STRICT;

-- The bot's own #alerts posts with their later prices, copied from the bot database by the supervisor.
CREATE TABLE track_alerts (
    alert_id INTEGER PRIMARY KEY,
    ticker TEXT NOT NULL CHECK(length(ticker) BETWEEN 1 AND 16),
    alerted_at REAL NOT NULL,
    price REAL NOT NULL,
    price_1h REAL,
    price_24h REAL,
    price_5d REAL
) STRICT;
CREATE INDEX track_alerts_time ON track_alerts(alerted_at);

-- SPY daily closes (one Schwab call a day) for the track record's "versus the market" line.
CREATE TABLE index_daily (
    symbol TEXT NOT NULL,
    day TEXT NOT NULL CHECK(length(day)=10),
    close REAL NOT NULL,
    fetched_at REAL NOT NULL,
    PRIMARY KEY (symbol, day)
) STRICT;
