.PHONY: setup lint format test check sources

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
