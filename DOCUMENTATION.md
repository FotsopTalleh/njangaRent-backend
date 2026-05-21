# mytenant-backend — Backend Documentation

> **Project role:** The Flask REST API backend for the MyTenant rent management platform.
> It authenticates users via Firebase Auth JWTs, persists all domain data in Cloud Firestore, generates PDF receipts with WeasyPrint and Jinja2, stores receipt files on Cloudinary, and dispatches in-app and email notifications.

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Technology Stack](#2-technology-stack)
3. [Project Structure](#3-project-structure)
4. [Application Factory & Bootstrap](#4-application-factory--bootstrap)
5. [Authentication & Middleware](#5-authentication--middleware)
6. [API Blueprint Reference](#6-api-blueprint-reference)
7. [Service Layer](#7-service-layer)
8. [Firestore Data Models](#8-firestore-data-models)
9. [Receipt Generation Pipeline](#9-receipt-generation-pipeline)
10. [Manual Receipt Workflow](#10-manual-receipt-workflow)
11. [Notification System](#11-notification-system)
12. [Background Tasks (Celery)](#12-background-tasks-celery)
13. [Environment Variables](#13-environment-variables)
14. [Running Locally](#14-running-locally)
15. [Docker](#15-docker)
16. [Testing](#16-testing)

---

## 1. Project Overview

`mytenant-backend` is a **Python Flask REST API** that powers two user roles:

| Role | Identifier | Description |
|------|-----------|-------------|
| **Landlord** | Firebase Auth UID | Creates properties, invites tenants, reviews payment proofs, generates receipts, views analytics |
| **Tenant** | Firebase Auth UID (linked to a Firestore `tenants` document) | Uploads rent payment proof images, views their payment history and receipts |

All API responses follow a consistent **JSON envelope**:

```json
// Success
{ "data": { ... }, "status": "success" }

// Paginated success
{ "data": [...], "page": 1, "limit": 20, "total": 42, "status": "success" }

// Error
{ "error": { "code": "VALIDATION_ERROR", "message": "...", "field": "tenantId" } }
```

---

## 2. Technology Stack

### Core Framework

| Technology | Version | Purpose |
|-----------|---------|---------|
| **Python** | 3.11+ | Runtime language |
| **Flask** | 3.0.3 | Micro web framework. Application factory pattern (`create_app()`) with Blueprint-based modular routing |
| **python-dotenv** | 1.0.1 | Loads `.env` variables into `os.environ` at startup before any configuration is read |
| **flask-cors** | 4.0.1 | Cross-Origin Resource Sharing (CORS) — allows the `rentflow-pro` frontend on a different origin to make authenticated requests. `supports_credentials=True` is required for the httpOnly `refresh_token` cookie |

### Authentication & Security

| Technology | Version | Purpose |
|-----------|---------|---------|
| **firebase-admin** | 6.5.0 | Firebase Admin Python SDK. Used for: Firestore client (`firestore.client()`), verifying Firebase ID tokens in the auth middleware, sending FCM push notifications via `messaging` |
| **PyJWT** | 2.8.0 | JWT encode/decode for the custom `access_token` and `refresh_token` issued by the backend (separate from Firebase tokens — the backend issues its own signed tokens after verifying Firebase credentials) |
| **bcrypt** | 4.1.3 | Password hashing for email/password authentication |
| **google-auth** | 2.29.0 | Google OAuth2 token verification for the "Sign in with Google" flow |

### Database

| Technology | Version | Purpose |
|-----------|---------|---------|
| **Cloud Firestore** (via firebase-admin) | 6.5.0 | Primary NoSQL document database for all domain data: users, properties, tenants, payments, receipts, notifications, invitations |

### File Storage & Media

| Technology | Version | Purpose |
|-----------|---------|---------|
| **Cloudinary** | 1.40.0 | Cloud media storage. Used for: storing uploaded rent payment proof images (OCR-processed), and storing generated PDF receipt files |

### PDF & Template Rendering

| Technology | Version | Purpose |
|-----------|---------|---------|
| **WeasyPrint** | 61.2 | HTML-to-PDF converter. Renders Jinja2 HTML receipt templates to a PDF binary. **Requires GTK3 + Cairo native libraries** on the host OS — use Docker in production |
| **Jinja2** | 3.1.4 | Python HTML templating engine. Receipt templates are in `app/templates/receipts/`. Also used directly in the receipt preview endpoint to render HTML for browser viewing |

### Validation

| Technology | Version | Purpose |
|-----------|---------|---------|
| **marshmallow** | 3.21.3 | Schema-based request body validation and deserialization. Each Blueprint has a `schemas.py` with marshmallow `Schema` subclasses for its POST/PATCH endpoints |
| **python-magic** | 0.4.27 | MIME-type detection from file content (not just extension) — used to validate that uploaded payment proof files are genuinely images |

### Rate Limiting

| Technology | Version | Purpose |
|-----------|---------|---------|
| **Flask-Limiter** | 3.7.0 | Per-endpoint and global rate limiting. Default limit: 200 requests/minute. Backed by Redis; degrades gracefully (`swallow_errors=True`) if Redis is unavailable |
| **redis** | 5.0.4 | Redis client used as the Flask-Limiter storage backend and as the Celery message broker |

### Background Tasks

| Technology | Version | Purpose |
|-----------|---------|---------|
| **Celery** | 5.4.0 | Distributed task queue. Used for asynchronous PDF generation and upload tasks so the HTTP request returns immediately |
| **celery[redis]** | 5.4.0 | Redis transport for Celery (broker + result backend) |

### HTTP & External APIs

| Technology | Version | Purpose |
|-----------|---------|---------|
| **requests** | 2.32.3 | HTTP client used for triggering n8n webhook automations |
| **sendgrid** | 6.11.0 | SendGrid API client for transactional email (invite emails, payment notifications) |

### Production Server

| Technology | Version | Purpose |
|-----------|---------|---------|
| **gunicorn** | 22.0.0 | WSGI HTTP server for production. Configured with multiple workers for concurrent request handling |

### Testing

| Technology | Version | Purpose |
|-----------|---------|---------|
| **pytest** | 8.2.2 | Python test runner |
| **pytest-flask** | 1.3.0 | Flask-specific pytest fixtures (provides `client`, `app` fixtures) |

### OCR

| Technology | Service | Purpose |
|-----------|---------|---------|
| **OCR service** (`app/services/ocr_service.py`) | External / configured | Extracts payment amounts from uploaded proof images to pre-fill the payment amount field. The extracted value is compared against the tenant's claimed amount during landlord review |

---

## 3. Project Structure

```
mytenant-backend/
├── app/
│   ├── __init__.py             # Application factory: create_app(), extension init, blueprint registration
│   ├── config.py               # Config classes (Development, Production); reads from env vars
│   ├── extensions.py           # Firestore singleton, Flask-Limiter, Cloudinary init
│   ├── blueprints/             # Feature modules — each is a Flask Blueprint
│   │   ├── auth/
│   │   │   ├── routes.py       # POST /auth/login, /signup, /refresh, /logout, /google, /forgot-password, /reset-password, /invite
│   │   │   └── schemas.py
│   │   ├── properties/
│   │   │   ├── routes.py       # GET/POST /properties, GET/PUT/DELETE /properties/<id>
│   │   │   └── schemas.py
│   │   ├── tenants/
│   │   │   ├── routes.py       # GET /tenants, GET /tenants/me, GET/DELETE /tenants/<id>, POST /tenants/invite
│   │   │   └── schemas.py
│   │   ├── payments/
│   │   │   ├── routes.py       # POST /payments/submit, GET /payments, GET /payments/<id>, POST /payments/<id>/review
│   │   │   └── schemas.py
│   │   ├── receipts/
│   │   │   ├── routes.py       # GET /receipts, GET /receipts/<id>, GET /receipts/<id>/download, GET /receipts/<id>/preview, POST /receipts/manual
│   │   │   └── schemas.py      # ManualReceiptSchema
│   │   ├── notifications/
│   │   │   ├── routes.py       # GET /notifications, POST /notifications/<id>/read, POST /notifications/read-all
│   │   │   └── schemas.py
│   │   └── webhooks/
│   │       └── routes.py       # POST /webhooks/n8n (internal n8n automation triggers)
│   ├── middleware/
│   │   ├── auth_middleware.py  # @require_auth, @require_role decorators
│   │   └── error_handlers.py   # Global Flask error handlers (404, 405, 500, etc.)
│   ├── services/
│   │   ├── auth_service.py     # User creation, JWT issue/verify, Google OAuth
│   │   ├── cloudinary_service.py # Upload to Cloudinary, delete assets
│   │   ├── invite_service.py   # Generate invite tokens, validate invites
│   │   ├── notification_service.py # Create in-app notifications, FCM push, email dispatch
│   │   ├── ocr_service.py      # Extract amounts from proof images
│   │   ├── payment_service.py  # Payment record CRUD, approval/rejection logic
│   │   ├── property_service.py # Property CRUD
│   │   ├── receipt_service.py  # PDF generation, Cloudinary upload, manual receipt creation
│   │   ├── tenant_service.py   # Tenant CRUD, active tenant lookups
│   │   └── user_service.py     # User profile CRUD (Firestore `users` collection)
│   ├── tasks/                  # Celery task definitions
│   ├── templates/
│   │   └── receipts/
│   │       └── receipt.html    # Jinja2 receipt template (rendered to PDF and HTML preview)
│   └── utils/
│       ├── constants.py        # Error code constants, PAYMENT_METHODS list
│       ├── pagination.py       # paginate_query(), parse_pagination_args()
│       └── response.py         # success_response(), error_response(), paginated_response() helpers
├── tasks/                      # Celery app entry point
├── tests/                      # pytest test suite
├── Dockerfile                  # Multi-stage Docker build (Python + GTK3/Cairo for WeasyPrint)
├── docker-compose.yml          # Flask + Redis + Celery worker composition
├── requirements.txt
├── firebase-service-account.json   # Firebase service account credentials (never commit!)
├── .env                        # Local environment variables (never commit!)
└── .env.example                # Template for required environment variables
```

---

## 4. Application Factory & Bootstrap

`app/__init__.py` — `create_app()`:

1. **Load .env** — `load_dotenv()` runs before any other import so all env vars are available.
2. **Config** — `app.config.from_object(get_config())` loads environment-specific settings from `app/config.py`.
3. **Flask-Limiter** — `limiter.init_app(app)` registers the rate limiter with Redis as the storage backend.
4. **Cloudinary** — `init_cloudinary(app)` configures the Cloudinary SDK from Flask app config.
5. **Firestore warmup** — Firestore's gRPC channel takes 3–8 seconds to establish on the first request. A background thread (`firestore-warmup`) fires a cheap `limit(1)` stream immediately at startup so the connection is pre-warmed before any user traffic.
6. **CORS** — `flask-cors` is configured to accept requests from all known frontend origins (localhost Vite ports and the production `FRONTEND_URL`). `supports_credentials=True` enables the httpOnly `refresh_token` cookie.
7. **Blueprints** — All 7 blueprints are registered: `auth_bp`, `properties_bp`, `tenants_bp`, `payments_bp`, `receipts_bp`, `notifications_bp`, `webhooks_bp`.
8. **Health check** — `GET /health` returns `{"status": "ok"}` — used by Docker and load balancer health checks.
9. **Error handlers** — Global Flask error handlers for 404, 405, 500, and validation errors are registered from `app/middleware/error_handlers.py`.

---

## 5. Authentication & Middleware

### JWT Token Strategy

The backend issues its own **short-lived access tokens** and **long-lived refresh tokens** (separate from Firebase ID tokens):

| Token | Storage | Lifetime | Signing |
|-------|---------|---------|--------|
| `access_token` | HTTP response body → Zustand in-memory | Configurable (default ~15 min) | Backend `SECRET_KEY` via PyJWT |
| `refresh_token` | httpOnly cookie | Configurable (default ~30 days) | Backend `SECRET_KEY` via PyJWT |

**Login flow:**
1. Client sends Firebase ID token (from Firebase client SDK) to `POST /auth/login` or `POST /auth/google`.
2. Backend verifies the Firebase ID token using `firebase_admin.auth.verify_id_token()`.
3. Backend looks up or creates the user record in Firestore.
4. Backend issues its own `access_token` (JWT payload: `{ sub, email, role }`) and `refresh_token`.
5. `refresh_token` is set as an httpOnly, SameSite=Lax cookie. `access_token` is returned in the response body.

**Refresh flow:**
- Client calls `POST /auth/refresh` with the httpOnly cookie.
- Backend verifies the refresh token, re-issues both tokens.

### Auth Middleware Decorators

Defined in `app/middleware/auth_middleware.py`:

```python
@require_auth
def my_endpoint():
    # g.user is now populated: { sub, email, role, ... }
    ...

@require_role("landlord")
def landlord_only_endpoint():
    # Returns 403 if g.user["role"] != "landlord"
    ...
```

`@require_auth`:
1. Reads `Authorization: Bearer <token>` header.
2. Verifies and decodes the JWT using the backend `SECRET_KEY`.
3. Populates `flask.g.user` with the decoded payload.
4. Returns `401 UNAUTHORIZED` if missing, expired, or invalid.

`@require_role(role)`:
- Calls `@require_auth` first, then checks `g.user["role"] == role`.
- Returns `403 FORBIDDEN` if the role does not match.

---

## 6. API Blueprint Reference

### `/auth` — `blueprints/auth/routes.py`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/auth/login` | None | Verify Firebase ID token, issue backend JWT tokens |
| POST | `/auth/signup` | None | Create user account + verify Firebase ID token |
| POST | `/auth/google` | None | Google OAuth sign-in, issue tokens |
| POST | `/auth/refresh` | httpOnly cookie | Issue new access + refresh tokens |
| POST | `/auth/logout` | Bearer | Invalidate refresh token |
| POST | `/auth/forgot-password` | None | Send password reset email |
| POST | `/auth/reset-password` | Reset token | Set new password |
| GET | `/auth/invite` | None | Preview invite details (tenant sign-up flow) |

### `/properties` — `blueprints/properties/routes.py`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/properties` | Landlord | List landlord's properties |
| POST | `/properties` | Landlord | Create a new property |
| GET | `/properties/<id>` | Landlord | Get property details |
| PUT | `/properties/<id>` | Landlord | Update property |
| DELETE | `/properties/<id>` | Landlord | Delete property |

### `/tenants` — `blueprints/tenants/routes.py`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/tenants` | Landlord | List tenants; enriched with `fullName` + `email` from user profiles |
| POST | `/tenants/invite` | Landlord | Send invitation email + create invite record |
| GET | `/tenants/me` | Tenant | Tenant fetches their own record |
| GET | `/tenants/<id>` | Landlord | Tenant detail with payment history |
| DELETE | `/tenants/<id>` | Landlord | Remove (deactivate) tenant |

> **Enrichment note:** The `GET /tenants` endpoint fetches each tenant's `userId`, then calls `UserService.get_by_id(userId)` to retrieve `fullName` and `email` from the `users` Firestore collection and appends them to the tenant document before returning. This enables the manual receipt form dropdown to show human-readable names.

### `/payments` — `blueprints/payments/routes.py`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/payments/submit` | Tenant | Submit a rent payment with proof image (multipart/form-data) |
| GET | `/payments` | Both | List payments (landlord sees all; tenant sees their own) |
| GET | `/payments/<id>` | Both | Get payment details |
| POST | `/payments/<id>/review` | Landlord | Approve or reject a payment; triggers receipt generation on approval |

### `/receipts` — `blueprints/receipts/routes.py`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/receipts` | Both | List receipts; landlord sees all, tenant sees their own (resolved via tenant document lookup) |
| GET | `/receipts/<id>` | Both | Get single receipt; ownership enforced |
| GET | `/receipts/<id>/download` | Both | Returns `{ pdfUrl, hasPreview }`. If pdfUrl is set (Cloudinary), frontend opens it directly. hasPreview=True signals the frontend to use `/preview` |
| GET | `/receipts/<id>/preview` | Both | Returns the receipt rendered as a full HTML page (via Jinja2 template). Auth header required; used as a fallback when PDF is unavailable |
| POST | `/receipts/manual` | Landlord | Create a manual receipt for a cash/hand payment (no proof image) |

#### Tenant ID resolution in receipt endpoints

`receipts` documents store `tenantId` as the Firestore **tenant document ID** — not the Firebase Auth UID. When a tenant requests their receipts, the backend must resolve their Firebase UID → tenant document ID before filtering:

```python
tenant = TenantService.get_by_user_id(user["sub"])
tenant_id = tenant["id"] if tenant else "__none__"
query = query.where("tenantId", "==", tenant_id)
```

### `/notifications` — `blueprints/notifications/routes.py`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/notifications` | Both | List notifications for the current user; ordered by `createdAt` desc |
| POST | `/notifications/<id>/read` | Both | Mark a notification as read |
| POST | `/notifications/read-all` | Both | Mark all notifications as read |

### `/webhooks` — `blueprints/webhooks/routes.py`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/webhooks/n8n` | `X-N8N-Secret` header | Triggered by n8n automation workflows for scheduled tasks (e.g., rent due reminders) |

---

## 7. Service Layer

All business logic lives in `app/services/`. Services are stateless classes with `@staticmethod` or `@classmethod` methods.

### `receipt_service.py` — `ReceiptService`

The most complex service. It orchestrates the full receipt lifecycle:

| Method | Description |
|--------|-------------|
| `generate_receipt(payment_id)` | Core pipeline: fetch payment → fetch tenant/landlord/property → render HTML → generate PDF (if WeasyPrint available) → upload to Cloudinary → write `receipts` document → return receipt dict |
| `generate_manual_receipt(...)` | Creates an approved payment record with `isManual=True`, then calls `generate_receipt()` |
| `list_receipts(user, ...)` | Queries the `receipts` collection with role-aware filtering |
| `get_receipt(id)` | Fetches a single receipt by ID |

**WeasyPrint availability guard:**

```python
try:
    from weasyprint import HTML as _WeasyHTML
    _WEASYPRINT_AVAILABLE = True
except (ImportError, OSError):
    _WeasyHTML = None
    _WEASYPRINT_AVAILABLE = False
```

If WeasyPrint's GTK/Cairo native dependencies are not installed (common on Windows dev machines), the service falls back to `pdfUrl = ""` and `hasPreview = True`, which tells the frontend to use the `/preview` HTML endpoint instead.

### `auth_service.py` — `AuthService`

Handles user creation, JWT issuance, Firebase token verification, and Google OAuth.

### `cloudinary_service.py` — `CloudinaryService`

| Method | Description |
|--------|-------------|
| `upload_image(file, folder, public_id)` | Uploads image bytes to Cloudinary; returns `(url, public_id)` |
| `upload_pdf(pdf_bytes, public_id)` | Uploads PDF bytes with `resource_type="raw"` |
| `delete(public_id)` | Deletes an asset from Cloudinary |

### `tenant_service.py` — `TenantService`

| Method | Description |
|--------|-------------|
| `get_by_id(tenant_id)` | Fetch tenant document by Firestore ID |
| `get_by_user_id(user_id)` | Resolve Firebase UID → tenant document |
| `get_by_user_and_landlord(user_id, landlord_id)` | Unique tenant lookup for a user-landlord pair |
| `list_for_landlord(landlord_id, ...)` | Firestore query: `where("landlordId", "==", ...)` |
| `create(...)` | Create a new tenant document |
| `remove(tenant_id)` | Set `status = "removed"` |
| `get_due_today(day_of_month)` | Find all active tenants with `rentDueDay == day_of_month` (used by Celery rent-due reminder task) |

### `notification_service.py` — `NotificationService`

| Method | Description |
|--------|-------------|
| `notify_payment_approved(...)` | Creates an in-app notification document and dispatches an email to the tenant |
| `notify_payment_rejected(...)` | In-app + email notification for rejection |
| `notify_rent_due(...)` | In-app + email reminder when rent is due |

### `user_service.py` — `UserService`

| Method | Description |
|--------|-------------|
| `get_by_id(user_id)` | Fetch user document by Firebase UID |
| `get_by_email(email)` | Lookup by email (for invite flow) |
| `create(user_id, ...)` | Create user profile in Firestore `users` collection |
| `update(user_id, data)` | Update user profile |

---

## 8. Firestore Data Models

All collections are flat (no sub-collections). Documents are linked by storing IDs.

### `users` collection

| Field | Type | Description |
|-------|------|-------------|
| `uid` | string | Firebase Auth UID (also the document ID) |
| `email` | string | User email |
| `fullName` | string | Display name |
| `role` | `"landlord" \| "tenant"` | User role |
| `createdAt` | Timestamp | |
| `updatedAt` | Timestamp | |

### `properties` collection

| Field | Type | Description |
|-------|------|-------------|
| `landlordId` | string | Firebase UID of the landlord |
| `name` | string | Property name |
| `address` | string | Street address |
| `type` | string | e.g. `"apartment"`, `"house"` |
| `createdAt` | Timestamp | |

### `tenants` collection

| Field | Type | Description |
|-------|------|-------------|
| `userId` | string | Firebase UID of the tenant user |
| `landlordId` | string | Firebase UID of the landlord |
| `propertyId` | string | Firestore `properties` document ID |
| `monthlyRent` | number | Monthly rent amount |
| `rentDueDay` | number | Day of month rent is due (1–28) |
| `status` | `"active" \| "removed"` | |
| `createdAt` | Timestamp | |
| `updatedAt` | Timestamp | |

### `payments` collection

| Field | Type | Description |
|-------|------|-------------|
| `tenantId` | string | Firestore `tenants` document ID |
| `userId` | string | Firebase UID of the tenant |
| `landlordId` | string | Firebase UID of the landlord |
| `propertyId` | string | Firestore `properties` document ID |
| `amountClaimed` | number | Amount stated by the tenant |
| `amountExtracted` | number | Amount extracted by OCR |
| `paymentDate` | string | `YYYY-MM-DD` |
| `paymentMethod` | string | `cash \| mobile_money \| bank_transfer \| other` |
| `proofImageUrl` | string | Cloudinary URL of the proof image |
| `proofPublicId` | string | Cloudinary public ID for deletion |
| `status` | `"pending" \| "approved" \| "rejected"` | |
| `isManual` | boolean | True for landlord-created (cash) payments |
| `referenceNumber` | string | Optional transaction reference |
| `notes` | string | Optional landlord notes |
| `submittedAt` | Timestamp | |
| `reviewedAt` | Timestamp | |
| `createdAt` | Timestamp | |
| `updatedAt` | Timestamp | |

### `receipts` collection

| Field | Type | Description |
|-------|------|-------------|
| `paymentId` | string | Firestore `payments` document ID |
| `tenantId` | string | Firestore `tenants` document ID |
| `landlordId` | string | Firebase UID of the landlord |
| `propertyId` | string | Firestore `properties` document ID |
| `receiptNumber` | string | Auto-generated unique number (e.g. `RCPT-20240521-001`) |
| `amountPaid` | number | Confirmed payment amount |
| `paymentDate` | string | `YYYY-MM-DD` |
| `paymentMethod` | string | |
| `referenceNumber` | string | Optional |
| `pdfUrl` | string | Cloudinary URL of the PDF (empty if WeasyPrint unavailable) |
| `pdfPublicId` | string | Cloudinary public ID of the PDF |
| `tenantName` | string | Denormalized from user profile at generation time |
| `landlordName` | string | Denormalized |
| `propertyName` | string | Denormalized |
| `propertyAddress` | string | Denormalized |
| `isManual` | boolean | True for cash/hand payments |
| `generatedAt` | Timestamp | |
| `createdAt` | Timestamp | |

### `notifications` collection

| Field | Type | Description |
|-------|------|-------------|
| `userId` | string | Firebase UID of the recipient |
| `type` | string | `payment_approved \| payment_rejected \| rent_due \| receipt_issued` |
| `title` | string | Short notification title |
| `body` | string | Full notification message |
| `read` | boolean | |
| `receiptId` | string | Optional — links to the relevant receipt |
| `paymentId` | string | Optional |
| `createdAt` | Timestamp | |

### `invitations` collection

| Field | Type | Description |
|-------|------|-------------|
| `token` | string | Secure random invite token |
| `email` | string | Invited tenant's email |
| `landlordId` | string | |
| `propertyId` | string | |
| `monthlyRent` | number | |
| `rentDueDay` | number | |
| `status` | `"pending" \| "accepted" \| "expired"` | |
| `expiresAt` | Timestamp | |
| `createdAt` | Timestamp | |

---

## 9. Receipt Generation Pipeline

When a landlord approves a payment (`POST /payments/<id>/review` with `action: "approved"`):

```
PaymentService.approve(payment_id)
        │
        └──► ReceiptService.generate_receipt(payment_id)
                    │
                    ├─ 1. Fetch payment document from Firestore
                    ├─ 2. Fetch tenant, user, landlord, property documents
                    ├─ 3. Generate unique receiptNumber (RCPT-YYYYMMDD-NNN)
                    ├─ 4. Render receipt.html via Jinja2
                    │       └─ paymentDate: safe datetime handling
                    │          (DatetimeWithNanoseconds → string)
                    │
                    ├─ 5. Generate PDF (WeasyPrint) if GTK/Cairo available
                    │       └─ If not available: pdfUrl = "", hasPreview = True
                    │
                    ├─ 6. Upload PDF to Cloudinary (folder: receipts/)
                    │       └─ Returns pdfUrl + pdfPublicId
                    │
                    ├─ 7. Write receipts document to Firestore
                    └─ 8. Return receipt dict to the calling endpoint
```

### HTML Preview Fallback

When `pdfUrl` is empty (WeasyPrint/GTK unavailable — common on Windows dev machines):

1. Frontend calls `GET /receipts/<id>/download` → receives `{ pdfUrl: "", hasPreview: true }`.
2. Frontend calls `GET /receipts/<id>/preview` with `responseType: "blob"`.
3. Backend calls `_render_receipt_html(receipt)` — renders the Jinja2 template to HTML string.
4. Returns the HTML with `Content-Type: text/html; charset=utf-8`.
5. Frontend creates a `Blob URL` from the HTML and navigates the already-open tab to it.
6. User can `Ctrl+P → Save as PDF` from the browser.

### Datetime Safety in `_render_receipt_html()`

Firestore stores timestamps as `DatetimeWithNanoseconds` objects (a `datetime` subclass). Older stored receipts may have `paymentDate` or `generatedAt` stored as Timestamp objects instead of strings. The `_render_receipt_html()` function handles this safely:

```python
payment_date = receipt.get("paymentDate", "")
if hasattr(payment_date, "strftime"):           # Firestore Timestamp
    payment_date = payment_date.strftime("%Y-%m-%d")
elif not isinstance(payment_date, str):
    payment_date = str(payment_date)
```

---

## 10. Manual Receipt Workflow

For cash / in-person payments where the tenant does not upload a proof image:

### Endpoint
`POST /receipts/manual` — requires `Landlord` role.

### Request body (validated by `ManualReceiptSchema`)

```json
{
  "tenantId": "firestore_tenant_doc_id",
  "amountPaid": 1500.00,
  "paymentDate": "2024-05-21",
  "paymentMethod": "cash",
  "referenceNumber": "optional",
  "notes": "optional"
}
```

### Workflow

```
POST /receipts/manual
        │
        ├─ 1. Validate request body (ManualReceiptSchema / marshmallow)
        ├─ 2. Verify tenantId belongs to this landlord (403 if not)
        ├─ 3. Verify tenant.status == "active" (422 if removed)
        │
        ├─ 4. ReceiptService.generate_manual_receipt(...)
        │       ├─ Create payments document:
        │       │     status = "approved"
        │       │     isManual = True
        │       │     proofImageUrl = ""  (no proof required)
        │       └─ Call generate_receipt(payment_id)
        │             └─ Full PDF generation pipeline (see §9)
        │
        ├─ 5. Tag receipt document: isManual = True
        │
        └─ 6. Notify tenant via NotificationService.notify_payment_approved()
                  └─ In-app notification + email
```

---

## 11. Notification System

`NotificationService` creates documents in the Firestore `notifications` collection and dispatches external alerts.

### In-App Notifications

Written directly to Firestore; the frontend polls via `GET /notifications` and displays an unread count badge.

### Email Notifications

Two email backends are supported (configured via env vars):

| Backend | Config | Notes |
|---------|--------|-------|
| **SendGrid** | `SENDGRID_API_KEY` set | Recommended for production |
| **SMTP** | `MAIL_SERVER`, `MAIL_PORT`, `MAIL_USERNAME`, `MAIL_PASSWORD` | Gmail SMTP supported; `MAIL_USERNAME` is used as the `From` address to satisfy Gmail SMTP restrictions |

Email dispatch runs in a `daemon=True` background thread so it does not block the HTTP response.

---

## 12. Background Tasks (Celery)

Celery is configured with Redis as both the message broker and the result backend.

**Starting the worker:**
```bash
celery -A tasks worker --loglevel=info
```

Current task definitions are in the `tasks/` directory. Example scheduled task: **rent due reminders** — queries `TenantService.get_due_today(day_of_month)` and dispatches notifications for each tenant whose rent is due today.

---

## 13. Environment Variables

Copy `.env.example` to `.env` and fill in all values:

```env
# ── Flask ─────────────────────────────────────────────────────────────────────
FLASK_ENV=development
SECRET_KEY=your-super-secret-key-change-this-in-prod
FRONTEND_URL=http://localhost:3000

# ── Firebase ──────────────────────────────────────────────────────────────────
FIREBASE_SERVICE_ACCOUNT_PATH=./firebase-service-account.json

# ── Cloudinary ────────────────────────────────────────────────────────────────
CLOUDINARY_CLOUD_NAME=your_cloud_name
CLOUDINARY_API_KEY=your_api_key
CLOUDINARY_API_SECRET=your_api_secret

# ── Redis ─────────────────────────────────────────────────────────────────────
REDIS_URL=redis://localhost:6379/0

# ── Email (choose one) ────────────────────────────────────────────────────────
# Option A: SendGrid
SENDGRID_API_KEY=SG.xxxxxxxxxxxx

# Option B: SMTP
MAIL_SERVER=smtp.gmail.com
MAIL_PORT=587
MAIL_USE_TLS=true
MAIL_USERNAME=your@gmail.com
MAIL_PASSWORD=your_app_password
MAIL_FROM_ADDRESS=noreply@mytenant.app
MAIL_FROM_NAME=MyTenant

# ── JWT ───────────────────────────────────────────────────────────────────────
ACCESS_TOKEN_EXPIRES_MINUTES=15
REFRESH_TOKEN_EXPIRES_DAYS=30

# ── n8n Webhook ───────────────────────────────────────────────────────────────
N8N_WEBHOOK_URL=https://your-n8n-instance/webhook/...
N8N_SECRET=your-webhook-secret

# ── Internal ──────────────────────────────────────────────────────────────────
INTERNAL_SECRET=your-internal-secret
```

---

## 14. Running Locally

**Prerequisites:**
- Python 3.11+
- Redis running on `localhost:6379`
- Firebase service account JSON file at `./firebase-service-account.json`
- (Optional) GTK3 + Cairo for WeasyPrint PDF generation — not required in dev; the HTML preview fallback works without it

```bash
cd mytenant-backend

# Create and activate virtual environment
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate    # macOS/Linux

# Install dependencies
pip install -r requirements.txt

# Copy and configure environment variables
cp .env.example .env
# Edit .env with your credentials

# Start the Flask development server
flask run --port 5000
# or
python -m flask --app "app:create_app()" run --port 5000

# (Separate terminal) Start Celery worker
celery -A tasks worker --loglevel=info
```

The backend will be available at `http://localhost:5000`. The `rentflow-pro` frontend proxies `/api/*` to this address.

---

## 15. Docker

`docker-compose.yml` starts three services:

| Service | Image | Port |
|---------|-------|------|
| `web` | `mytenant-backend` (Dockerfile) | 5000 |
| `redis` | `redis:7-alpine` | 6379 |
| `worker` | `mytenant-backend` (same image, Celery entrypoint) | — |

The `Dockerfile` installs GTK3 + Cairo (WeasyPrint dependencies) so PDF generation works fully in Docker even on Windows development machines.

```bash
# Build and start all services
docker-compose up --build

# Run in background
docker-compose up -d

# Stop
docker-compose down
```

---

## 16. Testing

```bash
# Run all tests
pytest

# Run with verbose output
pytest -v

# Run a specific test file
pytest tests/test_receipts.py -v
```

Test fixtures are provided by `pytest-flask` which auto-discovers the `conftest.py` file in `tests/` that creates a test Flask app with `TESTING=True` and an in-memory configuration.
