"""Shared helpers for dynamics tests.

Reference ODE integrators and trajectory extractors used to assert
epidemiological behavior (peak, final size, monotonicity over R0, ...).
"""

from __future__ import annotations

import numpy as np
from scipy.integrate import solve_ivp


def _integrate(rhs, y0: list[float], T: int) -> np.ndarray:
    """Integrate `rhs(t, y)` over `T` daily points starting at t=0. Returns y[:, T]."""
    sol = solve_ivp(
        rhs,
        t_span=(0.0, T - 1),
        y0=y0,
        t_eval=np.arange(T),
        method="RK45",
        rtol=1e-8,
        atol=1e-6,
    )
    return sol.y


def ode_sir(
    beta: float,
    gamma: float,
    N: float,
    S0: float,
    I0: float,
    R0: float,
    T: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Integrate homogeneous SIR for `T` days. Returns daily (S, I)."""

    def rhs(_t, y):
        S, I, _R = y
        infection = beta * S * I / N
        return [-infection, infection - gamma * I, gamma * I]

    y = _integrate(rhs, [S0, I0, R0], T)
    return y[0], y[1]


def ode_seir(
    beta: float,
    sigma: float,
    gamma: float,
    N: float,
    S0: float,
    E0: float,
    I0: float,
    R0: float,
    T: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Integrate homogeneous SEIR for `T` days. Returns daily (S, E, I).

    `sigma` is the incubation rate (1 / latent period).
    """

    def rhs(_t, y):
        S, E, I, _R = y
        infection = beta * S * I / N
        progression = sigma * E
        return [-infection, infection - progression, progression - gamma * I, gamma * I]

    y = _integrate(rhs, [S0, E0, I0, R0], T)
    return y[0], y[1], y[2]


def median_series(data: dict, compartment: str, age_group: str = "A") -> np.ndarray:
    """Pull the 0.5-quantile time series for a compartment out of a response body."""
    return np.array(data["compartments"]["data"][compartment][age_group]["0.5"], dtype=float)
