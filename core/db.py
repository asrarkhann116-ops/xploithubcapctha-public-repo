import sqlite3
import os
import secrets
import time
from typing import Optional, Dict, Any

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "unblocker.db")

def get_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cur = conn.cursor()
    
    # Users table
    cur.execute('''
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        discord_id TEXT UNIQUE,
        username TEXT,
        avatar TEXT,
        api_key TEXT UNIQUE,
        deposit_ref TEXT UNIQUE,
        credits REAL DEFAULT 10.0,
        has_promo INTEGER DEFAULT 0,
        promo_last_verified INTEGER DEFAULT 0,
        timeout_until INTEGER DEFAULT 0,
        created_at INTEGER
    )
    ''')
    
    # Deposits table
    cur.execute('''
    CREATE TABLE IF NOT EXISTS deposits (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        tx_hash TEXT UNIQUE,
        amount_usdt REAL,
        credits_added REAL,
        status TEXT,
        created_at INTEGER
    )
    ''')

    # Gift / Voucher Codes table
    cur.execute('''
    CREATE TABLE IF NOT EXISTS vouchers (
        code TEXT PRIMARY KEY,
        credits REAL NOT NULL,
        is_used INTEGER DEFAULT 0,
        used_by INTEGER,
        used_at INTEGER,
        created_at INTEGER
    )
    ''')
    
    # Scrape request logs
    cur.execute('''
    CREATE TABLE IF NOT EXISTS request_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        target_url TEXT,
        mode TEXT,
        status_code INTEGER,
        duration_ms INTEGER,
        cost REAL,
        created_at INTEGER
    )
    ''')
    
    # Migration checks for existing databases
    for col_def in [
        "ALTER TABLE users ADD COLUMN deposit_ref TEXT",
        "ALTER TABLE users ADD COLUMN email TEXT",
        "ALTER TABLE users ADD COLUMN password_hash TEXT",
        "ALTER TABLE users ADD COLUMN is_guest INTEGER DEFAULT 0"
    ]:
        try:
            cur.execute(col_def)
        except Exception:
            pass

    # Pre-seed a few demo vouchers if none exist
    cur.execute("SELECT COUNT(*) as cnt FROM vouchers")
    if cur.fetchone()['cnt'] == 0:
        cur.execute(
            "INSERT INTO vouchers (code, credits, is_used, created_at) VALUES (?, ?, 0, ?)",
            ("XPK-WELCOME-1000", 1000.0, int(time.time()))
        )
        cur.execute(
            "INSERT INTO vouchers (code, credits, is_used, created_at) VALUES (?, ?, 0, ?)",
            ("XPK-DISCORD-BOOST", 5000.0, int(time.time()))
        )

    conn.commit()
    conn.close()

import hashlib

def hash_password(password: str) -> str:
    salt = os.urandom(16)
    key = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 100000)
    return salt.hex() + ":" + key.hex()

def verify_password(stored_password: str, provided_password: str) -> bool:
    try:
        salt_hex, key_hex = stored_password.split(":")
        salt = bytes.fromhex(salt_hex)
        key = hashlib.pbkdf2_hmac('sha256', provided_password.encode('utf-8'), salt, 100000)
        return key.hex() == key_hex
    except Exception:
        return False

def register_user(email: str, username: str, password: str) -> Dict[str, Any]:
    """Register a new persistent user account."""
    email = email.strip().lower()
    username = username.strip()
    if not email or "@" not in email:
        return {"success": False, "error": "Please provide a valid email address."}
    if len(password) < 6:
        return {"success": False, "error": "Password must be at least 6 characters long."}
    if not username:
        username = email.split("@")[0]

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM users WHERE LOWER(email) = ? OR LOWER(username) = ?", (email, username.lower()))
    if cur.fetchone():
        conn.close()
        return {"success": False, "error": "An account with this email or username already exists."}

    pwd_hash = hash_password(password)
    api_key = generate_api_key()
    deposit_ref = generate_deposit_ref()
    now = int(time.time())

    cur.execute(
        """INSERT INTO users (email, username, password_hash, api_key, deposit_ref, credits, is_guest, created_at)
           VALUES (?, ?, ?, ?, ?, 10.0, 0, ?)""",
        (email, username, pwd_hash, api_key, deposit_ref, now)
    )
    conn.commit()
    new_id = cur.lastrowid
    cur.execute("SELECT * FROM users WHERE id = ?", (new_id,))
    user = dict(cur.fetchone())
    conn.close()
    return {"success": True, "user": user}

def authenticate_user(identity: str, password: str) -> Dict[str, Any]:
    """Authenticate existing user by email or username."""
    identity = identity.strip().lower()
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE LOWER(email) = ? OR LOWER(username) = ?", (identity, identity))
    row = cur.fetchone()
    conn.close()
    if not row or not row["password_hash"]:
        return {"success": False, "error": "Invalid email/username or password."}
    if not verify_password(row["password_hash"], password):
        return {"success": False, "error": "Invalid email/username or password."}
    return {"success": True, "user": dict(row)}

