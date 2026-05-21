# tests/test_payments.py
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


class TestPaymentSubmission:
    def test_unauthenticated_returns_401(self, client):
        resp = client.post("/payments")
        assert resp.status_code == 401

    def test_landlord_cannot_submit_payment(self, client, monkeypatch):
        from app.services.auth_service import AuthService
        svc = AuthService()
        token = svc.create_access_token("landlord-uid", "landlord", "landlord@test.com")
        resp = client.post(
            "/payments",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403
        assert resp.get_json()["error"]["code"] == "AUTH_FORBIDDEN"


class TestPaymentList:
    def test_unauthenticated_returns_401(self, client):
        resp = client.get("/payments")
        assert resp.status_code == 401

    def test_authenticated_landlord_returns_paginated(self, client, monkeypatch):
        from app.services.auth_service import AuthService
        from app.services.payment_service import PaymentService

        svc = AuthService()
        token = svc.create_access_token("landlord-uid", "landlord", "landlord@test.com")

        monkeypatch.setattr(
            "app.blueprints.payments.routes.PaymentService.list_query",
            lambda **kwargs: _MockQuery([]),
        )
        monkeypatch.setattr(
            "app.blueprints.payments.routes.paginate_query",
            lambda q, page, limit: ([], 0),
        )

        resp = client.get(
            "/payments",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["success"] is True
        assert "pagination" in body


class TestPaymentApproval:
    def test_approve_unauthenticated_returns_401(self, client):
        resp = client.patch("/payments/fake-id/approve")
        assert resp.status_code == 401

    def test_approve_by_tenant_returns_403(self, client, monkeypatch):
        from app.services.auth_service import AuthService
        svc = AuthService()
        token = svc.create_access_token("tenant-uid", "tenant", "tenant@test.com")
        resp = client.patch(
            "/payments/fake-id/approve",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403


class _MockQuery:
    def __init__(self, items):
        self._items = items

    def stream(self):
        return iter(self._items)
