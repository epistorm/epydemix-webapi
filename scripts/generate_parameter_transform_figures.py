"""Generate SVG figures for the Parameter Transforms guide.

Produces one figure per transform method matching the worked examples in
``web/docs/guides/parameter-transforms.mdx``:

- ``seasonality.svg`` — Balcan multiplier × baseline = 0.3, max=1, min=0.1,
  peak Jan 15 / trough Jul 15 over the 2024 calendar year.
- ``scale.svg`` — baseline 0.1 with factor=0.5 inside [Mar 1, Apr 1], yielding
  0.05 in-window and 0.1 outside.
- ``override.svg`` — baseline 0.3 with override 0.1 inside [Mar 1, Apr 1].

Re-run whenever the worked examples in the docs change.

Usage:
    uv run python scripts/generate_parameter_transform_figures.py
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np

# Prefer Helvetica/Arial; fall back to whatever sans-serif is available.
matplotlib.rcParams["font.family"] = "sans-serif"
matplotlib.rcParams["font.sans-serif"] = [
    "Helvetica",
    "Arial",
    "Liberation Sans",
    "DejaVu Sans",
]

from app.utils.scaling import get_scaled_parameter
from app.utils.seasonality import get_seasonal_transmission_balcan

OUT_DIR = Path(__file__).resolve().parents[1] / "web" / "static" / "img" / "parameter-transforms"

DATE_START = dt.date(2024, 1, 1)
DATE_STOP = dt.date(2024, 12, 31)
WINDOW_START = dt.date(2024, 3, 1)
WINDOW_STOP = dt.date(2024, 4, 1)


def _format_axes(
    ax, title: str, ylabel: str, baseline: float | None = None, ymax: float | None = None
) -> None:
    ax.set_title(title, fontsize=11)
    ax.set_ylabel(ylabel)
    ax.xaxis.set_major_locator(mdates.MonthLocator(bymonth=[1, 4, 7, 10]))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b"))
    ax.grid(True, linewidth=0.3, alpha=0.5)
    if baseline is not None:
        ax.axhline(
            baseline,
            color="gray",
            linewidth=0.8,
            linestyle="--",
            alpha=0.7,
            label=f"Baseline = {baseline}",
        )
    if ymax is not None:
        ax.set_ylim(0, ymax)


def _save(fig, name: str) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / name
    fig.savefig(out, format="svg", bbox_inches="tight")
    plt.close(fig)
    print(f"wrote {out.relative_to(Path.cwd())}")


def make_seasonality_figure() -> None:
    """Balcan multiplier × baseline. Matches the Seasonality example in the doc."""
    baseline = 0.3
    val_max, val_min = 1.0, 0.1
    date_tmax = dt.date(2024, 1, 15)
    date_tmin = dt.date(2024, 7, 15)

    dates_arr, multiplier = get_seasonal_transmission_balcan(
        date_start=DATE_START,
        date_stop=DATE_STOP,
        date_tmax=date_tmax,
        val_min=val_min,
        val_max=val_max,
        date_tmin=date_tmin,
    )
    dates = [d.astype("datetime64[D]").astype(dt.date) for d in dates_arr]
    effective = baseline * np.array(multiplier)

    fig, ax = plt.subplots(figsize=(7, 3.5), constrained_layout=True)
    ax.plot(
        dates, effective, color="tab:purple", linewidth=2.0, label="Effective transmission_rate"
    )
    ax.axvline(date_tmax, color="black", linewidth=0.7, linestyle="--", alpha=0.45)
    ax.axvline(date_tmin, color="black", linewidth=0.7, linestyle=":", alpha=0.45)
    _format_axes(
        ax,
        "Seasonality: baseline 0.3, max=1, min=0.1",
        "transmission_rate",
        baseline=baseline,
        ymax=baseline * val_max * 1.15,
    )
    # Place date labels at the top of each vertical line, inside the plot area.
    y_top = ax.get_ylim()[1]
    label_y = y_top - 0.02 * (y_top - ax.get_ylim()[0])
    ax.text(
        date_tmax,
        label_y,
        "Jan 15 (max)",
        va="top",
        ha="center",
        fontsize=8,
        alpha=0.75,
        bbox=dict(facecolor="white", edgecolor="none", pad=1.5),
    )
    ax.text(
        date_tmin,
        label_y,
        "Jul 15 (min)",
        va="top",
        ha="center",
        fontsize=8,
        alpha=0.75,
        bbox=dict(facecolor="white", edgecolor="none", pad=1.5),
    )
    ax.legend(loc="upper right", fontsize=9)
    _save(fig, "seasonality.svg")


def make_scale_figure() -> None:
    """Constant scaling inside a window. Matches the Scale example in the doc."""
    baseline = 0.1
    factor = 0.5

    dates_arr, multiplier = get_scaled_parameter(
        date_start=DATE_START,
        date_stop=DATE_STOP,
        scaling_start=WINDOW_START,
        scaling_stop=WINDOW_STOP,
        scaling_factor=factor,
    )
    dates = [d.astype("datetime64[D]").astype(dt.date) for d in dates_arr]
    effective = baseline * np.array(multiplier)

    fig, ax = plt.subplots(figsize=(7, 3.5), constrained_layout=True)
    ax.plot(dates, effective, color="tab:green", linewidth=2.0, label="Effective transmission_rate")
    ax.axvspan(WINDOW_START, WINDOW_STOP, color="tab:green", alpha=0.08, label="Scaling window")
    _format_axes(
        ax,
        "Scale: baseline 0.1, factor=0.5 in [Mar 1, Apr 1]",
        "transmission_rate",
        baseline=baseline,
        ymax=baseline * 1.4,
    )
    ax.legend(loc="upper right", fontsize=9)
    _save(fig, "scale.svg")


def make_override_figure() -> None:
    """Absolute replacement inside a window. Matches the Override example in the doc."""
    baseline = 0.3
    override_value = 0.1

    dates_arr, _ = get_scaled_parameter(
        date_start=DATE_START,
        date_stop=DATE_STOP,
        scaling_start=WINDOW_START,
        scaling_stop=WINDOW_STOP,
        scaling_factor=1.0,  # placeholder; we just want the date grid
    )
    dates = [d.astype("datetime64[D]").astype(dt.date) for d in dates_arr]
    effective = np.full(len(dates), baseline)
    in_window = np.array([WINDOW_START <= d <= WINDOW_STOP for d in dates])
    effective[in_window] = override_value

    fig, ax = plt.subplots(figsize=(7, 3.5), constrained_layout=True)
    ax.plot(dates, effective, color="tab:red", linewidth=2.0, label="Effective transmission_rate")
    ax.axvspan(WINDOW_START, WINDOW_STOP, color="tab:red", alpha=0.08, label="Override window")
    _format_axes(
        ax,
        "Override: baseline 0.3, value=0.1 in [Mar 1, Apr 1]",
        "transmission_rate",
        baseline=baseline,
        ymax=baseline * 1.4,
    )
    ax.legend(loc="upper right", fontsize=9)
    _save(fig, "override.svg")


def main() -> None:
    make_seasonality_figure()
    make_scale_figure()
    make_override_figure()


if __name__ == "__main__":
    main()
