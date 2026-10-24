"""Local user accounts and saved barn preferences."""
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB = os.path.join(ROOT, "crossr_users.db")

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,24}$")
SESSION_DAYS = 30


def db_path():
    return os.environ.get("USERS_DB_PATH", DEFAULT_DB)


def connect():
    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = connect()
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL UNIQUE,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                created_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                created_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS preferences (
                user_id INTEGER PRIMARY KEY,
                payload TEXT NOT NULL,
                updated_at INTEGER NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            """
        )
        conn.commit()
    finally:
        conn.close()


def empty_prefs():
    return {"starred": [], "hypofoals": [], "favorites": [], "analyzed": []}


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    iters = 210000
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iters)
    return f"pbkdf2_sha256${iters}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _algo, iters, salt_hex, digest_hex = stored.split("$")
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            bytes.fromhex(salt_hex),
            int(iters),
        )
        return hmac.compare_digest(digest.hex(), digest_hex)
    except Exception:
        return False


def public_user(row):
    return {
        "id": row["id"],
        "email": row["email"],
        "username": row["username"],
    }


def validate_register(email, username, password):
    email = (email or "").strip().lower()
    username = (username or "").strip()
    password = password or ""
    if not EMAIL_RE.match(email):
        return None, "Enter a valid email address."
    if not USERNAME_RE.match(username):
        return None, "Username must be 3–24 letters, numbers, or underscores."
    if len(password) < 8:
        return None, "Password must be at least 8 characters."
    return {"email": email, "username": username, "password": password}, None


def create_user(email, username, password, preferences=None):
    cleaned, err = validate_register(email, username, password)
    if err:
        return None, err
    now = int(time.time())
    conn = connect()
    try:
        exists = conn.execute(
            "SELECT email, username FROM users WHERE email = ? OR lower(username) = lower(?)",
            (cleaned["email"], cleaned["username"]),
        ).fetchone()
        if exists:
            if exists["email"] == cleaned["email"]:
                return None, "That email already has an account."
            return None, "That username is taken."
        cur = conn.execute(
            "INSERT INTO users (email, username, password_hash, created_at) VALUES (?, ?, ?, ?)",
            (cleaned["email"], cleaned["username"], hash_password(cleaned["password"]), now),
        )
        user_id = cur.lastrowid
        prefs = preferences if isinstance(preferences, dict) else empty_prefs()
        conn.execute(
            "INSERT INTO preferences (user_id, payload, updated_at) VALUES (?, ?, ?)",
            (user_id, json.dumps(_clean_prefs(prefs)), now),
        )
        token = _new_session(conn, user_id, now)
        conn.commit()
        user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return {"user": public_user(user), "token": token, "preferences": _clean_prefs(prefs)}, None
    finally:
        conn.close()


def login(identifier, password, preferences=None):
    ident = (identifier or "").strip()
    if not ident or not password:
        return None, "Enter your email or username and password."
    conn = connect()
    try:
        row = conn.execute(
            "SELECT * FROM users WHERE email = ? OR lower(username) = lower(?)",
            (ident.lower(), ident),
        ).fetchone()
        if not row or not verify_password(password, row["password_hash"]):
            return None, "Email/username or password is incorrect."
        now = int(time.time())
        token = _new_session(conn, row["id"], now)
        prefs = get_preferences(row["id"], conn)
        if isinstance(preferences, dict):
            prefs = _merge_prefs(prefs, preferences)
            conn.execute(
                "INSERT INTO preferences (user_id, payload, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(user_id) DO UPDATE SET payload = excluded.payload, updated_at = excluded.updated_at",
                (row["id"], json.dumps(prefs), now),
            )
        conn.commit()
        return {"user": public_user(row), "token": token, "preferences": prefs}, None
    finally:
        conn.close()


def logout(token):
    if not token:
        return
    conn = connect()
    try:
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
        conn.commit()
    finally:
        conn.close()


def user_from_session(token):
    if not token:
        return None
    now = int(time.time())
    conn = connect()
    try:
        row = conn.execute(
            """
            SELECT u.* FROM sessions s
            JOIN users u ON u.id = s.user_id
            WHERE s.token = ? AND s.expires_at > ?
            """,
            (token, now),
        ).fetchone()
        return public_user(row) if row else None
    finally:
        conn.close()


def get_preferences(user_id, conn=None):
    own = conn is None
    conn = conn or connect()
    try:
        row = conn.execute("SELECT payload FROM preferences WHERE user_id = ?", (user_id,)).fetchone()
        if not row:
            return empty_prefs()
        try:
            return _clean_prefs(json.loads(row["payload"]))
        except Exception:
            return empty_prefs()
    finally:
        if own:
            conn.close()


def save_preferences(user_id, payload):
    prefs = _clean_prefs(payload if isinstance(payload, dict) else empty_prefs())
    conn = connect()
    try:
        conn.execute(
            "INSERT INTO preferences (user_id, payload, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET payload = excluded.payload, updated_at = excluded.updated_at",
            (user_id, json.dumps(prefs), int(time.time())),
        )
        conn.commit()
        return prefs
    finally:
        conn.close()


def _new_session(conn, user_id, now):
    token = secrets.token_urlsafe(32)
    conn.execute(
        "INSERT INTO sessions (token, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
        (token, user_id, now, now + SESSION_DAYS * 86400),
    )
    return token


def _clean_prefs(raw):
    base = empty_prefs()
    if not isinstance(raw, dict):
        return base
    starred = raw.get("starred") or []
    favorites = raw.get("favorites") or []
    hypofoals = raw.get("hypofoals") or []
    analyzed = raw.get("analyzed") or []
    base["starred"] = [str(n) for n in starred if n][:80]
    base["favorites"] = [str(n) for n in favorites if n][:40]
    if isinstance(hypofoals, list):
        base["hypofoals"] = [h for h in hypofoals if isinstance(h, dict)][:40]
    if isinstance(analyzed, list):
        base["analyzed"] = [a for a in analyzed if isinstance(a, dict)][:40]
    return base


def _merge_prefs(remote, local):
    a = _clean_prefs(remote)
    b = _clean_prefs(local)

    def uniq(seq):
        out = []
        seen = set()
        for item in seq:
            if item in seen:
                continue
            seen.add(item)
            out.append(item)
        return out

    a["starred"] = uniq(a["starred"] + b["starred"])[:80]
    a["favorites"] = uniq(b["favorites"] + a["favorites"])[:40]
    foals = []
    seen_f = set()
    for item in (b["hypofoals"] + a["hypofoals"]):
        key = item.get("foal_name") or json.dumps(item, sort_keys=True)
        if key in seen_f:
            continue
        seen_f.add(key)
        foals.append(item)
    a["hypofoals"] = foals[:40]
    sales = []
    seen_s = set()
    for item in (b["analyzed"] + a["analyzed"]):
        key = item.get("id") or json.dumps(item, sort_keys=True)
        if key in seen_s:
            continue
        seen_s.add(key)
        sales.append(item)
    a["analyzed"] = sales[:40]
    return a
