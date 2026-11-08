"""Daily patient linkage: load one day's records, check them, then link.

Each run handles one simulated day. The data-quality gate stops a bad batch
before it can reach linkage. One failed run pauses the DAG, so no later day
starts until the problem is fixed, and the loader separately refuses a day whose
previous day is not loaded. ``depends_on_past`` is deliberately not used: a later
run waiting on a failed day holds the only run slot, which deadlocks recovery.

Tasks run the project's own commands from its separate virtual environment,
which keeps Airflow's dependencies and Splink's apart.
"""

from __future__ import annotations

import datetime as dt
import os

from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import DAG

START = dt.datetime(2026, 10, 1, tzinfo=dt.UTC)
BATCH_DAYS = 30

POPULATION = os.environ.get("LINKAGE_POPULATION", "pilot")
LEVEL = os.environ.get("LINKAGE_LEVEL", "medium")
LABEL = os.environ.get("LINKAGE_LABEL", f"{POPULATION}/{LEVEL}-daily")
RESULTS = os.environ.get(
    "LINKAGE_RESULTS",
    "data/processed/linkage/pilot-medium__pilot-medium.json",
)

DAY = "{{ (logical_date - dag.start_date).days + 1 }}"
RUN = "cd /opt/linkage && .venv/bin/python -m patient_linkage"

with DAG(
    dag_id="patient_linkage_daily",
    description="Load, check and link one day of patient records",
    start_date=START,
    end_date=START + dt.timedelta(days=BATCH_DAYS - 1),
    schedule="@daily",
    catchup=True,
    max_active_runs=1,
    is_paused_upon_creation=True,
    max_consecutive_failed_dag_runs=1,
    tags=["linkage"],
) as dag:
    # No retry: bad data stays bad until someone looks at it.
    load_and_check = BashOperator(
        task_id="load_and_check",
        retries=0,
        bash_command=(
            f"{RUN}.warehouse.pipeline --population {POPULATION} --level {LEVEL} "
            f"--label {LABEL} --batch-day {DAY}"
        ),
    )
    link_and_publish = BashOperator(
        task_id="link_and_publish",
        retries=1,
        retry_delay=dt.timedelta(seconds=30),
        bash_command=(
            f"{RUN}.linkage.publish --dataset {LABEL} --results {RESULTS} "
            f"--through-day {DAY}"
        ),
    )
    load_and_check >> link_and_publish
