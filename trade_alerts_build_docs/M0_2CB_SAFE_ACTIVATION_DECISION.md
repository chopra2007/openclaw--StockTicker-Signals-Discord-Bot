# M0.2CB off-by-default cleanup decision

## Decision

The measured M0.2CA result supports building the narrow cleanup action defined
by `M0_2A_STORAGE_CONTRACT.md`. It does **not** support turning cleanup on now.
The next step may add an off-by-default action that removes only records already
approved by the existing dry-run retention plan. Dry run remains the default.

This is a capacity and engineering decision only. It does not qualify a market
source, prove historical completeness, open Strategies #5 through #8, prove a
trading result, send an alert or enable any live switch.

## Evidence used

The owner-reopened measurement covered all 390 saved source files and 3,721,860
option rows. It verified unchanged source identities and exact source-to-compact
record equality. Scratch space peaked at 2,647,519,232 bytes against the
4,500,000,000-byte bound. Peak memory was 428,077,056 bytes against the
1,500,000,000-byte bound. Compaction took 888.3310328269145 seconds against the
owner-authorized 1,800-second limit. The run ended with 21,185,400,832 local
bytes free, above the 12,046,114,407-byte reserve.

M0.2CA's fresh protected proof passed both complete collector and storage test
files, the broader affected area and two fresh repeatability processes. The
independent review passed. The historical M0.2C blocked admission and every
earlier stopped or rejected attempt remain unchanged.

## Exact boundary for the next implementation

M0.2CC may implement only the off-by-default removal action. It must:

1. use the existing `plan_retention` result without widening its record classes;
2. keep dry run as the default and require the cleanup switch explicitly;
3. remove only eligible minute option parts, verified duplicate temporary files
   and expired zero-byte notification markers;
4. recheck the configured root, legal holds, current source identities,
   complete-set proof, ages and file identity immediately before each removal;
5. refuse symlinks, path escapes, changed files, incomplete dates, missing or
   invalid proof, unknown state and any class 1 or class 2 record;
6. write a durable per-file result and stop safely on the first mismatch or
   removal error; and
7. leave compaction, collection, cleanup and every live switch off in checked-in
   configuration.

No owner file may be removed while building or testing M0.2CC. Protected tests
must use temporary synthetic files. A later activation needs fresh protected
proof and independent review of M0.2CC; this decision is not that activation.

## Remaining gates

Original availability, corrections and finality, point-in-time membership,
historical borrow, complete-chain source proof, source qualification, held-out
validation, promotion, alerts and live use remain separate open gates. Rules
that depend on missing fields remain off and labelled untested under D-104.
