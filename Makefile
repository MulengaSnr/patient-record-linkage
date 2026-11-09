-include .env
export

.PHONY: setup lint format test check sources db-up db-down warehouse linkage publish spark marts airflow-up airflow-down airflow-resume

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

linkage: ## Train and evaluate linkage (TRAIN=pilot/medium EVAL=pilot/medium; for the one final test run add THRESHOLD=0.99 FINAL=1)
	uv run python -m patient_linkage.linkage.run --train $(or $(TRAIN),pilot/medium) --evaluate $(or $(EVAL),pilot/medium) $(if $(THRESHOLD),--threshold $(THRESHOLD)) $(if $(FINAL),--final)

publish: ## Assign stable person keys and fill the review queue (DATASET=pilot/medium)
	uv run python -m patient_linkage.linkage.publish --dataset $(or $(DATASET),pilot/medium) --results data/processed/linkage/$(subst /,-,$(or $(DATASET),pilot/medium))__$(subst /,-,$(or $(DATASET),pilot/medium)).json $(if $(DAY),--through-day $(DAY))

spark: ## Standardise with PySpark and compare with the warehouse (POP=pilot LEVEL=low; needs Java 17 or 21)
	uv run python -m patient_linkage.spark.standardise --population $(or $(POP),pilot) --level $(or $(LEVEL),low) --compare

marts: ## Rebuild the reporting views and export them for Power BI (DATASET=pilot/medium-daily)
	uv run python -m patient_linkage.warehouse.marts --dataset $(or $(DATASET),pilot/medium-daily)

airflow-up: ## Start Airflow on http://127.0.0.1:8080 (about 1 GB of memory)
	docker compose --profile airflow up -d --build airflow

airflow-down: ## Stop Airflow
	docker compose --profile airflow stop airflow

airflow-resume: ## After fixing a failed day: clear it and restart (DAY=2026-10-12)
	docker compose --profile airflow exec -T airflow airflow tasks clear patient_linkage_daily -s $(DAY) -e $(DAY) -y
	docker compose --profile airflow exec -T airflow airflow dags unpause patient_linkage_daily -y
