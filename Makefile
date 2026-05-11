.PHONY: sync-models check-models test

sync-models:
	sudo python3 scripts/sync_gateway_models.py

check-models:
	python3 scripts/sync_gateway_models.py --check

test:
	python3 -m pytest tests/ -v
