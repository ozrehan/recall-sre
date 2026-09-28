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
import json
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

# Per-user GitHub connection: each TraceMind user connects their OWN repo(s)
# with their OWN OAuth token. Replaces the old global github_oauth_token /
# github_repos / github_access_mode meta keys (migrated on first use).
GITHUB_SCHEMA = """
CREATE TABLE IF NOT EXISTS user_github (
  user_id      INTEGER PRIMARY KEY,
  github_token TEXT DEFAULT '',
  repos        TEXT DEFAULT '[]',
  access_mode  TEXT DEFAULT 'write',
  updated_at   TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS github_oauth_nonce (
  nonce      TEXT PRIMARY KEY,
  user_id    INTEGER NOT NULL,
  created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
"""

_ITERATIONS = 200_000
_TOKEN_TTL = 60 * 60 * 24 * 30  # 30 days
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

_SECRET = os.environ.get("AUTH_SECRET") or secrets.token_hex(32)


def ensure_schema(conn) -> None:
    conn.executescript(AUTH_SCHEMA)
    # migration: link GitHub identities for "Login with GitHub"
    try:
        conn.execute("ALTER TABLE users ADD COLUMN github_id TEXT")
    except Exception:
        pass
    try:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_users_github ON users(github_id)")
    except Exception:
        pass
    # per-user GitHub connections (token + repos + access mode)
    try:
        conn.executescript(GITHUB_SCHEMA)
    except Exception:
        pass
    # profile fields: username, bio, avatar, social links
    for _col in ("username TEXT", "bio TEXT DEFAULT ''",
                 "avatar_url TEXT DEFAULT ''",
                 "socials TEXT DEFAULT '{}'"):
        try:
            conn.execute(f"ALTER TABLE users ADD COLUMN {_col}")
        except Exception:
            pass
    try:
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username "
                     "ON users(username)")
    except Exception:
        pass


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
    user["provider"] = "google"
    autofill_profile(conn, user["id"], avatar_url=info.get("picture"))
    return {"token": issue_token(user["id"]), "user": user}


def github_login(conn, access_token: str) -> dict:
    """Log in / sign up with a GitHub OAuth access token.

    Verifies the token against api.github.com, then finds-or-creates the
    user by GitHub account id (linking to an existing same-email account).
    Stdlib-only, no extra dependencies.
    """
    import json as _json
    import urllib.request as _ur

    if not access_token:
        raise ValueError("missing GitHub credential")

    def gh_get(path):
        req = _ur.Request(
            "https://api.github.com" + path,
            headers={"Authorization": "Bearer " + access_token,
                     "Accept": "application/vnd.github+json",
                     "User-Agent": "TraceMind"})
        with _ur.urlopen(req, timeout=15) as r:
            return _json.load(r)

    try:
        me = gh_get("/user")
    except Exception:
        raise ValueError("couldn't verify GitHub sign-in — try again")
    gid = str(me.get("id") or "")
    if not gid:
        raise ValueError("GitHub didn't return an account id")
    email = (me.get("email") or "").strip().lower()
    if not email:
        try:
            emails = gh_get("/user/emails") or []
            prim = [e for e in emails if e.get("primary") and e.get("verified")]
            email = ((prim or emails)[0].get("email", "") if emails else "").strip().lower()
        except Exception:
            email = ""
    name = (me.get("name") or me.get("login") or email.split("@")[0]).strip()[:60]
    ensure_schema(conn)
    row = conn.execute(
        "SELECT id, name, email, created_at FROM users WHERE github_id=?",
        (gid,)).fetchone()
    if not row and email:
        row = conn.execute(
            "SELECT id, name, email, created_at FROM users WHERE email=?",
            (email,)).fetchone()
        if row:
            conn.execute("UPDATE users SET github_id=? WHERE id=?", (gid, row[0]))
    if row:
        user = _public(row)
        if not row[1] and name:
            conn.execute("UPDATE users SET name=? WHERE id=?", (name, user["id"]))
            user["name"] = name
    else:
        if not email:
            raise ValueError("GitHub didn't share a verified email for this account")
        cur = conn.execute(
            "INSERT INTO users (name, email, pw_hash, github_id) VALUES (?,?,?,?)",
            (name, email, "github-oauth", gid))
        row = conn.execute(
            "SELECT id, name, email, created_at FROM users WHERE id=?",
            (cur.lastrowid,)).fetchone()
        user = _public(row)
    user["provider"] = "github"
    autofill_profile(conn, user["id"], username=me.get("login"),
                     avatar_url=me.get("avatar_url"))
    return {"token": issue_token(user["id"]), "user": user}


