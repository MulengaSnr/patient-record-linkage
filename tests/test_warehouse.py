import numpy as np
import pandas as pd
import pytest
from pandera.errors import SchemaErrors

from patient_linkage.config import PROJECT_ROOT, load_config
from patient_linkage.data.population import (
    is_valid_nhs_number,
    reserved_range_nhs_numbers,
)
from patient_linkage.warehouse import pipeline, quality
from patient_linkage.warehouse.load import (
    apply_schema,
    file_schema,
    load_source,
    read_source,
    standardise,
)

CONFIG = load_config()
SOURCES = CONFIG["linkage_data"]["sources"]


@pytest.mark.parametrize(
    ("value", "expected"),
    [(0.0, "OK"), (0.05, "WARN"), (0.09, "WARN"), (0.1, "FAIL"), (0.5, "FAIL")],
)
def test_grade(value, expected):
    assert quality.grade(value, 0.05, 0.1) == expected


@pytest.mark.parametrize(
    ("status", "affected", "expected"),
    [
        ("FAIL", 1, "WARN"),
        ("FAIL", 4.9, "WARN"),
        ("FAIL", 5, "FAIL"),
        ("WARN", 1, "WARN"),
    ],
)
def test_a_failure_needs_enough_affected_records(status, affected, expected):
    assert quality._downgrade_small(status, affected, 5) == expected


def test_enforce_names_every_failure():
    results = [
        quality.CheckResult("gp", "missing_surname", 0.6, 0.01, 0.05, "FAIL"),
        quality.CheckResult("lab", "nhs_invalid_share", 0.5, 0.02, 0.1, "FAIL"),
        quality.CheckResult("gp", "missing_sex", 0.0, 0.05, 0.2, "OK"),
    ]
    with pytest.raises(quality.DataQualityError, match="gp.missing_surname.*lab"):
        quality.enforce(results)


def test_enforce_allows_warnings():
    quality.enforce([quality.CheckResult("gp", "x", 0.06, 0.05, 0.2, "WARN")])


def test_read_source_keeps_surnames_that_look_like_missing_values(tmp_path):
    file = tmp_path / "gp.csv"
    file.write_text("record_id,surname\nG0000001,Null\nG0000002,NA\nG0000003,\n")
    frame = read_source(file)
    assert frame["surname"].tolist()[:2] == ["Null", "NA"]
    assert pd.isna(frame["surname"].iloc[2])


def gp_frame(**changes):
    row = dict.fromkeys(SOURCES["gp"]["fields"], "x")
    row |= {"record_id": "G0000001", "batch_day": "3"}
    return pd.DataFrame([row | changes])


def test_file_schema_accepts_a_good_file():
    file_schema(SOURCES["gp"]).validate(gp_frame(), lazy=True)


@pytest.mark.parametrize(
    "bad",
    [
        gp_frame(record_id="H0000001"),
        gp_frame(batch_day="soon"),
        gp_frame(unexpected="value"),
        gp_frame().drop(columns="surname"),
        pd.concat([gp_frame(), gp_frame()]),
    ],
    ids=["wrong prefix", "bad day", "extra column", "missing column", "duplicate id"],
)
def test_file_schema_rejects_bad_files(bad):
    with pytest.raises(SchemaErrors):
        file_schema(SOURCES["gp"]).validate(bad, lazy=True)


def test_warehouse_code_never_reads_the_truth_table():
    code = PROJECT_ROOT / "src" / "patient_linkage" / "warehouse"
    for file in [*code.glob("*.py"), *(PROJECT_ROOT / "sql").glob("*.sql")]:
        text = file.read_text()
        assert "truth" not in text.lower(), file
        assert "person_id" not in text, file


def scalar(conn, query, *params):
    return conn.execute(query, params).fetchone()[0]


@pytest.mark.integration
def test_schema_can_be_applied_twice(conn):
    apply_schema(conn)
    apply_schema(conn)


@pytest.mark.integration
def test_pipeline_loads_every_row_and_passes_high_error_data(conn, folder):
    results = pipeline.run(conn, "t/high", folder, CONFIG)
    expected = sum(len(read_source(folder / f"{s}.csv")) for s in SOURCES)
    assert scalar(conn, "SELECT count(*) FROM raw.records") == expected
    assert scalar(conn, "SELECT count(*) FROM staging.records") == expected
    assert not [r for r in results if r.status == "FAIL"]
    assert scalar(conn, "SELECT count(*) FROM dq.check_results") == len(results)


