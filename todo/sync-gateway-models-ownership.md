# sync_gateway_models.py strips file ownership when run as root

**Status:** DONE 2026-05-22.
**Created:** 2026-05-22

**Layperson:** A helper script that syncs the LLM model chain to the gateway config breaks the gateway if you run it with sudo. The file ends up owned by root instead of openclaw, and the gateway (which runs as openclaw) can't read it and crashes with a misleading "missing gateway.mode" error.

**Reproduced 2026-05-15** during the TODO #5 fix (5-model chain rollout). Ran `python3 scripts/sync_gateway_models.py` — script implicitly required elevated perms — `/home/openclaw/.openclaw/openclaw.json` flipped from `openclaw:openclaw` to `root:root`. Gateway exit code 78/CONFIG. Manual `chown openclaw:openclaw` + restart restored service.

**Where:** `scripts/sync_gateway_models.py` — `_write_gateway_chain` shells out to `openclaw config patch`, which inherits the caller's UID and apparently rewrites the file fresh rather than in-place.

**Workaround in use:** run as `sudo -u openclaw python3 scripts/sync_gateway_models.py` instead of bare sudo. Verified ownership-preserving in the same session.

## Fix options
- (a) `os.chown(GATEWAY_JSON, openclaw_uid, openclaw_gid)` after `_write_gateway_chain` if the file is now root-owned.
- (b) Refuse to run if `os.geteuid() == 0` and `os.environ.get('SUDO_USER') != 'openclaw'`; print the `sudo -u openclaw` invocation.
- (c) Update the script's docstring (currently says `sudo python3 ...`) to say `sudo -u openclaw python3 ...`.

## Acceptance
Running the script the way the docstring instructs leaves `/home/openclaw/.openclaw/openclaw.json` owned by `openclaw:openclaw`; gateway restarts cleanly with no manual chown step.

**Bonus also worth fixing in the same PR:** the gateway's "missing gateway.mode" error is misleading when the real cause is EACCES — the read-failed banner appears first, then the schema check runs against an empty config. Either propagate the read error to the exit message, or skip the schema check when the file is unreadable.
