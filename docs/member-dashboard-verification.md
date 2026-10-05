# Member dashboard verification

October 5, 2026, Pacific time. Local implementation and review are complete.
**Production is NOT READY. Nothing was deployed or enabled.**

## Source and review

The full verification used `49037c45392d19a56f8403b1a52160dde02368bd`.
Focused fixes ended at `83f98c085a8712d0a176d535f356bbc975c3c293`.
Hashes confirm that the bot and protected-test sources did not change between
those commits. Codex implemented the changes; Claude Code performed the final
independent branch review and approved the focused fixes with no new findings.

The full suites ran once. Failures were retained and followed by focused checks;
the later fixes are not presented as a second full-suite pass.

## Results

| Check | Result |
| --- | --- |
| Bot regression | 4,451 passed; 12 unchanged baseline failures; 10 unchanged skips |
| Dashboard backend | 688 cases passed across Windows and Linux, including exact coverage of all 14 Windows skips |
| New backend regression cases | Six passed independently on the final code |
| Protected contracts | 153 passed, with expected isolation denials and complete cleanup |
| Frontend | Lint, type checks and production build passed |
| Browser suite | Initial run: 23 passed, three failed; all three fixed and passed focused checks, plus new pending-report and access-refresh checks |
| Calculation compatibility | All 11 saved original bot outputs matched byte for byte |
| Rollback database compatibility | Previous release's database code reads its matching schema-9 backup and rejects schema 10; quarantine restore upgrades to schema 10 and keeps access closed |

The base collection contained 5,314 disjoint test IDs, with none missing or
duplicated. The final change added six backend cases and removed none. Twelve
missing-research-artifact failures remain tracked in [TODO #120](../TODO.md).
The baseline was not changed. Six private-loopback setup failures, one isolated
DNS failure and three partition-related import-order failures were preserved;
their exact focused rechecks passed without changing application code or tests.
The DNS recheck resolved a hostname only; it did not fetch the URL.

The 20-member browser load ran for 300.015 seconds against synthetic data:

- Feed eligibility to browser rendering: 199 samples, 95th percentile 15.122 seconds.
- API reads: 1,497 samples, 95th percentile 0.130 seconds.
- Queue observations: 165; at most one running job and two compute threads,
  with no queued executor work observed.
- No load-test failures. Synthetic research took 4.947–11.548 seconds;
  these are not real-provider latency measurements.

Python runtime and development lock audits reported zero known vulnerabilities.
The production frontend audit also reported zero. The full frontend audit retained
nine high-severity development-chain entries for `GHSA-vfj7-8cjw-p6xm` involving
`braces` 3.0.3. No advisory was suppressed and no dependency override was applied.
This remains a development-tool concern and a launch re-audit requirement.

## Launch limits

Both existing bot services remained active, their working directory and symlink
were correct, and no matching drift or AI-health failure appeared in the checked
log window. Existing live edits were preserved. Test services, processes and
listeners were stopped after verification.

The ending disk check showed 5.13 GiB available and 93% used. It fails the required
10 GiB and 15% free-space thresholds. No unrelated cleanup was performed.

Real provider display, derived-analysis, retention and model-use rights; positive
current authority; complete account/IP quotas; actual assistant access; production
identities, mounts, egress and process containment; authorized HTTPS; physical
deletion and backup operations; and the same-host bot-latency comparison remain
unverified. Real providers and positive permission mappings stay unconfigured and
closed. Synthetic tests do not establish these permissions or production readiness.

Follow [the deployment runbook](../deploy/member-dashboard/README.md) and
[TODO #121](../TODO.md) before activation. Owner approval of the concrete launch
result comes after those gates, not before the evidence exists.

Detailed commands, exact IDs, original failures, source hashes, browser traces,
load samples and reviews are retained privately under
`.superpowers/sdd/2026-10-05-member-dashboard/`. That directory is intentionally
not included in the public repository.
