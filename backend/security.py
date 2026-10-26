"""Session authentication, CSRF checks, and simple login rate limiting."""

from __future__ import annotations

import time
from collections import defaultdict, deque
from functools import wraps
from urllib.parse import urlparse

from flask import current_app, g, jsonify, request, session

from backend.database import get_db

MAX_ATTEMPTS = 6
ATTEMPT_WINDOW_SECONDS = 5 * 60
_failed_attempts: dict[str, deque[float]] = defaultdict(deque)


def _client_key(email: str) -> str:
    forwarded = request.headers.get("X-Forwarded-For", "")
    ip = forwarded.split(",")[0].strip() if forwarded else request.remote_addr or "unknown"
    return f"{ip}:{email.lower()}"


def is_rate_limited(email: str) -> bool:
    attempts = _failed_attempts[_client_key(email)]
    cutoff = time.time() - ATTEMPT_WINDOW_SECONDS
    while attempts and attempts[0] < cutoff:
        attempts.popleft()
    return len(attempts) >= MAX_ATTEMPTS


def record_failed_login(email: str) -> None:
    _failed_attempts[_client_key(email)].append(time.time())


def clear_failed_logins(email: str | None = None) -> None:
    if email is None:
        _failed_attempts.clear()
    else:
        _failed_attempts.pop(_client_key(email), None)


def current_user():
    """Load the signed-in user once per request."""
    if "user" in g:
        return g.user
    user_id = session.get("user_id")
    if not user_id:
        g.user = None
        return None
    g.user = get_db().execute(
        "SELECT id, email, display_name, timezone, created_at FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()
    return g.user


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user()
        if user is None:
            return jsonify({"error": "Authentication required."}), 401
        return view(*args, **kwargs)

    return wrapped


def _same_origin(value: str | None) -> bool:
    if not value:
        return True
    parsed = urlparse(value)
    expected = urlparse(request.host_url)
    return (parsed.scheme, parsed.netloc) == (expected.scheme, expected.netloc)


def init_security(app) -> None:
    @app.before_request
    def protect_api():
        if not request.path.startswith("/api/"):
            return None
        if request.method in {"GET", "HEAD", "OPTIONS"}:
            return None

        if not _same_origin(request.headers.get("Origin")):
            return jsonify({"error": "Cross-origin request rejected."}), 403

        expected = session.get("csrf_token")
        if expected and request.headers.get("X-CSRF-Token") != expected:
            return jsonify({"error": "Missing or invalid CSRF token."}), 403

        return None

    @app.after_request
    def security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        if current_app.config.get("SESSION_COOKIE_SECURE"):
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return response
