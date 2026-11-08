"""Check the DAG file loads and has the expected shape. Runs inside Airflow."""

from __future__ import annotations

import sys

from airflow.dag_processing.dagbag import DagBag


def main() -> None:
    """Exit non-zero if the DAG fails to import or its shape is wrong."""
    bag = DagBag(dag_folder=sys.argv[1])
    if bag.import_errors:
        sys.exit(f"Import errors: {bag.import_errors}")
    dag = bag.dags["patient_linkage_daily"]
    tasks = dag.task_dict
    problems = []
    if set(tasks) != {"load_and_check", "link_and_publish"}:
        problems.append(f"unexpected tasks: {sorted(tasks)}")
    elif tasks["link_and_publish"].upstream_task_ids != {"load_and_check"}:
        problems.append("linkage must run only after the quality gate")
    if tasks["load_and_check"].retries != 0:
        problems.append("a failed quality gate must not be retried")
    if dag.max_active_runs != 1:
        problems.append("days must not run at the same time")
    if dag.max_consecutive_failed_dag_runs != 1:
        problems.append("one failed day must pause the DAG")
    if any(task.depends_on_past for task in tasks.values()):
        problems.append("depends_on_past deadlocks recovery with one run slot")
    if problems:
        sys.exit("; ".join(problems))
    print(f"{dag.dag_id}: OK ({len(tasks)} tasks)")


if __name__ == "__main__":
    main()
