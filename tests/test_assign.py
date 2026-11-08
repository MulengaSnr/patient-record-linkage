import numpy as np
import pandas as pd
import pytest

from patient_linkage.config import PROJECT_ROOT, load_config
from patient_linkage.linkage import assign, model, publish
from patient_linkage.linkage.records import read_records
from patient_linkage.warehouse import pipeline

CONFIG = load_config()
SETTINGS = {**CONFIG["linkage"], "u_max_pairs": 1e5}


def clusters(groups):
    return pd.DataFrame(
        [
            {"unique_id": record, "cluster_id": label}
            for label, members in groups.items()
            for record in members
        ]
    )


def events(result, kind):
    return [(e.person_key, e.related_key) for e in result.events if e.event == kind]


def test_first_run_creates_a_key_per_cluster():
    result = assign.assign_keys(clusters({9: ["a", "b"], 3: ["c"]}), {}, 1)
    assert result.record_keys == {"a": "P00000001", "b": "P00000001", "c": "P00000002"}
    assert len(events(result, "created")) == 2
    assert result.next_number == 3
    assert result.moved_records == 0


def test_rerun_with_new_cluster_ids_keeps_every_key():
    previous = {"a": "P00000001", "b": "P00000001", "c": "P00000002"}
    result = assign.assign_keys(clusters({77: ["c"], 12: ["a", "b"]}), previous, 3)
    assert result.record_keys == previous
    assert result.events == []
    assert result.moved_records == 0


def test_a_new_record_joins_the_existing_person():
    previous = {"a": "P00000001"}
    result = assign.assign_keys(clusters({1: ["a", "b"]}), previous, 2)
    assert result.record_keys["b"] == "P00000001"
    assert result.events == []


def test_merge_keeps_the_key_with_more_records():
    previous = {"a": "P00000002", "b": "P00000002", "c": "P00000001"}
    result = assign.assign_keys(clusters({1: ["a", "b", "c"]}), previous, 3)
    assert set(result.record_keys.values()) == {"P00000002"}
    assert events(result, "merged") == [("P00000001", "P00000002")]
    assert result.moved_records == 1


def test_a_tied_merge_keeps_the_lower_key():
    previous = {"a": "P00000002", "b": "P00000001"}
    result = assign.assign_keys(clusters({1: ["a", "b"]}), previous, 3)
    assert set(result.record_keys.values()) == {"P00000001"}


def test_split_gives_the_larger_part_the_old_key():
    previous = {"a": "P00000001", "b": "P00000001", "c": "P00000001"}
    result = assign.assign_keys(clusters({1: ["a"], 2: ["b", "c"]}), previous, 2)
    assert result.record_keys["b"] == result.record_keys["c"] == "P00000001"
    assert result.record_keys["a"] == "P00000002"
    assert events(result, "split") == [("P00000002", "P00000001")]
    assert result.moved_records == 1


def test_a_key_is_never_shared_between_clusters():
    previous = {r: "P00000001" for r in "abcd"}
    result = assign.assign_keys(clusters({1: ["a", "b"], 2: ["c", "d"]}), previous, 2)
    assert len(set(result.record_keys.values())) == 2


def test_merge_and_split_together():
    previous = {"a": "P1", "b": "P1", "c": "P2", "d": "P2", "e": "P2"}
    result = assign.assign_keys(
        clusters({1: ["a", "c"], 2: ["b"], 3: ["d", "e"]}), previous, 5
    )
    assert result.record_keys["d"] == "P2"
    assert result.record_keys["a"] == "P1"
    assert result.record_keys["b"] == "P00000005"


def test_assignment_does_not_depend_on_input_order():
    previous = {"a": "P00000001", "b": "P00000002", "c": "P00000002"}
    frame = clusters({1: ["a", "b"], 2: ["c", "d"], 3: ["e"]})
    first = assign.assign_keys(frame, previous, 3)
    shuffled = frame.sample(frac=1, random_state=np.random.RandomState(4))
    second = assign.assign_keys(shuffled, previous, 3)
    assert first == second


def test_a_run_may_not_lose_assigned_records():
    with pytest.raises(ValueError, match="missing from this run"):
        assign.assign_keys(clusters({1: ["a"]}), {"a": "P1", "b": "P1"}, 2)


def test_keys_reveal_nothing_about_the_person():
    assert assign.format_key(42) == "P00000042"


def pair_frame(rows):
    return pd.DataFrame(
        rows, columns=["unique_id_l", "unique_id_r", "match_probability"]
    )


def test_review_keeps_only_unlinked_pairs_in_the_band_most_likely_first():
    pairs = pair_frame(
        [
            ("a", "b", 0.60),
            ("c", "d", 0.80),
            ("a", "x", 0.40),
            ("e", "f", 0.99),
            ("g", "h", 0.70),
        ]
    )
    frame = clusters(
        {1: ["a"], 2: ["b"], 3: ["c"], 4: ["d"], 5: ["x"], 6: ["e", "f"], 7: ["g", "h"]}
    )
    result = assign.review_pairs(pairs, frame, 0.5, 0.95)
    assert result["unique_id_l"].tolist() == ["c", "a"]


def test_review_boundaries_include_lower_and_exclude_threshold():
    pairs = pair_frame([("a", "b", 0.5), ("c", "d", 0.95)])
    frame = clusters({1: ["a"], 2: ["b"], 3: ["c"], 4: ["d"]})
    assert assign.review_pairs(pairs, frame, 0.5, 0.95)["unique_id_l"].tolist() == ["a"]


