import importlib.util

import pandas as pd
import pytest
from shiny import App

from patient_linkage.config import PROJECT_ROOT
from patient_linkage.visualisation import charts, metrics

TABLES = metrics.load_tables()
DQ = TABLES["dq_checks"]
PEOPLE = TABLES["dim_people"]
RUNS = TABLES["run_history"]
QUEUE = TABLES["review_queue"]
RESULTS = TABLES["linkage_results"]
ERRORS = TABLES["recall_by_error"]
THEMES = list(charts.THEMES.values())


def checks(rows):
    columns = [
        "batch_day",
        "source",
        "check_name",
        "check_type",
        "latest_attempt",
        "affected_records",
        "records_in_batch",
        "status",
    ]
    return pd.DataFrame(rows, columns=columns)


def share_for(source, check):
    shares = metrics.share_affected(DQ, ["source", "check_name"])
    row = shares[(shares["source"] == source) & (shares["check_name"] == check)]
    return float(row["share"].iloc[0])


def test_figures_match_the_published_totals():
    position = metrics.position_after(RUNS, int(RUNS["run_number"].max()))
    assert position.records == len(TABLES["fact_records"]) == 2507
    assert position.people == len(PEOPLE) == 1213
    assert round(position.records_per_person, 2) == 2.07
    assert position.merged_so_far == 33
    assert (PEOPLE["records"] > 1).sum() == 870
    assert (PEOPLE["conflicting_nhs_numbers"] == "Yes").sum() == 3
    assert metrics.warning_count(DQ) == 31
    assert len(metrics.stopped_loads(DQ)) == 1
    assert round(share_for("GP", "missing_postcode"), 3) == 0.274
    assert round(share_for("Hospital", "missing_postcode"), 3) == 0.328
    assert len(QUEUE) == 255


def test_position_counts_merges_only_up_to_that_run():
    runs = pd.DataFrame(
        {
            "run_number": [1, 2, 3],
            "records": [10, 20, 30],
            "people": [10, 10, 15],
            "merged": [1, 2, 4],
        }
    )
    position = metrics.position_after(runs, 2)
    assert (position.records, position.people, position.merged_so_far) == (20, 10, 3)
    assert position.records_per_person == 2


def test_share_is_weighted_by_batch_size():
    frame = checks(
        [
            (1, "GP", "c", "Share", "Yes", 1, 2, "OK"),
            (2, "GP", "c", "Share", "Yes", 0, 98, "OK"),
        ]
    )
    result = metrics.share_affected(frame, ["source"])
    assert result["share"].iloc[0] == pytest.approx(0.01)  # a plain average gives 0.25


def test_share_ignores_replaced_attempts_and_counts():
    frame = checks(
        [
            (12, "GP", "c", "Share", "No", 38, 38, "FAIL"),
            (12, "GP", "c", "Share", "Yes", 0, 38, "OK"),
            (12, "GP", "record_count", "Count", "Yes", None, 38, "OK"),
        ]
    )
    result = metrics.share_affected(frame, ["source"])
    assert result["affected"].iloc[0] == 0
    assert result["records"].iloc[0] == 38


def test_stopped_loads_keep_attempts_that_were_later_corrected():
    frame = checks(
        [
            (12, "GP", "c", "Share", "No", 38, 38, "FAIL"),
            (12, "GP", "c", "Share", "Yes", 0, 38, "OK"),
        ]
    ).assign(attempt=[1, 2])
    assert metrics.stopped_loads(frame)["attempt"].tolist() == [1]


@pytest.mark.parametrize("theme", THEMES)
def test_every_chart_builds_in_both_themes(theme):
    shares = metrics.share_affected(DQ, ["source", "check_name"])
    daily = metrics.share_affected(
        DQ[DQ["check_name"] == "missing_postcode"], ["source", "batch_day"]
    )
    figures = [
        charts.people_by_sources(PEOPLE, theme),
        charts.growth(RUNS, theme),
        charts.quality_matrix(shares, theme),
        charts.daily_share(daily, 0.4, 0.6, theme),
        charts.pairs_by_band(QUEUE, theme),
        charts.pairs_by_source(QUEUE, theme),
        charts.queue_growth(RUNS, theme),
        charts.metric_by_level(RESULTS, "recall", theme),
        charts.linked_by_error(ERRORS[ERRORS["error_level"] == "high"], theme),
    ]
    assert all(figure.data for figure in figures)


def test_matrix_sends_nulls_for_fields_a_source_does_not_collect():
    # The widget cannot serialise NaN, and one NaN ends the whole session.
    shares = metrics.share_affected(DQ, ["source", "check_name"])
    figure = charts.quality_matrix(shares, THEMES[0])
    row = list(figure.data[0].y).index("Missing address")
    lab = list(figure.data[0].x).index("Lab")
    assert figure.data[0].z[row][lab] is None


def test_source_keeps_its_colour_when_another_is_absent():
    theme = THEMES[0]
    daily = pd.DataFrame(
        {"source": ["Hospital", "Lab"], "batch_day": [1, 1], "share": [0.1, 0.2]}
    )
    figure = charts.daily_share(daily, 0.4, 0.6, theme)
    assert {trace.name: trace.line.color for trace in figure.data} == {
        "Hospital": theme.second,
        "Lab": theme.third,
    }


@pytest.mark.parametrize(
    ("ends", "labelled"), [((0.1, 0.5), True), ((0.0, 0.0), False)]
)
def test_line_end_labels_are_dropped_when_they_would_collide(ends, labelled):
    daily = pd.DataFrame(
        {
            "source": ["GP", "GP", "Lab", "Lab"],
            "batch_day": [1, 2, 1, 2],
            "share": [0.2, ends[0], 0.2, ends[1]],
        }
    )
    figure = charts.daily_share(daily, 0.4, 0.6, THEMES[0])
    assert all((trace.text[-1] != "") is labelled for trace in figure.data)


def test_empty_probability_bands_stay_on_the_axis():
    pairs = pd.DataFrame({"probability_band": ["0.5 to 0.6"]})
    figure = charts.pairs_by_band(pairs, THEMES[0])
    assert tuple(figure.data[0].x) == charts.BANDS
    assert list(figure.data[0].y) == [1, 0, 0, 0, 0]


def test_recall_chart_runs_from_low_to_high():
    figure = charts.metric_by_level(RESULTS, "recall", THEMES[0])
    assert list(figure.data[0].x) == ["Low", "Medium", "High"]


def test_app_module_loads():
    spec = importlib.util.spec_from_file_location(
        "dashboard_app", PROJECT_ROOT / "app" / "app.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert isinstance(module.app, App)
