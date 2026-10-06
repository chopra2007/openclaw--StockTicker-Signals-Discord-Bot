# Member dashboard launch package

**NOT READY for production.** These files are review templates. Every service has
an unconditional false start condition, and fixed Linux role composition rejects
unknown fields, paths or identities. Nothing in a configuration file can assert production readiness.
No unit, proxy, timer, account, certificate or provider has been installed.

The convenience browser composition is **synthetic staging only**. Its API owns a supervisor
and a Windows Job/Linux process-group compute child for convenient local tests.
That arrangement is not the production security boundary. The production API must
have only web state, no market mount, provider configuration, control socket or
privileged child-launch ability. The production supervisor, compute child, quota
broker and frontend require separate reviewed identities and filesystem views.

## Concrete remaining launch gates

- The ending local verification disk check still failed capacity; see the
  [verification record](../../docs/member-dashboard-verification.md). A fresh
  owner-approved capacity solution must meet 10 GiB and 15% disk free, 3 GiB
  available memory before startup, aggregate web resident memory <=2 GiB, and
  1 GiB remaining during load. Do not delete unrelated files to meet this gate.
- Independent local verification and the 20-member five-minute synthetic browser
  load are recorded in the verification record above, including focused fixes,
  baseline failures and the development-tool advisory. Actual deployment checks
  remain required. Same-host bot latency requires separate authorization and no
  sustained increase above 10%.
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
- The implemented encrypted archive retention/size maintenance still needs actual
  deployment integration. No maintenance timer was installed. Expired backups cannot restore;
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
supervisor UID may call `register(worker UUID, PID)`, `reconcile(worker UUID)` or
the bounded recovery inventory used during supervisor restart. Reconciled tombstones
remain in that inventory so a crash before the web commit cannot lose the handoff.
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
issue time and <=300-second expiry. A separate non-restored high-water checkpoint
must match the pair, including after restart; a matching older pair cannot renew.
All three live outside web backups. Only a trusted
updater may append/renew; expiry, an older journal/anchor, chain mismatch or an
interrupted journal/anchor update blocks mutation/restore. Root ownership alone
is not accepted as freshness. Exhaustion fails closed pending reviewed compaction.

Configured admin suspension/session revocation/feature-off, member history deletion,
source denial and explicit retraction append durably **before** changing web state.
An append failure aborts the web transaction. Schema 10 records the applied revision
and digest. Bound stores reconcile before and after every transaction, including
startup, so a committed denial survives a subsequent web rollback. Reads never append.
Synthetic staging composes this updater;
the Linux authority role now owns append/renew and an authenticated denial-only RPC.
External mutation coverage and positive permission authority remain unconfigured.

`scripts/member_dashboard_backup.py backup` accepts explicit source/output,
quota-path, protected 32-byte key-file and Node executable paths. SQLite backup API
captures committed WAL state, with a 64 MiB/10-second snapshot bound. AES-256-GCM
encrypts and authenticates the archive with a <=30-day expiry; key bytes arrive on
stdin, never command-line/environment. Sources requiring special backup deletion
are rejected from the actual consistent snapshot. Only `.mdb` archives are accepted;
an OS lock serializes capacity checks and publication across processes. Private
temporary snapshots are removed, but this does not prove
physical media/WAL erasure.

`restore-closed` additionally requires the current external denial journal and
anchor and independent checkpoint. It restores into a fresh file, validates schema/integrity, applies current
denials, revokes all old sessions/invitations/resets, suspends old accounts, disables
features, closes runnable jobs and retains source-retraction withholding. This is
**quarantine**, not functioning restored access. A trusted positive-current-state
reconciliation is required before selective reactivation. The independent quota
ledger is never replaced; historical quota policy in a web snapshot is disabled.

Task 12 adds schema 10 for the durable denial projection. The backup reader accepts
schema 9 or 10 and upgrades quarantine to 10. A schema 9 executable rejects schema
10; rollback must use its paired schema 9 backup and still enforce current authority
before serving. Previous-release rollback verification remains a final gate.

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


## Fixed Linux composition (disabled templates)

