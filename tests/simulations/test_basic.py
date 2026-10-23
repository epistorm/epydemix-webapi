"""Core simulation run paths: presets, custom model, interventions, seeds, trajectories, metadata."""


def test_run_sir_simulation_with_preset(client):
    """Test running a basic SIR simulation using a preset."""
    request = {
        "model": {
            "preset": "SIR",
            "parameters": {
                "transmission_rate": 0.3,
                "recovery_rate": 0.1,
            },
        },
        "population": {
            "name": "United_States",
        },
        "simulation": {
            "start_date": "2024-01-01",
            "end_date": "2024-01-31",
            "Nsim": 10,
            "dt": 1.0,
        },
    }

    response = client.post("/api/v1/simulations", json=request)
    assert response.status_code == 200

    data = response.json()
    assert data["status"] == "completed"
    assert "simulation_id" in data
    assert data["metadata"]["model"]["preset"] == "SIR"
    assert data["metadata"]["population"]["name"] == "United_States"
    assert data["metadata"]["simulation"]["Nsim"] == 10

    # Check results structure
    assert "results" in data
    assert "compartments" in data["results"]
    assert "transitions" in data["results"]
    # Jan 1 to Jan 31 = 31 dates (inclusive)
    assert len(data["results"]["compartments"]["dates"]) == 31


def test_run_seir_simulation(client):
    """Test running a SEIR simulation."""
    request = {
        "model": {
            "preset": "SEIR",
        },
        "population": {
            "name": "United_States",
        },
        "simulation": {
            "start_date": "2024-01-01",
            "end_date": "2024-01-15",
            "Nsim": 5,
        },
    }

    response = client.post("/api/v1/simulations", json=request)
    assert response.status_code == 200

    data = response.json()
    assert data["status"] == "completed"
    assert "Exposed" in data["metadata"]["model"]["compartments"]


def test_simulation_with_intervention(client):
    """Test simulation with an intervention."""
    request = {
        "model": {
            "preset": "SIR",
        },
        "population": {
            "name": "United_States",
        },
        "simulation": {
            "start_date": "2024-01-01",
            "end_date": "2024-03-01",
            "Nsim": 5,
        },
        "interventions": [
            {
                "layer_name": "school",
                "start_date": "2024-01-15",
                "end_date": "2024-01-30",
                "reduction_factor": 0.2,
                "name": "school_closure",
            }
        ],
    }

    response = client.post("/api/v1/simulations", json=request)
    assert response.status_code == 200

    data = response.json()
    assert data["status"] == "completed"


def test_simulation_validation_error(client):
    """Test that invalid requests return validation errors."""
    # Missing required fields (end_date is now mandatory)
    request = {
        "model": {"preset": "SIR"},
        "population": {"name": "United_States"},
        "simulation": {
            "start_date": "2024-01-01",
            # end_date is missing
        },
    }

    response = client.post("/api/v1/simulations", json=request)
    assert response.status_code == 422  # Validation error


def test_custom_model_simulation(client):
    """Test simulation with a custom model."""
    request = {
        "model": {
            "compartments": ["S", "I", "R"],
            "parameters": {
                "beta": 0.3,
                "gamma": 0.1,
            },
            "transitions": [
                {
                    "source": "S",
                    "target": "I",
                    "kind": "mediated",
                    "params": ["beta", "I"],
                },
                {
                    "source": "I",
                    "target": "R",
                    "kind": "spontaneous",
                    "params": "gamma",
                },
            ],
        },
        "population": {
            "name": "United_States",
        },
        "simulation": {
            "start_date": "2024-01-01",
            "end_date": "2024-01-31",
            "Nsim": 5,
        },
    }

    response = client.post("/api/v1/simulations", json=request)
    assert response.status_code == 200

    data = response.json()
    assert data["status"] == "completed"
    assert data["metadata"]["model"]["compartments"] == ["S", "I", "R"]


def test_simulation_with_custom_age_groups(client):
    """Test simulation with custom age group mapping.

    When using prem contacts (prem_2017, prem_2021), the age_group_mapping
    should use 5-year age group names like "0-4", "5-9", etc.
    """
    request = {
        "model": {
            "preset": "SIR",
        },
        "population": {
            "name": "United_States",
            "contacts_source": "prem_2021",
            "age_group_mapping": {
                "0-19": ["0-4", "5-9", "10-14", "15-19"],
                "20-49": ["20-24", "25-29", "30-34", "35-39", "40-44", "45-49"],
                "50-64": ["50-54", "55-59", "60-64"],
                "65+": ["65-69", "70-74", "75+"],
            },
        },
        "simulation": {
            "start_date": "2024-01-01",
            "end_date": "2024-01-31",
            "Nsim": 5,
        },
    }

    response = client.post("/api/v1/simulations", json=request)
    assert response.status_code == 200

    data = response.json()
    assert data["status"] == "completed"
    # Custom age groups should result in 4 age groups
    assert len(data["metadata"]["population"]["age_groups"]) == 4
    assert (
        data["metadata"]["population"]["age_group_mapping"]
        == request["population"]["age_group_mapping"]
    )


