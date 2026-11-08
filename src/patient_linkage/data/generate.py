"""Build the simulated source systems and the truth table.

Run from the project root:

    uv run python -m patient_linkage.data.generate --population pilot

Each person is copied, with errors, into some of the source systems. Source
files hold only what a real system would hold. Which person each record belongs
to is written separately, to ``data/truth``, and is used only for evaluation.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import os
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from patient_linkage.config import PROJECT_ROOT, load_config
from patient_linkage.data.errors import corrupt
from patient_linkage.data.population import load_people

logger = logging.getLogger(__name__)

FIELDS = (
    "nhs_number",
    "first_name",
    "middle_name",
    "surname",
    "date_of_birth",
    "sex",
    "address",
    "city",
    "postcode",
)
_AGE_BANDS = ((18, "<18"), (40, "18-39"), (60, "40-59"), (80, "60-79"))


def age_band(date_of_birth: dt.date, reference: dt.date) -> str:
    """Age band at the reference date, for the fairness analysis."""
    had_birthday = (reference.month, reference.day) >= (
        date_of_birth.month,
        date_of_birth.day,
    )
    age = reference.year - date_of_birth.year - (0 if had_birthday else 1)
    for limit, label in _AGE_BANDS:
        if age < limit:
            return label
    return "80+"


def _membership(
    count: int, sources: dict[str, dict[str, Any]], rng: np.random.Generator
) -> dict[str, np.ndarray]:
    """Which people each source holds; everyone is in at least one source."""
    held = {
        name: rng.random(count) < source["coverage"] for name, source in sources.items()
    }
    largest = max(sources, key=lambda name: sources[name]["coverage"])
    held[largest] = held[largest] | ~np.logical_or.reduce(list(held.values()))
    return held


def _source_row(
    record: dict[str, Any], source: dict[str, Any], rng: np.random.Generator
) -> dict[str, Any]:
    """Keep the source's fields, in the way that source records them."""
    row = {field: record[field] for field in source["fields"]}
    if "nhs_number" in row and rng.random() >= source["nhs_present"]:
        row["nhs_number"] = None
    date = row["date_of_birth"]
    row["date_of_birth"] = date.strftime(source["date_format"]) if date else None
    if source.get("uppercase_names"):
        for field in ("first_name", "middle_name", "surname"):
            if row.get(field):
                row[field] = row[field].upper()
    return row


def build_sources(
    people: pd.DataFrame,
    settings: dict[str, Any],
    rates: dict[str, float],
    reference: dt.date,
    rng: np.random.Generator,
) -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
    """Create each source system's records and the truth table.

    Args:
        people: Output of ``load_people``.
        settings: The ``linkage_data`` section of the configuration.
        rates: Error probabilities for one error level.
        reference: The date the population was generated for.
        rng: Random generator.

    Returns:
        Records by source name, and one truth row per record.
    """
    sources = settings["sources"]
    donors = people.to_dict("records")
    held = _membership(len(people), sources, rng)
    tables: dict[str, pd.DataFrame] = {}
    truth: list[pd.DataFrame] = []

    for name, source in sources.items():
        rows, facts = [], []
        for index in np.flatnonzero(held[name]):
            person = donors[int(index)]
            day = int(rng.integers(1, settings["batch_days"] + 1))
            copies = [day]
            if rng.random() < rates["duplicate_within_source"]:
                copies.append(int(rng.integers(day, settings["batch_days"] + 1)))
            for copy, batch_day in enumerate(copies):
                record, errors = corrupt(person, rates, donors, reference, rng)
                rows.append(
                    {**_source_row(record, source, rng), "batch_day": batch_day}
                )
                if copy:
                    errors = [*errors, "duplicate_within_source"]
                facts.append(
                    {
                        "person_id": person["person_id"],
                        "errors": ";".join(errors),
                        "sex": person["sex"],
                        "age_band": age_band(person["date_of_birth"], reference),
                        "race": person["race"],
                        "ethnicity": person["ethnicity"],
                    }
                )
        # Shuffle before numbering, so neither order nor IDs reveal who is who.
        order = rng.permutation(len(rows))
        ids = [f"{source['prefix']}{i:07d}" for i in range(1, len(rows) + 1)]
        table = pd.DataFrame([rows[i] for i in order])
        table.insert(0, "record_id", ids)
        tables[name] = table
        facts_table = pd.DataFrame([facts[i] for i in order])
        facts_table.insert(0, "source", name)
        facts_table.insert(0, "record_id", ids)
        truth.append(facts_table)

    return tables, pd.concat(truth, ignore_index=True)


def summarise(
    people: pd.DataFrame, tables: dict[str, pd.DataFrame], truth: pd.DataFrame
) -> dict[str, Any]:
    """Counts used to check a generated dataset."""
    applied = Counter(e for row in truth["errors"] for e in row.split(";") if e)
    return {
        "people": len(people),
        "records": len(truth),
        "people_with_records": int(truth["person_id"].nunique()),
        "records_by_source": {name: len(table) for name, table in tables.items()},
        "records_with_no_error": round(float((truth["errors"] == "").mean()), 4),
        "error_rates": {
            k: round(v / len(truth), 4) for k, v in sorted(applied.items())
        },
    }


def generate(population: str, level: str, root: Path = PROJECT_ROOT) -> dict[str, Any]:
    """Generate one population at one error level and write it to disk.

    Args:
        population: A key of ``linkage_data.populations``.
        level: A key of ``linkage_data.error_levels``.
        root: Project root.

    Returns:
        The dataset summary.
    """
    config = load_config()
    settings = config["linkage_data"]
    spec = settings["populations"][population]
    levels = list(settings["error_levels"])
    base = Path(os.environ.get("SYNTHEA_DIR", settings["synthea_dir"])).expanduser()
    reference = dt.date.fromisoformat(settings["reference_date"])

    people_rng = np.random.default_rng([spec["seed"], 0])
    people = load_people(base / spec["folder"] / "csv" / "patients.csv", people_rng)
    rng = np.random.default_rng([spec["seed"], 1 + levels.index(level)])
    tables, truth = build_sources(
        people, settings, settings["error_levels"][level], reference, rng
    )

    out = root / config["paths"]["processed"] / "sources" / population / level
    secret = root / settings["truth_dir"] / population / level
    out.mkdir(parents=True, exist_ok=True)
    secret.mkdir(parents=True, exist_ok=True)
    for name, table in tables.items():
        table.to_csv(out / f"{name}.csv", index=False)
    truth.to_csv(secret / "truth.csv", index=False)
    summary = summarise(people, tables, truth)
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary


def main() -> None:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--population", required=True)
    parser.add_argument("--level", help="one error level; default is all of them")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    settings = load_config()["linkage_data"]
    for level in [args.level] if args.level else list(settings["error_levels"]):
        summary = generate(args.population, level)
        logger.info("%s/%s: %s", args.population, level, json.dumps(summary))


if __name__ == "__main__":
    main()
