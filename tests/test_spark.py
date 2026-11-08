import os
import shutil
from datetime import date

import pytest

pytest.importorskip("pyspark")

from pyspark.sql import functions as sf  # noqa: E402

from patient_linkage.config import load_config  # noqa: E402
from patient_linkage.spark import standardise as standardise_module  # noqa: E402
from patient_linkage.spark.standardise import (  # noqa: E402
    clean_name,
    clean_text,
    collect_rows,
    create_session,
    fetch_staging,
    find_differences,
    nhs_is_valid,
    read_source,
    run,
    safe_date,
)
from patient_linkage.warehouse.load import file_checksum, load_source  # noqa: E402
from patient_linkage.warehouse.load import read_source as load_raw  # noqa: E402
from patient_linkage.warehouse.load import standardise as load_staging  # noqa: E402

pytestmark = pytest.mark.integration

SOURCES = load_config()["linkage_data"]["sources"]

NAMES = [
    "smith",
    "  Mary   Ann ",
    "O'Brien-Jones",
    "José",
    "Müller",
    "Łukasz",
    "x1y2",
    "123",
    "   ",
    "tab\tname",
    "NA",
    None,
]
TEXTS = ["1 High  St", "\tA\nB ", "  ", "José Rd", "a b", None]
NHS_NUMBERS = [
    "9434765919",  # valid
    "9434765918",  # wrong check digit
    "943476591",
    "94347659190",
    "943476591a",
    "9434765919\n",
    "0000000000",
    "1000000010",  # check digit would be 10, so never valid
    "",
    None,
]
DATES = {
    "DD/MM/YYYY": (
        "dd/MM/yyyy",
        ["18/11/1978", "31/02/2000", "1/2/2000", "18-11-1978"],
    ),
    "YYYY-MM-DD": ("yyyy-MM-dd", ["1978-11-18", "1978-13-01", "78-11-18", "abc"]),
    "YYYYMMDD": ("yyyyMMdd", ["19781118", "20010229", "20000229", "1978111", None]),
}


@pytest.fixture(scope="module")
def spark():
    if not (os.environ.get("JAVA_HOME") or shutil.which("java")):
        if os.environ.get("CI"):
            pytest.fail("Java must be available in CI")
        pytest.skip("Java is not installed")
    session = create_session()
    session.sparkContext.setLogLevel("ERROR")
    yield session
    session.stop()


def apply(spark, values, expression):
    frame = spark.createDataFrame([(v,) for v in values], ["v"], "v string")
    return [row[0] for row in frame.select(expression(sf.col("v"))).collect()]


def sql_values(conn, call, values):
    return [conn.execute(f"SELECT {call}", (v,)).fetchone()[0] for v in values]


def test_clean_name_matches_sql(spark, conn):
    assert apply(spark, NAMES, clean_name) == sql_values(
        conn, "staging.clean_name(%s::text)", NAMES
    )


def test_clean_text_matches_sql(spark, conn):
    call = "nullif(trim(regexp_replace(upper(%s::text), '\\s+', ' ', 'g')), '')"
    assert apply(spark, TEXTS, clean_text) == sql_values(conn, call, TEXTS)


def test_nhs_check_matches_sql(spark, conn):
    assert apply(spark, NHS_NUMBERS, nhs_is_valid) == sql_values(
        conn, "staging.nhs_is_valid(%s::text)", NHS_NUMBERS
    )


@pytest.mark.parametrize("sql_format", DATES)
def test_safe_date_matches_sql(spark, conn, sql_format):
    pattern, values = DATES[sql_format]
    expected = [
        conn.execute("SELECT staging.safe_date(%s, %s)", (v, sql_format)).fetchone()[0]
        for v in values
    ]
    assert apply(spark, values, lambda c: safe_date(c, pattern)) == expected


def test_read_source_keeps_words_and_fills_missing_columns(spark, tmp_path):
    path = tmp_path / "lab.csv"
    path.write_text(
        "record_id,nhs_number,first_name,surname,date_of_birth,sex,batch_day\n"
        'L0000001,,"Null",NA,20000101,F,3\n'
    )
    row = read_source(spark, path, SOURCES["lab"]["fields"]).first()
    assert (row["first_name"], row["surname"]) == ("Null", "NA")
    assert row["nhs_number"] is None
    assert row["address"] is None


def test_read_source_rejects_unexpected_header(spark, tmp_path):
    path = tmp_path / "lab.csv"
    path.write_text("record_id,wrong,batch_day\nL0000001,x,3\n")
    with pytest.raises(Exception, match="(?i)header|schema|malformed"):
        read_source(spark, path, SOURCES["lab"]["fields"]).collect()


def test_find_differences_reports_values_and_unmatched_records(monkeypatch):
    key = ("d", "gp", "G1")
    left = [(*key, "a", date(2000, 1, 1)), ("d", "gp", "G2", "b", None)]
    right = [(*key, "A", date(2000, 1, 1)), ("d", "gp", "G3", "c", None)]
    monkeypatch.setattr(
        standardise_module,
        "STAGING_COLUMNS",
        ("dataset", "source", "record_id", "x", "y"),
    )
    found = find_differences(left, right)
    assert {"record": ("d", "gp", "G2"), "only_in": "spark"} in found
    assert {"record": ("d", "gp", "G3"), "only_in": "sql"} in found
    assert {"record": key, "column": "x", "spark": "a", "sql": "A"} in found
    assert len(found) == 3


def test_whole_job_matches_warehouse(spark, conn, folder, tmp_path):
    # Load directly: the full pipeline's quality gate can reject this small
    # fixture and roll back, which would leave nothing to compare.
    for name, source in SOURCES.items():
        path = folder / f"{name}.csv"
        load_source(conn, "d", name, load_raw(path), file_checksum(path))
        load_staging(conn, "d", name, source["pg_date_format"])
    staged = fetch_staging(conn, "d")
    assert staged

    written = run(spark, "d", folder, tmp_path / "out", SOURCES)
    assert find_differences(collect_rows(written), staged) == []
