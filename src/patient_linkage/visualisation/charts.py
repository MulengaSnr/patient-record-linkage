"""Plotly charts for the dashboard. Each function takes prepared data and a theme."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise
from typing import Any

import pandas as pd
import plotly.graph_objects as go

from patient_linkage.visualisation.metrics import CHECK_LABELS

SOURCES = ("GP", "Hospital", "Lab")
METHODS = ("Splink", "Baseline")
BANDS = ("0.5 to 0.6", "0.6 to 0.7", "0.7 to 0.8", "0.8 to 0.9", "0.9 to 1.0")
HEIGHT = 340


@dataclass(frozen=True)
class Theme:
    """Colours for one display mode."""

    ink: str
    secondary: str
    muted: str
    grid: str
    axis: str
    first: str
    second: str
    third: str
    ramp_low: str
    ramp_high: str

    @property
    def source_colours(self) -> dict[str, str]:
        """Each source keeps its colour, whatever else is on the chart."""
        return dict(zip(SOURCES, (self.first, self.second, self.third), strict=True))

    @property
    def method_colours(self) -> dict[str, str]:
        """Each method keeps its colour, whatever else is on the chart."""
        return dict(zip(METHODS, (self.first, self.second), strict=True))


THEMES = {
    "light": Theme(
        ink="#0b0b0b",
        secondary="#52514e",
        muted="#898781",
        grid="#e1e0d9",
        axis="#c3c2b7",
        first="#2a78d6",
        second="#eb6834",
        third="#1baf7a",
        ramp_low="#cde2fb",
        ramp_high="#0d366b",
    ),
    "dark": Theme(
        ink="#f0efec",
        secondary="#c3c2b7",
        muted="#898781",
        grid="#2c2c2a",
        axis="#383835",
        first="#3987e5",
        second="#d95926",
        third="#199e70",
        ramp_low="#0d366b",
        ramp_high="#cde2fb",
    ),
}


def _layout(theme: Theme, height: int = HEIGHT, **overrides: Any) -> dict[str, Any]:
    axis = {
        "gridcolor": theme.grid,
        "linecolor": theme.axis,
        "zeroline": False,
        "tickfont": {"color": theme.secondary, "size": 12},
        "title": {"font": {"color": theme.secondary, "size": 12}},
        "automargin": True,
    }
    layout = {
        "template": "none",
        "height": height,
        "paper_bgcolor": "rgba(0,0,0,0)",
        "plot_bgcolor": "rgba(0,0,0,0)",
        "font": {"color": theme.secondary, "size": 12},
        "margin": {"l": 8, "r": 16, "t": 36, "b": 8},
        "legend": {
            "orientation": "h",
            "x": 0,
            "y": 1.02,
            "yanchor": "bottom",
            "font": {"color": theme.secondary},
        },
        "xaxis": dict(axis),
        "yaxis": dict(axis),
        "barcornerradius": 4,
        "bargap": 0.35,
        "bargroupgap": 0.08,
        "showlegend": False,
    }
    return layout | overrides


def _merged_axis(base: dict[str, Any], **changes: Any) -> dict[str, Any]:
    return base | changes


def _line(
    x: pd.Series,
    y: pd.Series,
    name: str,
    colour: str,
    theme: Theme,
    value: str,
    labelled: bool = True,
) -> go.Scatter:
    """A 2px line, with its name at the right-hand end if ``labelled``."""
    labels = [""] * (len(x) - 1) + [name if labelled else ""]
    return go.Scatter(
        x=x,
        y=y,
        name=name,
        mode="lines+text",
        text=labels,
        textposition="top left",
        textfont={"color": theme.ink, "size": 12},
        line={"color": colour, "width": 2},
        cliponaxis=False,
        hovertemplate=f"<b>%{{y:{value}}}</b> {name}<extra></extra>",
    )


def _ends_are_apart(ends: list[float], span: float) -> bool:
    """Whether lines finish far enough apart for their labels not to collide."""
    ordered = sorted(ends)
    return all(high - low >= span * 0.08 for low, high in pairwise(ordered))


def _crosshair(figure: go.Figure, theme: Theme) -> None:
    figure.update_layout(hovermode="x unified")
    figure.update_xaxes(
        showspikes=True,
        spikemode="across",
        spikecolor=theme.muted,
        spikethickness=1,
        spikedash="solid",
        spikesnap="cursor",
    )


def people_by_sources(people: pd.DataFrame, theme: Theme) -> go.Figure:
    """People by the combination of systems that hold their records."""
    counts = people["source_combination"].value_counts(ascending=True)
    figure = go.Figure(
        go.Bar(
            x=counts.to_numpy(),
            y=counts.index,
            orientation="h",
            marker={"color": theme.first},
            text=counts.to_numpy(),
            textposition="outside",
            textfont={"color": theme.ink},
            cliponaxis=False,
            hovertemplate="<b>%{x:,}</b> people<br>%{y}<extra></extra>",
        )
    )
    layout = _layout(theme)
    layout["xaxis"] = _merged_axis(
        layout["xaxis"], showgrid=False, showticklabels=False
    )
    layout["yaxis"] = _merged_axis(layout["yaxis"], showgrid=False)
    layout["margin"] = {"l": 8, "r": 40, "t": 8, "b": 8}
    return figure.update_layout(**layout)


def growth(runs: pd.DataFrame, theme: Theme) -> go.Figure:
    """Records and people after each run. Both are counts, so they share an axis."""
    figure = go.Figure(
        [
            _line(runs["run_number"], runs[column], label, colour, theme, ",")
            for column, label, colour in (
                ("records", "Records", theme.first),
                ("people", "People", theme.second),
            )
        ]
    )
    layout = _layout(theme, showlegend=True)
    layout["xaxis"] = _merged_axis(
        layout["xaxis"], title={"text": "Run"}, showgrid=False, range=[1, 30]
    )
    layout["yaxis"] = _merged_axis(layout["yaxis"], rangemode="tozero", tickformat=",")
    figure.update_layout(**layout)
    _crosshair(figure, theme)
    return figure


def quality_matrix(shares: pd.DataFrame, theme: Theme) -> go.Figure:
    """Share affected by check and source. A blank cell is a field not collected."""
    order = list(CHECK_LABELS.values())
    table = (
        shares.assign(label=shares["check_name"].map(CHECK_LABELS))
        .pivot(index="label", columns="source", values="share")
        .reindex(index=order[::-1], columns=list(SOURCES))
    )
    text = table.map(lambda value: "" if pd.isna(value) else f"{value:.1%}")
    figure = go.Figure(
        go.Heatmap(
            # None, not NaN: the widget cannot send NaN to the browser.
            z=table.astype(object).where(table.notna(), None).to_numpy().tolist(),
            x=table.columns,
            y=table.index,
            text=text.to_numpy(),
            texttemplate="%{text}",
            xgap=2,
            ygap=2,
            zmin=0,
            colorscale=[[0, theme.ramp_low], [1, theme.ramp_high]],
            showscale=False,
            hoverongaps=False,
            hovertemplate="<b>%{text}</b> of records<br>%{y}, %{x}<extra></extra>",
        )
    )
    layout = _layout(theme, height=380)
    layout["xaxis"] = _merged_axis(layout["xaxis"], side="top", showgrid=False)
    layout["yaxis"] = _merged_axis(layout["yaxis"], showgrid=False)
    layout["margin"] = {"l": 8, "r": 8, "t": 28, "b": 8}
    return figure.update_layout(**layout)


def daily_share(
    daily: pd.DataFrame, warn_at: float, fail_at: float, theme: Theme
) -> go.Figure:
    """One check's share by day and source, against its warning and failure levels."""
    top = max(float(daily["share"].max()), fail_at) * 1.15
    parts = {
        source: part
        for source in SOURCES
        if not (part := daily[daily["source"] == source].sort_values("batch_day")).empty
    }
    labelled = _ends_are_apart([p["share"].iloc[-1] for p in parts.values()], top)
    figure = go.Figure(
        [
            _line(
                part["batch_day"],
                part["share"],
                source,
                theme.source_colours[source],
                theme,
                ".1%",
                labelled=labelled,
            )
            for source, part in parts.items()
        ]
    )
    for level, label in ((warn_at, "Warning"), (fail_at, "Failure")):
        figure.add_hline(
            y=level,
            line={"color": theme.muted, "width": 1, "dash": "dot"},
            annotation_text=f"{label} at {level:.2%}".replace(".00%", "%"),
            annotation_position="top left",
            annotation_font={"color": theme.secondary, "size": 11},
        )
    layout = _layout(theme, showlegend=True)
    layout["xaxis"] = _merged_axis(
        layout["xaxis"], title={"text": "Simulated day"}, showgrid=False, range=[1, 30]
    )
    layout["yaxis"] = _merged_axis(layout["yaxis"], range=[0, top], tickformat=".2~%")
    figure.update_layout(**layout)
    _crosshair(figure, theme)
    return figure


