ALTER TABLE assistant_runs ADD COLUMN input_message_id TEXT;
ALTER TABLE messages ADD COLUMN source_observed_at REAL;
ALTER TABLE assistant_runs ADD COLUMN ticker_context TEXT;
ALTER TABLE assistant_runs ADD COLUMN conversation_version INTEGER;
ALTER TABLE assistant_runs ADD COLUMN feature_mask TEXT;
ALTER TABLE assistant_runs ADD COLUMN worker_id TEXT;
ALTER TABLE assistant_runs ADD COLUMN lease_token TEXT;
ALTER TABLE assistant_runs ADD COLUMN lease_until REAL;
ALTER TABLE assistant_runs ADD COLUMN deadline REAL;
ALTER TABLE assistant_runs ADD COLUMN current_call_id TEXT;
ALTER TABLE assistant_runs ADD COLUMN response_message_id TEXT;
ALTER TABLE assistant_runs ADD COLUMN transport_fingerprint TEXT;
ALTER TABLE assistant_runs ADD COLUMN model_id TEXT;
ALTER TABLE assistant_runs ADD COLUMN actual_input_tokens INTEGER;
ALTER TABLE assistant_runs ADD COLUMN actual_output_tokens INTEGER;
ALTER TABLE assistant_runs ADD COLUMN cost REAL;
CREATE TABLE assistant_turns (
    run_id TEXT NOT NULL REFERENCES assistant_runs(id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL,
    call_id TEXT NOT NULL UNIQUE,
    input_bound INTEGER NOT NULL,
    output_bound INTEGER NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('prepared','completed','failed','uncertain')),
    actual_input_tokens INTEGER,
    actual_output_tokens INTEGER,
    created_at REAL NOT NULL,
    PRIMARY KEY(run_id,ordinal)
) STRICT;
