"""Constant-window scaling: factor inside ``[start, stop]``, 1.0 outside."""

from __future__ import annotations

import datetime as dt

import numpy as np
from epydemix.utils.utils import compute_simulation_dates

from .dates import to_datetime


def calc_scaling_at_date(
    date_t: dt.date | dt.datetime | str,
    scaling_start: dt.date | dt.datetime | str,
    scaling_stop: dt.date | dt.datetime | str,
    scaling_factor: float,
) -> float:
    """Return ``scaling_factor`` if ``date_t`` is in the window, else 1.0."""
    date_t = to_datetime(date_t)
    scaling_start = to_datetime(scaling_start)
    scaling_stop = to_datetime(scaling_stop)

    if scaling_start.date() <= date_t.date() <= scaling_stop.date():
        return scaling_factor
    return 1.0


def get_scaled_parameter(
    date_start: dt.date | dt.datetime | str,
    date_stop: dt.date | dt.datetime | str,
    scaling_start: dt.date | dt.datetime | str,
    scaling_stop: dt.date | dt.datetime | str,
    scaling_factor: float,
    delta_t: float = 1.0,
) -> tuple[np.ndarray, list[float]]:
    """Per-step scaling array: ``scaling_factor`` inside the window, 1.0 outside.

    Uses epydemix's ``compute_simulation_dates`` so the date grid matches what
    the simulator itself walks during ``run_simulations``.
    """
    dates = compute_simulation_dates(date_start, date_stop, dt=delta_t)
    values = [
        calc_scaling_at_date(
            date_t=to_datetime(d),
            scaling_start=scaling_start,
            scaling_stop=scaling_stop,
            scaling_factor=scaling_factor,
        )
        for d in dates
    ]
    return dates, values
