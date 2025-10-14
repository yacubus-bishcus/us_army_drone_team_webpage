"""Utility helpers for secure Velocidrone passcode usage."""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer


class VelocidroneConfigError(RuntimeError):
    """Raised when required Velocidrone integration settings are missing."""


class VelocidroneSessionError(RuntimeError):
    """Raised when a Velocidrone session token cannot be created or validated."""


@dataclass
class _Session:
    session_id: str
    user_id: Any
    callsign: str
    created_at: float
    used: bool = False

    def mark_used(self) -> None:
        self.used = True


_DEFAULT_TTL = 120  # seconds


def _get_serializer(app) -> URLSafeTimedSerializer:
    secret_key = app.config.get("SECRET_KEY")
    if not secret_key:
        raise VelocidroneConfigError("SECRET_KEY is required for Velocidrone token signing.")
    return URLSafeTimedSerializer(secret_key, salt="velocidrone-session")


def _get_store(app) -> Dict[str, _Session]:
    return app.extensions.setdefault("velocidrone_sessions", {})


def _cleanup_store(app, ttl: int) -> None:
    store = _get_store(app)
    now = time.monotonic()
    expired = [sid for sid, session in store.items() if now - session.created_at > ttl or session.used]
    for sid in expired:
        store.pop(sid, None)


def get_passcode(app) -> str:
    """Return the configured Velocidrone passcode or raise if missing."""
    passcode = app.config.get("VELOCIDRONE_PASSCODE")
    if not passcode:
        raise VelocidroneConfigError("VELOCIDRONE_PASSCODE is not configured.")
    return passcode


def get_login_url(app) -> str:
    login_url = (app.config.get("VELOCIDRONE_LOGIN_URL") or "").strip()
    if not login_url:
        raise VelocidroneConfigError("VELOCIDRONE_LOGIN_URL is not configured.")
    return login_url


def create_session(app, user_id: Any, callsign: str) -> str:
    callsign = (callsign or "").strip()
    if not callsign:
        raise VelocidroneSessionError("Callsign is required to request Velocidrone access.")

    ttl = int(app.config.get("VELOCIDRONE_SESSION_TTL", _DEFAULT_TTL))
    _cleanup_store(app, ttl)

    session_id = uuid.uuid4().hex
    store = _get_store(app)
    store[session_id] = _Session(
        session_id=session_id,
        user_id=user_id,
        callsign=callsign,
        created_at=time.monotonic(),
    )
    serializer = _get_serializer(app)
    token = serializer.dumps({"sid": session_id, "uid": str(user_id)})
    return token


def consume_session(app, token: str) -> _Session:
    ttl = int(app.config.get("VELOCIDRONE_SESSION_TTL", _DEFAULT_TTL))
    serializer = _get_serializer(app)
    try:
        payload = serializer.loads(token, max_age=ttl)
    except SignatureExpired as exc:
        raise VelocidroneSessionError("Velocidrone login link has expired.") from exc
    except BadSignature as exc:
        raise VelocidroneSessionError("Invalid Velocidrone login token.") from exc

    store = _get_store(app)
    session = store.get(payload.get("sid"))
    if not session:
        raise VelocidroneSessionError("Velocidrone login token is no longer valid.")
    if session.used:
        raise VelocidroneSessionError("Velocidrone login token was already used.")
    if str(session.user_id) != str(payload.get("uid")):
        raise VelocidroneSessionError("Velocidrone login token does not belong to this user.")

    session.mark_used()
    return session


def get_session_store_size(app) -> int:
    """Expose store size for diagnostics/testing."""
    return len(_get_store(app))