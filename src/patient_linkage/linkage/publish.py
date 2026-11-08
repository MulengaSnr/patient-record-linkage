"""Publish a linkage run: stable person keys and a clerical review queue.

Run from the project root, using a model and threshold from an earlier run:

    uv run python -m patient_linkage.linkage.publish --dataset pilot/medium \
        --results data/processed/linkage/pilot-medium__pilot-medium.json

Everything is written in one transaction, so a failed run changes nothing.
Decisions recorded in the review queue are kept, but do not yet alter clusters.
"""

from __future__ import annotations

import argparse
import json
import logging
import uuid
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import psycopg

from patient_linkage.config import load_config
from patient_linkage.linkage import assign, model
from patient_linkage.linkage.records import read_records
from patient_linkage.warehouse.load import apply_schema, connect

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PublishSummary:
    """Headline figures for a published run."""

    run_id: uuid.UUID
    records: int
    people: int
    created: int
    merged: int
    split: int
    moved_records: int
    open_review_pairs: int


def _previous_keys(conn: psycopg.Connection, dataset: str) -> dict[str, str]:
    rows = conn.execute(
        "SELECT record_id, person_key FROM linked.record_people WHERE dataset = %s",
        (dataset,),
    )
    return dict(rows.fetchall())


def _next_number(conn: psycopg.Connection, dataset: str) -> int:
    latest = conn.execute(
        "SELECT max(substr(person_key, 2)::bigint) FROM linked.people "
        "WHERE dataset = %s",
        (dataset,),
    ).fetchone()[0]
    return 1 if latest is None else latest + 1


def _store_people(
    conn: psycopg.Connection,
    dataset: str,
    run_id: uuid.UUID,
    result: assign.KeyAssignment,
) -> None:
    new_keys = [
        event.person_key
        for event in result.events
        if event.event in {"created", "split"}
    ]
    with conn.cursor() as cursor:
        cursor.executemany(
            "INSERT INTO linked.people (dataset, person_key, created_run) "
            "VALUES (%s, %s, %s)",
            [(dataset, key, run_id) for key in new_keys],
        )
        cursor.executemany(
            "INSERT INTO linked.person_events "
            "(run_id, dataset, event, person_key, related_key) "
            "VALUES (%s, %s, %s, %s, %s)",
            [
                (run_id, dataset, e.event, e.person_key, e.related_key)
                for e in result.events
            ],
        )
    for event in result.events:
        if event.event != "merged":
            continue
        # Earlier merges into this key must follow it to its new home.
        conn.execute(
            "UPDATE linked.people SET merged_into = %s "
            "WHERE dataset = %s AND (person_key = %s OR merged_into = %s)",
            (event.related_key, dataset, event.person_key, event.person_key),
        )


def _store_records(
    conn: psycopg.Connection,
    dataset: str,
    run_id: uuid.UUID,
    records: pd.DataFrame,
    result: assign.KeyAssignment,
) -> None:
    conn.execute("DELETE FROM linked.record_people WHERE dataset = %s", (dataset,))
    with (
        conn.cursor() as cursor,
        cursor.copy(
            "COPY linked.record_people "
            "(dataset, record_id, source, person_key, run_id) FROM STDIN"
        ) as copy,
    ):
        for record, source in zip(records["unique_id"], records["source"], strict=True):
            copy.write_row(
                (dataset, record, source, result.record_keys[record], run_id)
            )


def _store_review(
    conn: psycopg.Connection,
    dataset: str,
    run_id: uuid.UUID,
    pairs: pd.DataFrame,
) -> int:
    """Refresh open pairs. A pair a person has already decided is never reopened."""
    conn.execute(
        "DELETE FROM linked.review_queue WHERE dataset = %s AND status = 'open'",
        (dataset,),
    )
    with conn.cursor() as cursor:
        cursor.executemany(
            """
            INSERT INTO linked.review_queue
                (dataset, left_id, right_id, match_probability, run_id)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (dataset, left_id, right_id) DO NOTHING
            """,
            [
                (dataset, left, right, float(probability), run_id)
                for left, right, probability in pairs.itertuples(index=False)
            ],
        )
    return conn.execute(
        "SELECT count(*) FROM linked.review_queue "
        "WHERE dataset = %s AND status = 'open'",
        (dataset,),
    ).fetchone()[0]


