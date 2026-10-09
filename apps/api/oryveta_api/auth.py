"""Session and OAuth helpers with no dependency on GitHub API permissions for code."""

from __future__ import annotations

import hashlib
import secrets
import time
from typing import Any

from fastapi import HTTPException, Request

from .database import Database

SESSION_MAX_AGE = 60 * 60 * 24 * 7


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_session(db: Database, user_id: str) -> str:
    token = secrets.token_urlsafe(40)
    now = time.time()
    with db.connect() as conn:
        conn.execute("INSERT INTO sessions(token_hash,user_id,expires_at,created_at) VALUES(?,?,?,?)",
                     (hash_token(token), user_id, now + SESSION_MAX_AGE, now))
    return token


def current_user(request: Request) -> dict[str, Any]:
    token = request.cookies.get("oryveta_session", "")
    if not token:
        raise HTTPException(401, "Sign in required")
    with request.app.state.db.connect() as conn:
        row = conn.execute("""SELECT u.id,u.login,u.display_name,u.avatar_url
                              FROM sessions s JOIN users u ON u.id=s.user_id
                              WHERE s.token_hash=? AND s.expires_at>?""",
                           (hash_token(token), time.time())).fetchone()
    if not row:
        raise HTTPException(401, "Session expired or invalid")
    return dict(row)


def require_csrf(request: Request) -> None:
    # Authenticated mutations require both a same-origin browser request and a per-session CSRF value.
    origin = request.headers.get("origin")
    base_url = request.app.state.settings.base_url
    if origin and origin.rstrip("/") != base_url:
        raise HTTPException(403, "Untrusted origin")
    session = request.cookies.get("oryveta_session", "")
    csrf = request.headers.get("x-oryveta-csrf", "")
    expected = hashlib.sha256(("csrf:" + session).encode()).hexdigest()
    if not session or not secrets.compare_digest(csrf, expected):
        raise HTTPException(403, "Missing or invalid CSRF token")


def csrf_for_session(token: str) -> str:
    return hashlib.sha256(("csrf:" + token).encode()).hexdigest()
