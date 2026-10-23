"""Output summary configuration: defaults, per-field overrides, opt-out, quantiles, age groups."""


def test_simulation_summary_default_populated(client):
    """Summary should be populated by default: all compartments and transitions, all age groups."""
    request = {
        "model": {"preset": "SIR"},
        "population": {"name": "United_States"},
        "simulation": {
            "start_date": "2024-01-01",
            "end_date": "2024-01-15",
            "Nsim": 3,
        },
    }

    response = client.post("/api/v1/simulations", json=request)
    assert response.status_code == 200

    summary = response.json()["results"]["summary"]
    assert summary is not None

    assert set(summary["peaks"].keys()) == {"Susceptible", "Infected", "Recovered"}
    for by_age in summary["peaks"].values():
        assert "total" in by_age
        # Any per-age-group entry (including total) has quantiles + peak_date.
        for stat in by_age.values():
            assert "quantiles" in stat
            assert "0.5" in stat["quantiles"]
            assert "peak_date" in stat

    assert set(summary["totals"].keys()) == {"Susceptible_to_Infected", "Infected_to_Recovered"}
    for by_age in summary["totals"].values():
        assert "total" in by_age
        for stat in by_age.values():
            assert "quantiles" in stat
            assert "0.5" in stat["quantiles"]


def test_simulation_summary_user_override(client):
    """User-supplied summary fields override the per-field default, other fields keep defaulting."""
    request = {
        "model": {"preset": "SIR"},
        "population": {"name": "United_States"},
        "simulation": {
            "start_date": "2024-01-01",
            "end_date": "2024-01-15",
            "Nsim": 3,
        },
        "output": {
            "summary": {
                "peak_compartments": ["Infected"],
            },
        },
    }

    response = client.post("/api/v1/simulations", json=request)
    assert response.status_code == 200

    summary = response.json()["results"]["summary"]
    assert set(summary["peaks"].keys()) == {"Infected"}
    # total_transitions was not specified -> defaults to all
    assert set(summary["totals"].keys()) == {"Susceptible_to_Infected", "Infected_to_Recovered"}


def test_simulation_summary_explicit_opt_out(client):
    """An explicit empty list opts out of that part of the summary; both -> summary is null."""
    request = {
        "model": {"preset": "SIR"},
        "population": {"name": "United_States"},
        "simulation": {
            "start_date": "2024-01-01",
            "end_date": "2024-01-15",
            "Nsim": 3,
        },
        "output": {
            "summary": {
                "peak_compartments": [],
                "total_transitions": [],
            },
        },
    }

    response = client.post("/api/v1/simulations", json=request)
    assert response.status_code == 200

    assert response.json()["results"]["summary"] is None


def test_simulation_summary_honors_quantiles(client):
    """output.quantiles should drive which quantiles appear in the summary."""
    request = {
        "model": {"preset": "SIR"},
        "population": {"name": "United_States"},
        "simulation": {
            "start_date": "2024-01-01",
            "end_date": "2024-01-15",
            "Nsim": 3,
        },
        "output": {
            "quantiles": [0.1, 0.5, 0.9],
        },
    }

    response = client.post("/api/v1/simulations", json=request)
    assert response.status_code == 200

    peaks = response.json()["results"]["summary"]["peaks"]
    quantiles = peaks["Infected"]["total"]["quantiles"]
    assert set(quantiles.keys()) == {"0.1", "0.5", "0.9"}


def test_simulation_summary_honors_age_groups(client):
    """output.age_groups should filter which age groups appear in the summary."""
    request = {
        "model": {"preset": "SIR"},
        "population": {"name": "United_States"},
        "simulation": {
            "start_date": "2024-01-01",
            "end_date": "2024-01-15",
            "Nsim": 3,
        },
        "output": {
            "age_groups": ["total"],
        },
    }

    response = client.post("/api/v1/simulations", json=request)
    assert response.status_code == 200

    summary = response.json()["results"]["summary"]
    for by_age in summary["peaks"].values():
        assert set(by_age.keys()) == {"total"}
    for by_age in summary["totals"].values():
        assert set(by_age.keys()) == {"total"}
