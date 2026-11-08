"""Score a clustering against the truth table.

This is the only part of the linkage code allowed to read the truth table, and
nothing it produces feeds back into training.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pandas as pd

GROUPS = ("sex", "age_band", "race", "ethnicity")
MIN_GROUP_PEOPLE = 50


def read_truth(path: Path | str) -> pd.DataFrame:
    """Read a truth table.

    Args:
        path: Location of ``truth.csv``.

    Returns:
        One row per record, with ``errors`` as text and never missing.
    """
    truth = pd.read_csv(path, dtype=str, keep_default_na=False)
    return truth.rename(columns={"record_id": "unique_id"})


def _pairs(sizes: pd.Series) -> int:
    return int((sizes * (sizes - 1) // 2).sum())


def _joined(clusters: pd.DataFrame, truth: pd.DataFrame) -> pd.DataFrame:
    """Clusters with each record's true person; every record must match."""
    joined = clusters.merge(truth, on="unique_id", how="outer", indicator=True)
    if not (joined["_merge"] == "both").all():
        raise ValueError("Clusters and truth do not cover the same records")
    return joined.drop(columns="_merge")


def pairwise_metrics(clusters: pd.DataFrame, truth: pd.DataFrame) -> dict[str, float]:
    """Precision, recall and F1 over all pairs of records.

    Args:
        clusters: ``unique_id`` and ``cluster_id``.
        truth: Output of ``read_truth``.

    Returns:
        Pair counts and metrics. Precision is 1 when no pairs are predicted.
    """
    joined = _joined(clusters, truth)
    correct = _pairs(joined.groupby(["cluster_id", "person_id"]).size())
    predicted = _pairs(joined.groupby("cluster_id").size())
    actual = _pairs(joined.groupby("person_id").size())
    precision = correct / predicted if predicted else 1.0
    recall = correct / actual if actual else 1.0
    total = precision + recall
    return {
        "true_positive_pairs": correct,
        "predicted_pairs": predicted,
        "actual_pairs": actual,
        "precision": precision,
        "recall": recall,
        "f1": 2 * precision * recall / total if total else 0.0,
    }


def person_outcomes(clusters: pd.DataFrame, truth: pd.DataFrame) -> pd.DataFrame:
    """Whether each person was split across clusters or merged with someone else.

    Args:
        clusters: ``unique_id`` and ``cluster_id``.
        truth: Output of ``read_truth``.

    Returns:
        One row per person: their record count, ``split``, ``merged`` and the
        audit groups.
    """
    joined = _joined(clusters, truth)
    people_in_cluster = joined.groupby("cluster_id")["person_id"].transform("nunique")
    summary = joined.assign(shared=people_in_cluster > 1).groupby("person_id")
    outcome = pd.DataFrame(
        {
            "records": summary.size(),
            "clusters": summary["cluster_id"].nunique(),
            "merged": summary["shared"].any(),
        }
    )
    outcome["split"] = outcome["clusters"] > 1
    return outcome.join(summary[list(GROUPS)].first())


def cluster_metrics(clusters: pd.DataFrame, truth: pd.DataFrame) -> dict[str, float]:
    """Person-level error rates, which pair counts can hide.

    Args:
        clusters: ``unique_id`` and ``cluster_id``.
        truth: Output of ``read_truth``.

    Returns:
        The share of people with several records who were split, and the share
        of all people placed in a cluster with someone else.
    """
    outcome = person_outcomes(clusters, truth)
    several = outcome[outcome["records"] > 1]
    return {
        "people": int(len(outcome)),
        "people_with_several_records": int(len(several)),
        "split_rate": float(several["split"].mean()) if len(several) else 0.0,
        "false_merge_rate": float(outcome["merged"].mean()),
    }


def group_metrics(
    clusters: pd.DataFrame, truth: pd.DataFrame, groups: Sequence[str] = GROUPS
) -> list[dict[str, Any]]:
    """Split and false-merge rates for each audit group.

    Args:
        clusters: ``unique_id`` and ``cluster_id``.
        truth: Output of ``read_truth``.
        groups: Audit attributes to report.

    Returns:
        One row per group value; ``small_group`` marks too few people to judge.
    """
    outcome = person_outcomes(clusters, truth)
    rows = []
    for attribute in groups:
        for value, members in outcome.groupby(attribute):
            several = members[members["records"] > 1]
            rows.append(
                {
                    "attribute": attribute,
                    "group": value,
                    "people": int(len(members)),
                    "split_rate": float(several["split"].mean())
                    if len(several)
                    else None,
                    "false_merge_rate": float(members["merged"].mean()),
                    "small_group": len(members) < MIN_GROUP_PEOPLE,
                }
            )
    return rows


def recall_by_error(
    clusters: pd.DataFrame, truth: pd.DataFrame
) -> dict[str, dict[str, float]]:
    """How often records carrying each error type still reached their person.

    Only records whose person has another record can be counted.

    Args:
        clusters: ``unique_id`` and ``cluster_id``.
        truth: Output of ``read_truth``.

    Returns:
        For each error type (and ``none``), the record count and linked share.
    """
    joined = _joined(clusters, truth)
    size = joined.groupby("person_id")["unique_id"].transform("size")
    together = joined.groupby(["person_id", "cluster_id"])["unique_id"].transform(
        "size"
    )
    linkable = joined.assign(linked=together > 1)[size > 1]
    errors = linkable["errors"].str.split(";").explode().replace("", "none")
    linked = linkable["linked"].reindex(errors.index)
    grouped = linked.groupby(errors)
    return {
        name: {"records": int(group.size), "linked_share": float(group.mean())}
        for name, group in grouped
    }


def pick_threshold(
    sweep: Sequence[dict[str, float]], target_precision: float
) -> float | None:
    """The lowest threshold reaching the target precision.

    A lower threshold links more records, so this gives the best recall that
    still meets the precision target.

    Args:
        sweep: Rows with ``threshold`` and ``precision``.
        target_precision: Minimum acceptable pairwise precision.

    Returns:
        The chosen threshold, or ``None`` if none reaches the target.
    """
    passing = [r["threshold"] for r in sweep if r["precision"] >= target_precision]
    return min(passing) if passing else None
