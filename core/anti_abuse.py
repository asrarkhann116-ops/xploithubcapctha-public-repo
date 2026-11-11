import os
import time
import ipaddress
from collections import defaultdict
from typing import Tuple, Dict, Any, Optional
from fastapi import Request
from core.db import get_db

# ─── IN-MEMORY SLIDING RATE LIMITERS ──────────────────────────────────────────
# Key: ip -> list of timestamps
_FAILED_LOGINS = defaultdict(list)
_VOUCHER_ATTEMPTS = defaultdict(list)
_REGISTER_ATTEMPTS = defaultdict(list)

MAX_ACCOUNTS_PER_IP = 2
MAX_GUEST_PER_IP_HOURS = 24
VOUCHER_ATTEMPT_LIMIT = 5  # Max 5 attempts in 5 minutes per IP

TRUSTED_PROXIES = {"127.0.0.1", "::1", "localhost", "testclient"}
_env_trusted = os.getenv("TRUSTED_PROXIES", "")
if _env_trusted:
    for _p in _env_trusted.split(","):
        if _p.strip():
            TRUSTED_PROXIES.add(_p.strip())

def _is_trusted_proxy(host: Optional[str]) -> bool:
    if not host:
        return False
    if host in TRUSTED_PROXIES:
        return True
    try:
        ip = ipaddress.ip_address(host)
        return ip.is_loopback
    except ValueError:
        return False

def _sanitize_ip(candidate: Optional[str]) -> Optional[str]:
    if not candidate:
        return None
    raw = candidate.strip()
    try:
        return str(ipaddress.ip_address(raw))
    except ValueError:
        return None

def get_client_ip(request: Request) -> str:
    """
    Extracts the true client IP address.
    Only trusts proxy headers (CF-Connecting-IP, X-Forwarded-For, etc.) if the direct peer
    (request.client.host) matches trusted proxy addresses (e.g. 127.0.0.1, reverse proxies).
    """
    direct_host = request.client.host if request.client else None

    # Only inspect forwarding headers if the immediate connection is from a trusted proxy
    if _is_trusted_proxy(direct_host):
        # 1. Cloudflare
        cf_ip = _sanitize_ip(request.headers.get("cf-connecting-ip"))
        if cf_ip:
            return cf_ip

        # 2. True-Client-IP
        true_ip = _sanitize_ip(request.headers.get("true-client-ip"))
        if true_ip:
            return true_ip

        # 3. X-Forwarded-For (client is the leftmost non-internal IP)
        xff = request.headers.get("x-forwarded-for")
        if xff:
            parts = [p.strip() for p in xff.split(",") if p.strip()]
            for part in parts:
                sanitized = _sanitize_ip(part)
                if sanitized:
                    return sanitized

        # 4. X-Real-IP
        x_real = _sanitize_ip(request.headers.get("x-real-ip"))
        if x_real:
            return x_real

    # Direct client connection (or direct host if untrusted proxy)
    if direct_host:
        sanitized_direct = _sanitize_ip(direct_host)
        return sanitized_direct or direct_host

    return "127.0.0.1"


def check_rate_limit(store: dict, ip: str, limit: int, window_seconds: int) -> bool:
    """Sliding window rate limit checker."""
    now = time.time()
    cutoff = now - window_seconds
    # Purge old timestamps
    timestamps = [t for t in store.get(ip, []) if t > cutoff]
    if len(timestamps) >= limit:
        store[ip] = timestamps
        return False  # Rate limit exceeded
    timestamps.append(now)
    store[ip] = timestamps
    return True


LOGIN_ATTEMPT_LIMIT = 5  # Max 5 failed attempts in 60 seconds per IP

def check_login_rate_limit(ip: str) -> Tuple[bool, str]:
    """Check if IP is currently blocked due to repeated failed login attempts."""
    now = time.time()
    cutoff = now - 60
    failures = [t for t in _FAILED_LOGINS.get(ip, []) if t > cutoff]
    _FAILED_LOGINS[ip] = failures
    if len(failures) >= LOGIN_ATTEMPT_LIMIT:
        return False, "Too many failed login attempts. Please wait 60 seconds before trying again."
    return True, ""

