.PHONY: sync-models check-models test

sync-models:
	# run as openclaw: `openclaw config patch` writes openclaw.json as the
	# calling user, and the gateway needs it openclaw:openclaw-owned.
	sudo -u openclaw python3 scripts/sync_gateway_models.py

check-models:
	python3 scripts/sync_gateway_models.py --check

test:
	python3 -m pytest tests/ -v
