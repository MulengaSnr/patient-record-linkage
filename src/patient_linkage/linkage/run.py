"""Train a linkage model on one dataset and evaluate it on another.

Run from the project root (with the database up and the datasets loaded):

    uv run python -m patient_linkage.linkage.run --train pilot/medium \
        --evaluate pilot/medium

Results are written under ``data/processed/linkage``. Anything using the pilot
population is marked ``development_only``: the pilot is for building the code,
and its numbers are not results.
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path
from typing import Any

import pandas as pd

from patient_linkage.config import PROJECT_ROOT, load_config
from patient_linkage.linkage import baseline, evaluate, model
from patient_linkage.linkage.records import read_records
from patient_linkage.warehouse.load import connect

logger = logging.getLogger(__name__)


def assess(clusters: pd.DataFrame, truth: pd.DataFrame) -> dict[str, Any]:
    """Every metric for one clustering."""
    return {
        **evaluate.pairwise_metrics(clusters, truth),
        **evaluate.cluster_metrics(clusters, truth),
        "groups": evaluate.group_metrics(clusters, truth),
        "recall_by_error": evaluate.recall_by_error(clusters, truth),
    }


def run(
    train_records: pd.DataFrame,
    eval_records: pd.DataFrame,
    truth: pd.DataFrame,
    settings: dict[str, Any],
    threshold: float | None = None,
) -> dict[str, Any]:
    """Fit on one dataset, then compare Splink with the baseline on another.

    Args:
        train_records: Records used to estimate the model. Never labelled.
        eval_records: Records to link.
        truth: Truth table for ``eval_records``.
        settings: The ``linkage`` section of the configuration.
        threshold: Probability to report at. By default, the lowest swept value
            that reaches the target precision.

    Returns:
        The model, the threshold sweep and full metrics for both methods.
    """
    started = time.perf_counter()
    trained = model.train(train_records, settings)
    trained_at = time.perf_counter()
    linker, pairs = model.score(eval_records, trained, settings)
    scored_at = time.perf_counter()

    sweep = []
    for value in settings["threshold_sweep"]:
        clusters = model.cluster(linker, pairs, value)
        sweep.append(
            {
                "threshold": value,
                **evaluate.pairwise_metrics(clusters, truth),
                **evaluate.cluster_metrics(clusters, truth),
            }
        )
    chosen = (
        threshold
        if threshold is not None
        else evaluate.pick_threshold(sweep, settings["target_precision"])
    )
    deterministic = baseline.deterministic_clusters(
        eval_records, settings["baseline_rules"]
    )
    return {
        "model": trained,
        "threshold": chosen,
        "sweep": sweep,
        "splink": None
        if chosen is None
        else assess(model.cluster(linker, pairs, chosen), truth),
        "baseline": assess(deterministic, truth),
        "seconds": {
            "train": round(trained_at - started, 1),
            "score": round(scored_at - trained_at, 1),
        },
        "records_trained_on": len(train_records),
        "records_evaluated": len(eval_records),
    }


def check_final_test_rules(
    evaluate_dataset: str,
    train_dataset: str,
    threshold: float | None,
    final: bool,
    already_used: bool,
) -> None:
    """Enforce the design's rule that the test population is used once.

    Args:
        evaluate_dataset: The dataset being evaluated.
        train_dataset: The dataset the model was trained on.
        threshold: The threshold supplied, if any.
        final: Whether the caller confirmed this is the final evaluation.
        already_used: Whether a final result for this dataset already exists.

    Raises:
        ValueError: If the evaluation would break the rule.
    """
    if not evaluate_dataset.startswith("test/"):
        return
    if not final:
        raise ValueError("The test population needs --final: it is used once")
    if threshold is None:
        raise ValueError("Choose the threshold on the tune population first")
    if train_dataset.startswith("test/"):
        raise ValueError("The model must not be trained on the test population")
    if already_used:
        raise ValueError(f"{evaluate_dataset} has already been used for final results")


def main() -> None:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--train", required=True, help="dataset, e.g. pilot/medium")
    parser.add_argument("--evaluate", required=True)
    parser.add_argument("--threshold", type=float)
    parser.add_argument("--final", action="store_true", help="use the test set once")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    config = load_config()
    settings = config["linkage"]
    slug = f"{args.train}__{args.evaluate}".replace("/", "-")
    out = PROJECT_ROOT / config["paths"]["processed"] / "linkage" / f"{slug}.json"
    check_final_test_rules(
        args.evaluate, args.train, args.threshold, args.final, out.exists()
    )
    truth_path = (
        Path(PROJECT_ROOT)
        / config["linkage_data"]["truth_dir"]
        / args.evaluate
        / "truth.csv"
    )
    with connect() as conn:
        train_records = read_records(conn, args.train)
        eval_records = read_records(conn, args.evaluate)
    outcome = run(
        train_records,
        eval_records,
        evaluate.read_truth(truth_path),
        settings,
        args.threshold,
    )
    outcome["development_only"] = "pilot" in (args.train + args.evaluate)
    outcome["train_dataset"] = args.train
    outcome["evaluate_dataset"] = args.evaluate
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(outcome, indent=2, default=str) + "\n")
    logger.info("Wrote %s", out)


if __name__ == "__main__":
    main()
