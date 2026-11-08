import pandas as pd
import pytest

from patient_linkage.config import PROJECT_ROOT, load_config
from patient_linkage.linkage import baseline, evaluate, model
from patient_linkage.linkage.records import read_records
from patient_linkage.linkage.run import check_final_test_rules
from patient_linkage.warehouse import pipeline

CONFIG = load_config()
SETTINGS = CONFIG["linkage"]


def truth_frame(people):
    rows = []
    for index, person in enumerate(people):
        rows.append(
            {
                "unique_id": f"r{index}",
                "person_id": person,
                "source": "gp",
                "errors": "surname_typo" if index == 0 else "",
                "sex": "F" if person == "a" else "M",
                "age_band": "80+" if person == "a" else "18-39",
                "race": "white",
                "ethnicity": "nonhispanic",
            }
        )
    return pd.DataFrame(rows)


def clusters_frame(labels):
    return pd.DataFrame(
        {"unique_id": [f"r{i}" for i in range(len(labels))], "cluster_id": labels}
    )


def test_perfect_clustering_scores_one():
    truth = truth_frame(["a", "a", "b", "b"])
    result = evaluate.pairwise_metrics(clusters_frame([1, 1, 2, 2]), truth)
    assert result["precision"] == result["recall"] == result["f1"] == 1.0


def test_splitting_a_person_lowers_recall_only():
    truth = truth_frame(["a", "a", "a", "b"])
    result = evaluate.pairwise_metrics(clusters_frame([1, 1, 2, 3]), truth)
    assert result["precision"] == 1.0
    assert result["recall"] == pytest.approx(1 / 3)


def test_merging_two_people_lowers_precision_only():
    truth = truth_frame(["a", "a", "b", "b"])
    result = evaluate.pairwise_metrics(clusters_frame([1, 1, 1, 1]), truth)
    assert result["recall"] == 1.0
    assert result["precision"] == pytest.approx(2 / 6)


def test_no_predicted_pairs_counts_as_full_precision():
    truth = truth_frame(["a", "a"])
    result = evaluate.pairwise_metrics(clusters_frame([1, 2]), truth)
    assert result["precision"] == 1.0 and result["recall"] == 0.0


def test_metrics_reject_clusters_that_do_not_cover_truth():
    with pytest.raises(ValueError, match="same records"):
        evaluate.pairwise_metrics(clusters_frame([1]), truth_frame(["a", "b"]))


def test_cluster_metrics_count_people():
    truth = truth_frame(["a", "a", "b", "b", "c"])
    result = evaluate.cluster_metrics(clusters_frame([1, 2, 3, 3, 3]), truth)
    assert result["split_rate"] == pytest.approx(1 / 2)
    assert result["false_merge_rate"] == pytest.approx(2 / 3)


def test_group_metrics_report_each_group_and_flag_small_ones():
    truth = truth_frame(["a", "a", "b", "b"])
    rows = evaluate.group_metrics(clusters_frame([1, 2, 3, 3]), truth, ["age_band"])
    by_group = {r["group"]: r for r in rows}
    assert by_group["80+"]["split_rate"] == 1.0
    assert by_group["18-39"]["split_rate"] == 0.0
    assert all(r["small_group"] for r in rows)


def test_recall_by_error_ignores_people_with_one_record():
    truth = truth_frame(["a", "a", "b"])
    result = evaluate.recall_by_error(clusters_frame([1, 2, 3]), truth)
    assert result["surname_typo"] == {"records": 1, "linked_share": 0.0}
    assert result["none"]["records"] == 1


def test_pick_threshold_takes_the_lowest_that_reaches_the_target():
    sweep = [
        {"threshold": 0.5, "precision": 0.9},
        {"threshold": 0.9, "precision": 0.996},
        {"threshold": 0.99, "precision": 0.999},
    ]
    assert evaluate.pick_threshold(sweep, 0.995) == 0.9
    assert evaluate.pick_threshold(sweep, 0.9999) is None


