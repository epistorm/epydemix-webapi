"""Shared date helpers for parameter transforms."""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd


def to_datetime(value: dt.date | dt.datetime | str | np.datetime64) -> dt.datetime:
    """Coerce date/datetime/ISO string/numpy datetime64 to ``datetime``."""
    if isinstance(value, np.datetime64):
        return dt.datetime.fromisoformat(str(np.datetime_as_string(value, unit="s")))
    if isinstance(value, str):
        value = dt.date.fromisoformat(value)
    if isinstance(value, dt.datetime):
        return value
    return dt.datetime.combine(value, dt.time())


def format_date_axis(dates) -> list[str]:
    """Keep date-only daily axes, and preserve timestamps when a day has substeps."""
    timestamps = pd.DatetimeIndex(dates)
    subdaily = bool((timestamps != timestamps.normalize()).any())
    if subdaily:
        return [value.isoformat() for value in timestamps]
    return [value.strftime("%Y-%m-%d") for value in timestamps]
