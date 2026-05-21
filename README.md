# MyTenant Backend

Production-ready Flask REST API backend for **MyTenant** — a digital rent management SaaS for landlords and tenants.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Framework | Flask 3 (Blueprint architecture) |
| Database | Google Firestore (Firebase Admin SDK) |
| Auth | PyJWT (HS256) — custom, no Firebase Auth |
| Media Storage | Cloudinary (server-side only) |
| PDF Generation | WeasyPrint + Jinja2 |
| Rate Limiting | Flask-Limiter + Redis |
| Push Notifications | Firebase Admin SDK (FCM HTTP v1) |
| OCR | n8n webhook (self-hosted) |
| Task Scheduling | Celery + Celery Beat + Redis |
| Containerisation | Docker + Docker Compose |

---

## Project Structure

```
mytenant-backend/
  app/
    __init__.py          ← Flask app factory (create_app())
    config.py            ← DevelopmentConfig / ProductionConfig
    extensions.py        ← Limiter, Firestore, Cloudinary, Firebase
    blueprints/          ← auth, properties, tenants, payments, receipts, notifications, webhooks
    services/            ← Business logic layer
    middleware/          ← JWT decorators, error handlers, rate limit keys
    utils/               ← response.py, validators.py, pagination.py, constants.py
    templates/receipts/  ← Jinja2 HTML template for PDF receipts
    tasks/               ← Celery app + rent_reminder task
  tasks/                 ← Project-root shims for Celery CLI
  tests/                 ← pytest test suite
  Dockerfile
  docker-compose.yml
  requirements.txt
  .env.example
```

---

## Quick Start

### 1. Prerequisites

- Docker + Docker Compose
- Firebase project with Firestore enabled
- A downloaded Firebase service account JSON file
- Cloudinary account
- (Optional) SendGrid API key for email

### 2. Environment Setup

```bash
cp .env.example .env
# Edit .env and fill in all placeholder values
```

Generate secrets:
```bash
python -c "import secrets; print(secrets.token_hex(64))"   # ACCESS_TOKEN_SECRET
python -c "import secrets; print(secrets.token_hex(64))"   # REFRESH_TOKEN_SECRET
python -c "import secrets; print(secrets.token_hex(32))"   # N8N_WEBHOOK_SECRET
```

Place your Firebase service account at `./firebase-service-account.json`.

### 3. Run with Docker Compose

```bash
docker compose up --build
```

Services:
| Service | Port | Role |
|---|---|---|
| `flask` | 5000 | API server |
| `redis` | 6379 | Broker + cache |
| `n8n` | 5678 | OCR automation |
| `celery-worker` | — | Background tasks |
| `celery-beat` | — | Scheduler |

### 4. Local Development (without Docker)

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt

# Start Redis locally (or via Docker):
docker run -d -p 6379:6379 redis:7-alpine

flask run --port 5000
```

---

## API Reference

### Authentication

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| POST | `/auth/signup` | — | Register as landlord |
| POST | `/auth/login` | — | Email/password login |
| POST | `/auth/google` | — | Google OAuth (verify ID token) |
| POST | `/auth/refresh` | cookie | Rotate refresh token |
| POST | `/auth/logout` | cookie | Blacklist refresh token |
| POST | `/auth/forgot-password` | — | Trigger reset email |
| POST | `/auth/reset-password` | — | Set new password via token |
| GET  | `/auth/invite/:token/verify` | — | Preview invitation details |
| POST | `/auth/invite/:token/complete` | — | Accept invite, create tenant account |

### Properties (landlord only)

| Method | Endpoint | Description |
|---|---|---|
| GET | `/properties` | List all properties (paginated) |
| POST | `/properties` | Create property |
| GET | `/properties/:id` | Get property + active tenants |
| PUT | `/properties/:id` | Update property (partial) |
| DELETE | `/properties/:id` | Delete (blocks if active tenants) |

### Tenants (landlord only)

| Method | Endpoint | Description |
|---|---|---|
| GET | `/tenants` | List tenants (filterable by propertyId, status) |
| POST | `/tenants/invite` | Send tenant invitation email |
| GET | `/tenants/:id` | Get tenant profile + recent payments |
| DELETE | `/tenants/:id` | Soft-remove tenant |

### Payments

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| POST | `/payments` | tenant | Submit proof (multipart, max 10 MB) |
| GET | `/payments` | both | List (landlord sees all, tenant sees own) |
| GET | `/payments/:id` | both | Get payment detail |
| PATCH | `/payments/:id/approve` | landlord | Approve + trigger OCR |
| PATCH | `/payments/:id/reject` | landlord | Reject + notify tenant |

### Receipts

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| GET | `/receipts` | both | List receipts |
| GET | `/receipts/:id` | both | Get receipt |
| GET | `/receipts/:id/download` | both | Get Cloudinary PDF URL |

### Notifications

| Method | Endpoint | Description |
|---|---|---|
| GET | `/notifications` | List (filterable by read=false) |
| PATCH | `/notifications/:id/read` | Mark single as read |
| PATCH | `/notifications/read-all` | Batch mark all as read |
| POST | `/notifications/subscribe` | Register FCM token |
| DELETE | `/notifications/subscribe` | Remove FCM token |

### Webhooks (internal — not public)

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| POST | `/webhooks/n8n/ocr-result` | X-N8N-Secret header | Receive OCR result from n8n |

---

## Response Envelope

All responses follow a standard JSON envelope:

```json
// Success
{ "success": true, "data": { ... }, "message": "optional" }

