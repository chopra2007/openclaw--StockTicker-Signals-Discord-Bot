# Member dashboard launch package

**NOT READY for production.** These files are review templates. Every service has
an unconditional false start condition, and Python production composition rejects
unconfigured roles. Nothing in a configuration file can assert production readiness.
No unit, proxy, timer, account, certificate or provider has been installed.

The runnable composition is **synthetic staging only**. Its API owns a supervisor
and a Windows Job/Linux process-group compute child for convenient local tests.
That arrangement is not the production security boundary. The production API must
have only web state, no market mount, provider configuration, control socket or
privileged child-launch ability. The production supervisor, compute child, quota
broker and frontend require separate reviewed identities and filesystem views.

## Concrete remaining launch gates

- Recorded deployment disk was approximately 2.2 GiB free and 97% used. A fresh
  owner-approved capacity solution must meet 10 GiB and 15% disk free, 3 GiB
  available memory before startup, aggregate web resident memory <=2 GiB, and
  1 GiB remaining during load. Do not delete unrelated files to meet this gate.
- Independent final bot/web/frontend/browser suites and the 20-member five-minute
  browser load remain required. A short smoke is not acceptance. Same-host bot
  latency requires separate authorization and no sustained increase above 10%.
- Real display/derived/retention/model-use permissions, actual section coverage,
  complete intersecting provider quotas and a functioning restricted assistant
  remain unknown. A key, synthetic grant, HTTP success or public source is not proof.
- Existing authorized hostname/certificate, private service users, exact source
  DB/WAL/SHM mounts, provider egress proxy and dedicated compute cgroup/private PID
  namespace launcher need reviewed production integration and actual OS proof.
- Current-authority updater identity, denial coverage for every external trusted
  mutation path, positive grant reconciliation and source-specific deletion proof
  remain required. The local denial journal below is a conservative primitive;
  it does not grant access or prove legal/physical deletion compliance.
- Encrypted archive retention/size maintenance must be integrated into the actual
  deployment. No maintenance timer was installed. Expired backups cannot restore;
  automatic media erasure and 30-day physical removal are not yet proven.
- Owner approval of the concrete launch result is last, after these evidence
  gates. A separate host additionally needs a reviewed authenticated bounded
  export service. Never mount bot SQLite across hosts.

## Fixed interfaces

`python scripts/member_dashboard_probe.py --mode preflight --output ABSOLUTE_PATH`
writes a new private sanitized report and returns 2 for NOT READY. `verify` also
returns incomplete until real acceptance evidence exists. It only inspects the
local output volume; it does not infer deployment capacity or invoke migrations.
The existing output directory must be private. Unknown measurements stay null.

`python scripts/member_dashboard_load.py --base-url https://localhost:3443
--members 20 --duration-seconds 300 --manifest ABSOLUTE_MANIFEST
--output NEW_PRIVATE_REPORT --node ABSOLUTE_NODE` uses actual isolated browser
contexts. The wrapper validates the protected local manifest, exact loopback
origin, expiration, nonce and server certificate before traffic. Browser requests
also pass through the same certificate pin; redirects and other origins fail.
Synthetic accounts are created only in that fixture. No provider or Discord sends
are used. API reads, source eligibility/publication/render and provider completion
durations are separate. The fixture's data is explicitly synthetic.

Start staging with `MEMBER_LAUNCH=1` and the existing `e2e/serve.mjs` after the final
frontend build. The private run manifest is referenced by `.e2e/staging-current.json`.
Use the existing private Node/Python/browser paths in execution-environment.md.
The original browser suites retain their existing default fixture interface.

The frontend monitor polls exactly `127.0.0.1:3444/healthz` with a half-second
deadline every five seconds. Admin reads cached state only. Missing or 15-second
stale observations remain unavailable/stale; API health never implies frontend or
compute progress. No admin-supplied URL or process-control operation exists.

## Trusted exit and quota ordering

