-- A probe waiter is not the owner of the actual operation or its circuit state.
CREATE TABLE provider_probes (
    provider TEXT PRIMARY KEY REFERENCES provider_circuits(provider) ON DELETE CASCADE,
    call_id TEXT NOT NULL UNIQUE,
    worker_id TEXT NOT NULL,
    started_at REAL NOT NULL
) STRICT;
