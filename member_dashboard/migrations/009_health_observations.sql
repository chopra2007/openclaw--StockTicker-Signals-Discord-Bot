CREATE TABLE health_observations (
    component TEXT PRIMARY KEY CHECK(component IN ('supervisor','compute')),
    instance_id TEXT NOT NULL,
    observed_at REAL NOT NULL,
    progress_at REAL,
    state TEXT NOT NULL CHECK(state IN ('idle','busy','draining','blocked'))
) STRICT;