`ExitControlServer` is a separate Linux local socket. Only the configured distinct
supervisor UID may call `register(worker UUID, PID)` or `reconcile(worker UUID)`.
The broker derives boot/PID/start identity and a dedicated cgroup path/inode from
the kernel; the child must be gated alone and owned by the configured compute UID.
No client-supplied owner, cgroup, path or dead flag is accepted. The ordinary budget
socket still exposes only reserve/finish. When ExitRegistry is composed, dashboard
admission requires registration before the actual provider call.

Reconciliation independently checks exact process exit and that the still-existing
same cgroup is empty, including descendants. Missing/recreated cgroups fail closed.
Each call settles at most 100 quota rows, preserving units and marking uncertainty;
the supervisor retries while feed/heartbeat continue. Only after all batches finish
does it settle web calls/probes, recover leases, and replace the child. A missing
ledger or unknown previous owner never creates fresh capacity. Dedicated cgroup
creation/retention and socket ACLs are still production integration gates.

## Denial journal and backup/restore

`DenialJournal` stores at most 1,000 fixed denial records in a separate private
SQLite file. Its independent anchor holds the monotonic revision, hash-chain head,
issue time and <=300-second expiry. Both live outside web backups. Only a trusted
updater may append/renew; expiry, an older journal/anchor, chain mismatch or an
interrupted journal/anchor update blocks mutation/restore. Root ownership alone
is not accepted as freshness. Exhaustion fails closed pending reviewed compaction.

Configured admin suspension/session revocation/feature-off, member history deletion,
source denial and explicit retraction append durably **before** changing web state.
An append failure aborts the web transaction. A crash after append can over-deny,
which is deliberate. Reads never append. Synthetic staging composes this updater;
production mutation coverage and positive permission authority remain unconfigured.

`scripts/member_dashboard_backup.py backup` accepts explicit source/output,
quota-path, protected 32-byte key-file and Node executable paths. SQLite backup API
captures committed WAL state, with a 64 MiB/10-second snapshot bound. AES-256-GCM
encrypts and authenticates the archive with a <=30-day expiry; key bytes arrive on
stdin, never command-line/environment. Sources requiring special backup deletion
are rejected. Private temporary snapshots are removed, but this does not prove
physical media/WAL erasure.

`restore-closed` additionally requires the current external denial journal and
anchor. It restores into a fresh file, validates schema/integrity, applies current
denials, revokes all old sessions/invitations/resets, suspends old accounts, disables
features, closes runnable jobs and retains source-retraction withholding. This is
**quarantine**, not functioning restored access. A trusted positive-current-state
reconciliation is required before selective reactivation. The independent quota
ledger is never replaced; historical quota policy in a web snapshot is disabled.

Task 12 adds no web migration: web schema remains 9, matching the preceding reviewed
release. That is the format window, not proof that the previous executable has been
tested with every restored scenario. Previous-release rollback verification remains
part of the final acceptance record.

## Deployment and rollback order

1. Preserve a verified private backup of the current live dirty checkout; identify
   the service working directory and reconcile only reviewed shared-command edits.
   Never reset or overwrite the live repository. Build the web release separately.
2. Resolve every gate above, review exact users/mounts/TLS/proxy/cgroups, run actual
   sandbox and member flow checks, then seek final owner approval. Do not remove
   the false unit conditions merely because a synthetic check passes.
3. Use the aggregate slice (2 GiB, one CPU); one API process/four request threads,
   one compute child, bounded actual provider operations, and the independent broker.
   The frontend has no database/config mounts. The namespaced journal configuration
   caps stored logs at 10 MiB with rotation. Verify limits on the actual host.
4. On rollback stop/drain only web worker/API/frontend, restore the previous web
   release and compatible quarantined backup, reconcile current authority, and
   verify bot service/link/drift/config hash and shared-computation behavior.
   Retain quota while bot clients depend on it. Returning bot clients to legacy
   admission requires all dashboard work terminated and shared reservations settled.
   Revert only reviewed shared extraction changes, preserving unrelated live edits.
