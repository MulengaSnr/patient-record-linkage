"""Build the reporting views and export them as CSV files for the dashboard.

The dashboard reads exported files rather than the warehouse, so it can run
without the database (decision D18).

    uv run python -m patient_linkage.warehouse.marts --dataset pilot/medium-daily
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
from pathlib import Path

import psycopg
from psycopg import sql

from patient_linkage.config import PROJECT_ROOT, load_config
from patient_linkage.warehouse.load import SQL_DIR, apply_schema, connect

logger = logging.getLogger(__name__)

# View name and the columns that give each export a stable row order.
MARTS = {
    "fact_records": ("record_id",),
    "dim_people": ("person_key",),
    "dq_checks": ("batch_day", "attempt", "source", "check_name"),
    "run_history": ("run_number",),
    "review_queue": ("left_id", "right_id"),
}
METHODS = ("splink", "baseline")
RESULT_METRICS = (
    "precision",
    "recall",
    "f1",
    "split_rate",
    "false_merge_rate",
    "people",
    "actual_pairs",
)
# Lets charts show levels in this order rather than alphabetically.
LEVEL_ORDER = {"low": 1, "medium": 2, "high": 3}
DEFAULT_OUTPUT = PROJECT_ROOT / "app" / "data"


def apply_marts(conn: psycopg.Connection) -> None:
    """Rebuild the ``mart`` schema from ``sql/marts.sql``."""
    apply_schema(conn)
    conn.execute((SQL_DIR / "marts.sql").read_text())


def export_mart(conn: psycopg.Connection, name: str, dataset: str, output: Path) -> int:
    """Write one dataset's rows from one view to ``<output>/<name>.csv``.

    Args:
        conn: Open connection.
        name: A key of ``MARTS``.
        dataset: Dataset label.
        output: Folder to write to.

    Returns:
        The number of data rows written.
    """
    statement = sql.SQL(
        "COPY (SELECT * FROM {view} WHERE dataset = {dataset} ORDER BY {order}) "
        "TO STDOUT WITH (FORMAT csv, HEADER)"
    ).format(
        view=sql.Identifier("mart", name),
        dataset=sql.Literal(dataset),
        order=sql.SQL(", ").join(map(sql.Identifier, MARTS[name])),
    )
    path = output / f"{name}.csv"
    with (
        path.open("wb") as handle,
        conn.cursor() as cursor,
        cursor.copy(statement) as copy,
    ):
        for chunk in copy:
            handle.write(chunk)
    with path.open(encoding="utf-8", newline="") as handle:
        return sum(1 for _ in csv.reader(handle)) - 1


def read_results(folder: Path) -> tuple[list[dict], list[dict]]:
    """Flatten the final test-population results into two tables.

    Only ``train-*__test-*.json`` files are read, so the figures match the
    published results. They are aggregate scores, with no row-level data.

    Args:
        folder: Folder of linkage result files.

    Returns:
        Overall metrics per level and method, and the share of records still
        linked for each kind of injected error.

    Raises:
        FileNotFoundError: If there are no final result files.
    """
    paths = sorted(folder.glob("train-*__test-*.json"))
    if not paths:
        raise FileNotFoundError(f"No final linkage results in {folder}")
    overall: list[dict] = []
    by_error: list[dict] = []
    for path in paths:
        outcome = json.loads(path.read_text())
        level = outcome["evaluate_dataset"].split("/")[1]
        for method in METHODS:
            metrics = outcome[method]
            common = {
                "error_level": level,
                "level_order": LEVEL_ORDER[level],
                "method": method.title(),
            }
            overall.append(
                {
                    **common,
                    "threshold": outcome["threshold"],
                    **{name: metrics[name] for name in RESULT_METRICS},
                }
            )
            by_error += [
                {
                    **common,
                    "injected_error": error,
                    "records": detail["records"],
                    "linked_share": detail["linked_share"],
                }
                for error, detail in sorted(metrics["recall_by_error"].items())
            ]
    return overall, by_error


def write_rows(path: Path, rows: list[dict]) -> None:
    """Write dictionaries with identical keys to a CSV file."""
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def export(
    conn: psycopg.Connection, dataset: str, results: Path, output: Path
) -> dict[str, int]:
    """Rebuild the views and write every file the report needs.

    Args:
        conn: Open connection.
        dataset: Dataset label.
        results: Folder of linkage result files.
        output: Folder to write to, created if needed.

    Returns:
        Rows written per file.

    Raises:
        ValueError: If the dataset has no records, so no file is overwritten
            with an empty one.
    """
    apply_marts(conn)
    conn.commit()
    found = conn.execute(
        "SELECT count(*) FROM mart.fact_records WHERE dataset = %s", (dataset,)
    ).fetchone()[0]
    if not found:
        raise ValueError(f"No records for dataset {dataset!r}")
    overall, by_error = read_results(results)

    output.mkdir(parents=True, exist_ok=True)
    written = {name: export_mart(conn, name, dataset, output) for name in MARTS}
    write_rows(output / "linkage_results.csv", overall)
    write_rows(output / "recall_by_error.csv", by_error)
    return written | {"linkage_results": len(overall), "recall_by_error": len(by_error)}


def main() -> None:
    """Command-line entry point."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dataset", default="pilot/medium-daily")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    results = PROJECT_ROOT / load_config()["paths"]["processed"] / "linkage"
    with connect() as conn:
        written = export(conn, args.dataset, results, args.output)
    logger.info("%s exported to %s: %s", args.dataset, args.output, written)


if __name__ == "__main__":
    main()
