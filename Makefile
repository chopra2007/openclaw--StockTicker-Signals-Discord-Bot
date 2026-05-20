.PHONY: sync-models check-models test install-hooks

sync-models:
	# run as openclaw: `openclaw config patch` writes openclaw.json as the
	# calling user, and the gateway needs it openclaw:openclaw-owned.
	sudo -u openclaw python3 scripts/sync_gateway_models.py

check-models:
	python3 scripts/sync_gateway_models.py --check

test:
	python3 -m pytest tests/ -v

install-hooks:
	# install the pre-push regression gate (see CLAUDE.md "Regression Gate")
	cp scripts/pre-push .git/hooks/pre-push
	chmod +x .git/hooks/pre-push
	@echo "installed .git/hooks/pre-push"
