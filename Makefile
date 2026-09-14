.PHONY: setup build verify test lint format demo setup-tracking mlflow tracking-sync verify-tracking
setup: setup-tracking
	npm ci --ignore-scripts
	npm run build
build:
	npm run build
verify: lint
	npm run verify
test:
	npm run verify
lint:
	uv run --locked ruff check src bin tests examples agent/skills templates/project
	uv run --locked ruff format --check src bin tests examples agent/skills templates/project
	npm run format:check
format:
	uv run --locked ruff format src bin tests examples agent/skills templates/project
	npm run format
demo:
	python3 bin/godel.py demo
setup-tracking:
	uv sync --locked --extra tracking
mlflow:
	python3 bin/godel.py tracking serve
tracking-sync:
	python3 bin/godel.py tracking sync
verify-tracking:
	GODEL_TEST_MLFLOW=1 .venv/bin/python -m unittest discover -s tests -p 'test_tracking.py' -v
	GODEL_TEST_MLFLOW=1 .venv/bin/python -m unittest discover -s tests -p 'test_traces.py' -v
