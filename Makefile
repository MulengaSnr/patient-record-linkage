-include .env
export

.PHONY: setup lint format test check sources db-up db-down warehouse linkage

setup:   ## Create the virtual environment and install dependencies
	uv sync

lint:    ## Static checks (PEP 8, imports, docstrings, common bugs)
	uv run ruff check .
	uv run ruff format --check .

format:  ## Auto-fix formatting and safe lint issues
	uv run ruff format .
	uv run ruff check --fix .

test:    ## Run the test suite with coverage
	uv run pytest --cov=src --cov-report=term-missing

check: lint test  ## Everything CI runs

sources: ## Build source systems and truth from Synthea (POP=pilot|train|tune|test)
	uv run python -m patient_linkage.data.generate --population $(or $(POP),pilot)

db-up:   ## Start the local PostgreSQL warehouse and wait until it is ready
	docker compose up -d --wait

db-down: ## Stop the warehouse (data is kept)
	docker compose down

warehouse: ## Load sources and apply the quality gate (POP=pilot LEVEL=low)
	uv run python -m patient_linkage.warehouse.pipeline --population $(or $(POP),pilot) --level $(or $(LEVEL),low)

linkage: ## Train and evaluate linkage (TRAIN=pilot/medium EVAL=pilot/medium)
	uv run python -m patient_linkage.linkage.run --train $(or $(TRAIN),pilot/medium) --evaluate $(or $(EVAL),pilot/medium)