@pytest.mark.integration
def test_loading_the_same_files_twice_adds_nothing(conn, folder):
    pipeline.run(conn, "t/high", folder, CONFIG)
    before = scalar(conn, "SELECT count(*) FROM raw.records")
    pipeline.run(conn, "t/high", folder, CONFIG)
    assert scalar(conn, "SELECT count(*) FROM raw.records") == before
    assert scalar(conn, "SELECT count(*) FROM staging.records") == before
    assert scalar(conn, "SELECT count(*) FROM raw.load_audit") == len(SOURCES)


@pytest.mark.integration
def test_datasets_are_kept_apart(conn, folder):
    pipeline.run(conn, "t/one", folder, CONFIG)
    first = scalar(conn, "SELECT count(*) FROM staging.records")
    pipeline.run(conn, "t/two", folder, CONFIG)
    assert scalar(conn, "SELECT count(*) FROM staging.records") == 2 * first


def stage(conn, frame, source="hospital", date_format="DD/MM/YYYY"):
    load_source(conn, "t", source, frame, "checksum")
    standardise(conn, "t", source, date_format)
    return conn.execute(
        "SELECT nhs_number, nhs_was_invalid, first_name, surname, date_of_birth, "
        "dob_unparseable, sex, postcode FROM staging.records"
    ).fetchone()


def record(**fields):
    return pd.DataFrame([{"record_id": "H0000001", "batch_day": "1"} | fields])


@pytest.mark.integration
def test_staging_standardises_values(conn):
    row = stage(
        conn,
        record(
            first_name="  mary-jane ",
            surname="O'Connell",
            date_of_birth="24/08/2006",
            sex="f",
            postcode="02019",
            nhs_number="9434765919",
        ),
    )
    assert row[0] == "9434765919" and row[1] is False
    assert row[2] == "MARYJANE" and row[3] == "OCONNELL"
    assert str(row[4]) == "2006-08-24" and row[5] is False
    assert row[6] == "F" and row[7] == "02019"


@pytest.mark.integration
@pytest.mark.parametrize("bad_date", ["31/02/2000", "2000-01-05", "soon"])
def test_bad_dates_are_flagged_not_fatal(conn, bad_date):
    row = stage(conn, record(date_of_birth=bad_date, surname="Smith"))
    assert row[4] is None and row[5] is True


@pytest.mark.integration
def test_a_missing_date_is_not_counted_as_unparseable(conn):
    row = stage(conn, record(surname="Smith"))
    assert row[4] is None and row[5] is False


@pytest.mark.integration
def test_invalid_nhs_number_is_removed_and_flagged(conn):
    row = stage(conn, record(nhs_number="9434765918"))
    assert row[0] is None and row[1] is True


@pytest.mark.integration
@pytest.mark.parametrize("sex", ["X", "unknown"])
def test_unrecognised_sex_becomes_missing(conn, sex):
    assert stage(conn, record(sex=sex))[6] is None


@pytest.mark.integration
def test_sql_nhs_check_agrees_with_python(conn):
    rng = np.random.default_rng(5)
    numbers = reserved_range_nhs_numbers(300, rng)
    numbers += [f"{int(n):010d}" for n in rng.integers(0, 10**10, 700)]
    numbers += ["", "12345", "abcdefghij", "99912345678"]
    for number in numbers:
        in_sql = scalar(conn, "SELECT staging.nhs_is_valid(%s)", number)
        assert in_sql == is_valid_nhs_number(number), number


@pytest.mark.integration
def test_gate_stops_a_broken_feed_and_keeps_the_evidence(conn, folder):
    gp = pd.read_csv(folder / "gp.csv", dtype=str)
    gp["date_of_birth"] = None
    gp.to_csv(folder / "gp.csv", index=False)
    with pytest.raises(quality.DataQualityError, match="gp.missing_date_of_birth"):
        pipeline.run(conn, "t/broken", folder, CONFIG)
    assert (
        scalar(
            conn,
            "SELECT count(*) FROM dq.check_results "
            "WHERE status = 'FAIL' AND check_name = 'missing_date_of_birth'",
        )
        == 1
    )


@pytest.mark.integration
def test_gate_stops_a_file_with_the_wrong_columns_before_loading(conn, folder):
    lab = pd.read_csv(folder / "lab.csv", dtype=str).drop(columns="surname")
    lab.to_csv(folder / "lab.csv", index=False)
    with pytest.raises(quality.DataQualityError, match="lab: file failed"):
        pipeline.run(conn, "t/shape", folder, CONFIG)
    conn.rollback()
    assert scalar(conn, "SELECT count(*) FROM raw.records") == 0


@pytest.mark.integration
def test_no_identity_columns_exist_in_the_warehouse(conn, folder):
    pipeline.run(conn, "t/high", folder, CONFIG)
    names = {
        row[0]
        for row in conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema IN ('raw', 'staging', 'dq')"
        )
    }
    assert not names & {"person_id", "errors", "race", "ethnicity", "age_band"}


