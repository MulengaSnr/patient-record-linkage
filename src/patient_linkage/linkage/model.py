"""Train and apply the Splink probabilistic linkage model.

Training is unsupervised: nothing here can see which person a record belongs
to. Splink runs on DuckDB (design decision D2).
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

import duckdb
import pandas as pd
import splink.comparison_library as cl
from splink import Linker, SettingsCreator, block_on
from splink.backends.duckdb import DuckDBAPI
from splink.internals.splink_dataframe import SplinkDataFrame

_LOG_LEVEL = logging.WARNING


def _rules(groups: Sequence[Sequence[str]]) -> list[Any]:
    return [block_on(*group) for group in groups]


def build_settings(settings: dict[str, Any]) -> SettingsCreator:
    """The linkage model's comparisons and blocking rules.

    Args:
        settings: The ``linkage`` section of the configuration.

    Returns:
        Splink settings for deduplicating one combined table.
    """
    return SettingsCreator(
        link_type="dedupe_only",
        unique_id_column_name="unique_id",
        comparisons=[
            cl.ForenameSurnameComparison(
                "first_name",
                "surname",
                forename_surname_concat_col_name="first_name_surname",
            ),
            cl.DateOfBirthComparison("date_of_birth", input_is_string=True),
            cl.ExactMatch("sex"),
            cl.ExactMatch("nhs_number"),
            cl.LevenshteinAtThresholds("postcode", [1]),
            cl.JaroWinklerAtThresholds("address", [0.9]),
        ],
        blocking_rules_to_generate_predictions=_rules(settings["blocking_rules"]),
        retain_intermediate_calculation_columns=False,
    )


def _database(settings: dict[str, Any]) -> DuckDBAPI:
    connection = duckdb.connect()
    connection.execute(f"SET memory_limit='{settings['duckdb_memory_limit']}'")
    connection.execute(f"SET threads={int(settings['duckdb_threads'])}")
    return DuckDBAPI(connection=connection)


def train(records: pd.DataFrame, settings: dict[str, Any]) -> dict[str, Any]:
    """Estimate the model's parameters without using any labels.

    Args:
        records: Output of ``read_records``.
        settings: The ``linkage`` section of the configuration.

    Returns:
        The trained model as a dictionary.
    """
    database = _database(settings)
    table = database.register(records, table_name="records")
    linker = Linker(table, build_settings(settings), log_level=_LOG_LEVEL)
    training = linker.training
    training.estimate_probability_two_random_records_match(
        _rules(settings["prior_rules"]), recall=settings["prior_recall"]
    )
    training.estimate_u_using_random_sampling(
        max_pairs=float(settings["u_max_pairs"]), seed=settings["seed"]
    )
    for group in settings["em_blocking"]:
        training.estimate_parameters_using_expectation_maximisation(block_on(*group))
    return linker.misc.save_model_to_json()


def score(
    records: pd.DataFrame, model: dict[str, Any], settings: dict[str, Any]
) -> tuple[Linker, SplinkDataFrame]:
    """Score candidate record pairs with a trained model.

    Args:
        records: Output of ``read_records``.
        model: Output of ``train``.
        settings: The ``linkage`` section of the configuration.

    Returns:
        The linker and its scored pairs, for clustering at any threshold.
    """
    database = _database(settings)
    table = database.register(records, table_name="records")
    linker = Linker(table, model, log_level=_LOG_LEVEL)
    pairs = linker.inference.predict(
        threshold_match_probability=settings["min_pair_probability"]
    )
    return linker, pairs


def cluster(linker: Linker, pairs: SplinkDataFrame, threshold: float) -> pd.DataFrame:
    """Group records connected by pairs at or above a match probability.

    Args:
        linker: Linker from ``score``.
        pairs: Scored pairs from ``score``.
        threshold: Minimum match probability that links two records.

    Returns:
        ``unique_id`` and ``cluster_id`` for every record.
    """
    clusters = linker.clustering.cluster_pairwise_predictions_at_threshold(
        pairs, threshold_match_probability=threshold
    )
    return clusters.as_duckdbpyrelation().df()[["unique_id", "cluster_id"]]
