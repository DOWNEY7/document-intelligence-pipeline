"""
Unit tests for Authentication Layer and CORS Security Configuration.
Tests API Key enforcement (X-API-Key / Bearer token), unauthorized rejection,
and verified CORS credential vs wildcard constraints.
"""

from fastapi.testclient import TestClient

from src.api.app import create_app
from src.config import Settings


class TestAuthenticationLayer:
    """Test API key authentication under different environment configurations."""

    def test_anonymous_access_allowed_by_default(self, temp_storage_dir):
        """When REQUIRE_AUTH=False and API_KEY is unset, endpoints accept requests without auth header."""
        settings = Settings(
            UPLOAD_DIR=temp_storage_dir,
            REQUIRE_AUTH=False,
            API_KEY=None,
        )
        app = create_app(settings)
        client = TestClient(app)

        resp = client.get("/api/v1/invoices")
        assert resp.status_code == 200

    def test_enforced_auth_missing_header_raises_401(self, temp_storage_dir):
        """When REQUIRE_AUTH=True, request without credentials yields 401 Unauthorized."""
        settings = Settings(
            UPLOAD_DIR=temp_storage_dir,
            REQUIRE_AUTH=True,
            API_KEY="test-secret-token",
        )
        app = create_app(settings)
        client = TestClient(app)

        resp = client.get("/api/v1/invoices")
        assert resp.status_code == 401
        assert "Missing API Key" in resp.json()["detail"]

    def test_enforced_auth_invalid_header_raises_403(self, temp_storage_dir):
        """When REQUIRE_AUTH=True, request with invalid key yields 403 Forbidden."""
        settings = Settings(
            UPLOAD_DIR=temp_storage_dir,
            REQUIRE_AUTH=True,
            API_KEY="test-secret-token",
        )
        app = create_app(settings)
        client = TestClient(app)

        resp = client.get("/api/v1/invoices", headers={"X-API-Key": "wrong-key"})
        assert resp.status_code == 403
        assert "Invalid API Key" in resp.json()["detail"]

    def test_enforced_auth_valid_x_api_key_succeeds(self, temp_storage_dir):
        """Valid X-API-Key header grants access to protected endpoints."""
        settings = Settings(
            UPLOAD_DIR=temp_storage_dir,
            REQUIRE_AUTH=True,
            API_KEY="test-secret-token",
        )
        app = create_app(settings)
        client = TestClient(app)

        resp = client.get("/api/v1/invoices", headers={"X-API-Key": "test-secret-token"})
        assert resp.status_code == 200

    def test_enforced_auth_valid_bearer_token_succeeds(self, temp_storage_dir):
        """Valid Bearer authorization header grants access to protected endpoints."""
        settings = Settings(
            UPLOAD_DIR=temp_storage_dir,
            REQUIRE_AUTH=True,
            API_KEY="test-secret-token",
        )
        app = create_app(settings)
        client = TestClient(app)

        resp = client.get(
            "/api/v1/invoices",
            headers={"Authorization": "Bearer test-secret-token"},
        )
        assert resp.status_code == 200

    def test_health_check_remains_public_with_auth_enabled(self, temp_storage_dir):
        """The /health endpoint is public and does not require authentication even when REQUIRE_AUTH=True."""
        settings = Settings(
            UPLOAD_DIR=temp_storage_dir,
            REQUIRE_AUTH=True,
            API_KEY="test-secret-token",
        )
        app = create_app(settings)
        client = TestClient(app)

        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] in ["healthy", "degraded"]


class TestCORSSecurityConfiguration:
    """Test CORS headers and wildcard + credentials misconfiguration fix."""

    def test_cors_explicit_origin_allows_credentials(self, temp_storage_dir):
        """When explicit origins are configured, credentials are permitted."""
        settings = Settings(
            UPLOAD_DIR=temp_storage_dir,
            CORS_ORIGINS=["http://localhost:8501", "http://localhost:3000"],
        )
        app = create_app(settings)
        client = TestClient(app)

        resp = client.options(
            "/api/v1/invoices",
            headers={
                "Origin": "http://localhost:8501",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert resp.headers.get("access-control-allow-origin") == "http://localhost:8501"
        assert resp.headers.get("access-control-allow-credentials") == "true"

    def test_cors_wildcard_origin_disables_credentials(self, temp_storage_dir):
        """When wildcard '*' is configured, allow_credentials must be False per CORS spec."""
        settings = Settings(
            UPLOAD_DIR=temp_storage_dir,
            CORS_ORIGINS=["*"],
        )
        app = create_app(settings)
        client = TestClient(app)

        resp = client.options(
            "/api/v1/invoices",
            headers={
                "Origin": "http://example.com",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert resp.headers.get("access-control-allow-origin") == "*"
        # Per CORS spec, Access-Control-Allow-Credentials cannot be 'true' with wildcard
        assert resp.headers.get("access-control-allow-credentials") != "true"
