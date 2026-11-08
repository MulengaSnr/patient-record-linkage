"""Deterministic baseline that Splink has to beat.

Two records are linked if they agree exactly on every field of any rule, and
linked records are grouped transitively.
"""

from __future__ import annotations

from collections.abc import Sequence

import pandas as pd


class _DisjointSet:
    """Groups items, merging groups whenever two members are linked."""

    def __init__(self, items: Sequence[str]) -> None:
        self.parent = {item: item for item in items}

    def find(self, item: str) -> str:
        root = item
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[item] != root:
            self.parent[item], item = root, self.parent[item]
        return root

    def union(self, left: str, right: str) -> None:
        first, second = self.find(left), self.find(right)
        if first != second:
            self.parent[max(first, second)] = min(first, second)


def deterministic_clusters(
    records: pd.DataFrame, rules: Sequence[Sequence[str]]
) -> pd.DataFrame:
    """Cluster records using exact-match rules.

    A record missing any field of a rule cannot be linked by that rule.

    Args:
        records: Records with a ``unique_id`` column and the rule fields.
        rules: Each rule is a list of fields that must all agree.

    Returns:
        ``unique_id`` and ``cluster_id`` for every record.
    """
    groups = _DisjointSet(records["unique_id"].tolist())
    for rule in rules:
        usable = records.dropna(subset=list(rule))
        for _, members in usable.groupby(list(rule), sort=False)["unique_id"]:
            ids = members.tolist()
            for other in ids[1:]:
                groups.union(ids[0], other)
    return pd.DataFrame(
        {
            "unique_id": records["unique_id"],
            "cluster_id": [groups.find(i) for i in records["unique_id"]],
        }
    )