def test_simulation_with_seed_reproducibility(client):
    """Test that using the same seed produces reproducible results."""
    request = {
        "model": {"preset": "SIR"},
        "population": {"name": "United_States"},
        "simulation": {
            "start_date": "2024-01-01",
            "end_date": "2024-01-15",
            "Nsim": 5,
            "seed": 42,
        },
    }

    # Run twice with same seed
    response1 = client.post("/api/v1/simulations", json=request)
    response2 = client.post("/api/v1/simulations", json=request)

    assert response1.status_code == 200
    assert response2.status_code == 200

    data1 = response1.json()
    data2 = response2.json()

    assert data1["metadata"]["simulation"]["seed"] == 42
    assert data2["metadata"]["simulation"]["seed"] == 42

    # Results should be identical with same seed
    assert data1["results"]["compartments"] == data2["results"]["compartments"]


def test_simulation_with_different_seeds(client):
    """Test that using different seeds produces different results."""
    base_request = {
        "model": {"preset": "SIR"},
        "population": {"name": "United_States"},
        "simulation": {
            "start_date": "2024-01-01",
            "end_date": "2024-01-15",
            "Nsim": 5,
        },
    }

    # Run with different seeds
    request1 = {**base_request, "simulation": {**base_request["simulation"], "seed": 42}}
    request2 = {**base_request, "simulation": {**base_request["simulation"], "seed": 123}}

    response1 = client.post("/api/v1/simulations", json=request1)
    response2 = client.post("/api/v1/simulations", json=request2)

    assert response1.status_code == 200
    assert response2.status_code == 200

    data1 = response1.json()
    data2 = response2.json()

    assert data1["metadata"]["simulation"]["seed"] == 42
    assert data2["metadata"]["simulation"]["seed"] == 123

    # Results should be different with different seeds
    assert data1["results"]["compartments"] != data2["results"]["compartments"]


def test_simulation_include_trajectories(client):
    """Test including raw trajectory data in response."""
    request = {
        "model": {"preset": "SIR"},
        "population": {"name": "United_States"},
        "simulation": {
            "start_date": "2024-01-01",
            "end_date": "2024-01-10",
            "Nsim": 3,
        },
        "output": {
            "include_trajectories": True,
            "age_groups": ["total"],  # Only include aggregated totals
        },
    }

    response = client.post("/api/v1/simulations", json=request)
    assert response.status_code == 200

    data = response.json()
    assert data["status"] == "completed"

    # Check trajectories are included
    assert "trajectories" in data["results"]
    assert data["results"]["trajectories"] is not None

    trajectories = data["results"]["trajectories"]
    assert "dates" in trajectories
    assert "runs" in trajectories
    assert len(trajectories["runs"]) == 3  # Nsim = 3

    # Each run should have compartments and transitions (hierarchical structure)
    for run in trajectories["runs"]:
        assert "compartments" in run
        assert "transitions" in run
        # With age_groups=["total"], each compartment should only have "total" key
        for _comp_name, age_groups in run["compartments"].items():
            assert "total" in age_groups
            assert len(age_groups) == 1  # Only "total" age group


def test_simulation_population_metadata(client):
    """Population metadata should include total, per-age-group counts, and resolved contacts config."""
    request = {
        "model": {"preset": "SIR"},
        "population": {"name": "United_States"},
        "simulation": {
            "start_date": "2024-01-01",
            "end_date": "2024-01-10",
            "Nsim": 3,
        },
    }

    response = client.post("/api/v1/simulations", json=request)
    assert response.status_code == 200

    population = response.json()["metadata"]["population"]

    assert population["name"] == "United_States"
    assert population["total"] > 0
    assert population["contacts_source"] is not None
    assert population["layers"] == ["home", "work", "school", "community"]
    assert population["age_group_mapping"] is None

    age_groups = population["age_groups"]
    assert isinstance(age_groups, dict)
    assert len(age_groups) > 0
    assert all(isinstance(v, int) for v in age_groups.values())
    assert sum(age_groups.values()) == population["total"]
