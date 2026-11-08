import datetime as dt
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from patient_linkage.config import load_config
from patient_linkage.data import errors as err
from patient_linkage.data.generate import age_band, build_sources, summarise
from patient_linkage.data.population import (
    is_valid_nhs_number,
    load_people,
    nhs_check_digit,
    reserved_range_nhs_numbers,
    strip_name_digits,
)

REFERENCE = dt.date(2026, 11, 1)
SETTINGS = load_config()["linkage_data"]
NO_ERRORS = dict.fromkeys(SETTINGS["error_levels"]["low"], 0.0)


def write_patients(path: Path, count: int) -> Path:
    rows = [
        {
            "Id": f"id-{i:05d}",
            "BIRTHDATE": f"{1940 + i % 70}-{1 + i % 12:02d}-{1 + i % 28:02d}",
            "FIRST": f"Wilfredo{i}",
            "MIDDLE": None if i % 2 else f"Lee{i}",
            "LAST": f"O'Connell{i}",
            "MAIDEN": None if i % 3 else f"Terry{i}",
            "GENDER": "F" if i % 2 else "M",
            "RACE": "white",
            "ETHNICITY": "nonhispanic",
            "ADDRESS": f"{i} Schamberger Rapid",
            "CITY": "Boston",
            "ZIP": f"{2000 + i:05d}",
            "SSN": "not-used",
        }
        for i in range(count)
    ]
    file = path / "patients.csv"
    pd.DataFrame(rows).to_csv(file, index=False)
    return file


@pytest.fixture
def people(tmp_path):
    return load_people(write_patients(tmp_path, 1500), np.random.default_rng(1))


def build(people, rates, seed=7):
    return build_sources(
        people, SETTINGS, rates, REFERENCE, np.random.default_rng(seed)
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("Wilfredo622", "Wilfredo"), ("O'Connell601", "O'Connell"), (None, None)],
)
def test_strip_name_digits(raw, expected):
    assert strip_name_digits(raw) == expected


def test_known_nhs_check_digit():
    # 943 476 5919 is the example number commonly used to illustrate the check.
    assert nhs_check_digit("943476591") == 9
    assert is_valid_nhs_number("9434765919")
    assert not is_valid_nhs_number("9434765918")


def test_generated_nhs_numbers_are_valid_distinct_and_in_test_range():
    numbers = reserved_range_nhs_numbers(5000, np.random.default_rng(3))
    assert len(set(numbers)) == 5000
    assert all(n.startswith("999") and is_valid_nhs_number(n) for n in numbers)


def test_load_people_cleans_names_and_is_order_independent(tmp_path):
    file = write_patients(tmp_path, 50)
    first = load_people(file, np.random.default_rng(1))
    assert not first["first_name"].str.contains(r"\d").any()
    shuffled = pd.read_csv(file, dtype=str).sample(frac=1, random_state=5)
    shuffled.to_csv(file, index=False)
    second = load_people(file, np.random.default_rng(1))
    pd.testing.assert_frame_equal(first, second)


def test_placeholder_postcode_becomes_missing(tmp_path):
    file = write_patients(tmp_path, 40)
    raw = pd.read_csv(file, dtype=str)
    raw.loc[:9, "ZIP"] = "00000"
    raw.to_csv(file, index=False)
    loaded = load_people(file, np.random.default_rng(1))
    assert loaded["postcode"].isna().sum() == 10
    assert not (loaded["postcode"] == "00000").any()


def test_people_with_no_postcode_survive_every_error(people):
    people = people.assign(postcode=None)
    tables, _ = build(people, SETTINGS["error_levels"]["high"])
    assert tables["gp"]["postcode"].isna().all()


def test_missing_names_are_none_not_nan(people):
    assert people["maiden_name"].map(lambda v: v is None or isinstance(v, str)).all()
    assert people["maiden_name"].isna().any()


def test_people_without_a_maiden_name_keep_their_surname(people):
    rates = {**NO_ERRORS, "surname_maiden": 1.0}
    tables, truth = build(people, rates)
    gp = (
        tables["gp"]
        .merge(truth, on="record_id")
        .merge(people, on="person_id", suffixes=("", "_true"))
    )
    no_maiden = gp[gp["maiden_name"].isna()]
    assert len(no_maiden) > 0
    assert (no_maiden["surname"] == no_maiden["surname_true"]).all()
    has_maiden = gp[gp["maiden_name"].notna()]
    assert (has_maiden["surname"] == has_maiden["maiden_name"]).all()


def test_typo_changes_text_and_keeps_first_letter():
    rng = np.random.default_rng(2)
    results = [err.typo("Margaret", rng) for _ in range(200)]
    assert all(r[0] == "M" for r in results)
    assert sum(r != "Margaret" for r in results) > 180


def test_short_values_survive_typo():
    assert err.typo("Al", np.random.default_rng(1)) == "Al"


def test_digit_typo_changes_exactly_one_digit():
    rng = np.random.default_rng(2)
    for _ in range(100):
        altered = err.digit_typo("9991234567", rng)
        assert sum(a != b for a, b in zip(altered, "9991234567", strict=True)) == 1


