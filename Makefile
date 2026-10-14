UV ?= uv run
IMAGE_NAME := heimdall
IMAGE_TARGET ?= embeddings
IMAGE := $(IMAGE_NAME):$(IMAGE_TARGET)

PATHS := heimdall/ tests/
COV := --cov=heimdall
TESTS := tests/

.DEFAULT_GOAL := help

.PHONY: help sync lint format format-check type test test-cov check clean \
	build build-slim

help: ## Show available targets
	@grep -E '^[a-zA-Z0-9_-]+:.*?##' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

sync: ## Install deps (dev + embeddings, for local run)
	uv sync --group dev --group embeddings

lint: ## Run ruff lint
	$(UV) ruff check $(PATHS)

format: ## Apply ruff fixes and format
	$(UV) ruff check $(PATHS) --fix
	$(UV) ruff format $(PATHS)

format-check: ## Check ruff formatting (CI)
	$(UV) ruff format --check $(PATHS)

type: ## Run mypy
	$(UV) mypy heimdall

test: ## Run pytest
	$(UV) pytest $(TESTS)

test-cov: ## Pytest with coverage + junit.xml (CI defaults)
	$(UV) pytest $(TESTS) $(COV) --cov-report=term-missing \
		--cov-report=xml:coverage.xml --junitxml=junit.xml

check: lint format-check type test ## Full quality gate (matches CI minus actionlint)
	@:

clean: ## Remove caches and test artifacts
	rm -rf .pytest_cache .coverage coverage.xml junit.xml .mypy_cache .ruff_cache
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true

build: ## Build Docker image (default target: embeddings)
	docker compose build

build-slim: ## Build slim Docker image (no local embedder)
	HEIMDALL_IMAGE_TARGET=slim docker compose build
