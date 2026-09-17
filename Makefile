PYTHON ?= python3

.PHONY: help test test-fast test-cov test-docs docs docs-clean docs-serve lint fmt format verify clean

help:  ## Show this help message
	@awk 'BEGIN {FS = ":.*##"; printf "Usage: make \033[36m<target>\033[0m\n\nTargets:\n"} /^[a-zA-Z_-]+:.*?##/ { printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2 }' $(MAKEFILE_LIST)

test:  ## Run pytest suite (sin coverage, mas rapido)
	uv run pytest -q --no-cov

test-fast:  ## Solo tests rapidos (skip slow)
	uv run pytest -q --no-cov -m "not slow"

test-cov:  ## Run pytest con coverage (default del pyproject)
	uv run pytest -q

test-docs:  ## Ejecuta los bloques bash del README contra `capmd`
	uv run pytest tests/test_docs.py -v --no-cov

docs:  ## Build sphinx docs HTML
	cd docs && uv run sphinx-build . _build/html

docs-clean:  ## Wipe sphinx _build/
	rm -rf docs/_build

docs-serve:  ## Build + serve en localhost:8000
	make docs
	cd docs/_build/html && python3 -m http.server 8000

lint:  ## ruff check (lint)
	uv run ruff check src tests

fmt:  ## ruff format (auto-fix)
	uv run ruff format src tests

format: fmt  ## alias de fmt

verify:  ## smoke test del install + smoke test del PyPI publish
	bash scripts/verify-install.sh
	bash scripts/verify-pypi-install.sh 0.1.0 || true  # skip si sin red

clean: docs-clean  ## Clean all build artifacts
	find . -name '__pycache__' -type d -exec rm -rf {} +
	rm -rf .pytest_cache .ruff_cache .mypy_cache dist build htmlcov
