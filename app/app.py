"""Interactive dashboard over the exported marts. Run it with ``make app``."""

from __future__ import annotations

from typing import Any

from shiny import App, reactive, render, ui
from shinywidgets import output_widget, render_plotly

from patient_linkage.visualisation import charts, metrics
from patient_linkage.visualisation.metrics import CHECK_LABELS

TABLES = metrics.load_tables()
DQ = TABLES["dq_checks"]
PEOPLE = TABLES["dim_people"]
RUNS = TABLES["run_history"]
QUEUE = TABLES["review_queue"]
RESULTS = TABLES["linkage_results"]
ERRORS = TABLES["recall_by_error"]
LAST_RUN = int(RUNS["run_number"].max())
ALL_PAIRS = "All source pairs"
TABLE_HEIGHT = "320px"

STYLE = """
:root[data-bs-theme="light"] { --bs-body-bg: #fcfcfb; --bs-card-bg: #fcfcfb; }
:root[data-bs-theme="dark"] { --bs-body-bg: #1a1a19; --bs-card-bg: #1a1a19; }
.filters { display: flex; flex-wrap: wrap; gap: 24px; margin-bottom: 8px; }
.filters .form-group, .filters .shiny-input-container { margin-bottom: 0; }
.bslib-value-box .value-box-title { font-size: 0.9rem; }
.page-note { color: var(--bs-secondary-color); margin-bottom: 12px; }
"""


def chart_card(title: str, widget: str, note: str | None = None) -> Any:
    """A titled chart that can be expanded to full screen."""
    parts = [ui.card_header(title), output_widget(widget)]
    if note:
        parts.append(ui.card_footer(note))
    return ui.card(*parts, full_screen=True)


def table_panel(table: str) -> Any:
    """The figures behind a page, so nothing depends on reading a chart."""
    return ui.accordion(
        ui.accordion_panel("Data table", ui.output_data_frame(table)),
        open=False,
    )


def tile(title: str, output: str) -> Any:
    """A headline number."""
    return ui.value_box(title, ui.output_text(output))


overview = ui.nav_panel(
    "Overview",
    ui.p(
        "How many people are behind these records? The pilot population was "
        "loaded and linked once a day for 30 simulated days.",
        class_="page-note",
    ),
    ui.div(
        ui.input_slider(
            "through_run",
            "Show the position after run",
            min=1,
            max=LAST_RUN,
            value=LAST_RUN,
            step=1,
            width="360px",
            animate=True,
        ),
        class_="filters",
    ),
    ui.layout_columns(
        tile("Records", "records"),
        tile("People", "people"),
        tile("Records per person", "records_per_person"),
        tile("Person keys merged so far", "merged"),
        col_widths={"sm": 6, "lg": 3},
    ),
    ui.layout_columns(
        chart_card("Records and people after each run", "growth"),
        chart_card(
            "People by the systems holding their records",
            "people_by_sources",
            f"After run {LAST_RUN}. "
            f"{int((PEOPLE['records'] > 1).sum()):,} of {len(PEOPLE):,} people have "
            "more than one record.",
        ),
        col_widths={"sm": 12, "lg": 6},
    ),
    table_panel("overview_table"),
)

quality = ui.nav_panel(
    "Data quality",
    ui.p(
        "Can each feed be trusted? Shares use the load that was finally accepted "
        "for each day, weighted by batch size.",
        class_="page-note",
    ),
    ui.layout_columns(
        tile("Warnings", "warnings"),
        tile("Loads stopped by the gate", "stopped"),
        col_widths={"sm": 6, "lg": 3},
    ),
    ui.layout_columns(
        chart_card(
            "Share of records affected, by feed",
            "quality_matrix",
            "A blank cell means that feed does not collect the field.",
        ),
        ui.card(
            ui.card_header("One check by feed and simulated day"),
            ui.input_select(
                "check",
                "Check",
                {name: label for name, label in CHECK_LABELS.items()},
                selected="missing_postcode",
                width="300px",
            ),
            output_widget("daily_share"),
            full_screen=True,
        ),
        col_widths={"sm": 12, "lg": 6},
    ),
    ui.card(
        ui.card_header("What the gate stopped"),
        ui.output_data_frame("stopped_table"),
        ui.card_footer(
            "A deliberately corrupted GP file. It was stopped, corrected and "
            "reloaded, so it does not appear in the shares above."
        ),
    ),
    table_panel("quality_table"),
)

review = ui.nav_panel(
    "Review queue",
    ui.p(
        "What is left for a person to check? These pairs scored between 0.5 and "
        "the 0.99 linking threshold and were not linked.",
        class_="page-note",
    ),
    ui.div(
        ui.input_select(
            "source_pair",
            "Source pair",
            [ALL_PAIRS, *sorted(QUEUE["source_pair"].unique())],
            width="300px",
        ),
        class_="filters",
    ),
    ui.layout_columns(
        tile("Open review pairs", "open_pairs"),
        tile("People with conflicting NHS numbers", "conflicts"),
        col_widths={"sm": 6, "lg": 3},
    ),
    ui.layout_columns(
        chart_card("Open pairs by match probability", "pairs_by_band"),
        chart_card("Open pairs by source", "pairs_by_source"),
        chart_card("Open pairs after each run", "queue_growth"),
        col_widths={"sm": 12, "lg": 4},
    ),
    table_panel("review_table"),
)