@pytest.mark.parametrize(
    ("train", "threshold", "final", "used", "message"),
    [
        ("train/medium", 0.9, False, False, "--final"),
        ("train/medium", None, True, False, "tune population"),
        ("test/medium", 0.9, True, False, "trained on the test"),
        ("train/medium", 0.9, True, True, "already been used"),
    ],
)
def test_final_test_rules_block_misuse(train, threshold, final, used, message):
    with pytest.raises(ValueError, match=message):
        check_final_test_rules("test/medium", train, threshold, final, used)


def test_final_test_rules_allow_a_proper_final_run():
    check_final_test_rules("test/medium", "train/medium", 0.95, True, False)


def test_final_test_rules_do_not_apply_to_other_populations():
    check_final_test_rules("pilot/medium", "pilot/medium", None, False, True)


def records(rows):
    fields = ("unique_id", "nhs_number", "first_name", "surname", "date_of_birth")
    return pd.DataFrame([dict(zip(fields, row, strict=True)) for row in rows])


RULES = [["nhs_number"], ["first_name", "surname", "date_of_birth"]]


def test_baseline_links_on_any_rule_and_transitively():
    frame = records(
        [
            ("a", "111", "ANN", "LEE", "2000-01-01"),
            ("b", "111", "AN", "LEE", "1999-01-01"),
            ("c", None, "AN", "LEE", "1999-01-01"),
            ("d", "222", "BOB", "RAY", "1980-02-02"),
        ]
    )
    result = baseline.deterministic_clusters(frame, RULES).set_index("unique_id")
    assert result.loc["a", "cluster_id"] == result.loc["c", "cluster_id"]
    assert result.loc["d", "cluster_id"] != result.loc["a", "cluster_id"]


def test_baseline_does_not_link_on_missing_values():
    frame = records(
        [
            ("a", None, "ANN", "LEE", None),
            ("b", None, "ANN", "LEE", None),
        ]
    )
    result = baseline.deterministic_clusters(frame, RULES)
    assert result["cluster_id"].nunique() == 2


def test_only_evaluation_reads_the_truth_table():
    code = PROJECT_ROOT / "src" / "patient_linkage" / "linkage"
    for name in ("records.py", "baseline.py", "model.py"):
        text = (code / name).read_text()
        assert "read_truth" not in text
        assert "person_id" not in text
        assert "truth.csv" not in text


@pytest.fixture
def loaded(conn, folder):
    pipeline.run(conn, "t/high", folder, CONFIG)
    return read_records(conn, "t/high")


@pytest.mark.integration
def test_read_records_returns_every_record_with_none_for_missing(loaded):
    assert loaded["unique_id"].is_unique
    assert not loaded["surname"].map(lambda v: v != v).any()


@pytest.mark.integration
def test_read_records_rejects_an_unknown_dataset(conn):
    with pytest.raises(ValueError, match="No staging records"):
        read_records(conn, "t/none")


@pytest.mark.integration
def test_model_trains_scores_and_clusters_every_record(loaded):
    settings = {**SETTINGS, "u_max_pairs": 1e5}
    trained = model.train(loaded, settings)
    linker, pairs = model.score(loaded, trained, settings)
    clusters = model.cluster(linker, pairs, 0.9)
    assert set(clusters["unique_id"]) == set(loaded["unique_id"])
    assert clusters["cluster_id"].nunique() < len(loaded)


@pytest.mark.integration
def test_trained_model_has_learned_parameters(loaded):
    settings = {**SETTINGS, "u_max_pairs": 1e5}
    trained = model.train(loaded, settings)
    levels = trained["comparisons"][3]["comparison_levels"]
    exact = next(level for level in levels if level.get("m_probability"))
    assert 0 < exact["m_probability"] <= 1
    assert 0 < trained["probability_two_random_records_match"] < 1
