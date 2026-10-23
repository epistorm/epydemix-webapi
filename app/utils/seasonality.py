"""Seasonality calculations.
Computes a per-step seasonal scaling factor over a date range that, multiplied by an
existing parameter, yields the seasonally adjusted value.
"""

from __future__ import annotations

import datetime as dt

import numpy as np
from epydemix.utils.utils import compute_simulation_dates

from .dates import to_datetime


def _calc_seasonality_balcan_at_t(
    t: float, t_max: float, val_min: float, val_max: float, period: float = 365.0
) -> float:
    """Seasonal scaling factor at time t, using eq.25 from (Balcan D et al. J. Comput. Sci. 2010, eq. 25; https://doi.org/10.1016/j.jocs.2010.07.002).

    Returns a value in ``[val_min/val_max, 1]`` that, multiplied by ``val_max``,
    yields the seasonally adjusted parameter at time ``t``.
    """
    return (
        (1 - (val_min / val_max)) * np.sin((2 * np.pi / period) * (t - t_max) + (np.pi / 2))
        + 1
        + (val_min / val_max)
    ) / 2


def calc_seasonality_balcan_at_date(
    date_t: dt.date | dt.datetime | str,
    date_start: dt.date | dt.datetime | str,
    date_tmax: dt.date | dt.datetime | str,
    val_min: float,
    val_max: float,
    date_tmin: dt.date | dt.datetime | str | None = None,
    period: float | None = None,
    delta_t: float = 1.0,
) -> float:
    """Balcan seasonal factor on a calendar date."""
    date_t = to_datetime(date_t)
    date_start = to_datetime(date_start)
    date_tmax = to_datetime(date_tmax)
    if date_tmin is not None:
        date_tmin = to_datetime(date_tmin)

    t_days = (date_t - date_start).total_seconds() / 86400
    t_max_days = (date_tmax - date_start).total_seconds() / 86400

    t_units = t_days / delta_t
    t_max_units = t_max_days / delta_t

    if period is not None:
        period_days = period
    elif date_tmin is not None:
        t_min_days = (date_tmin - date_start).total_seconds() / 86400
        period_days = 2 * abs(t_min_days - t_max_days)
    else:
        period_days = 365

    period_units = period_days / delta_t

    return _calc_seasonality_balcan_at_t(t_units, t_max_units, val_min, val_max, period_units)


def get_seasonal_transmission_balcan(
    date_start: dt.date | dt.datetime | str,
    date_stop: dt.date | dt.datetime | str,
    date_tmax: dt.date | dt.datetime | str,
    val_min: float,
    val_max: float,
    date_tmin: dt.date | dt.datetime | str | None = None,
    delta_t: float = 1.0,
) -> tuple[np.ndarray, list[float]]:
    """Per-step Balcan seasonal scaling array over ``[date_start, date_stop]``."""
    dates = compute_simulation_dates(date_start, date_stop, dt=delta_t)
    values = [
        calc_seasonality_balcan_at_date(
            date_t=to_datetime(d),
            date_start=date_start,
            date_tmax=date_tmax,
            date_tmin=date_tmin,
            val_min=val_min,
            val_max=val_max,
            delta_t=delta_t,
        )
        for d in dates
    ]
    return dates, values