model = ui.nav_panel(
    "Model results",
    ui.p(
        "Is the model better than the rules? Held-out test population of "
        f"{int(RESULTS['people'].iloc[0]):,} people, separate from the 30-day "
        "pilot on the other pages.",
        class_="page-note",
    ),
    ui.layout_columns(
        chart_card("True matches found (recall)", "recall"),
        chart_card("People whose records stayed split", "split_rate"),
        col_widths={"sm": 12, "lg": 6},
    ),
    ui.card(
        ui.card_header("Records still linked to their person, by injected error"),
        ui.input_select(
            "level",
            "Error level",
            {"low": "Low", "medium": "Medium", "high": "High"},
            selected="high",
            width="200px",
        ),
        output_widget("linked_by_error"),
        full_screen=True,
    ),
    table_panel("model_table"),
)

app_ui = ui.page_navbar(
    overview,
    quality,
    review,
    model,
    ui.nav_spacer(),
    ui.nav_control(ui.input_dark_mode(id="mode")),
    title="Patient record linkage",
    header=ui.tags.style(STYLE),
    footer=ui.p(
        "Synthetic data: no real patients.",
        class_="text-center page-note mt-3",
    ),
    window_title="Patient record linkage",
)


def grid(frame: Any) -> render.DataGrid:
    """A table sized to sit inside a page."""
    return render.DataGrid(frame, width="100%", height=TABLE_HEIGHT)


def server(input: Any, output: Any, session: Any) -> None:  # noqa: A002, ARG001
    """Connect the filters to the tiles, charts and tables."""

    @reactive.calc
    def theme() -> charts.Theme:
        return charts.THEMES[input.mode() or "light"]

    @reactive.calc
    def runs_so_far() -> Any:
        return RUNS[RUNS["run_number"] <= input.through_run()]

    @reactive.calc
    def position() -> metrics.RunPosition:
        return metrics.position_after(RUNS, input.through_run())

    @reactive.calc
    def pairs() -> Any:
        chosen = input.source_pair()
        return QUEUE if chosen == ALL_PAIRS else QUEUE[QUEUE["source_pair"] == chosen]

    @render.text
    def records() -> str:
        return f"{position().records:,}"

    @render.text
    def people() -> str:
        return f"{position().people:,}"

    @render.text
    def records_per_person() -> str:
        return f"{position().records_per_person:.2f}"

    @render.text
    def merged() -> str:
        return f"{position().merged_so_far:,}"

    @render.text
    def warnings() -> str:
        return f"{metrics.warning_count(DQ):,}"

    @render.text
    def stopped() -> str:
        return f"{len(metrics.stopped_loads(DQ)):,}"

    @render.text
    def open_pairs() -> str:
        return f"{len(pairs()):,}"

    @render.text
    def conflicts() -> str:
        return f"{(PEOPLE['conflicting_nhs_numbers'] == 'Yes').sum():,}"

    @render_plotly
    def growth() -> Any:
        return charts.growth(runs_so_far(), theme())

    @render_plotly
    def people_by_sources() -> Any:
        return charts.people_by_sources(PEOPLE, theme())

    @render_plotly
    def quality_matrix() -> Any:
        shares = metrics.share_affected(DQ, ["source", "check_name"])
        return charts.quality_matrix(shares, theme())

    @render_plotly
    def daily_share() -> Any:
        check = input.check()
        chosen = DQ[DQ["check_name"] == check]
        daily = metrics.share_affected(chosen, ["source", "batch_day"])
        warn_at, fail_at = metrics.thresholds(DQ, check)
        return charts.daily_share(daily, warn_at, fail_at, theme())

    @render_plotly
    def pairs_by_band() -> Any:
        return charts.pairs_by_band(pairs(), theme())

    @render_plotly
    def pairs_by_source() -> Any:
        return charts.pairs_by_source(pairs(), theme())

    @render_plotly
    def queue_growth() -> Any:
        return charts.queue_growth(RUNS, theme())

    @render_plotly
    def recall() -> Any:
        return charts.metric_by_level(RESULTS, "recall", theme())

    @render_plotly
    def split_rate() -> Any:
        return charts.metric_by_level(RESULTS, "split_rate", theme())

    @render_plotly
    def linked_by_error() -> Any:
        chosen = ERRORS[ERRORS["error_level"] == input.level()]
        return charts.linked_by_error(chosen, theme())

    @render.data_frame
    def overview_table() -> render.DataGrid:
        return grid(
            runs_so_far()[
                ["run_number", "records", "people", "created", "merged", "split"]
            ]
        )

    @render.data_frame
    def stopped_table() -> render.DataGrid:
        stopped_rows = metrics.stopped_loads(DQ).assign(
            check_name=lambda frame: frame["check_name"].map(CHECK_LABELS)
        )
        return render.DataGrid(
            stopped_rows.rename(
                columns={
                    "batch_day": "Simulated day",
                    "attempt": "Attempt",
                    "source": "Feed",
                    "check_name": "Check",
                    "affected_records": "Records affected",
                    "records_in_batch": "Records in batch",
                }
            ),
            width="100%",
        )

    @render.data_frame
    def quality_table() -> render.DataGrid:
        shares = metrics.share_affected(DQ, ["source", "check_name"])
        return grid(shares.round({"share": 4}))

    @render.data_frame
    def review_table() -> render.DataGrid:
        columns = ["left_id", "right_id", "source_pair", "match_probability"]
        return grid(
            pairs()[columns]
            .sort_values("match_probability", ascending=False)
            .round({"match_probability": 3})
        )

    @render.data_frame
    def model_table() -> render.DataGrid:
        columns = [
            "error_level",
            "method",
            "precision",
            "recall",
            "f1",
            "split_rate",
            "false_merge_rate",
        ]
        return grid(RESULTS.sort_values(["level_order", "method"])[columns].round(4))


app = App(app_ui, server)
