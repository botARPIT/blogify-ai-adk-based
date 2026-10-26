"""Checks for the public, versioned OpenAPI contract."""

from src.api.main import app


def test_openapi_publishes_versioned_health_routes_once() -> None:
    paths = app.openapi()["paths"]

    assert "/api/health" not in paths
    assert sorted(path for path in paths if path.startswith("/api/v1/health")) == [
        "/api/v1/health",
        "/api/v1/health/detailed",
        "/api/v1/health/live",
        "/api/v1/health/ready",
        "/api/v1/health/startup",
    ]
