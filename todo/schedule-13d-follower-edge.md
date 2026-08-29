# Test whether public Schedule 13D filings lead to profitable share trades

**Status:** DONE
**Created:** 2026-08-29

**CURRENT STATUS (2026-08-29):** **NOT TESTABLE.** The all-symbol price file is
real, but the machine lacks point-in-time common-share and listing history,
complete company-action and delisting outcomes, and full-universe executable
opening evidence. No returns were calculated, no sealed data was opened, and
nothing was built or turned on.

## Goal

Test whether buying a liquid common stock at the first eligible market opening
after an initial Schedule 13D filing becomes public earns an after-cost profit
over five complete market sessions. Build an owner-only Discord setup card only
if every locked data, profit, risk, timing, and independent-review check passes.

No brokerage order may be placed, previewed, staged, or automated. No data may
be bought during this run.

## Source plan

`.omc/plans/schedule-13d-owner-only-share-feature-prompt.md`

## Work location

`.omc/research/schedule-13d-follower-edge/`

## Required ending

One of these three outcomes must be proved:

- The historical rule passed and the owner-only share feature is on.
- The after-publication rule failed its locked checks.
- The test cannot be trusted because point-in-time filing, security, corporate-action, or executable-price history is incomplete.
