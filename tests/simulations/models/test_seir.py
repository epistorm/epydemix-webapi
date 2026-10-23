"""Dynamics tests for the SEIR preset.

Locks down core epidemiological behavior on a homogeneous one-age-group
population: ODE-match in expectation, R0 monotonicity, longer-incubation
delays the peak, and subcritical dieout.
"""

import numpy as np
import pytest

from ._dynamics import median_series, ode_seir

N = 100_000


def _request(
    R0: float,
    recovery_rate: float,
    incubation_rate: float,
    end_date: str = "2024-06-01",
    **overrides,
):
    req = {
        "model": {
            "preset": "SEIR",
            "parameters": {
                "R0": R0,
                "recovery_rate": recovery_rate,
                "incubation_rate": incubation_rate,
            },
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


def test_homogeneous_seir_matches_ode_solution(client):
    """Stochastic median (Nsim=100, seed=42) matches an RK4 reference of the same IC.

    The API receives R0, recovery_rate, and incubation_rate; the RK4 reference
    uses the equivalent beta = R0 * gamma (the contact matrix is 1x1 with
    eigenvalue 1) and sigma = incubation_rate.
    """
    R0, GAMMA, SIGMA = 3.0, 0.1, 0.2
    BETA = R0 * GAMMA
    results = _run(client, R0=R0, recovery_rate=GAMMA, incubation_rate=SIGMA)
    S_med = median_series(results, "Susceptible")
    E_med = median_series(results, "Exposed")
    I_med = median_series(results, "Infected")
    T = len(S_med)

    S0, E0, I0 = float(S_med[0]), float(E_med[0]), float(I_med[0])
    R0_init = N - S0 - E0 - I0
    S_ode, _, I_ode = ode_seir(BETA, SIGMA, GAMMA, N, S0, E0, I0, R0_init, T)

    peak_day_sim = int(np.argmax(I_med))
    peak_day_ode = int(np.argmax(I_ode))
    # Peak timing within +-3 days (SEIR has slower onset; allow a touch more slack than SIR).
    assert peak_day_sim == pytest.approx(peak_day_ode, abs=3)
    # Peak height within 5%.
    assert I_med[peak_day_sim] == pytest.approx(I_ode[peak_day_ode], rel=0.05)
    # Final epidemic size within 2%. Most stable invariant.
    assert (N - S_med[-1]) == pytest.approx(N - S_ode[-1], rel=0.02)


def test_higher_r0_increases_peak_and_final_size(client):
    """Sweeping R0 upward strictly increases peak and final size."""
    gamma, sigma = 0.1, 0.2
    r0_values = [1.5, 2.5, 4.0]
    peaks: list[float] = []
    finals: list[float] = []
    for r0 in r0_values:
        results = _run(client, R0=r0, recovery_rate=gamma, incubation_rate=sigma)
        I_med = median_series(results, "Infected")
        S_med = median_series(results, "Susceptible")
        peaks.append(float(I_med.max()))
        finals.append(float(N - S_med[-1]))

    assert peaks == sorted(peaks), f"peaks not monotone in R0: {dict(zip(r0_values, peaks))}"
    assert finals == sorted(finals), (
        f"final sizes not monotone in R0: {dict(zip(r0_values, finals))}"
    )


def test_longer_incubation_delays_peak(client):
    """A longer latent period (smaller incubation_rate) pushes the peak later in time.

    Final size is governed by R0 only, so we only assert on peak timing, not
    on peak height or attack rate.
    """
    gamma = 0.1
    fast_incubation = _run(client, R0=2.5, recovery_rate=gamma, incubation_rate=0.5)
    slow_incubation = _run(client, R0=2.5, recovery_rate=gamma, incubation_rate=0.1)

    fast_peak_day = int(np.argmax(median_series(fast_incubation, "Infected")))
    slow_peak_day = int(np.argmax(median_series(slow_incubation, "Infected")))

    assert slow_peak_day > fast_peak_day, (
        f"longer incubation did not delay peak: "
        f"slow={slow_peak_day}, fast={fast_peak_day}"
    )


def test_subcritical_r0_dies_out(client):
    """R0 < 1: infections never grow above the seed; final size stays small."""
    results = _run(client, R0=0.5, recovery_rate=0.1, incubation_rate=0.2)
    I_med = median_series(results, "Infected")
    E_med = median_series(results, "Exposed")
    S_med = median_series(results, "Susceptible")

    # No outbreak: I+E (active infection load) does not exceed its initial value.
    initial_active = I_med[0] + E_med[0]
    peak_active = float((I_med + E_med).max())
    assert peak_active <= initial_active, (
        f"subcritical R0 produced growth: initial E+I={initial_active}, peak={peak_active}"
    )
    # Final size bounded by total ever-infected expected at R0=0.5
    # (loose 5% cap on the population to absorb stochastic noise).
    final_size = N - S_med[-1]
    assert final_size < 0.05 * N, f"subcritical final size too large: {final_size} / {N}"
