"""Data-quality gate on the staging layer.

Each check produces a share of records with a problem, graded OK, WARN or FAIL
against thresholds in ``configs/default.yaml``. A single FAIL stops the run.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg import sql


class DataQualityError(RuntimeError):
    """Raised when data fails a check and the run must stop."""


@dataclass(frozen=True)
class CheckResult:
    """The outcome of one check on one source."""

    source: str
    check_name: str
    value: float
    warn_at: float | None
    fail_at: float | None
    status: str


def grade(value: float, warn_at: float, fail_at: float) -> str:
    """Grade a value where higher is worse.

    Args:
        value: The measured value.
        warn_at: Value at which the check warns.
        fail_at: Value at which the check fails.

    Returns:
        ``OK``, ``WARN`` or ``FAIL``.
    """
    if value >= fail_at:
        return "FAIL"
    return "WARN" if value >= warn_at else "OK"


def _downgrade_small(status: str, affected: float, minimum: int) -> str:
    """A FAIL needs enough affected records; one bad value in ten proves little."""
    return "WARN" if status == "FAIL" and affected < minimum else status


def _share(
    conn: psycopg.Connection,
    dataset: str,
    source: str,
    numerator: sql.Composable,
    batch_day: int | None,
) -> float:
    """Share of a source's staging records for which a condition holds."""
    query = sql.SQL(
        "SELECT coalesce(avg(({})::int)::float8, 0) FROM staging.records "
        "WHERE dataset = %s AND source = %s "
        "AND (%s::integer IS NULL OR batch_day = %s::integer)"
    ).format(numerator)
    return conn.execute(query, (dataset, source, batch_day, batch_day)).fetchone()[0]


def _graded(
    source: str,
    name: str,
    value: float,
    limits: dict[str, float],
    count: int,
    minimum: int,
) -> CheckResult:
    status = grade(value, limits["warn"], limits["fail"])
    return CheckResult(
        source,
        name,
        value,
        limits["warn"],
        limits["fail"],
        _downgrade_small(status, value * count, minimum),
    )


def check_source(
    conn: psycopg.Connection,
    dataset: str,
    source: str,
    fields: Iterable[str],
    thresholds: dict[str, Any],
    batch_day: int | None = None,
) -> list[CheckResult]:
    """Run every check on one source.

    Args:
        conn: Open connection.
        dataset: Dataset label.
        source: Source system name.
        fields: Fields this source holds; others are not checked for missingness.
        thresholds: The ``quality`` section of the configuration.
        batch_day: If given, judge only this day's records, so that one bad day
            cannot hide behind weeks of good data.

    Returns:
        One result per check.
    """
    count = conn.execute(
        "SELECT count(*) FROM staging.records WHERE dataset = %s AND source = %s "
        "AND (%s::integer IS NULL OR batch_day = %s::integer)",
        (dataset, source, batch_day, batch_day),
    ).fetchone()[0]
    minimum = thresholds["min_records"]
    results = [
        CheckResult(
            source,
            "record_count",
            float(count),
            None,
            float(minimum),
            "FAIL" if count < minimum else "OK",
        )
    ]

    available = set(fields)
    for field, limits in thresholds["missing_share"].items():
        if field in available:
            condition = sql.SQL("{} IS NULL").format(sql.Identifier(field))
            results.append(
                _graded(
                    source,
                    f"missing_{field}",
                    _share(conn, dataset, source, condition, batch_day),
                    limits,
                    count,
                    thresholds["min_affected_records"],
                )
            )

    conditions = {
        "dob_unparseable_share": "dob_unparseable",
        "dob_in_future_share": "date_of_birth IS NOT NULL "
        "AND date_of_birth > current_date",
        "nhs_invalid_share": "nhs_was_invalid",
    }
    for name, condition in conditions.items():
        value = _share(conn, dataset, source, sql.SQL(condition), batch_day)
        results.append(
            _graded(
                source,
                name,
                value,
                thresholds[name],
                count,
                thresholds["min_affected_records"],
            )
        )
    return results


def record_results(
    conn: psycopg.Connection,
    dataset: str,
    results: Iterable[CheckResult],
    batch_day: int | None = None,
) -> uuid.UUID:
    """Store results so a failed run leaves evidence behind.

    Args:
        conn: Open connection. The caller commits.
        dataset: Dataset label.
        results: The results to store.
        batch_day: The batch that was judged, if any.

    Returns:
        The identifier of this run.
    """
    run_id = uuid.uuid4()
    with conn.cursor() as cursor:
        cursor.executemany(
            """
            INSERT INTO dq.check_results
                (run_id, dataset, source, check_name, value, warn_at, fail_at,
                 status, batch_day)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            [
                (
                    run_id,
                    dataset,
                    r.source,
                    r.check_name,
                    r.value,
                    r.warn_at,
                    r.fail_at,
                    r.status,
                    batch_day,
                )
                for r in results
            ],
        )
    return run_id


def enforce(results: Iterable[CheckResult]) -> None:
    """Stop the run if any check failed.

    Args:
        results: The results to inspect.

    Raises:
        DataQualityError: If any result is ``FAIL``, naming each one.
    """
    failed = [r for r in results if r.status == "FAIL"]
    if failed:
        detail = "; ".join(
            f"{r.source}.{r.check_name}={r.value:.4f} (fail at {r.fail_at})"
            for r in failed
        )
        raise DataQualityError(f"Data-quality gate failed: {detail}")