def pairs_by_band(pairs: pd.DataFrame, theme: Theme) -> go.Figure:
    """Open pairs by match probability. Empty bands stay visible."""
    counts = pairs["probability_band"].value_counts().reindex(BANDS, fill_value=0)
    figure = go.Figure(
        go.Bar(
            x=counts.index,
            y=counts.to_numpy(),
            marker={"color": theme.first},
            text=counts.to_numpy(),
            textposition="outside",
            textfont={"color": theme.ink},
            cliponaxis=False,
            hovertemplate="<b>%{y:,}</b> pairs<br>Probability %{x}<extra></extra>",
        )
    )
    layout = _layout(theme)
    layout["xaxis"] = _merged_axis(
        layout["xaxis"], title={"text": "Match probability"}, showgrid=False
    )
    layout["yaxis"] = _merged_axis(
        layout["yaxis"], showticklabels=False, showgrid=False
    )
    layout["margin"] = {"l": 8, "r": 8, "t": 24, "b": 8}
    return figure.update_layout(**layout)


def pairs_by_source(pairs: pd.DataFrame, theme: Theme) -> go.Figure:
    """Open pairs by the two systems involved."""
    counts = pairs["source_pair"].value_counts(ascending=True)
    figure = go.Figure(
        go.Bar(
            x=counts.to_numpy(),
            y=counts.index,
            orientation="h",
            marker={"color": theme.first},
            text=counts.to_numpy(),
            textposition="outside",
            textfont={"color": theme.ink},
            cliponaxis=False,
            hovertemplate="<b>%{x:,}</b> pairs<br>%{y}<extra></extra>",
        )
    )
    layout = _layout(theme)
    layout["xaxis"] = _merged_axis(
        layout["xaxis"], showgrid=False, showticklabels=False
    )
    layout["yaxis"] = _merged_axis(layout["yaxis"], showgrid=False)
    layout["margin"] = {"l": 8, "r": 40, "t": 8, "b": 8}
    return figure.update_layout(**layout)


