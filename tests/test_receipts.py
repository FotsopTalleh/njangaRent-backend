# tests/test_receipts.py
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


class TestReceiptsList:
    def test_unauthenticated_returns_401(self, client):
        resp = client.get("/receipts")
        assert resp.status_code == 401

    def test_authenticated_returns_ok(self, client, monkeypatch):
        from app.services.auth_service import AuthService
        svc = AuthService()
        token = svc.create_access_token("landlord-uid", "landlord", "landlord@test.com")

        monkeypatch.setattr(
            "app.blueprints.receipts.routes._db",
            lambda: _MockDb([]),
        )
        monkeypatch.setattr(
            "app.blueprints.receipts.routes.paginate_query",
            lambda q, page, limit: ([], 0),
        )
        resp = client.get(
            "/receipts",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True


class TestReceiptDownload:
    def test_unauthenticated_returns_401(self, client):
        resp = client.get("/receipts/fake-id/download")
        assert resp.status_code == 401

    def test_not_found_returns_404(self, client, monkeypatch):
        from app.services.auth_service import AuthService
        svc = AuthService()
        token = svc.create_access_token("landlord-uid", "landlord", "landlord@test.com")

        monkeypatch.setattr(
            "app.blueprints.receipts.routes._db",
            lambda: _MockDbNotFound(),
        )
        resp = client.get(
            "/receipts/nonexistent/download",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 404
        assert resp.get_json()["error"]["code"] == "RECEIPT_NOT_FOUND"


class _MockDb:
    def __init__(self, docs):
        self._docs = docs

    def collection(self, name):
        return self

    def where(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def stream(self):
        return iter(self._docs)

    def document(self, doc_id):
        return _MockDocRef(exists=False)


class _MockDbNotFound:
    def collection(self, name):
        return self

    def document(self, doc_id):
        return _MockDocRef(exists=False)


class _MockDocRef:
    def __init__(self, exists):
        self.exists = exists

    def get(self):
        return self

    def to_dict(self):
        return {}
