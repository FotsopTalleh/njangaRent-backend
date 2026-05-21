# tests/test_auth.py
import pytest
from app import create_app


@pytest.fixture
def app():
    return create_app({
        "TESTING": True,
        "SECRET_KEY": "test-secret",
        "ACCESS_TOKEN_SECRET": "test-access-secret",
        "REFRESH_TOKEN_SECRET": "test-refresh-secret",
        "REDIS_URL": "redis://localhost:6379/1",
        "FIREBASE_SERVICE_ACCOUNT_PATH": "./firebase-service-account.json",
        "CLOUDINARY_CLOUD_NAME": "test",
        "CLOUDINARY_API_KEY": "test",
        "CLOUDINARY_API_SECRET": "test",
        "FRONTEND_URL": "http://localhost:3000",
    })


@pytest.fixture
def client(app):
    return app.test_client()


# ── Signup ────────────────────────────────────────────────────────────────────

class TestSignup:
    def test_missing_fields_returns_422(self, client):
        resp = client.post("/auth/signup", json={})
        assert resp.status_code == 422
        data = resp.get_json()
        assert data["success"] is False
        assert data["error"]["code"] == "VALIDATION_ERROR"

    def test_invalid_email_returns_422(self, client):
        resp = client.post("/auth/signup", json={
            "fullName": "Test User",
            "email": "not-an-email",
            "password": "password123",
        })
        assert resp.status_code == 422

    def test_short_password_returns_422(self, client):
        resp = client.post("/auth/signup", json={
            "fullName": "Test User",
            "email": "test@example.com",
            "password": "short",
        })
        assert resp.status_code == 422


# ── Login ─────────────────────────────────────────────────────────────────────

class TestLogin:
    def test_missing_credentials_returns_422(self, client):
        resp = client.post("/auth/login", json={})
        assert resp.status_code == 422

    def test_invalid_credentials_returns_401(self, client, monkeypatch):
        from app.services import user_service
        monkeypatch.setattr(
            "app.blueprints.auth.routes.UserService.get_by_email",
            lambda email: None,
        )
        resp = client.post("/auth/login", json={
            "email": "nobody@example.com",
            "password": "wrongpassword",
        })
        assert resp.status_code == 401
        assert resp.get_json()["error"]["code"] == "AUTH_INVALID_CREDENTIALS"


# ── Refresh ───────────────────────────────────────────────────────────────────

class TestRefresh:
    def test_no_cookie_returns_401(self, client):
        resp = client.post("/auth/refresh")
        assert resp.status_code == 401
        assert resp.get_json()["error"]["code"] == "AUTH_TOKEN_INVALID"


# ── Logout ────────────────────────────────────────────────────────────────────

class TestLogout:
    def test_logout_clears_cookie(self, client):
        resp = client.post("/auth/logout")
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True


# ── Invite verify ─────────────────────────────────────────────────────────────

class TestInviteVerify:
    def test_invalid_token_returns_400(self, client):
        resp = client.get("/auth/invite/bad-token-here/verify")
        assert resp.status_code == 400
        code = resp.get_json()["error"]["code"]
        assert code in ("AUTH_INVITE_INVALID", "AUTH_INVITE_EXPIRED")