def queue_growth(runs: pd.DataFrame, theme: Theme) -> go.Figure:
    """Open review pairs after each run."""
    figure = go.Figure(
        go.Scatter(
            x=runs["run_number"],
            y=runs["open_review_pairs"],
            mode="lines",
            line={"color": theme.first, "width": 2},
            hovertemplate="<b>%{y:,}</b> open pairs<extra></extra>",
        )
    )
    layout = _layout(theme)
    layout["xaxis"] = _merged_axis(
        layout["xaxis"], title={"text": "Run"}, showgrid=False, range=[1, 30]
    )
    layout["yaxis"] = _merged_axis(layout["yaxis"], rangemode="tozero")
    layout["margin"] = {"l": 8, "r": 16, "t": 16, "b": 8}
    figure.update_layout(**layout)
    _crosshair(figure, theme)
    return figure


def metric_by_level(results: pd.DataFrame, metric: str, theme: Theme) -> go.Figure:
    """One metric for each method at each error level."""
    ordered = results.sort_values("level_order")
    figure = go.Figure(
        [
            go.Bar(
                x=part["error_level"].str.capitalize(),
                y=part[metric],
                name=method,
                marker={"color": theme.method_colours[method]},
                text=part[metric].map("{:.1%}".format),
                textposition="outside",
                textfont={"color": theme.ink},
                cliponaxis=False,
                hovertemplate=(
                    f"<b>%{{y:.2%}}</b> {method}<br>%{{x}} errors<extra></extra>"
                ),
            )
            for method in METHODS
            if not (part := ordered[ordered["method"] == method]).empty
        ]
    )
    layout = _layout(theme, showlegend=True, barmode="group")
    layout["xaxis"] = _merged_axis(
        layout["xaxis"], title={"text": "Injected error level"}, showgrid=False
    )
    layout["yaxis"] = _merged_axis(
        layout["yaxis"], rangemode="tozero", tickformat=".0%"
    )
    return figure.update_layout(**layout)


def linked_by_error(errors: pd.DataFrame, theme: Theme) -> go.Figure:
    """Share of records still linked, per injected error, worst for Splink first."""
    named = errors.assign(
        label=errors["injected_error"]
        .str.replace("_", " ")
        .str.capitalize()
        .str.replace("Nhs", "NHS")
        .str.replace("Dob", "Date of birth")
        .replace({"None": "No injected error"})
    )
    splink = named[named["method"] == "Splink"].sort_values("linked_share")
    order = splink["label"].tolist()
    figure = go.Figure(
        [
            go.Bar(
                x=part["linked_share"],
                y=part["label"],
                name=method,
                orientation="h",
                marker={"color": theme.method_colours[method]},
                customdata=part["records"],
                hovertemplate=(
                    f"<b>%{{x:.1%}}</b> {method}<br>"
                    "%{y}, %{customdata:,} records<extra></extra>"
                ),
            )
            for method in METHODS
            if not (part := named[named["method"] == method]).empty
        ]
    )
    layout = _layout(theme, height=620, showlegend=True, barmode="group")
    layout["xaxis"] = _merged_axis(layout["xaxis"], range=[0, 1], tickformat=".0%")
    layout["yaxis"] = _merged_axis(
        layout["yaxis"],
        showgrid=False,
        categoryorder="array",
        categoryarray=order,
        autorange="reversed",  # first category and first method at the top
    )
    return figure.update_layout(**layout)
