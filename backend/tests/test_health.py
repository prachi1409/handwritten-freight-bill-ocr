"""Unit tests for FastAPI health endpoint."""


def test_health_check_endpoint(client):
    """Verify GET /health returns 200 OK and status ok."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

