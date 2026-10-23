"""Parameter transform dispatcher.

Builds the per-step scaling array for a `balcan` / `scale` transform (delegating
to ``seasonality``) and applies it to a parameter's existing value, handling
the four shapes epydemix may have stored.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from .scaling import get_scaled_parameter
from .seasonality import get_seasonal_transmission_balcan

if TYPE_CHECKING:
    from ..api.v1.schemas.simulation import ParameterTransformConfig


def broadcast_to_time_and_age(value, T: int, N: int) -> np.ndarray:
    """Broadcast a parameter value to a fresh ``(T, N)`` float array.

    Accepts the same shapes ``apply_transform_to_parameter`` does:
      - scalar (no ``__len__``)            → ``(T, N)`` filled
      - 1D length T (time-varying)         → ``(T, N)`` tiled across age
      - 1D length N (age-varying)          → ``(T, N)`` tiled across time
      - 2D ``(1, N)``                      → ``(T, N)`` tiled across time
      - 2D ``(T, N)``                      → ``(T, N)`` copy

    Always returns a freshly allocated, contiguous ``np.ndarray`` of dtype
    float so callers can overwrite slices in place.
    """
    if not hasattr(value, "__len__"):
        return np.full((T, N), float(value), dtype=np.float64)
    arr = np.asarray(value, dtype=np.float64)
    if arr.ndim == 1 and arr.shape[0] == T:
        return np.broadcast_to(arr[:, None], (T, N)).copy()
    if arr.ndim == 1 and arr.shape[0] == N:
        return np.broadcast_to(arr[None, :], (T, N)).copy()
    if arr.ndim == 2 and arr.shape == (1, N):
        return np.broadcast_to(arr, (T, N)).copy()
    if arr.ndim == 2 and arr.shape == (T, N):
        return arr.copy()
    raise ValueError(f"Cannot broadcast parameter value of shape {arr.shape} to (T={T}, N={N})")


def window_mask_for_dates(
    start_date: str,
    end_date: str,
    dates: np.ndarray,
) -> np.ndarray:
    """Return a boolean mask over ``dates`` for ``[start_date, end_date]``.

    ``dates`` is the simulation date grid (``numpy.datetime64`` array, the
    output of ``compute_simulation_dates``). The mask is inclusive on both
    ends and aligned to the day. Steps falling between two daily grid points
    are included if their grid date sits within the window.
    """
    date_ts = pd.to_datetime([np.datetime_as_string(d, unit="D") for d in dates])
    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date)
    return np.asarray((date_ts >= start) & (date_ts <= end))


def apply_transform_to_parameter(existing_value, transform_array: np.ndarray) -> np.ndarray:
    """Multiply an existing parameter value by a 1D transform array (length T).

    Always returns a freshly allocated array — never returns ``existing_value``
    by reference, even if the transform is a no-op. Callers compose transforms
    sequentially and must be able to overwrite without aliasing the previous
    step's result.

    Handles the four shapes epydemix may have stored:
      - scalar (no ``__len__``)               → ``(T,)``
      - 1D length T (already time-varying)    → ``(T,)`` element-wise
      - 1D length N (age-varying constant)    → ``(T, N)``, tiled across time
      - 2D ``(1, N)`` or ``(T, N)``           → ``(T, N)``, per-column multiply
    """
    transform_array = np.asarray(transform_array)
    T = transform_array.shape[0]

    if not hasattr(existing_value, "__len__"):
        return transform_array * float(existing_value)

    arr = np.asarray(existing_value)

    if arr.ndim == 1 and arr.shape[0] == T:
        return transform_array * arr

    if arr.ndim == 1:
        N = arr.shape[0]
        out = np.zeros((T, N))
        for i in range(N):
            out[:, i] = transform_array * arr[i]
        return out

    if arr.ndim == 2 and (arr.shape == (T, arr.shape[1]) or arr.shape == (1, arr.shape[1])):
        N = arr.shape[1]
        out = np.zeros((T, N))
        for i in range(N):
            out[:, i] = transform_array * arr[:, i]
        return out

    raise ValueError(f"Cannot apply transform to existing parameter with shape {arr.shape}")


def compute_transform_array(
    transform_config: ParameterTransformConfig,
    date_start: str,
    date_stop: str,
    delta_t: float,
) -> np.ndarray:
    """Return the 1D length-T scaling array for a balcan/scale transform."""
    if transform_config.method == "balcan":
        _, values = get_seasonal_transmission_balcan(
            date_start=date_start,
            date_stop=date_stop,
            date_tmax=transform_config.max_date,
            date_tmin=transform_config.min_date,
            val_min=transform_config.min_value,
            val_max=transform_config.max_value,
            delta_t=delta_t,
        )
        return np.array(values)

    if transform_config.method == "scale":
        _, values = get_scaled_parameter(
            date_start=date_start,
            date_stop=date_stop,
            scaling_start=transform_config.start_date,
            scaling_stop=transform_config.end_date,
            scaling_factor=transform_config.factor,
            delta_t=delta_t,
        )
        return np.array(values)

    raise TypeError(f"compute_transform_array does not handle method '{transform_config.method}'")
