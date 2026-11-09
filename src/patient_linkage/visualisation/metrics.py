"""Load the exported marts and calculate the figures shown in the dashboard."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from patient_linkage.config import PROJECT_ROOT

DATA_DIR = PROJECT_ROOT / "app" / "data"
TABLES = (
    "fact_records",
    "dim_people",
    "dq_checks",
    "run_history",
    "review_queue",
    "linkage_results",
    "recall_by_error",
)
CHECK_LABELS = {
    "missing_first_name": "Missing first name",
    "missing_surname": "Missing surname",
    "missing_date_of_birth": "Missing date of birth",
    "missing_sex": "Missing sex",
    "missing_address": "Missing address",
    "missing_postcode": "Missing postcode",
    "nhs_invalid_share": "Invalid NHS number",
    "dob_unparseable_share": "Unreadable date of birth",
    "dob_in_future_share": "Date of birth in the future",
}


@dataclass(frozen=True)
class RunPosition:
    """Where linkage stood after one run."""

    records: int
    people: int
    records_per_person: float
    merged_so_far: int


def load_tables(folder: Path | str = DATA_DIR) -> dict[str, pd.DataFrame]:
    """Read every exported mart.

    Args:
        folder: Folder written by ``make marts``.

    Returns:
        One frame per mart, keyed by name.
    """
    return {name: pd.read_csv(Path(folder) / f"{name}.csv") for name in TABLES}


def position_after(runs: pd.DataFrame, run_number: int) -> RunPosition:
    """Summarise linkage as it stood after a given run.

    Args:
        runs: The ``run_history`` mart.
        run_number: The run to report on.

    Returns:
        Totals at that run, with merges counted up to and including it.
    """
    so_far = runs[runs["run_number"] <= run_number]
    latest = so_far.iloc[-1]
    return RunPosition(
        records=int(latest["records"]),
        people=int(latest["people"]),
        records_per_person=float(latest["records"] / latest["people"]),
        merged_so_far=int(so_far["merged"].sum()),
    )


def latest_shares(dq_checks: pd.DataFrame) -> pd.DataFrame:
    """Share-type checks from the attempt that was finally accepted for each day."""
    return dq_checks[
        (dq_checks["check_type"] == "Share") & (dq_checks["latest_attempt"] == "Yes")
    ]


def share_affected(dq_checks: pd.DataFrame, by: list[str]) -> pd.DataFrame:
    """Share of records affected, weighted by batch size.

    Averaging each batch's share would give small batches too much weight, so
    this adds up the affected records and divides by the total records.

    Args:
        dq_checks: The ``dq_checks`` mart.
        by: Columns to group by.

    Returns:
        The grouping columns plus ``affected``, ``records`` and ``share``.
    """
    totals = (
        latest_shares(dq_checks)
        .groupby(by, as_index=False)[["affected_records", "records_in_batch"]]
        .sum()
        .rename(columns={"affected_records": "affected", "records_in_batch": "records"})
    )
    return totals.assign(share=totals["affected"] / totals["records"])


def warning_count(dq_checks: pd.DataFrame) -> int:
    """Number of warnings on the attempts that were finally accepted."""
    return int((latest_shares(dq_checks)["status"] == "WARN").sum())


def stopped_loads(dq_checks: pd.DataFrame) -> pd.DataFrame:
    """Checks that failed, from every attempt, including those later corrected."""
    return dq_checks.loc[
        dq_checks["status"] == "FAIL",
        [
            "batch_day",
            "attempt",
            "source",
            "check_name",
            "affected_records",
            "records_in_batch",
        ],
    ]


def thresholds(dq_checks: pd.DataFrame, check_name: str) -> tuple[float, float]:
    """The warning and failure levels of one check.

    Args:
        dq_checks: The ``dq_checks`` mart.
        check_name: Name of the check.

    Returns:
        The warning level and the failure level.
    """
    row = dq_checks[dq_checks["check_name"] == check_name].iloc[0]
    return float(row["warn_at"]), float(row["fail_at"])