def test_publishing_code_never_reads_the_truth_table():
    code = PROJECT_ROOT / "src" / "patient_linkage" / "linkage"
    for name in ("assign.py", "publish.py"):
        text = (code / name).read_text()
        assert "read_truth" not in text and "person_id" not in text


def write(conn, dataset, groups, pairs=None, threshold=0.9):
    frame = clusters(groups)
    records = frame.assign(source="gp").rename(columns={"cluster_id": "_"})
    empty = pair_frame([])
    return publish.publish(
        conn, dataset, records, frame, empty if pairs is None else pairs, threshold, 0.5
    )


def keys(conn, dataset="d"):
    rows = conn.execute(
        "SELECT record_id, person_key FROM linked.record_people WHERE dataset = %s",
        (dataset,),
    )
    return dict(rows.fetchall())


@pytest.mark.integration
def test_published_keys_survive_a_rerun(conn):
    write(conn, "d", {1: ["a", "b"], 2: ["c"]})
    first = keys(conn)
    summary = write(conn, "d", {50: ["c"], 60: ["a", "b"]})
    assert keys(conn) == first
    assert summary.moved_records == 0 and summary.created == 0


@pytest.mark.integration
def test_new_keys_continue_the_sequence(conn):
    write(conn, "d", {1: ["a"]})
    write(conn, "d", {1: ["a"], 2: ["b"]})
    assert keys(conn)["b"] == "P00000002"


@pytest.mark.integration
def test_datasets_have_independent_keys(conn):
    write(conn, "one", {1: ["a"]})
    write(conn, "two", {1: ["a"]})
    assert keys(conn, "one")["a"] == keys(conn, "two")["a"] == "P00000001"


@pytest.mark.integration
def test_merged_keys_redirect_to_the_surviving_key(conn):
    write(conn, "d", {1: ["a", "b"], 2: ["c"]})
    write(conn, "d", {1: ["a", "b", "c"]})
    row = conn.execute(
        "SELECT merged_into FROM linked.people WHERE person_key = 'P00000002'"
    ).fetchone()
    assert row[0] == "P00000001"


@pytest.mark.integration
def test_a_chain_of_merges_points_at_the_final_key(conn):
    write(conn, "d", {1: ["a", "b", "c"], 2: ["d", "e"], 3: ["f"]})
    write(conn, "d", {1: ["a", "b", "c"], 2: ["d", "e", "f"]})
    write(conn, "d", {1: ["a", "b", "c", "d", "e", "f"]})
    targets = conn.execute(
        "SELECT merged_into FROM linked.people WHERE status = 'merged'"
    ).fetchall()
    assert targets == [("P00000001",), ("P00000001",)]


@pytest.mark.integration
def test_review_queue_fills_and_refreshes(conn):
    pairs = pair_frame([("a", "b", 0.7)])
    first = write(conn, "d", {1: ["a"], 2: ["b"]}, pairs)
    assert first.open_review_pairs == 1
    second = write(conn, "d", {1: ["a", "b"]})
    assert second.open_review_pairs == 0


@pytest.mark.integration
def test_a_decided_review_pair_is_not_reopened(conn):
    pairs = pair_frame([("a", "b", 0.7)])
    write(conn, "d", {1: ["a"], 2: ["b"]}, pairs)
    conn.execute(
        "UPDATE linked.review_queue SET status = 'non_match', decided_at = now()"
    )
    summary = write(conn, "d", {1: ["a"], 2: ["b"]}, pairs)
    assert summary.open_review_pairs == 0
    assert (
        conn.execute("SELECT status FROM linked.review_queue").fetchone()[0]
        == "non_match"
    )


@pytest.mark.integration
def test_a_failed_publish_changes_nothing(conn):
    write(conn, "d", {1: ["a", "b"]})
    conn.commit()
    first = keys(conn)
    with pytest.raises(ValueError, match="missing from this run"):
        write(conn, "d", {1: ["a"]})
    conn.rollback()
    assert keys(conn) == first


@pytest.mark.integration
def test_run_is_logged(conn):
    summary = write(conn, "d", {1: ["a", "b"], 2: ["c"]})
    row = conn.execute("SELECT records, people, created FROM linked.runs").fetchone()
    assert row == (3, 2, 2)
    assert summary.people == 2


@pytest.fixture
def trained(conn, folder):
    pipeline.run(conn, "t/high", folder, CONFIG)
    return model.train(read_records(conn, "t/high"), SETTINGS)


@pytest.mark.integration
def test_every_record_gets_exactly_one_person_key(conn, trained):
    publish.link_and_publish(conn, "t/high", trained, 0.95, SETTINGS)
    missing = conn.execute(
        """
        SELECT count(*) FROM staging.records s
        LEFT JOIN linked.record_people p
          ON p.dataset = s.dataset AND p.record_id = s.record_id
        WHERE s.dataset = 't/high' AND p.person_key IS NULL
        """
    ).fetchone()[0]
    assert missing == 0


@pytest.mark.integration
def test_relinking_the_same_data_changes_no_keys(conn, trained):
    publish.link_and_publish(conn, "t/high", trained, 0.95, SETTINGS)
    first = keys(conn, "t/high")
    summary = publish.link_and_publish(conn, "t/high", trained, 0.95, SETTINGS)
    assert keys(conn, "t/high") == first
    assert summary.moved_records == 0


@pytest.mark.integration
def test_later_batches_can_be_linked_after_earlier_ones(conn, trained):
    early = publish.link_and_publish(
        conn, "t/high", trained, 0.95, SETTINGS, through_day=15
    )
    later = publish.link_and_publish(conn, "t/high", trained, 0.95, SETTINGS)
    assert later.records > early.records
