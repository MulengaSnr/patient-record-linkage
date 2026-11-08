"""Give clusters stable person keys across linkage runs.

Splink's cluster IDs can change every run, but downstream users need an
identifier that does not. Each new cluster inherits the existing key it shares
the most records with. A key can go to only one cluster. Decisions are made
strictly in sorted order, so the same input always gives the same keys.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field

import pandas as pd


@dataclass(frozen=True)
class PersonEvent:
    """A change to the set of person keys."""

    event: str
    person_key: str
    related_key: str | None = None


@dataclass(frozen=True)
class KeyAssignment:
    """The outcome of assigning keys for one run."""

    record_keys: dict[str, str]
    events: list[PersonEvent] = field(default_factory=list)
    next_number: int = 1
    moved_records: int = 0


def format_key(number: int) -> str:
    """An opaque person key, carrying no information about the person."""
    return f"P{number:08d}"


def assign_keys(
    clusters: pd.DataFrame, previous: Mapping[str, str], next_number: int
) -> KeyAssignment:
    """Assign a person key to every record.

    Args:
        clusters: ``unique_id`` and ``cluster_id`` for every record.
        previous: Each already-assigned record's current key.
        next_number: The number to use for the next new key.

    Returns:
        The key for each record and the events that occurred.

    Raises:
        ValueError: If a previously assigned record is absent from ``clusters``.
    """
    known = set(clusters["unique_id"])
    missing = sorted(set(previous) - known)
    if missing:
        raise ValueError(
            f"{len(missing)} assigned records are missing from this run, "
            f"for example {missing[0]}"
        )

    members = {
        min(ids): sorted(ids)
        for ids in clusters.groupby("cluster_id")["unique_id"].agg(list)
    }
    overlaps = {
        cluster: Counter(previous[i] for i in ids if i in previous)
        for cluster, ids in members.items()
    }

    # Largest overlap first; ties go to the lowest key, then the lowest cluster.
    candidates = sorted(
        (-count, key, cluster)
        for cluster, counts in overlaps.items()
        for key, count in counts.items()
    )
    cluster_key: dict[str, str] = {}
    key_cluster: dict[str, str] = {}
    for _, key, cluster in candidates:
        if key not in key_cluster and cluster not in cluster_key:
            cluster_key[cluster] = key
            key_cluster[key] = cluster

    events: list[PersonEvent] = []
    number = next_number
    for cluster in sorted(members):
        if cluster in cluster_key:
            continue
        new_key = format_key(number)
        number += 1
        cluster_key[cluster] = new_key
        counts = overlaps[cluster]
        if counts:
            source = sorted(counts, key=lambda key: (-counts[key], key))[0]
            events.append(PersonEvent("split", new_key, source))
        else:
            events.append(PersonEvent("created", new_key))

    # A key that won no cluster has been absorbed by the cluster holding most of
    # its records.
    for key in sorted(set(previous.values()) - set(key_cluster)):
        holders = [
            (-counts[key], cluster)
            for cluster, counts in overlaps.items()
            if counts[key] > 0
        ]
        events.append(PersonEvent("merged", key, cluster_key[min(holders)[1]]))

    record_keys = {
        record: cluster_key[cluster]
        for cluster, ids in members.items()
        for record in ids
    }
    moved = sum(record_keys[r] != key for r, key in previous.items())
    return KeyAssignment(record_keys, events, number, moved)


def review_pairs(
    pairs: pd.DataFrame,
    clusters: pd.DataFrame,
    lower: float,
    threshold: float,
) -> pd.DataFrame:
    """Uncertain pairs that a person should look at.

    Args:
        pairs: ``unique_id_l``, ``unique_id_r`` and ``match_probability``.
        clusters: ``unique_id`` and ``cluster_id``.
        lower: Lowest probability worth reviewing.
        threshold: Probability at which pairs are linked automatically.

    Returns:
        Pairs in that range that ended up in different clusters, most likely
        matches first.
    """
    lookup = clusters.set_index("unique_id")["cluster_id"]
    band = pairs[
        (pairs["match_probability"] >= lower) & (pairs["match_probability"] < threshold)
    ]
    different = band["unique_id_l"].map(lookup) != band["unique_id_r"].map(lookup)
    return (
        band.loc[different, ["unique_id_l", "unique_id_r", "match_probability"]]
        .sort_values(
            ["match_probability", "unique_id_l", "unique_id_r"],
            ascending=[False, True, True],
        )
        .reset_index(drop=True)
    )