`python -m member_dashboard.operations ROLE --config ABSOLUTE_FILE` selects one
fixed role. The six JSON templates show the complete accepted fields. Placeholder
UID/GID strings deliberately fail validation. Config files are owned by their role,
private, and mounted read-only; ownership is not positive rights evidence. Socket
ACLs must grant connect access only, without write access to their owning directory.
No role accepts commands, plugin/module names, provider credentials or verified flags.

| Role | Owned access and concrete behavior |
| --- | --- |
| API | Web state, 32-byte signing key and denial RPC only. No source path, reader, compute launcher, control RPC or provider registry. Four request threads; fixed frontend observation. |
| Supervisor | Web state and exact read-only market DB/WAL/SHM mounts; bounded feed projection, cgroup launcher and exit RPC. No provider credentials. Source lineage/positive authority remains unavailable. |
| Compute | Distinct UID/GID in private PID namespace, gated before app/config import. Empty provider registry and no assistant transport while external evidence is absent; no quota/source secret access is inferred. |
| Quota | Separate retained quota DB, ordinary budget socket and supervisor-only control socket. Does not open web/journal/checkpoint. Startup preserves accounting but disables historical positive policy flags until current external account integration exists. |
| Authority | Journal/anchor and separate non-restored high-water file. Readers/writers are explicit peer UID sets. Only current-denial pages and denial append exist; no positive grants, paths or renewal request on wire. |
| Archive | Archive directory and protected key only; no live DB/journal/quota mounts. Authenticates expired candidates before removing at most two per run. |

The launcher uses only `/usr/bin/unshare --pid --fork --mount-proc`, the current
Python executable and the fixed compute module. Kernel SCM_CREDENTIALS supplies
the actual child PID/UID/GID after privilege drop. Before that handshake, compute
explicitly clears effective/permitted/inheritable/ambient capabilities, verifies all
four sets are zero and all real/effective/saved/filesystem IDs match, and requires
no_new_privs. This covers a nonroot supervisor with ambient capabilities as well as
root. Bounding-set ceilings are not held privileges; no extra SETPCAP capability is
added merely to erase those ceilings. The supervisor moves that gated
child into a UUID cgroup under its explicitly delegated service subtree, then the
independent broker verifies and registers it before admission. All descendants
inherit that group. Replacement first inventories pending broker owners and kills/
reconciles retained groups and carries the exact confirmed identities into durable
web call/probe/lease settlement before replacement. The broker retains its tombstones
if the supervisor crashes between broker and web commits; repeating the handoff is
idempotent. Absent or recreated evidence blocks. At most 32 worker
groups are retained. No automatic cgroup cleanup or broad host writes occur.

The exact delegated subtree must preexist and lie beneath the supervisor's current
service cgroup. The service manager must retain it through reconciliation/restart;
if it removes the subtree, recovery deliberately blocks. The template capability
and writable-subtree declarations still need actual host review. No system unit,
user, mount, ACL, egress rule or cgroup delegation was installed by this task.

Authority initialization is an explicit trusted provisioning operation using
CheckpointStore.create and DenialJournal.create; normal service startup never
recreates missing state. Renewal validates the entire chain against the independent
checkpoint, and fails on expiry/mismatch. A bounded OS lock serializes reads, append
and renewal through the complete journal/checkpoint/anchor publication, across
objects/processes. Only lock contention waits; unknown mismatches are never retried.
Malformed decoder recursion is contained to its RPC connection. The service must be running to maintain
its <=300-second continuity window. Lost/expired authority needs trusted recovery;
this code does not manufacture an external-current receipt. Denial continuity
cannot upgrade source/account/model rights. API and worker source policies remain
closed and compute providers unavailable until evidence-specific integration exists.

Archive creation rejects any source/payload retention deadline or special deletion
obligation in the actual snapshot. The hourly disabled maintenance template scans
at most 30 canonical archives/128 MiB, authenticates at most two expired candidates
per call, and fails closed on tampering. This proves logical expiry enforcement,
not physical disk/WAL/media erasure or licensed-source deletion compliance.
