"""Load one generated dataset into the warehouse and apply the quality gate.

Run from the project root (with the database up):

    uv run python -m patient_linkage.warehouse.pipeline --population pilot --level low

Exits with an error if the gate fails, so an orchestrator stops at this step.
Results are committed first, so a failed run still leaves its evidence.
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


def run(
    conn: psycopg.Connection,
    dataset: str,
    folder: Path,
    config: dict[str, Any],
) -> list[CheckResult]:
    """Validate, load, standardise and check every source in a folder.

    Args:
        conn: Open connection.
        dataset: Dataset label, for example ``pilot/low``.
        folder: Folder holding one CSV per source.
        config: Parsed configuration.

    Returns:
        All check results.

    Raises:
        DataQualityError: If a file has the wrong shape or a check fails.
    """
    sources = config["linkage_data"]["sources"]
    apply_schema(conn)
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
        frames[name] = (frame, file_checksum(path))

    results: list[CheckResult] = []
    for name, (frame, checksum) in frames.items():
        inserted = load_source(conn, dataset, name, frame, checksum)
        written = standardise(conn, dataset, name, sources[name]["pg_date_format"])
        logger.info("%s: %d new raw rows, %d staged", name, inserted, written)
        results += check_source(
            conn, dataset, name, sources[name]["fields"], config["quality"]
        )
    record_results(conn, dataset, results)
    conn.commit()
    enforce(results)
    return results


def main() -> None:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--population", required=True)
    parser.add_argument("--level", required=True)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    config = load_config()
    dataset = f"{args.population}/{args.level}"
    folder = (
        PROJECT_ROOT
        / config["paths"]["processed"]
        / "sources"
        / args.population
        / args.level
    )
    with connect() as conn:
        try:
            results = run(conn, dataset, folder, config)
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