def record_failed_login(ip: str):
    """Record a failed login attempt for brute-force tracking."""
    _FAILED_LOGINS[ip].append(time.time())

def clear_failed_logins(ip: str):
    """Clear failed login history on successful authentication."""
    _FAILED_LOGINS.pop(ip, None)

def check_ip_account_limit(ip: str) -> Tuple[bool, str]:
    """
    Verifies that this IP has not exceeded the maximum of 2 registered accounts.
    Returns: (is_allowed, error_message)
    """
    # Exclude localhost from strict limit during local development
    if ip in ("127.0.0.1", "::1", "localhost"):
        return True, ""

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT COUNT(*) as cnt FROM users WHERE created_ip = ? AND is_guest = 0",
        (ip,)
    )
    count = cur.fetchone()["cnt"] or 0
    conn.close()

    if count >= MAX_ACCOUNTS_PER_IP:
        return False, f"Anti-Abuse Block: Maximum {MAX_ACCOUNTS_PER_IP} accounts allowed per IP address. Limit reached for {ip}."
    return True, ""


def check_voucher_abuse(ip: str, user_id: int, voucher_code: str) -> Tuple[bool, str]:
    """
    Enforces strict anti-cheat on voucher redemptions:
    - Rate limits redemption attempts to stop brute forcing.
    - Prevents any IP from redeeming the same voucher code twice.
    - Prevents any IP from redeeming more than 2 vouchers total.
    """
    # 1. Brute-force rate limit
    if not check_rate_limit(_VOUCHER_ATTEMPTS, ip, limit=VOUCHER_ATTEMPT_LIMIT, window_seconds=300):
        return False, "Too many voucher attempts! Rate limit active. Please wait 5 minutes before trying again."

    # 2. Check if this IP already redeemed THIS specific code
    conn = get_db()
    cur = conn.cursor()
    
    # Ensure voucher_redemptions table exists
    cur.execute('''
    CREATE TABLE IF NOT EXISTS voucher_redemptions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        voucher_code TEXT,
        user_id INTEGER,
        ip TEXT,
        redeemed_at INTEGER
    )
    ''')

    cur.execute(
        "SELECT id FROM voucher_redemptions WHERE voucher_code = ? AND ip = ?",
        (voucher_code.upper(), ip)
    )
    if cur.fetchone():
        conn.close()
        return False, "This promo voucher has already been redeemed from your IP address or network."

    # 3. Check total vouchers redeemed by this IP
    cur.execute(
        "SELECT COUNT(*) as total FROM voucher_redemptions WHERE ip = ?",
        (ip,)
    )
    total_ip_vouchers = cur.fetchone()["total"] or 0
    if total_ip_vouchers >= 3:
        conn.close()
        return False, "Anti-Cheat: Maximum voucher redemption quota reached for your IP address."

    conn.close()
    return True, ""


def record_voucher_redemption(ip: str, user_id: int, voucher_code: str):
    """Records voucher redemption with IP tracking."""
    conn = get_db()
    cur = conn.cursor()
    now = int(time.time())
    cur.execute(
        "INSERT INTO voucher_redemptions (voucher_code, user_id, ip, redeemed_at) VALUES (?, ?, ?, ?)",
        (voucher_code.upper(), user_id, ip, now)
    )
    conn.commit()
    conn.close()


def check_promo_ip_claimed(ip: str) -> bool:
    """Checks if any user from this IP has already claimed the 500 Discord promo credits."""
    if ip in ("127.0.0.1", "::1", "localhost"):
        return False
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT id FROM users WHERE created_ip = ? AND has_promo = 1",
        (ip,)
    )
    claimed = cur.fetchone() is not None
    conn.close()
    return claimed
