# ---------------------------------------------------------------------------
# sockets/chat.py — Flask-SocketIO event handlers for real-time chat
# ---------------------------------------------------------------------------
import logging
from datetime import datetime, timezone

from flask import request
from flask_socketio import SocketIO, emit, join_room, leave_room, disconnect

from app.extensions import get_db
from app.services.auth_service import AuthService

logger = logging.getLogger(__name__)
_auth = AuthService()

CONVS_COL = "conversations"
MSGS_COL  = "messages"

# Module-level reference to the SocketIO instance (set by register_handlers)
_socketio: SocketIO = None


def register_handlers(socketio: SocketIO) -> None:
    """Register all Socket.io event handlers on the given SocketIO instance."""
    global _socketio
    _socketio = socketio

    @socketio.on("connect")
    def on_connect():
        """Verify JWT on connect. Disconnect unauthenticated clients immediately."""
        token = request.args.get("token", "")
        if not token:
            logger.warning("Socket.io connection rejected: no token")
            disconnect()
            return False

        try:
            payload = _auth.verify_access_token(token)
            # Store user context on the request session
            from flask import g
            g.socket_user = payload
            logger.debug("Socket.io connect: user=%s", payload.get("sub"))
        except AuthService.TokenExpiredError:
            logger.warning("Socket.io connection rejected: token expired")
            disconnect()
            return False
        except AuthService.TokenInvalidError:
            logger.warning("Socket.io connection rejected: token invalid")
            disconnect()
            return False

    @socketio.on("disconnect")
    def on_disconnect():
        logger.debug("Socket.io disconnect: sid=%s", request.sid)

    @socketio.on("join_conversation")
    def on_join(data):
        """Client joins a conversation room after verifying participation."""
        conv_id = data.get("conversationId", "")
        if not conv_id:
            return

        token = request.args.get("token", "")
        try:
            payload = _auth.verify_access_token(token)
            user_id = payload["sub"]
        except Exception:
            disconnect()
            return

        db   = get_db()
        doc  = db.collection(CONVS_COL).document(conv_id).get()
        if not doc.exists:
            return

        conv = doc.to_dict()
        if conv.get("studentId") != user_id and conv.get("landlordId") != user_id:
            logger.warning("User %s attempted to join conversation %s they don't own", user_id, conv_id)
            return

        join_room(conv_id)
        logger.debug("User %s joined room %s", user_id, conv_id)

    @socketio.on("send_message")
    def on_send_message(data):
        """Save message to Firestore and broadcast to the conversation room."""
        conv_id = data.get("conversationId", "")
        content = data.get("content", {})  # { type: "text"|"image", text?, imageUrl? }

        token = request.args.get("token", "")
        try:
            payload = _auth.verify_access_token(token)
            user_id   = payload["sub"]
            user_role = payload.get("role", "")
        except Exception:
            disconnect()
            return

        if not conv_id or not content:
            return

        db  = get_db()
        doc = db.collection(CONVS_COL).document(conv_id).get()
        if not doc.exists:
            return

        conv = doc.to_dict()
        if conv.get("studentId") != user_id and conv.get("landlordId") != user_id:
            return

        now = datetime.now(timezone.utc)
        msg_ref = db.collection(MSGS_COL).document()
        msg_data = {
            "conversationId": conv_id,
            "senderId":       user_id,
            "senderRole":     "student" if user_role in ("student", "tenant") else "landlord",
            "content":        content,
            "createdAt":      now,
        }
        msg_ref.set(msg_data)
        msg_data["id"] = msg_ref.id

        # Update conversation summary
        last_text = content.get("text", "[image]") if content.get("type") == "text" else "[image]"
        conv_updates = {
            "lastMessage":  last_text[:200],
            "lastActivity": now,
        }
        # Increment unread for the OTHER party
        if user_id == conv.get("studentId"):
            conv_updates["landlordUnreadCount"] = (conv.get("landlordUnreadCount", 0) or 0) + 1
        else:
            conv_updates["studentUnreadCount"] = (conv.get("studentUnreadCount", 0) or 0) + 1

        db.collection(CONVS_COL).document(conv_id).update(conv_updates)

        # Serialize datetime for JSON
        msg_data["createdAt"] = now.isoformat()

        emit("new_message", msg_data, room=conv_id)
        emit("conversation_updated", {
            "conversationId": conv_id,
            "lastMessage":    last_text[:200],
            "lastActivity":   now.isoformat(),
        }, room=conv_id)

        logger.debug("Message saved id=%s conv=%s sender=%s", msg_ref.id, conv_id, user_id)

    @socketio.on("read_messages")
    def on_read_messages(data):
        """Reset unread count for the sender's role."""
        conv_id = data.get("conversationId", "")
        token   = request.args.get("token", "")
        try:
            payload = _auth.verify_access_token(token)
            user_id   = payload["sub"]
            user_role = payload.get("role", "")
        except Exception:
            return

        if not conv_id:
            return

        db  = get_db()
        doc = db.collection(CONVS_COL).document(conv_id).get()
        if not doc.exists:
            return

        conv = doc.to_dict()
        if user_id == conv.get("studentId"):
            db.collection(CONVS_COL).document(conv_id).update({"studentUnreadCount": 0})
        elif user_id == conv.get("landlordId"):
            db.collection(CONVS_COL).document(conv_id).update({"landlordUnreadCount": 0})

    @socketio.on("typing_start")
    def on_typing_start(data):
        conv_id = data.get("conversationId", "")
        token   = request.args.get("token", "")
        try:
            payload = _auth.verify_access_token(token)
            user_id = payload["sub"]
        except Exception:
            return
        if conv_id:
            emit("typing", {"userId": user_id, "conversationId": conv_id},
                 room=conv_id, include_self=False)

    @socketio.on("typing_stop")
    def on_typing_stop(data):
        conv_id = data.get("conversationId", "")
        token   = request.args.get("token", "")
        try:
            payload = _auth.verify_access_token(token)
            user_id = payload["sub"]
        except Exception:
            return
        if conv_id:
            emit("stop_typing", {"userId": user_id, "conversationId": conv_id},
                 room=conv_id, include_self=False)
