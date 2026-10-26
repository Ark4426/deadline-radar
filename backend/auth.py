"""Register, login, logout, and current-user endpoints."""

from __future__ import annotations

import re
import secrets
import sqlite3

from flask import Blueprint, jsonify, request, session
from werkzeug.security import check_password_hash, generate_password_hash

from backend.database import ensure_settings, get_db, utc_now
from backend.security import (
    clear_failed_logins,
    current_user,
    is_rate_limited,
    login_required,
    record_failed_login,
)

auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MIN_PASSWORD = 8
MAX_PASSWORD = 128


def public_user(row) -> dict:
    return {
        "id": row["id"],
        "email": row["email"],
        "display_name": row["display_name"],
        "timezone": row["timezone"],
        "created_at": row["created_at"],
    }


def _start_session(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    session.clear()
    session.permanent = True
    session["user_id"] = user_id
    session["csrf_token"] = token
    return token


def _validate_registration(payload: dict) -> str | None:
    email = (payload.get("email") or "").strip()
    password = payload.get("password") or ""
    display_name = (payload.get("display_name") or "").strip()

    if not email or not EMAIL_RE.match(email):
        return "Enter a valid email address."
    if len(email) > 254:
        return "Email address is too long."
    if len(display_name) < 2:
        return "Display name must be at least 2 characters."
    if len(display_name) > 60:
        return "Display name must be 60 characters or fewer."
    if len(password) < MIN_PASSWORD:
        return f"Password must be at least {MIN_PASSWORD} characters."
    if len(password) > MAX_PASSWORD:
        return "Password is too long."
    return None


@auth_bp.post("/register")
def register():
    payload = request.get_json(silent=True) or {}
    error = _validate_registration(payload)
    if error:
        return jsonify({"error": error}), 400

    email = payload["email"].strip().lower()
    now = utc_now()
    db = get_db()

    if db.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
        return jsonify({"error": "An account with that email already exists."}), 409

    try:
        cursor = db.execute(
            """
            INSERT INTO users
                (email, display_name, password_hash, timezone, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                email,
                payload["display_name"].strip(),
                generate_password_hash(payload["password"]),
                (payload.get("timezone") or "UTC").strip()[:64],
                now,
                now,
            ),
        )
        db.commit()
    except sqlite3.IntegrityError:
        db.rollback()
        return jsonify({"error": "That account could not be created."}), 409

    user_id = cursor.lastrowid
    ensure_settings(db, user_id)
    db.commit()
    token = _start_session(user_id)

    user = db.execute(
        "SELECT id, email, display_name, timezone, created_at FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()
    return jsonify({"user": public_user(user), "csrf_token": token}), 201


@auth_bp.post("/login")
def login():
    payload = request.get_json(silent=True) or {}
    email = (payload.get("email") or "").strip().lower()
    password = payload.get("password") or ""

    if not email or not password:
        return jsonify({"error": "Email and password are required."}), 400
    if is_rate_limited(email):
        return jsonify({"error": "Too many attempts. Try again in a few minutes."}), 429

    db = get_db()
    user = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    if user is None or not check_password_hash(user["password_hash"], password):
        record_failed_login(email)
        return jsonify({"error": "Email or password is incorrect."}), 401

    clear_failed_logins(email)
    token = _start_session(user["id"])
    ensure_settings(db, user["id"])
    db.commit()
    return jsonify({"user": public_user(user), "csrf_token": token})


@auth_bp.post("/logout")
@login_required
def logout():
    session.clear()
    return jsonify({"ok": True})


@auth_bp.get("/me")
def me():
    user = current_user()
    if user is None:
        return jsonify({"error": "Not signed in."}), 401
    return jsonify({"user": public_user(user), "csrf_token": session.get("csrf_token")})
