import csv
import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from patient_linkage.warehouse.marts import apply_marts, export, read_results

pytestmark = pytest.mark.integration

DATASET = "d"
IDENTIFIERS = {
    "first_name",
    "middle_name",
    "surname",
    "date_of_birth",
    "address",
    "city",
    "postcode",
    "nhs_number",
}
START = datetime(2026, 1, 1, tzinfo=UTC)


def add_run(conn, seconds=0, dataset=DATASET):
    run_id = uuid.uuid4()
    conn.execute(
        """
        INSERT INTO linked.runs (run_id, dataset, threshold, records, finished_at)
        VALUES (%s, %s, 0.99, %s, %s)
        """,
        (run_id, dataset, seconds, START + timedelta(seconds=seconds)),
    )
    return run_id


def add_person(conn, key, run_id, merged_into=None):
    conn.execute(
        "INSERT INTO linked.people (dataset, person_key, merged_into, created_run) "
        "VALUES (%s, %s, %s, %s)",
        (DATASET, key, merged_into, run_id),
    )


def add_record(
    conn,
    record_id,
    source,
    key=None,
    run_id=None,
    nhs=None,
    nhs_invalid=False,
    dob="2000-01-01",
    dob_bad=False,
    sex="F",
    day=1,
):
    conn.execute(
        """
        INSERT INTO staging.records (
            dataset, source, record_id, nhs_number, nhs_was_invalid, date_of_birth,
            dob_unparseable, sex, batch_day
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (DATASET, source, record_id, nhs, nhs_invalid, dob, dob_bad, sex, day),
    )
    if key:
        conn.execute(
            "INSERT INTO linked.record_people "
            "(dataset, record_id, source, person_key, run_id) "
            "VALUES (%s, %s, %s, %s, %s)",
            (DATASET, record_id, source, key, run_id),
        )


def add_checks(conn, day, seconds, size, missing, status="OK"):
    run_id = uuid.uuid4()
    at = START + timedelta(seconds=seconds)
    for name, value, state in (
        ("record_count", size, "OK"),
        ("missing_surname", missing, status),
    ):
        conn.execute(
            """
            INSERT INTO dq.check_results (
                run_id, dataset, source, check_name, value, status, checked_at,
                batch_day
            ) VALUES (%s, %s, 'gp', %s, %s, %s, %s, %s)
            """,
            (run_id, DATASET, name, value, state, at, day),
        )


def mart(conn, view, columns):
    apply_marts(conn)
    return conn.execute(
        f"SELECT {columns} FROM mart.{view} WHERE dataset = %s ORDER BY 1, 2",
        (DATASET,),
    ).fetchall()


def test_no_mart_exposes_identifiers(conn):
    apply_marts(conn)
    columns = {
        row[0]
        for row in conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'mart'"
        )
    }
    assert columns
    assert not columns & IDENTIFIERS


def test_fact_records_labels_status_and_keeps_unkeyed_records(conn):
    run_id = add_run(conn)
    add_person(conn, "P1", run_id)
    add_record(conn, "G1", "gp", "P1", run_id, nhs="9434765919")
    add_record(conn, "H1", "hospital", nhs_invalid=True, dob=None, dob_bad=True)
    add_record(conn, "L1", "lab", dob=None, sex=None)
    rows = mart(
        conn,
        "fact_records",
        "record_id, source, person_key, nhs_status, dob_status, sex",
    )
    assert rows == [
        ("G1", "GP", "P1", "Valid", "Valid", "F"),
        ("H1", "Hospital", None, "Invalid", "Unparseable", "F"),
        ("L1", "Lab", None, "Missing", "Missing", "Unknown"),
    ]


def test_dim_people_leaves_out_merged_keys_and_flags_conflicts(conn):
    run_id = add_run(conn)
    add_person(conn, "P1", run_id)
    add_person(conn, "P2", run_id, merged_into="P1")
    add_person(conn, "P3", run_id)
    add_record(conn, "G1", "gp", "P1", run_id, nhs="9434765919", day=4)
    add_record(conn, "H1", "hospital", "P1", run_id, nhs="9434765870", day=2)
    add_record(conn, "G2", "gp", "P3", run_id, nhs="9434765919")
    add_record(conn, "G3", "gp", "P3", run_id, nhs="9434765919")
    rows = mart(
        conn,
        "dim_people",
        "person_key, records, sources, source_combination, first_batch_day, "
        "conflicting_nhs_numbers",
    )
    assert rows == [
        ("P1", 2, 2, "GP + Hospital", 2, "Yes"),
        ("P3", 2, 1, "GP", 1, "No"),
    ]


def test_dq_checks_separates_attempts_at_a_corrected_day(conn):
    add_checks(conn, 12, 0, 40, 1.0, "FAIL")
    add_checks(conn, 12, 60, 38, 0.25)
    add_checks(conn, 13, 120, 10, 0.0)
    apply_marts(conn)
    rows = conn.execute(
        """
        SELECT batch_day, attempt, latest_attempt, status, records_in_batch,
               affected_records, check_type
        FROM mart.dq_checks
        WHERE check_name = 'missing_surname'
        ORDER BY 1, 2
        """
    ).fetchall()
    assert rows == [
        (12, 1, "No", "FAIL", 40, 40, "Share"),
        (12, 2, "Yes", "OK", 38, 10, "Share"),  # 0.25 * 38 = 9.5, rounds to even
        (13, 1, "Yes", "OK", 10, 0, "Share"),
    ]


def test_run_history_numbers_runs_in_order(conn):
    add_run(conn, 20)
    add_run(conn, 10)
    rows = mart(conn, "run_history", "run_number, records, finished_at_utc")
    assert rows == [
        (1, 10, "2026-01-01 00:00:10"),
        (2, 20, "2026-01-01 00:00:20"),
    ]


@pytest.mark.parametrize(
    ("probability", "band"),
    [
        (0.5, "0.5 to 0.6"),
        (0.59, "0.5 to 0.6"),
        (0.9, "0.9 to 1.0"),
        (0.989, "0.9 to 1.0"),
    ],
)
def test_review_queue_orders_sources_and_bands_probability(conn, probability, band):
    run_id = add_run(conn)
    add_person(conn, "P1", run_id)
    add_person(conn, "P2", run_id)
    add_record(conn, "L1", "lab", "P1", run_id)
    add_record(conn, "G1", "gp", "P2", run_id)
    conn.execute(
        "INSERT INTO linked.review_queue "
        "(dataset, left_id, right_id, match_probability, run_id) "
        "VALUES (%s, 'L1', 'G1', %s, %s)",
        (DATASET, probability, run_id),
    )
    rows = mart(conn, "review_queue", "left_id, source_pair, probability_band, status")
    assert rows == [("L1", "GP / Lab", band, "open")]


def write_result(folder, name, level):
    metrics = {
        "precision": 0.9,
        "recall": 0.8,
        "f1": 0.85,
        "split_rate": 0.1,
        "false_merge_rate": 0.01,
        "people": 5,
        "actual_pairs": 7,
        "recall_by_error": {"typo": {"records": 3, "linked_share": 0.5}},
    }
    (folder / name).write_text(
        json.dumps(
            {
                "threshold": 0.99,
                "evaluate_dataset": f"test/{level}",
                "splink": metrics,
                "baseline": metrics,
            }
        )
    )


def test_read_results_uses_only_final_test_files(tmp_path):
    write_result(tmp_path, "train-low__test-low.json", "low")
    write_result(tmp_path, "train-low__tune-low.json", "other")
    overall, by_error = read_results(tmp_path)
    assert {(r["error_level"], r["method"]) for r in overall} == {
        ("low", "Splink"),
        ("low", "Baseline"),
    }
    assert by_error[0] == {
        "error_level": "low",
        "level_order": 1,
        "method": "Splink",
        "injected_error": "typo",
        "records": 3,
        "linked_share": 0.5,
    }


def test_read_results_requires_final_files(tmp_path):
    with pytest.raises(FileNotFoundError):
        read_results(tmp_path)


def test_export_writes_every_file_in_a_stable_order(conn, tmp_path):
    results = tmp_path / "results"
    results.mkdir()
    write_result(results, "train-low__test-low.json", "low")
    run_id = add_run(conn)
    add_person(conn, "P1", run_id)
    add_record(conn, "H9", "hospital", "P1", run_id)
    add_record(conn, "G1", "gp", "P1", run_id)
    add_checks(conn, 1, 0, 2, 0.0)

    written = export(conn, DATASET, results, tmp_path / "out")

    assert written["fact_records"] == 2
    assert written["dim_people"] == 1
    assert written["linkage_results"] == 2
    with (tmp_path / "out" / "fact_records.csv").open(newline="") as handle:
        assert [row["record_id"] for row in csv.DictReader(handle)] == ["G1", "H9"]


def test_export_refuses_an_unknown_dataset(conn, tmp_path):
    with pytest.raises(ValueError, match="No records"):
        export(conn, "typo/dataset", tmp_path, tmp_path / "out")
    assert not (tmp_path / "out").exists()