def publish(
    conn: psycopg.Connection,
    dataset: str,
    records: pd.DataFrame,
    clusters: pd.DataFrame,
    pairs: pd.DataFrame,
    threshold: float,
    review_lower: float,
) -> PublishSummary:
    """Write one run's person keys and review queue. The caller commits.

    Args:
        conn: Open connection.
        dataset: Dataset label.
        records: Records that were linked, with ``unique_id`` and ``source``.
        clusters: ``unique_id`` and ``cluster_id`` for every record.
        pairs: Scored pairs: IDs and ``match_probability``.
        threshold: The probability used to link records.
        review_lower: Lowest probability sent for review.

    Returns:
        A summary of what changed.
    """
    conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (dataset,))
    run_id = uuid.uuid4()
    result = assign.assign_keys(
        clusters, _previous_keys(conn, dataset), _next_number(conn, dataset)
    )
    conn.execute(
        "INSERT INTO linked.runs (run_id, dataset, threshold) VALUES (%s, %s, %s)",
        (run_id, dataset, threshold),
    )
    _store_people(conn, dataset, run_id, result)
    _store_records(conn, dataset, run_id, records, result)
    queue = assign.review_pairs(pairs, clusters, review_lower, threshold)
    open_pairs = _store_review(conn, dataset, run_id, queue)

    counts = Counter(event.event for event in result.events)
    summary = PublishSummary(
        run_id,
        len(records),
        len(set(result.record_keys.values())),
        counts["created"],
        counts["merged"],
        counts["split"],
        result.moved_records,
        open_pairs,
    )
    conn.execute(
        """
        UPDATE linked.runs SET records = %s, people = %s, created = %s, merged = %s,
            split = %s, moved_records = %s, open_review_pairs = %s
        WHERE run_id = %s
        """,
        (
            summary.records,
            summary.people,
            summary.created,
            summary.merged,
            summary.split,
            summary.moved_records,
            summary.open_review_pairs,
            run_id,
        ),
    )
    return summary


def link_and_publish(
    conn: psycopg.Connection,
    dataset: str,
    trained: dict[str, Any],
    threshold: float,
    settings: dict[str, Any],
    through_day: int | None = None,
) -> PublishSummary:
    """Score a dataset with a trained model and publish the result.

    Args:
        conn: Open connection. The caller commits.
        dataset: Dataset label.
        trained: A trained model.
        threshold: The probability used to link records.
        settings: The ``linkage`` section of the configuration.
        through_day: Only link records received up to this batch day.

    Returns:
        A summary of what changed.
    """
    apply_schema(conn)
    records = read_records(conn, dataset, through_day)
    linker, scored = model.score(records, trained, settings)
    clusters = model.cluster(linker, scored, threshold)
    pairs = scored.as_duckdbpyrelation().df()[
        ["unique_id_l", "unique_id_r", "match_probability"]
    ]
    return publish(
        conn,
        dataset,
        records,
        clusters,
        pairs,
        threshold,
        settings["review_lower_probability"],
    )


def main() -> None:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--results", required=True, type=Path)
    parser.add_argument("--through-day", type=int)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    outcome = json.loads(args.results.read_text())
    if outcome["threshold"] is None:
        raise SystemExit("That run did not choose a threshold, so nothing to publish")
    settings = load_config()["linkage"]
    with connect() as conn:
        summary = link_and_publish(
            conn,
            args.dataset,
            outcome["model"],
            outcome["threshold"],
            settings,
            args.through_day,
        )
    logger.info("%s: %s", args.dataset, summary)


if __name__ == "__main__":
    main()