// Paginated
{ "success": true, "data": [...], "pagination": { "page": 1, "limit": 20, "total": 84, "hasNext": true } }

// Error
{ "success": false, "error": { "code": "ERROR_CODE", "message": "Human readable", "field": null } }
```

---

## n8n OCR Workflow (self-hosted)

n8n is responsible for OCR processing. The Flask backend does **not** implement OCR itself.

**Flask → n8n (trigger):**
```json
POST http://n8n:5678/webhook/ocr-trigger
X-N8N-Secret: <N8N_WEBHOOK_SECRET>
{
  "paymentId": "...",
  "proofImageUrl": "https://res.cloudinary.com/...",
  "landlordId": "...",
  "tenantId": "...",
  "callbackUrl": "http://flask:5000/webhooks/n8n/ocr-result"
}
```

**n8n → Flask (callback):**
```json
POST http://flask:5000/webhooks/n8n/ocr-result
X-N8N-Secret: <N8N_WEBHOOK_SECRET>
{
  "paymentId": "...",
  "extractedAmount": 1500.00,
  "extractedDate": "2025-05-01",
  "extractedReference": "TXN123",
  "extractedPayerName": "John Doe",
  "ocrSuccess": true
}
```

Configure your n8n workflow to:
1. Receive `POST /webhook/ocr-trigger`
2. Download `proofImageUrl` from Cloudinary
3. Run OCR (Google Vision API, AWS Textract, or Tesseract)
4. POST structured result to `callbackUrl`

---

## Celery Scheduled Tasks

The `celery-beat` service runs a daily task at **08:00 UTC**:

- Queries all active tenants whose `rentDueDay` equals today's date
- Skips tenants who already have an approved payment for the current month
- Sends an FCM push notification to the rest

---

## Firestore Composite Indexes

Create these in the Firebase Console → Firestore → Indexes:

| Collection | Fields | Order |
|---|---|---|
| `payments` | `landlordId`, `status`, `submittedAt` | DESC |
| `payments` | `tenantId`, `createdAt` | DESC |
| `payments` | `propertyId`, `status`, `createdAt` | DESC |
| `tenants` | `landlordId`, `status` | — |
| `notifications` | `userId`, `read`, `createdAt` | DESC |

---

## Production Deployment Notes

- **Switch to Gunicorn:** `gunicorn -w 4 -b 0.0.0.0:5000 "app:create_app()"`
- **HTTPS:** Terminate TLS at Nginx or a cloud load balancer — Flask does not handle TLS
- **Secrets:** Mount `firebase-service-account.json` as a Docker secret, not a bind volume
- **Redis:** Enable AOF persistence (`--appendonly yes` — already set in `docker-compose.yml`)
- **FLASK_ENV:** Set to `production` to enable strict cookie security and disable debug mode
- **CORS:** `FRONTEND_URL` must match the exact origin of your deployed frontend

---

## Running Tests

```bash
pip install -r requirements.txt
pytest tests/ -v
```

> **Note:** Tests requiring live Firestore/Firebase connections use `monkeypatch` to mock
> external dependencies. Ensure a local Redis is running on port 6379 for full test execution.
