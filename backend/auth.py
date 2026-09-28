"""TraceMind auth — simple email/password accounts in the same SQLite DB.

Pure stdlib: PBKDF2-SHA256 password hashes, stateless HMAC-signed session
tokens (no server-side session store, so nothing extra to persist).

Endpoints live in server.py:
  POST /api/auth/signup  {name, email, password} -> {token, user}
  POST /api/auth/login   {email, password}       -> {token, user}
  GET  /api/auth/me     (Authorization: Bearer <token>) -> {user}
  POST /api/auth/logout -> {ok: true}  (client discards the token)

NOTE: Render free disks are ephemeral — accounts persist until the next
deploy/redeploy, same as the incident DB. Hindsight remains the durable
memory layer.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import secrets
import time

AUTH_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  name       TEXT NOT NULL,
  email      TEXT NOT NULL UNIQUE,
  pw_hash    TEXT NOT NULL,
  created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
"""

_ITERATIONS = 200_000
_TOKEN_TTL = 60 * 60 * 24 * 30  # 30 days
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

_SECRET = os.environ.get("AUTH_SECRET") or secrets.token_hex(32)


def ensure_schema(conn) -> None:
    conn.executescript(AUTH_SCHEMA)


def _hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _ITERATIONS)
    return f"pbkdf2${_ITERATIONS}${salt.hex()}${dk.hex()}"


def _check_password(password: str, stored: str) -> bool:
    try:
        algo, iters, salt_hex, dk_hex = stored.split("$")
        assert algo == "pbkdf2"
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(),
                                 bytes.fromhex(salt_hex), int(iters))
        return hmac.compare_digest(dk.hex(), dk_hex)
    except Exception:
        return False


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _b64dec(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def issue_token(user_id: int) -> str:
    exp = int(time.time()) + _TOKEN_TTL
    payload = f"{user_id}.{exp}".encode()
    sig = hmac.new(_SECRET.encode(), payload, hashlib.sha256).digest()
    return f"{_b64(payload)}.{_b64(sig)}"


def verify_token(token: str):
    """Return user_id or None."""
    try:
        payload_b64, sig_b64 = token.split(".")
        payload = _b64dec(payload_b64)
        sig = _b64dec(sig_b64)
        expect = hmac.new(_SECRET.encode(), payload, hashlib.sha256).digest()
        if not hmac.compare_digest(sig, expect):
            return None
        uid, exp = payload.decode().split(".")
        if int(exp) < time.time():
            return None
        return int(uid)
    except Exception:
        return None


def _public(row) -> dict:
    return {"id": row[0], "name": row[1], "email": row[2],
            "created_at": row[3]}


def _validate_email(email: str) -> str:
    email = (email or "").strip().lower()
    if not _EMAIL_RE.match(email):
        raise ValueError("enter a valid email address")
    return email


def _validate_password(password: str) -> str:
    password = password or ""
    if len(password) < 6:
        raise ValueError("password must be at least 6 characters")
    return password


def signup(conn, name: str, email: str, password: str) -> dict:
    name = (name or "").strip()[:60]
    email = _validate_email(email)
    _validate_password(password)
    if not name:
        raise ValueError("enter your name")
    ensure_schema(conn)
    cur = conn.execute("SELECT id FROM users WHERE email=?", (email,))
    if cur.fetchone():
        raise ValueError("an account with this email already exists — log in instead")
    cur = conn.execute(
        "INSERT INTO users (name, email, pw_hash) VALUES (?,?,?)",
        (name, email, _hash_password(password)))
    row = conn.execute(
        "SELECT id, name, email, created_at FROM users WHERE id=?",
        (cur.lastrowid,)).fetchone()
    user = _public(row)
    return {"token": issue_token(user["id"]), "user": user}


def login(conn, email: str, password: str) -> dict:
    email = _validate_email(email)
    ensure_schema(conn)
    row = conn.execute(
        "SELECT id, name, email, created_at, pw_hash FROM users WHERE email=?",
        (email,)).fetchone()
    if not row or not _check_password(password or "", row[4]):
        raise ValueError("wrong email or password")
    user = _public(row)
    return {"token": issue_token(user["id"]), "user": user}


def get_user(conn, user_id: int):
    ensure_schema(conn)
    row = conn.execute(
        "SELECT id, name, email, created_at FROM users WHERE id=?",
        (user_id,)).fetchone()
    return _public(row) if row else None


def google_login(conn, id_token: str, client_id: str) -> dict:
    """Verify a Google ID token via Google's tokeninfo and find-or-create the user.

    Uses Google's server-side verification (TLS) instead of local RSA checks —
    stdlib-only, no extra dependencies.
    """
    import json as _json
    import urllib.parse as _up
    import urllib.request as _ur

    if not client_id:
        raise ValueError("Google login is not configured on the server yet")
    if not id_token:
        raise ValueError("missing Google credential")
    url = ("https://oauth2.googleapis.com/tokeninfo?"
           + _up.urlencode({"id_token": id_token}))
    try:
        with _ur.urlopen(url, timeout=15) as r:
            info = _json.load(r)
    except Exception:
        raise ValueError("couldn't verify Google sign-in — try again")
    if info.get("aud") != client_id:
        raise ValueError("Google sign-in rejected (audience mismatch)")
    if info.get("email_verified") not in ("true", True):
        raise ValueError("your Google email is not verified")
    email = (info.get("email") or "").strip().lower()
    name = (info.get("name") or email.split("@")[0]).strip()[:60]
    if not email:
        raise ValueError("Google didn't return an email address")
    ensure_schema(conn)
    row = conn.execute(
        "SELECT id, name, email, created_at FROM users WHERE email=?",
        (email,)).fetchone()
    if row:
        user = _public(row)
        if not row[1] and name:
            conn.execute("UPDATE users SET name=? WHERE id=?",
                         (name, user["id"]))
            user["name"] = name
    else:
        # password-less account: pw_hash sentinel never matches _check_password
        cur = conn.execute(
            "INSERT INTO users (name, email, pw_hash) VALUES (?,?,?)",
            (name, email, "google-oauth"))
        row = conn.execute(
            "SELECT id, name, email, created_at FROM users WHERE id=?",
            (cur.lastrowid,)).fetchone()
        user = _public(row)
    return {"token": issue_token(user["id"]), "user": user}