# ---------- per-user GitHub connection ----------

def _gh_row(conn, user_id: int):
    ensure_schema(conn)
    return conn.execute(
        "SELECT github_token, repos, access_mode FROM user_github WHERE user_id=?",
        (user_id,)).fetchone()


def get_user_github(conn, user_id: int) -> dict:
    """This user's GitHub connection: token, repos, access_mode."""
    row = _gh_row(conn, user_id)
    if not row:
        return {"token": "", "repos": [], "access_mode": "write"}
    try:
        repos = json.loads(row[1] or "[]")
        if not isinstance(repos, list):
            repos = []
    except Exception:
        repos = []
    return {"token": row[0] or "", "repos": repos,
            "access_mode": row[2] or "write"}


def set_user_github_token(conn, user_id: int, token: str) -> dict:
    ensure_schema(conn)
    conn.execute(
        """INSERT INTO user_github (user_id, github_token, updated_at)
           VALUES (?,?,strftime('%Y-%m-%dT%H:%M:%SZ','now'))
           ON CONFLICT(user_id) DO UPDATE SET
             github_token=excluded.github_token,
             updated_at=strftime('%Y-%m-%dT%H:%M:%SZ','now')""",
        (user_id, token or ""))
    return get_user_github(conn, user_id)


def set_user_github_repos(conn, user_id: int, repos: list) -> dict:
    ensure_schema(conn)
    conn.execute(
        """INSERT INTO user_github (user_id, repos, updated_at)
           VALUES (?,?,strftime('%Y-%m-%dT%H:%M:%SZ','now'))
           ON CONFLICT(user_id) DO UPDATE SET
             repos=excluded.repos,
             updated_at=strftime('%Y-%m-%dT%H:%M:%SZ','now')""",
        (user_id, json.dumps(repos or [])))
    return get_user_github(conn, user_id)


def set_user_github_mode(conn, user_id: int, mode: str) -> dict:
    ensure_schema(conn)
    mode = "write" if mode == "write" else "read"
    conn.execute(
        """INSERT INTO user_github (user_id, access_mode, updated_at)
           VALUES (?,?,strftime('%Y-%m-%dT%H:%M:%SZ','now'))
           ON CONFLICT(user_id) DO UPDATE SET
             access_mode=excluded.access_mode,
             updated_at=strftime('%Y-%m-%dT%H:%M:%SZ','now')""",
        (user_id, mode))
    return get_user_github(conn, user_id)


def clear_user_github(conn, user_id: int) -> None:
    ensure_schema(conn)
    conn.execute("DELETE FROM user_github WHERE user_id=?", (user_id,))


def create_github_nonce(conn, user_id: int) -> str:
    """One-time nonce tying the OAuth redirect back to the logged-in user."""
    ensure_schema(conn)
    nonce = secrets.token_urlsafe(24)
    conn.execute("DELETE FROM github_oauth_nonce WHERE user_id=?", (user_id,))
    conn.execute("INSERT INTO github_oauth_nonce (nonce, user_id) VALUES (?,?)",
                 (nonce, user_id))
    return nonce


def consume_github_nonce(conn, nonce: str):
    """Return the user_id for a nonce (single use, 15-min expiry), else None."""
    ensure_schema(conn)
    row = conn.execute(
        "SELECT user_id, created_at FROM github_oauth_nonce WHERE nonce=?",
        (nonce or "",)).fetchone()
    if not row:
        return None
    conn.execute("DELETE FROM github_oauth_nonce WHERE nonce=?", (nonce,))
    try:
        import datetime as _dt
        created = _dt.datetime.strptime(
            row[1], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=_dt.timezone.utc)
        age = (_dt.datetime.now(_dt.timezone.utc) - created).total_seconds()
        if age > 900:
            return None
    except Exception:
        return None
    return row[0]


def users_with_github(conn) -> list:
    """All user_ids that have a GitHub token (for background loops)."""
    ensure_schema(conn)
    try:
        return [r[0] for r in conn.execute(
            "SELECT user_id FROM user_github WHERE github_token<>''")]
    except Exception:
        return []


# ---------- user profile ----------

