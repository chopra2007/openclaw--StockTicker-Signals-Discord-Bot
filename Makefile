.PHONY: sync-models check-models test install-hooks test-baseline

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

test-baseline:
	# regenerate .test-baseline — the known-failing list the pre-push gate uses
	python3 -m pytest tests/ -q --tb=no -p no:cacheprovider | grep -E '^(FAILED|ERROR) ' | sed -E 's/^(FAILED|ERROR) //; s/ - .*$$//' | sort -u > .test-baseline
	@echo "wrote .test-baseline ($$(grep -c '^' .test-baseline) known-failing tests)"
