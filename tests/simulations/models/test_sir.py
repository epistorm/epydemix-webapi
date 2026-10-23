"""Dynamics tests for the SIR preset.

Locks down core epidemiological behavior on a homogeneous one-age-group
population: ODE-match in expectation, R0 monotonicity, and subcritical dieout.
"""

import numpy as np
import pytest

from ._dynamics import median_series, ode_sir

N = 100_000


def _request(R0: float, recovery_rate: float, end_date: str = "2024-06-01", **overrides):
    req = {
        "model": {
            "preset": "SIR",
            "parameters": {"R0": R0, "recovery_rate": recovery_rate},
        },
        "population": {
            "source": "custom",
            "name": f"Homogeneous N={N}",
            "age_groups": {"A": N},
            "contact_matrices": {"all": [[1.0]]},
        },
        "simulation": {
            "start_date": "2024-01-01",
            "end_date": end_date,
            "Nsim": 100,
            "dt": 0.25,
            "seed": 42,
        },
    }
    req.update(overrides)
    return req


def _run(client, **kwargs):
    response = client.post("/api/v1/simulations", json=_request(**kwargs))
    assert response.status_code == 200, response.text
    return response.json()["results"]


def test_homogeneous_sir_matches_ode_solution(client):
    """Stochastic median (Nsim=100, seed=42) matches an RK4 reference of the same IC.

    The API receives R0 and recovery_rate; the RK4 reference uses the equivalent
    beta = R0 * gamma (the contact matrix is 1x1 with eigenvalue 1).

    Tolerances are sized at ~2x the empirical errors measured at this config
    so seed-noise / environment drift have headroom without dulling regression
    detection.
    """
    R0, GAMMA = 3.0, 0.1
    BETA = R0 * GAMMA
    results = _run(client, R0=R0, recovery_rate=GAMMA)
    S_med = median_series(results, "Susceptible")
    I_med = median_series(results, "Infected")
    T = len(S_med)

    S0, I0 = float(S_med[0]), float(I_med[0])
    S_ode, I_ode = ode_sir(BETA, GAMMA, N, S0, I0, N - S0 - I0, T)

    peak_day_sim = int(np.argmax(I_med))
    peak_day_ode = int(np.argmax(I_ode))
    # Peak timing within +-2 days (measured shift at this config: +1 day).
    assert peak_day_sim == pytest.approx(peak_day_ode, abs=2)
    # Peak height within 3% (measured: ~1.3%).
    assert I_med[peak_day_sim] == pytest.approx(I_ode[peak_day_ode], rel=0.03)
    # Final epidemic size within 1% (measured: ~0.27%). Most stable invariant.
    assert (N - S_med[-1]) == pytest.approx(N - S_ode[-1], rel=0.01)


def test_higher_r0_increases_peak_and_final_size(client):
    """Sweeping R0 upward strictly increases peak and final size."""
    gamma = 0.1
    r0_values = [1.5, 2.5, 4.0]
    peaks: list[float] = []
    finals: list[float] = []
    for r0 in r0_values:
        results = _run(client, R0=r0, recovery_rate=gamma)
        I_med = median_series(results, "Infected")
        S_med = median_series(results, "Susceptible")
        peaks.append(float(I_med.max()))
        finals.append(float(N - S_med[-1]))

    assert peaks == sorted(peaks), f"peaks not monotone in R0: {dict(zip(r0_values, peaks))}"
    assert finals == sorted(finals), (
        f"final sizes not monotone in R0: {dict(zip(r0_values, finals))}"
    )


def test_seasonality_suppresses_peak_when_low_during_outbreak(client):
    """Balcan seasonality with `min_date` inside the outbreak window lowers peak incidence."""
    baseline = _run(client, R0=3.0, recovery_rate=0.1)
    seasonal = _run(
        client,
        R0=3.0,
        recovery_rate=0.1,
        parameter_transforms=[
            {
                "target_parameter": "transmission_rate",
                "method": "balcan",
                "max_date": "2024-09-01",
                "min_date": "2024-03-01",
                "max_value": 1.0,
                "min_value": 0.3,
            }
        ],
    )

    baseline_peak = float(median_series(baseline, "Infected").max())
    seasonal_peak = float(median_series(seasonal, "Infected").max())

    assert seasonal_peak < 0.5 * baseline_peak, (
        f"seasonality did not suppress peak: baseline={baseline_peak:.0f}, "
        f"seasonal={seasonal_peak:.0f}"
    )


def test_subcritical_r0_dies_out(client):
    """R0 < 1: infections never grow above the seed; final size stays small."""
    results = _run(client, R0=0.5, recovery_rate=0.1)
    I_med = median_series(results, "Infected")
    S_med = median_series(results, "Susceptible")

    # No outbreak: peak does not exceed the initial infected count.
    assert I_med.max() <= I_med[0], (
        f"subcritical R0 produced growth: I0={I_med[0]}, peak={I_med.max()}"
    )
    # Final size is bounded by the total ever-infected expected at R0=0.5
    # (loose 5% cap on the population to absorb stochastic noise).
    final_size = N - S_med[-1]
    assert final_size < 0.05 * N, f"subcritical final size too large: {final_size} / {N}"