def get_profile(conn, user_id: int):
    """Public profile for the settings/profile page."""
    ensure_schema(conn)
    row = conn.execute(
        "SELECT id, name, email, created_at, username, bio, avatar_url, socials"
        " FROM users WHERE id=?", (user_id,)).fetchone()
    if not row:
        return None
    try:
        socials = json.loads(row[7] or "{}")
        if not isinstance(socials, dict):
            socials = {}
    except Exception:
        socials = {}
    return {"id": row[0], "name": row[1], "email": row[2],
            "created_at": row[3], "username": row[4] or "",
            "bio": row[5] or "", "avatar_url": row[6] or "",
            "socials": socials}


_USERNAME_RE = None

def _username_re():
    global _USERNAME_RE
    if _USERNAME_RE is None:
        import re as _re
        _USERNAME_RE = _re.compile(r"^[a-zA-Z0-9_.]{3,30}$")
    return _USERNAME_RE


def update_profile(conn, user_id: int, name=None, username=None,
                   bio=None, avatar_url=None, socials=None) -> dict:
    """Update editable profile fields. Raises ValueError on bad input."""
    ensure_schema(conn)
    updates, params = [], []
    if name is not None:
        name = (name or "").strip()[:60]
        if not name:
            raise ValueError("name can't be empty")
        updates.append("name=?")
        params.append(name)
    if username is not None:
        username = (username or "").strip().lstrip("@").lower()
        if username:
            if not _username_re().match(username):
                raise ValueError(
                    "username must be 3-30 letters, numbers, . or _")
            dup = conn.execute(
                "SELECT id FROM users WHERE lower(username)=? AND id<>?",
                (username, user_id)).fetchone()
            if dup:
                raise ValueError("that username is taken")
            updates.append("username=?")
            params.append(username)
        else:
            updates.append("username=NULL")
    if bio is not None:
        updates.append("bio=?")
        params.append((bio or "").strip()[:280])
    if avatar_url is not None:
        avatar_url = (avatar_url or "").strip()
        if len(avatar_url) > 600_000:
            raise ValueError("profile picture is too large")
        updates.append("avatar_url=?")
        params.append(avatar_url)
    if socials is not None:
        # keep only known networks, normalize to full URLs
        clean = _clean_socials(socials if isinstance(socials, dict) else {})
        updates.append("socials=?")
        params.append(json.dumps(clean))
    if updates:
        params.append(user_id)
        conn.execute(f"UPDATE users SET {', '.join(updates)} WHERE id=?",
                     params)
    return get_profile(conn, user_id)


def autofill_profile(conn, user_id: int, username=None,
                     avatar_url=None) -> None:
    """Fill empty username/avatar from an OAuth provider (best effort)."""
    try:
        ensure_schema(conn)
        row = conn.execute(
            "SELECT username, avatar_url FROM users WHERE id=?",
            (user_id,)).fetchone()
        if not row:
            return
        sets, params = [], []
        if not row[0] and username and _username_re().match(username.lower()):
            dup = conn.execute("SELECT id FROM users WHERE lower(username)=?",
                               (username.lower(),)).fetchone()
            if not dup:
                sets.append("username=?")
                params.append(username.lower())
        if not row[1] and avatar_url:
            sets.append("avatar_url=?")
            params.append(avatar_url[:2000])
        if sets:
            params.append(user_id)
            conn.execute(f"UPDATE users SET {', '.join(sets)} WHERE id=?",
                         params)
    except Exception:
        pass


# ---------- social links ----------

SOCIAL_NETWORKS = ("linkedin", "leetcode", "twitter", "instagram",
                   "github", "tiktok", "website")

_SOCIAL_BASE = {
    "linkedin": "https://www.linkedin.com/in/",
    "leetcode": "https://leetcode.com/u/",
    "twitter": "https://x.com/",
    "instagram": "https://www.instagram.com/",
    "github": "https://github.com/",
    "tiktok": "https://www.tiktok.com/@",
}


def _clean_socials(socials: dict) -> dict:
    """Keep known networks; turn bare handles into full profile URLs."""
    clean = {}
    for net in SOCIAL_NETWORKS:
        val = (socials.get(net) or "").strip()
        if not val:
            continue
        if net == "website":
            if not val.startswith(("http://", "https://")):
                val = "https://" + val
            clean[net] = val[:300]
            continue
        if "://" in val:
            # full URL pasted: keep as-is if it's the right site
            clean[net] = val[:300]
            continue
        handle = val.lstrip("@").strip("/")
        if handle:
            clean[net] = _SOCIAL_BASE[net] + handle
    return clean
