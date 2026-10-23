"""Gzip compression middleware behavior."""


def test_large_response_is_gzipped(client):
    """A simulation response exceeds the 1 KB minimum_size and should come back gzipped."""
    request = {
        "model": {"preset": "SIR"},
        "population": {"name": "United_States"},
        "simulation": {
            "start_date": "2024-01-01",
            "end_date": "2024-01-15",
            "Nsim": 3,
            "seed": 1,
        },
    }
    response = client.post(
        "/api/v1/simulations",
        json=request,
        headers={"Accept-Encoding": "gzip"},
    )
    assert response.status_code == 200
    assert response.headers.get("content-encoding") == "gzip"


def test_small_response_is_not_gzipped(client):
    """The health endpoint payload (~67 bytes) is below the 1 KB cutoff and stays uncompressed."""
    response = client.get(
        "/api/v1/health",
        headers={"Accept-Encoding": "gzip"},
    )
    assert response.status_code == 200
    assert "content-encoding" not in response.headers


def test_gzip_skipped_when_client_does_not_accept(client):
    """Client without Accept-Encoding: gzip should receive uncompressed bytes."""
    request = {
        "model": {"preset": "SIR"},
        "population": {"name": "United_States"},
        "simulation": {
            "start_date": "2024-01-01",
            "end_date": "2024-01-15",
            "Nsim": 3,
            "seed": 1,
        },
    }
    response = client.post(
        "/api/v1/simulations",
        json=request,
        headers={"Accept-Encoding": "identity"},
    )
    assert response.status_code == 200
    assert "content-encoding" not in response.headers
