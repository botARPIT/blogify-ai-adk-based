"""Tests for authentication - login and protected routes."""

from unittest.mock import AsyncMock, MagicMock, patch


class TestLogin:
    """Test user login with credentials."""

    def test_login_valid_credentials_returns_token(self, test_client):
        """Test user can login with correct email/password and receives JWT token."""
        with patch(
            "src.models.repositories.auth_user_repository.AuthUserRepository.get_by_email"
        ) as mock_get:
            mock_user = MagicMock()
            mock_user.id = 1
            mock_user.email = "test@example.com"
            mock_user.password_hash = "$2b$12$hashedpassword"  # Pre-hashed
            mock_user.display_name = "Test User"
            mock_user.is_active = True
            mock_user.created_at = None
            mock_user.last_login_at = None
            mock_get.return_value = mock_user

            with patch(
                "src.services.auth_service.AuthService.login", new_callable=AsyncMock
            ) as mock_login:
                mock_login.return_value = "test-jwt-token"

                response = test_client.post(
                    "/api/v1/auth/login",
                    json={"email": "test@example.com", "password": "password123"},
                )

                assert response.status_code == 200
                data = response.json()
                assert data["authenticated"] is True
                assert data["user"]["email"] == "test@example.com"
                assert "Set-Cookie" in response.headers or "token" in data

    def test_login_invalid_password_returns_401(self, test_client):
        """Test login fails with incorrect password returns 401."""
        with patch(
            "src.models.repositories.auth_user_repository.AuthUserRepository.get_by_email"
        ) as mock_get:
            mock_user = MagicMock()
            mock_user.id = 1
            mock_user.email = "test@example.com"
            mock_user.password_hash = "$2b$12$hashedpassword"
            mock_user.is_active = True
            mock_get.return_value = mock_user

            with patch(
                "src.services.auth_service.AuthService.login", new_callable=AsyncMock
            ) as mock_login:
                mock_login.side_effect = ValueError("Invalid password")

                response = test_client.post(
                    "/api/v1/auth/login",
                    json={"email": "test@example.com", "password": "wrongpassword"},
                )

                assert response.status_code == 401

    def test_login_nonexistent_user_returns_401(self, test_client):
        """Test login fails for non-existent user returns 401."""
        with patch(
            "src.models.repositories.auth_user_repository.AuthUserRepository.get_by_email"
        ) as mock_get:
            mock_get.return_value = None

            response = test_client.post(
                "/api/v1/auth/login",
                json={"email": "nonexistent@example.com", "password": "password123"},
            )

            assert response.status_code == 401


class TestProtectedRoutes:
    """Test that protected routes require authentication."""

    def test_blogs_list_without_auth_returns_401(self, test_client):
        """Test GET /api/v1/blogs/ returns 401 without authentication."""
        response = test_client.get("/api/v1/blogs/")
        assert response.status_code == 401

    def test_generate_blog_without_auth_returns_401(self, test_client):
        """Test POST /api/v1/blogs/generate returns 401 without authentication."""
        response = test_client.post(
            "/api/v1/blogs/generate",
            json={"topic": "Test Topic", "audience": "test", "tone": "professional"},
        )
        assert response.status_code == 401

    def test_budget_without_auth_returns_401(self, test_client):
        """Test GET /api/v1/blogs/budget returns 401 without authentication."""
        response = test_client.get("/api/v1/blogs/budget")
        assert response.status_code == 401

    def test_session_detail_without_auth_returns_401(self, test_client):
        """Test GET /api/v1/blogs/1/detail returns 401 without authentication."""
        response = test_client.get("/api/v1/blogs/1/detail")
        assert response.status_code == 401

    def test_session_status_without_auth_returns_401(self, test_client):
        """Test GET /api/v1/blogs/1/status returns 401 without authentication."""
        response = test_client.get("/api/v1/blogs/1/status")
        assert response.status_code == 401

    def test_outline_without_auth_returns_401(self, test_client):
        """Test GET /api/v1/blogs/1/outline returns 401 without authentication."""
        response = test_client.get("/api/v1/blogs/1/outline")
        assert response.status_code == 401

    def test_content_without_auth_returns_401(self, test_client):
        """Test GET /api/v1/blogs/1/content returns 401 without authentication."""
        response = test_client.get("/api/v1/blogs/1/content")
        assert response.status_code == 401

    def test_versions_without_auth_returns_401(self, test_client):
        """Test GET /api/v1/blogs/1/versions/latest returns 401 without authentication."""
        response = test_client.get("/api/v1/blogs/1/versions/latest")
        assert response.status_code == 401


class TestAuthenticatedRequests:
    """Test that authenticated requests pass through."""

    def test_authenticated_blogs_list_passes(self, test_client):
        """Test authenticated request to /blogs/ passes."""
        with patch("src.api.auth.get_current_user") as mock_auth:
            mock_auth.return_value = MagicMock(user_id=1)

            with patch(
                "src.models.repositories.blog_session_repository.BlogSessionRepository.get_for_user"
            ) as mock_get:
                mock_get.return_value = []

                response = test_client.get(
                    "/api/v1/blogs/", cookies={"auth_token": "valid-jwt-token"}
                )

                assert response.status_code == 200

    def test_protected_route_without_valid_cookie_still_returns_401(self, test_client):
        """Test request with invalid/expired cookie returns 401."""
        response = test_client.get("/api/v1/blogs/", cookies={"auth_token": "invalid-token"})

        assert response.status_code in [401, 403]


class TestAuthMe:
    """Test /auth/me endpoint."""

    def test_auth_me_without_auth_returns_unauthenticated(self, test_client):
        """Test GET /api/v1/auth/me returns unauthenticated when no cookie."""
        response = test_client.get("/api/v1/auth/me")
        assert response.status_code == 200
        data = response.json()
        assert data["authenticated"] is False
        assert data["user"] is None

    def test_auth_me_with_invalid_cookie_returns_unauthenticated(self, test_client):
        """Test GET /api/v1/auth/me returns unauthenticated with invalid cookie."""
        response = test_client.get("/api/v1/auth/me", cookies={"auth_token": "invalid-token"})
        assert response.status_code == 200
        data = response.json()
        assert data["authenticated"] is False
