# ---------------------------------------------------------------------------
# app/__init__.py — Flask application factory (NjangaRent)
# ---------------------------------------------------------------------------
import logging
import os

from dotenv import load_dotenv
from flask import Flask
from flask_cors import CORS
from flask_socketio import SocketIO

load_dotenv()  # Load .env before anything else


def create_app(config_override=None) -> Flask:
    """Application factory.

    Usage::

        # dev server
        app = create_app()

        # testing
        app = create_app({"TESTING": True, ...})
    """
    app = Flask(__name__, template_folder="templates")

    # ── Load config ───────────────────────────────────────────────────────────
    from app.config import get_config
    app.config.from_object(get_config())
    if config_override:
        app.config.update(config_override)

    # ── Logging ───────────────────────────────────────────────────────────────
    log_level = logging.DEBUG if app.config.get("DEBUG") else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    # Flask-Limiter emits ERROR on every request when Redis is unavailable.
    # Demote to WARNING in dev (Redis is optional); no effect in prod where Redis runs.
    logging.getLogger("flask_limiter").setLevel(logging.WARNING)

    # ── Extensions ────────────────────────────────────────────────────────────
    from app.extensions import init_cloudinary, limiter, get_db
    limiter.init_app(app)
    init_cloudinary(app)

    # Eagerly initialise Firestore client (validates credentials, fast)
    with app.app_context():
        try:
            db = get_db()
        except Exception as exc:
            app.logger.warning("Firestore init deferred/failed: %s", exc)
            db = None

    # ── Firestore gRPC warmup ─────────────────────────────────────────────────
    # The Firestore admin SDK establishes the gRPC channel on the FIRST real
    # network call — making the first user request (login, signup) take 3-8s.
    # Fix: fire a lightweight background read immediately at startup so the
    # connection is pre-established before any user traffic arrives.
    if db is not None:
        import threading

        def _warmup():
            try:
                # A limit(1) stream on a non-existent collection is the cheapest
                # possible Firestore operation — no documents returned, but the
                # gRPC channel + Google auth tokens are fully initialised.
                list(db.collection("_warmup").limit(1).stream())
                app.logger.info("Firestore gRPC connection warmed up.")
            except Exception as exc:
                app.logger.debug("Firestore warmup skipped (non-fatal): %s", exc)

        threading.Thread(target=_warmup, daemon=True, name="firestore-warmup").start()

    # ── CORS ──────────────────────────────────────────────────────────────────
    # Allow configured FRONTEND_URL + common Vite dev-server ports
    _frontend = app.config.get("FRONTEND_URL", "http://localhost:3000")
    _cors_origins = list({
        _frontend,
        "http://localhost:3000",
        "http://localhost:5173",
        "http://localhost:4173",
        "http://localhost:8080",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:8080",
    })
    CORS(
        app,
        origins=_cors_origins,
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        supports_credentials=True,
        allow_headers=["Authorization", "Content-Type", "X-N8N-Secret", "X-Internal-Secret"],
    )

    # ── Flask-SocketIO (NjangaRent real-time chat) ────────────────────────────
    from app.extensions import socketio
    socketio.init_app(
        app,
        cors_allowed_origins=_cors_origins,
        async_mode="eventlet",
        logger=False,
        engineio_logger=False,
    )
    # Register Socket.io event handlers
    from app.sockets.chat import register_handlers
    register_handlers(socketio)

    # ── Blueprints ────────────────────────────────────────────────────────────
    # Original MyTenant blueprints
    from app.blueprints.auth.routes         import auth_bp
    from app.blueprints.notifications.routes import notifications_bp
    from app.blueprints.payments.routes     import payments_bp
    from app.blueprints.properties.routes   import properties_bp
    from app.blueprints.receipts.routes     import receipts_bp
    from app.blueprints.tenants.routes      import tenants_bp
    from app.blueprints.webhooks.routes     import webhooks_bp
    # NjangaRent new blueprints
    from app.blueprints.listings.routes     import listings_bp
    from app.blueprints.messages.routes     import messages_bp
    from app.blueprints.appointments.routes import appointments_bp
    from app.blueprints.nkwa_payments.routes import nkwa_bp
    from app.blueprints.admin.routes        import admin_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(properties_bp)
    app.register_blueprint(tenants_bp)
    app.register_blueprint(payments_bp)
    app.register_blueprint(receipts_bp)
    app.register_blueprint(notifications_bp)
    app.register_blueprint(webhooks_bp)
    app.register_blueprint(listings_bp)
    app.register_blueprint(messages_bp)
    app.register_blueprint(appointments_bp)
    app.register_blueprint(nkwa_bp)
    app.register_blueprint(admin_bp)

    # ── Health check ──────────────────────────────────────────────────────────
    @app.route("/health", methods=["GET"])
    def health():
        from flask import jsonify
        return jsonify({"status": "ok"}), 200

    # ── Global error handlers ─────────────────────────────────────────────────
    from app.middleware.error_handlers import register_error_handlers
    register_error_handlers(app)

    app.logger.info(
        "NjangaRent backend started [env=%s debug=%s]",
        os.environ.get("FLASK_ENV", "development"),
        app.config.get("DEBUG"),
    )
    return app
