# tests/test_webhooks.py
import json
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
        "N8N_WEBHOOK_SECRET": "test-webhook-secret-32chars0000000",
    })


@pytest.fixture
def client(app):
    return app.test_client()


VALID_SECRET = "test-webhook-secret-32chars0000000"

OCR_PAYLOAD = {
    "paymentId":       "test-payment-id",
    "extractedAmount": 1500.0,
    "extractedDate":   "2025-05-01",
    "ocrSuccess":      True,
}


class TestOcrResultWebhook:
    def test_missing_secret_returns_401(self, client):
        resp = client.post(
            "/webhooks/n8n/ocr-result",
            json=OCR_PAYLOAD,
        )
        assert resp.status_code == 401
        assert resp.get_json()["error"]["code"] == "AUTH_TOKEN_INVALID"

    def test_wrong_secret_returns_401(self, client):
        resp = client.post(
            "/webhooks/n8n/ocr-result",
            json=OCR_PAYLOAD,
            headers={"X-N8N-Secret": "wrong-secret"},
        )
        assert resp.status_code == 401

    def test_missing_payment_id_returns_success_with_message(self, client):
        resp = client.post(
            "/webhooks/n8n/ocr-result",
            json={"ocrSuccess": True},
            headers={"X-N8N-Secret": VALID_SECRET},
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["success"] is True   # n8n must not retry
        assert "paymentId" in body.get("message", "").lower() or body["data"] is None

    def test_payment_not_found_returns_404(self, client, monkeypatch):
        monkeypatch.setattr(
            "app.blueprints.webhooks.routes.PaymentService.get_by_id",
            lambda pid: None,
        )
        resp = client.post(
            "/webhooks/n8n/ocr-result",
            json=OCR_PAYLOAD,
            headers={"X-N8N-Secret": VALID_SECRET},
        )
        assert resp.status_code == 404
        assert resp.get_json()["error"]["code"] == "PAYMENT_NOT_FOUND"

    def test_non_approved_payment_skipped(self, client, monkeypatch):
        monkeypatch.setattr(
            "app.blueprints.webhooks.routes.PaymentService.get_by_id",
            lambda pid: {"id": pid, "status": "pending", "landlordId": "l1", "tenantId": "t1"},
        )
        resp = client.post(
            "/webhooks/n8n/ocr-result",
            json=OCR_PAYLOAD,
            headers={"X-N8N-Secret": VALID_SECRET},
        )
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True
