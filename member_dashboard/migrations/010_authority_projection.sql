CREATE TABLE authority_projection (
    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
    revision INTEGER NOT NULL DEFAULT 0 CHECK(revision>=0),
    digest TEXT NOT NULL,
    source_withheld INTEGER NOT NULL DEFAULT 0 CHECK(source_withheld IN (0,1))
) STRICT;
INSERT INTO authority_projection(singleton,revision,digest) VALUES (1,0,'0000000000000000000000000000000000000000000000000000000000000000');