def create_guest_user() -> Dict[str, Any]:
    """Create a temporary guest tester account with test credits only (no API key access)."""
    conn = get_db()
    cur = conn.cursor()
    guest_id = f"guest_{secrets.token_hex(6)}"
    guest_name = f"Guest-{secrets.token_hex(2).upper()}"
    api_key = generate_api_key()
    deposit_ref = generate_deposit_ref()
    now = int(time.time())
    cur.execute(
        """INSERT INTO users (discord_id, username, api_key, deposit_ref, credits, is_guest, created_at)
           VALUES (?, ?, ?, ?, 5.0, 1, ?)""",
        (guest_id, guest_name, api_key, deposit_ref, now)
    )
    conn.commit()
    new_id = cur.lastrowid
    cur.execute("SELECT * FROM users WHERE id = ?", (new_id,))
    user = dict(cur.fetchone())
    conn.close()
    return user


def generate_api_key() -> str:
    return "xpk_" + secrets.token_hex(20)

def generate_deposit_ref() -> str:
    return "XPK-" + secrets.token_hex(4).upper()

def get_or_create_user(discord_id: str, username: str, avatar: str = "") -> Dict[str, Any]:
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE discord_id = ?", (discord_id,))
    row = cur.fetchone()
    
    now = int(time.time())
    if row:
        deposit_ref = row['deposit_ref']
        if not deposit_ref:
            deposit_ref = generate_deposit_ref()
            cur.execute("UPDATE users SET deposit_ref = ? WHERE id = ?", (deposit_ref, row['id']))
        cur.execute("UPDATE users SET username = ?, avatar = ? WHERE id = ?", (username, avatar, row['id']))
        conn.commit()
        cur.execute("SELECT * FROM users WHERE id = ?", (row['id'],))
        user = dict(cur.fetchone())
        conn.close()
        return user
    
    api_key = generate_api_key()
    deposit_ref = generate_deposit_ref()
    # 10 free trial credits for new users
    cur.execute(
        "INSERT INTO users (discord_id, username, avatar, api_key, deposit_ref, credits, has_promo, created_at) VALUES (?, ?, ?, ?, ?, 10.0, 0, ?)",
        (discord_id, username, avatar, api_key, deposit_ref, now)
    )
    conn.commit()
    new_id = cur.lastrowid
    cur.execute("SELECT * FROM users WHERE id = ?", (new_id,))
    user = dict(cur.fetchone())
    conn.close()
    return user

def regenerate_user_api_key(user_id: int) -> str:
    """Regenerates a fresh random API key for the given user in database."""
    new_key = generate_api_key()
    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE users SET api_key = ? WHERE id = ?", (new_key, user_id))
    conn.commit()
    conn.close()
    return new_key


def redeem_voucher(code: str, user_id: int) -> Dict[str, Any]:
    code = code.strip().upper()
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM vouchers WHERE code = ?", (code,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return {"success": False, "error": "Invalid voucher / gift code!"}
    
    if row["is_used"]:
        conn.close()
        return {"success": False, "error": "This voucher has already been redeemed!"}
    
    credits_to_add = float(row["credits"])
    now = int(time.time())
    cur.execute(
        "UPDATE vouchers SET is_used = 1, used_by = ?, used_at = ? WHERE code = ?",
        (user_id, now, code)
    )
    cur.execute("UPDATE users SET credits = credits + ? WHERE id = ?", (credits_to_add, user_id))
    cur.execute("SELECT credits FROM users WHERE id = ?", (user_id,))
    new_credits = cur.fetchone()['credits']
    conn.commit()
    conn.close()
    
    return {
        "success": True,
        "credits_added": credits_to_add,
        "new_balance": new_credits,
        "message": f"Successfully redeemed voucher {code} (+{credits_to_add:,.0f} credits)!"
    }

def get_user_by_api_key(api_key: str) -> Optional[Dict[str, Any]]:
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE api_key = ?", (api_key,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None

def get_user_by_discord_id(discord_id: str) -> Optional[Dict[str, Any]]:
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE discord_id = ?", (discord_id,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None

def deduct_credit(user_id: int, amount: float = 1.0) -> bool:
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT credits FROM users WHERE id = ?", (user_id,))
    row = cur.fetchone()
    if not row or row['credits'] < amount:
        conn.close()
        return False
    
    cur.execute("UPDATE users SET credits = credits - ? WHERE id = ?", (amount, user_id))
    conn.commit()
    conn.close()
    return True

def add_credit(user_id: int, amount: float) -> float:
    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE users SET credits = credits + ? WHERE id = ?", (amount, user_id))
    conn.commit()
    cur.execute("SELECT credits FROM users WHERE id = ?", (user_id,))
    new_credits = cur.fetchone()['credits']
    conn.close()
    return new_credits

def set_user_timeout(user_id: int, hours: int = 5):
    timeout_until = int(time.time()) + (hours * 3600)
    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE users SET timeout_until = ?, has_promo = 0 WHERE id = ?", (timeout_until, user_id))
    conn.commit()
    conn.close()

def log_request(user_id: int, target_url: str, mode: str, status_code: int, duration_ms: int, cost: float):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO request_logs (user_id, target_url, mode, status_code, duration_ms, cost, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (user_id, target_url, mode, status_code, duration_ms, cost, int(time.time()))
    )
    conn.commit()
    conn.close()

# Initialize on import
init_db()