def batch_days(folder):
    return sorted(
        {int(d) for s in SOURCES for d in read_source(folder / f"{s}.csv")["batch_day"]}
    )


@pytest.mark.integration
def test_batches_load_only_their_own_day_and_add_up(conn, folder):
    days = batch_days(folder)
    assert days == list(range(1, days[-1] + 1))
    pipeline.run(conn, "t/daily", folder, CONFIG, batch_day=days[0])
    first = scalar(conn, "SELECT count(*) FROM raw.records")
    expected = sum(
        (read_source(folder / f"{s}.csv")["batch_day"] == str(days[0])).sum()
        for s in SOURCES
    )
    assert first == expected
    for day in days[1:]:
        pipeline.run(conn, "t/daily", folder, CONFIG, batch_day=day)
    total = sum(len(read_source(folder / f"{s}.csv")) for s in SOURCES)
    assert scalar(conn, "SELECT count(*) FROM raw.records") == total


@pytest.mark.integration
def test_reloading_a_batch_adds_nothing(conn, folder):
    day = batch_days(folder)[0]
    pipeline.run(conn, "t/daily", folder, CONFIG, batch_day=day)
    before = scalar(conn, "SELECT count(*) FROM raw.records")
    pipeline.run(conn, "t/daily", folder, CONFIG, batch_day=day)
    assert scalar(conn, "SELECT count(*) FROM raw.records") == before


@pytest.mark.integration
def test_one_bad_day_cannot_hide_behind_good_days(conn, folder):
    days = batch_days(folder)
    for day in days[:-1]:
        pipeline.run(conn, "t/daily", folder, CONFIG, batch_day=day)
    gp = pd.read_csv(folder / "gp.csv", dtype=str)
    gp.loc[gp["batch_day"] == str(days[-1]), "surname"] = None
    gp.to_csv(folder / "gp.csv", index=False)
    with pytest.raises(quality.DataQualityError, match="gp.missing_surname"):
        pipeline.run(conn, "t/daily", folder, CONFIG, batch_day=days[-1])
    whole = quality.check_source(
        conn, "t/daily", "gp", SOURCES["gp"]["fields"], CONFIG["quality"]
    )
    surname = next(r for r in whole if r.check_name == "missing_surname")
    assert surname.value < 0.2


@pytest.mark.integration
def test_results_record_which_batch_was_judged(conn, folder):
    day = batch_days(folder)[0]
    pipeline.run(conn, "t/daily", folder, CONFIG, batch_day=day)
    assert scalar(conn, "SELECT min(batch_day) FROM dq.check_results") == day


@pytest.mark.integration
def test_a_failed_batch_leaves_evidence_but_no_data(conn, folder):
    gp = pd.read_csv(folder / "gp.csv", dtype=str)
    gp["surname"] = None
    gp.to_csv(folder / "gp.csv", index=False)
    with pytest.raises(quality.DataQualityError):
        pipeline.run(conn, "t/bad", folder, CONFIG)
    assert scalar(conn, "SELECT count(*) FROM raw.records") == 0
    assert scalar(conn, "SELECT count(*) FROM staging.records") == 0
    assert scalar(conn, "SELECT count(*) FROM raw.load_audit") == 0
    assert scalar(conn, "SELECT count(*) FROM dq.check_results WHERE status='FAIL'") > 0


@pytest.mark.integration
def test_a_corrected_batch_replaces_a_failed_one(conn, folder):
    day = batch_days(folder)[0]
    good = pd.read_csv(folder / "gp.csv", dtype=str)
    bad = good.copy()
    bad.loc[bad["batch_day"] == str(day), "surname"] = None
    bad.to_csv(folder / "gp.csv", index=False)
    with pytest.raises(quality.DataQualityError):
        pipeline.run(conn, "t/fix", folder, CONFIG, batch_day=day)
    good.to_csv(folder / "gp.csv", index=False)
    pipeline.run(conn, "t/fix", folder, CONFIG, batch_day=day)
    missing = scalar(
        conn,
        "SELECT count(*) FROM staging.records WHERE source='gp' AND surname IS NULL",
    )
    assert missing == 0
    assert scalar(conn, "SELECT count(*) FROM staging.records WHERE source='gp'") > 0


@pytest.mark.integration
def test_a_day_cannot_be_loaded_before_the_previous_day(conn, folder):
    with pytest.raises(quality.DataQualityError, match="day 4 is not loaded"):
        pipeline.run(conn, "t/daily", folder, CONFIG, batch_day=5)
    assert scalar(conn, "SELECT count(*) FROM raw.records") == 0
