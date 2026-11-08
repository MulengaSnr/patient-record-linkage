"""Load one generated dataset into the warehouse and apply the quality gate.

Run from the project root (with the database up):

    uv run python -m patient_linkage.warehouse.pipeline --population pilot --level low

Exits with an error if the gate fails, so an orchestrator stops at this step.
A failed run keeps its check results but none of its data.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Any

import pandera.errors as pa_errors
import psycopg

from patient_linkage.config import PROJECT_ROOT, load_config
from patient_linkage.warehouse.load import (
    apply_schema,
    connect,
    file_checksum,
    file_schema,
    frame_checksum,
    load_source,
    read_source,
    standardise,
)
from patient_linkage.warehouse.quality import (
    CheckResult,
    DataQualityError,
    check_source,
    enforce,
    record_results,
)

logger = logging.getLogger(__name__)


def check_previous_day_loaded(
    conn: psycopg.Connection, dataset: str, batch_day: int
) -> None:
    """Refuse a day whose previous day has not been loaded.

    Args:
        conn: Open connection.
        dataset: Dataset label.
        batch_day: The day about to be loaded.

    Raises:
        DataQualityError: If day ``batch_day - 1`` has no records.
    """
    if batch_day <= 1:
        return
    previous = conn.execute(
        "SELECT 1 FROM raw.records WHERE dataset = %s AND batch_day = %s LIMIT 1",
        (dataset, str(batch_day - 1)),
    ).fetchone()
    if previous is None:
        raise DataQualityError(
            f"{dataset}: day {batch_day - 1} is not loaded, so day {batch_day} "
            "cannot be loaded yet"
        )


def run(
    conn: psycopg.Connection,
    dataset: str,
    folder: Path,
    config: dict[str, Any],
    batch_day: int | None = None,
) -> list[CheckResult]:
    """Validate, load, standardise and check every source in a folder.

    Args:
        conn: Open connection.
        dataset: Dataset label, for example ``pilot/low``.
        folder: Folder holding one CSV per source.
        config: Parsed configuration.
        batch_day: If given, load and judge only this day's records.

    Returns:
        All check results.

    Raises:
        DataQualityError: If a file has the wrong shape or a check fails.
    """
    sources = config["linkage_data"]["sources"]
    apply_schema(conn)
    conn.commit()
    if batch_day is not None:
        check_previous_day_loaded(conn, dataset, batch_day)
    frames = {}
    for name, source in sources.items():
        path = folder / f"{name}.csv"
        frame = read_source(path)
        try:
            file_schema(source).validate(frame, lazy=True)
        except pa_errors.SchemaErrors as error:
            cases = error.failure_cases.head().to_dict()
            raise DataQualityError(
                f"{name}: file failed validation: {cases}"
            ) from error
        if batch_day is None:
            frames[name] = (frame, file_checksum(path))
        else:
            day = frame[frame["batch_day"].astype(int) == batch_day]
            frames[name] = (day, frame_checksum(day))

    results: list[CheckResult] = []
    for name, (frame, checksum) in frames.items():
        inserted = load_source(conn, dataset, name, frame, checksum)
        written = standardise(conn, dataset, name, sources[name]["pg_date_format"])
        logger.info("%s: %d new raw rows, %d staged", name, inserted, written)
        results += check_source(
            conn, dataset, name, sources[name]["fields"], config["quality"], batch_day
        )
    if any(result.status == "FAIL" for result in results):
        # Keep the evidence but none of the data, or a corrected file with the
        # same record IDs could never replace the bad rows.
        conn.rollback()
    record_results(conn, dataset, results, batch_day)
    conn.commit()
    enforce(results)
    return results


def main() -> None:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--population", required=True)
    parser.add_argument("--level", required=True)
    parser.add_argument("--label", help="dataset label; default is population/level")
    parser.add_argument("--batch-day", type=int, help="load only this day's records")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    config = load_config()
    dataset = args.label or f"{args.population}/{args.level}"
    folder = (
        PROJECT_ROOT
        / config["paths"]["processed"]
        / "sources"
        / args.population
        / args.level
    )
    with connect() as conn:
        try:
            results = run(conn, dataset, folder, config, args.batch_day)
        except DataQualityError as error:
            logger.error("%s", error)
            sys.exit(1)
    for result in results:
        if result.status != "OK":
            logger.warning(
                "%s %s.%s = %.4f",
                result.status,
                result.source,
                result.check_name,
                result.value,
            )
    counts = {s: sum(r.status == s for r in results) for s in ("OK", "WARN", "FAIL")}
    logger.info("%s passed the gate: %s", dataset, counts)


if __name__ == "__main__":
    main()