def test_shortened_uses_nicknames_then_short_forms():
    rng = np.random.default_rng(2)
    assert err.shortened("William", rng) == "Bill"
    assert err.shortened("Wilfredo", rng) in {"Wil", "Wilf"}
    assert err.shortened("Ann", rng) == "Ann"


def test_nhs_digit_typo_stays_in_test_range_and_fails_the_check():
    rng = np.random.default_rng(2)
    number = reserved_range_nhs_numbers(1, rng)[0]
    for _ in range(300):
        altered = err.nhs_digit_typo(number, rng)
        assert altered.startswith("999")
        assert altered != number
        assert not is_valid_nhs_number(altered)


def test_every_nhs_number_in_every_source_is_in_test_range(people):
    tables, _ = build(
        people, {**SETTINGS["error_levels"]["high"], "nhs_digit_typo": 0.5}
    )
    for table in tables.values():
        assert table["nhs_number"].dropna().str.startswith("999").all()


def test_day_month_swap():
    assert err.swap_day_month(dt.date(1980, 3, 7)) == dt.date(1980, 7, 3)
    assert err.swap_day_month(dt.date(1980, 3, 25)) is None
    assert err.swap_day_month(dt.date(1980, 3, 3)) is None


def test_date_typo_is_valid_and_not_in_future():
    rng = np.random.default_rng(4)
    for _ in range(200):
        altered = err.date_typo(dt.date(2020, 2, 29), REFERENCE, rng)
        assert altered is None or (
            altered != dt.date(2020, 2, 29) and altered <= REFERENCE
        )


def test_age_band_boundaries():
    assert age_band(dt.date(2008, 11, 2), REFERENCE) == "<18"
    assert age_band(dt.date(2008, 11, 1), REFERENCE) == "18-39"
    assert age_band(dt.date(1940, 1, 1), REFERENCE) == "80+"


def test_no_error_rates_copy_details_faithfully(people):
    tables, truth = build(people, NO_ERRORS)
    assert (truth["errors"].fillna("") == "").all()
    gp = (
        tables["gp"]
        .merge(truth, on="record_id")
        .merge(people, on="person_id", suffixes=("", "_true"))
    )
    assert (gp["surname"] == gp["surname_true"]).all()
    assert (gp["address"] == gp["address_true"]).all()


def test_sources_do_not_reveal_identity(people):
    tables, _ = build(people, SETTINGS["error_levels"]["medium"])
    for table in tables.values():
        assert not {"person_id", "errors", "race", "ethnicity"} & set(table.columns)
        assert not table["record_id"].astype(str).str.contains("id-").any()


def test_every_person_is_in_at_least_one_source(people):
    tables, truth = build(people, SETTINGS["error_levels"]["low"])
    assert set(truth["person_id"]) == set(people["person_id"])
    assert truth["record_id"].is_unique
    assert len(truth) == sum(len(t) for t in tables.values())


def test_generation_is_reproducible(people):
    rates = SETTINGS["error_levels"]["high"]
    first_tables, first_truth = build(people, rates, seed=9)
    second_tables, second_truth = build(people, rates, seed=9)
    pd.testing.assert_frame_equal(first_truth, second_truth)
    for name, table in first_tables.items():
        pd.testing.assert_frame_equal(table, second_tables[name])


def test_a_different_seed_gives_different_records(people):
    rates = SETTINGS["error_levels"]["high"]
    assert not build(people, rates, seed=1)[1].equals(build(people, rates, seed=2)[1])


@pytest.mark.parametrize("error", ["surname_typo", "moved_address", "postcode_missing"])
def test_applied_error_rates_are_near_configured_rates(people, error):
    rates = SETTINGS["error_levels"]["high"]
    tables, truth = build(people, rates)
    observed = summarise(people, tables, truth.fillna({"errors": ""}))["error_rates"][
        error
    ]
    assert observed == pytest.approx(rates[error], abs=0.02)


def test_error_levels_increase():
    levels = SETTINGS["error_levels"]
    for name in levels["low"]:
        assert levels["low"][name] <= levels["medium"][name] <= levels["high"][name]


def test_error_levels_list_the_same_errors():
    levels = SETTINGS["error_levels"]
    assert set(levels["low"]) == set(levels["medium"]) == set(levels["high"])


def test_sources_keep_only_their_own_fields(people):
    tables, _ = build(people, SETTINGS["error_levels"]["low"])
    for name, source in SETTINGS["sources"].items():
        assert set(tables[name].columns) == {
            "record_id",
            "batch_day",
            *source["fields"],
        }


def test_truth_tables_are_not_committable():
    import subprocess

    from patient_linkage.config import PROJECT_ROOT

    path = f"{SETTINGS['truth_dir']}/pilot/low/truth.csv"
    result = subprocess.run(
        ["git", "check-ignore", "-q", path], cwd=PROJECT_ROOT, check=False
    )
    assert result.returncode == 0
