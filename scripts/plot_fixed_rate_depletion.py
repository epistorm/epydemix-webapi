"""Generate figure for the Fixed rate (per-day hazard) section of the Campaigns guide.

Produces ``fixed-rate-depletion.svg``: the same V-SEIHR run as the flat-count
plot, but driven by a ``fixed_rate`` campaign at a hazard rate chosen so the
initial per-day delivery matches the flat-count budget. Shows how the
per-day delivered count tapers smoothly as the susceptible pool shrinks,
contrasting with flat_count's hard cliff.

Re-run whenever the worked example in the docs changes.

Usage:
    uv run python scripts/plot_fixed_rate_depletion.py
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np

matplotlib.rcParams["font.family"] = "sans-serif"
matplotlib.rcParams["font.sans-serif"] = [
    "Helvetica",
    "Arial",
    "Liberation Sans",
    "DejaVu Sans",
]

from fastapi.testclient import TestClient

from app.main import app

OUT_DIR = Path(__file__).resolve().parents[1] / "web" / "static" / "img" / "vaccination"

N_POP = 1_000_000.0
START = "2025-01-01"
END = "2025-10-31"
C_START = "2025-02-01"
C_END = "2025-10-15"
# Rate chosen so initial per-day delivery (rate * S0) matches the flat-count
# plot's 5,000/day budget, making the two plots directly comparable.
RATE = 0.005
NSIM = 100
SEED = 11

REQUEST = {
    "model": {
        "preset": "V-SEIR",
        "parameters": {
            "R0": 1.4,
            "incubation_period": 3.0,
            "infectious_period": 2.5,
            "VE_S": 0.85,
        },
    },
    "population": {
        "source": "custom",
        "name": "homogeneous",
        "age_groups": {"all": int(N_POP)},
        "contact_matrices": {"all": [[1.0]]},
    },
    "simulation": {
        "start_date": START,
        "end_date": END,
        "Nsim": NSIM,
        "seed": SEED,
        "dt": 1.0,
    },
    "initial_conditions": {
        "method": "percentage",
        "initial_percentages": {"Infected": 0.02},
    },
    "vaccination": {
        "campaigns": [
            {
                "start_date": C_START,
                "end_date": C_END,
                "rollout": {"type": "fixed_rate", "rate": RATE},
            }
        ]
    },
}


def _format_axes(ax, ylabel: str, title: str | None = None) -> None:
    if title is not None:
        ax.set_title(title, fontsize=11)
    ax.set_ylabel(ylabel)
    ax.xaxis.set_major_locator(mdates.MonthLocator(bymonth=[1, 3, 5, 7, 9, 11]))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b"))
    ax.grid(True, linewidth=0.3, alpha=0.5)


def _series_median(body: dict, kind: str, name: str) -> np.ndarray:
    section = body["results"][kind]["data"][name]
    keys = [k for k in section if k != "total"]
    return np.array(section[keys[0]]["0.5"], dtype=np.float64)


def _save(fig, name: str) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / name
    fig.savefig(out, format="svg", bbox_inches="tight")
    plt.close(fig)
    print(f"wrote {out.relative_to(Path.cwd())}")


def main() -> None:
    client = TestClient(app)
    response = client.post("/api/v1/simulations", json=REQUEST)
    response.raise_for_status()
    body = response.json()

    dates_iso = body["results"]["compartments"]["dates"]
    dates = [dt.date.fromisoformat(d) for d in dates_iso]

    delivered = _series_median(body, "transitions", "Susceptible_to_Susceptible_vax")
    if len(delivered) < len(dates):
        pad = np.full(len(dates) - len(delivered), np.nan)
        delivered = np.concatenate([pad, delivered])
    susceptible = _series_median(body, "compartments", "Susceptible")

    c_start = dt.date.fromisoformat(C_START)
    c_end = dt.date.fromisoformat(C_END)
    rate_schedule = np.array(
        [RATE if c_start <= d <= c_end else 0.0 for d in dates]
    )

    fig, axes = plt.subplots(
        3,
        1,
        figsize=(7, 7),
        sharex=True,
        constrained_layout=True,
        gridspec_kw={"height_ratios": [0.7, 1.0, 0.85]},
    )

    ax0 = axes[0]
    ax0.plot(
        dates,
        rate_schedule,
        color="gray",
        linewidth=1.5,
        linestyle="--",
        label=f"Rate ({RATE}/day)",
    )
    ax0.axvspan(c_start, c_end, color="tab:blue", alpha=0.06, label="Campaign window")
    _format_axes(
        ax0,
        "Hazard rate",
        title=f"Fixed-rate rollout, V-SEIR, N={int(N_POP):,}, R0=1.4",
    )
    ax0.set_ylim(0, RATE * 1.5)
    ax0.legend(loc="upper right", fontsize=9)

    ax1 = axes[1]
    ax1.plot(
        dates,
        delivered,
        color="tab:blue",
        linewidth=2.0,
        label="Delivered (S to S_vax, median)",
    )
    ax1.axvspan(c_start, c_end, color="tab:blue", alpha=0.06)
    _format_axes(ax1, "Doses per day")
    ax1.set_ylim(0, 6000)
    ax1.legend(loc="upper right", fontsize=9)

    ax2 = axes[2]
    ax2.plot(
        dates,
        susceptible,
        color="tab:green",
        linewidth=2.0,
        label="Susceptible (median)",
    )
    ax2.axvspan(c_start, c_end, color="tab:blue", alpha=0.06)
    _format_axes(ax2, "Population")
    ax2.legend(loc="upper right", fontsize=9)

    _save(fig, "fixed-rate-depletion.svg")


if __name__ == "__main__":
    main()
