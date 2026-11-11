"""
Adversarial Red Team Stress Test Suite: Authentication, Privilege Escalation & Admin Security
Target Codebase: xploit-unblocker-api
Author: Red Team Challenger 3

Tests:
1. Admin Key via URL Query Parameter Prohibited (?key= / ?admin_key= rejected with 401/403)
2. Session HMAC Forgery with Insecure Default Secret (rejection of forged cookies, fallback secret check)
3. Timing-Safe Auth Verification (hmac.compare_digest in verify_password, verify_admin_key)
4. Guest Privilege Escalation Verification (API key isolation, regeneration block, solve exhaustion, anti-cheat, admin upgrade)
"""

import os
import sys
import time
import hmac
import hashlib
import unittest
import tempfile
import shutil
from unittest.mock import patch, Mock

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from starlette.testclient import TestClient
import server
from server import (
    app,
    verify_session_uid,
    sign_session_uid,
    authenticate_api_key,
    verify_admin_key
)
from core import db
from core.db import (
    get_db,
    init_db,
    admin_set_user_plan,
    deduct_credit,
    get_or_reuse_guest_user,
    create_guest_user,
    register_user,
    verify_password,
    hash_password,
    get_user_by_id,
    get_user_by_api_key
)


class BaseAuthPrivilegeTestCase(unittest.TestCase):
    """Base fixture providing isolated SQLite database and fresh TestClient."""

    @classmethod
    def setUpClass(cls):
        cls.test_dir = tempfile.mkdtemp(prefix="xpk_red_auth_")
        cls.orig_db_path = db.DB_PATH
        cls.test_db_path = os.path.join(cls.test_dir, "test_auth.db")
        db.DB_PATH = cls.test_db_path
        db.init_db()

        cls.admin_secret = "xpk-test-admin-secret-2026-secure"
        cls.orig_admin_secret = server.ADMIN_SECRET
        server.ADMIN_SECRET = cls.admin_secret
        os.environ["ADMIN_SECRET"] = cls.admin_secret

        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        db.DB_PATH = cls.orig_db_path
        server.ADMIN_SECRET = cls.orig_admin_secret
        if cls.orig_admin_secret:
            os.environ["ADMIN_SECRET"] = cls.orig_admin_secret
        else:
            os.environ.pop("ADMIN_SECRET", None)
        shutil.rmtree(cls.test_dir, ignore_errors=True)


class TestRedAdminQueryParamProhibited(BaseAuthPrivilegeTestCase):
    """
    Adversarial Challenge 1:
    Admin keys transmitted via URL query parameters (?key=... or ?admin_key=...) must be
    strictly rejected with HTTP 403 or 401. Only the X-Admin-Key header is permitted.
    """

    def test_overview_query_param_key_rejected(self):
        """Attacker passes valid admin key in ?key= query string without header."""
        res = self.client.get(f"/api/admin/overview?key={self.admin_secret}")
        self.assertIn(
            res.status_code,
            (401, 403),
            f"VULNERABILITY DETECTED: Admin overview permitted ?key= query parameter auth (Status {res.status_code}). Must strictly require X-Admin-Key header."
        )

    def test_overview_query_param_admin_key_rejected(self):
        """Attacker passes valid admin key in ?admin_key= query string without header."""
        res = self.client.get(f"/api/admin/overview?admin_key={self.admin_secret}")
        self.assertIn(
            res.status_code,
            (401, 403),
            f"VULNERABILITY DETECTED: Admin overview permitted ?admin_key= query parameter auth (Status {res.status_code}). Must strictly require X-Admin-Key header."
        )

    def test_adjust_credits_query_param_rejected(self):
        """Attacker attempts credit modification passing admin key in query parameter."""
        res = self.client.post(
            f"/api/admin/users/credits?key={self.admin_secret}",
            json={"user_id": 1, "amount": 100.0}
        )
        self.assertIn(
            res.status_code,
            (401, 403),
            f"VULNERABILITY DETECTED: /api/admin/users/credits accepted query parameter key and executed endpoint logic (Status {res.status_code})."
        )

    def test_set_plan_query_param_rejected(self):
        """Attacker attempts plan modification passing admin key in query parameter."""
        res = self.client.post(
            f"/api/admin/users/set-plan?key={self.admin_secret}",
            json={"user_id": 1, "plan": "vince", "duration_days": 30}
        )
        self.assertIn(
            res.status_code,
            (401, 403),
            f"VULNERABILITY DETECTED: /api/admin/users/set-plan accepted query parameter key and executed endpoint logic (Status {res.status_code})."
        )

    def test_vouchers_create_query_param_rejected(self):
        """Attacker attempts voucher creation passing admin key in query parameter."""
        res = self.client.post(
            f"/api/admin/vouchers/create?key={self.admin_secret}",
            json={"code": "XPK-TEST-VOUCHER", "credits": 50.0}
        )
        self.assertIn(
            res.status_code,
            (401, 403),
            f"VULNERABILITY DETECTED: /api/admin/vouchers/create accepted query parameter key (Status {res.status_code})."
        )

    def test_proxies_status_query_param_rejected(self):
        """Attacker passes admin key in query parameter to inspect proxy infrastructure."""
        res = self.client.get(f"/api/proxies/status?key={self.admin_secret}")
        self.assertIn(
            res.status_code,
            (401, 403),
            f"VULNERABILITY DETECTED: /api/proxies/status accepted query parameter key (Status {res.status_code})."
        )

    def test_admin_valid_header_accepted(self):
        """Legitimate admin request with X-Admin-Key header succeeds with HTTP 200."""
        res = self.client.get(
            "/api/admin/overview",
            headers={"X-Admin-Key": self.admin_secret}
        )
        self.assertEqual(res.status_code, 200, f"Valid X-Admin-Key header rejected: {res.text}")
        data = res.json()
        self.assertTrue(data.get("success"), "Expected success=True from admin overview.")

    def test_admin_invalid_header_rejected(self):
        """Attacker sends incorrect X-Admin-Key header."""
        res = self.client.get(
            "/api/admin/overview",
            headers={"X-Admin-Key": "wrong-adversarial-guess-000"}
        )
        self.assertIn(res.status_code, (401, 403), "Expected 401/403 for invalid X-Admin-Key.")


class TestRedSessionHMACForgery(BaseAuthPrivilegeTestCase):
    """
    Adversarial Challenge 2:
    Session HMAC forgery using known default/fallback secrets must strictly fail.
    Tampered cookie payloads must be detected and rejected.
    """

    KNOWN_DEFAULT_FALLBACKS = [
        "xpk-secure-session-key-sign-2026-prod",
        "xpk-worker-default-secret",
        "default-secret",
        "secret",
        "changeme"
    ]

    def test_forged_cookie_with_insecure_default_secret_rejected(self):
        """
        Attacker crafts signed cookie 1.<sig> using known static repository fallbacks.
        Hardened verification must reject all forged cookies.
        """
        for fallback_secret in self.KNOWN_DEFAULT_FALLBACKS:
            sig = hmac.new(fallback_secret.encode(), b"1", hashlib.sha256).hexdigest()[:24]
            forged_cookie = f"1.{sig}"

            verified_uid = verify_session_uid(forged_cookie)
            self.assertIsNone(
                verified_uid,
                f"CRITICAL VULNERABILITY: Forged session cookie '{forged_cookie}' using default fallback secret '{fallback_secret}' was accepted!"
            )

    def test_active_session_secret_not_default_string(self):
        """Verify that server.SESSION_SECRET is NOT set to the insecure fallback default string."""
        insecure_default = "xpk-secure-session-key-sign-2026-prod"
        self.assertNotEqual(
            server.SESSION_SECRET,
            insecure_default,
            f"VULNERABILITY: server.SESSION_SECRET is using static repo fallback string '{insecure_default}'!"
        )

    def test_tampered_cookie_uid_rejected(self):
        """
        Attacker takes a legitimate signed cookie for user ID 2 and changes UID prefix to 1 (Admin/Victim)
        retaining the existing HMAC.
        """
        valid_cookie_user2 = sign_session_uid(2)
        _, sig_user2 = valid_cookie_user2.split(".", 1)

        tampered_cookie = f"1.{sig_user2}"
        verified = verify_session_uid(tampered_cookie)
        self.assertIsNone(verified, f"Tampered cookie '{tampered_cookie}' bypassed HMAC verification!")

    def test_malformed_session_cookie_fuzzing(self):
        """Fuzz session cookie validator with edge-case and boundary payloads."""
        malformed_payloads = [
            "",
            "1",
            "1.",
            ".sig",
            "1.sig.extra",
            "admin.45f94c493de51c9c5498b952",
            "-1.45f94c493de51c9c5498b952",
            "1.ZZZZZZZZZZZZZZZZZZZZZZZZ",
            "1." + ("a" * 1000),
            None
        ]
        for payload in malformed_payloads:
            verified = verify_session_uid(payload)
            self.assertIsNone(verified, f"Malformed cookie payload '{payload}' unexpectedly verified as UID {verified}")


class TestRedTimingSafeAuth(BaseAuthPrivilegeTestCase):
    """
    Adversarial Challenge 3:
    Authentication checks for passwords and admin keys must execute in constant time
    using hmac.compare_digest to prevent byte-by-byte timing discrepancy extraction.
    """

    def test_password_verification_uses_compare_digest(self):
        """Verify core.db.verify_password invokes hmac.compare_digest."""
        pwd = "TargetPassword!123"
        hashed = hash_password(pwd)

        with patch("hmac.compare_digest", wraps=hmac.compare_digest) as mock_digest:
            result = verify_password(hashed, pwd)
            self.assertTrue(result, "Valid password verification failed.")
            self.assertGreater(
                mock_digest.call_count,
                0,
                "TIMING VULNERABILITY: core.db.verify_password does NOT use hmac.compare_digest! Standard string equality (==) exposes password verification to timing side-channels."
            )

    def test_admin_key_verification_uses_compare_digest(self):
        """Verify server.verify_admin_key invokes hmac.compare_digest."""
        with patch("hmac.compare_digest", wraps=hmac.compare_digest) as mock_digest:
            try:
                verify_admin_key(x_admin_key=self.admin_secret)
            except Exception as e:
                self.fail(f"verify_admin_key raised unexpected exception: {e}")

            self.assertGreater(
                mock_digest.call_count,
                0,
                "TIMING VULNERABILITY: server.verify_admin_key does NOT use hmac.compare_digest! Standard string comparison exposes admin key to timing attacks."
            )

    def test_password_verification_mismatch_uses_compare_digest(self):
        """Verify failed password verification also uses constant-time comparison."""
        hashed = hash_password("CorrectPassword!123")
        with patch("hmac.compare_digest", wraps=hmac.compare_digest) as mock_digest:
            result = verify_password(hashed, "WrongPassword!456")
            self.assertFalse(result, "Wrong password unexpectedly verified.")
            self.assertGreater(
                mock_digest.call_count,
                0,
                "TIMING VULNERABILITY: Failed password check did not invoke hmac.compare_digest."
            )


class TestRedGuestPrivilegeEscalation(BaseAuthPrivilegeTestCase):
    """
    Adversarial Challenge 4:
    Guest users must be strictly contained:
    - No access to permanent API keys (/api/user/my-key must return api_key=None)
    - Cannot regenerate API keys (/api/user/regenerate-key must return 403)
    - Internal guest API keys cannot be used for external automation (/v1/unlock must return 403)
    - Solve limit (5 solves) cannot be exceeded (returns 402 when exhausted)
    - IP anti-cheat recycling prevents clearing cookies for infinite credits
    - Full privileges granted ONLY after legitimate admin plan assignment
    """

    def setUp(self):
        self.guest_user = create_guest_user(ip="198.51.100.10", initial_credits=5.0)
        self.guest_cookie = sign_session_uid(self.guest_user["id"])

    def test_guest_cannot_access_api_key(self):
        """Guest user visiting /api/user/my-key must receive api_key=None."""
        res = self.client.get(
            "/api/user/my-key",
            cookies={"xpk_uid": self.guest_cookie}
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data.get("is_guest"), "Expected is_guest=True for guest session.")
        self.assertIsNone(data.get("api_key"), f"PRIVILEGE LEAK: Guest user accessed API key: {data.get('api_key')}")

    def test_guest_cannot_regenerate_api_key(self):
        """Guest user invoking /api/user/regenerate-key must be rejected with HTTP 403."""
        res = self.client.post(
            "/api/user/regenerate-key",
            cookies={"xpk_uid": self.guest_cookie}
        )
        self.assertEqual(
            res.status_code,
            403,
            f"PRIVILEGE ESCALATION: Guest user was allowed to regenerate API key (Status {res.status_code})."
        )

    def test_guest_internal_api_key_rejected_for_automation(self):
        """
        Attacker extracts guest user's internal api_key from local DB/storage and attempts
        to pass it as X-API-Key for external script automation on /v1/unlock.
        """
        raw_key = self.guest_user["api_key"]
        self.assertTrue(raw_key, "Guest user must have an internal DB key.")

        res = self.client.post(
            "/v1/unlock",
            headers={"X-API-Key": raw_key},
            json={"url": "https://httpbin.org/status/200"}
        )
        self.assertEqual(
            res.status_code,
            403,
            f"PRIVILEGE ESCALATION: Guest API key permitted automation on /v1/unlock (Status {res.status_code}): {res.text}"
        )

    def test_guest_solve_limit_and_exhaustion(self):
        """
        Guest user with 5 credits is allowed up to 5 solves.
        Once credits reach 0, further solves must be blocked with HTTP 402.
        """
        uid = self.guest_user["id"]

        # Deduct 5 credits (1 credit at a time)
        for i in range(5):
            success = deduct_credit(uid, 1.0)
            self.assertTrue(success, f"Deduction {i+1} failed unexpectedly.")

        # 6th deduction must fail
        overdraft_success = deduct_credit(uid, 1.0)
        self.assertFalse(overdraft_success, "Guest balance allowed overdraft beyond 5 solves!")

        # Verify user record in DB reflects 0 credits
        updated_guest = get_user_by_id(uid)
        self.assertEqual(updated_guest["credits"], 0.0)

        # Calling authenticated unblock endpoint with exhausted guest session cookie must return HTTP 402
        res = self.client.post(
            "/v1/unlock",
            cookies={"xpk_uid": self.guest_cookie},
            json={"url": "https://httpbin.org/status/200"}
        )
        self.assertEqual(res.status_code, 402, f"Expected HTTP 402 for exhausted guest, got {res.status_code}: {res.text}")
        self.assertIn("Guest trial credits exhausted", res.text)

    def test_guest_anti_cheat_ip_recycling(self):
        """
        Anti-Cheat IP Recycling:
        1. Subsequent guest creation from same IP within 24h returns identical user ID.
        2. IPs creating 2+ guests receive 0.0 trial credits on subsequent sessions.
        """
        test_ip = "198.51.100.99"

        # Session 1
        g1 = get_or_reuse_guest_user(ip=test_ip)
        self.assertEqual(g1["credits"], 5.0)

        # Session 2 (cleared cookies, same IP)
        g2 = get_or_reuse_guest_user(ip=test_ip)
        self.assertEqual(g1["id"], g2["id"], "Anti-Cheat bypassed: Cleared cookie did not recycle same guest ID!")

        # Simulate 2 distinct historical guest accounts from another test IP
        abuse_ip = "198.51.100.188"
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO users (username, api_key, credits, is_guest, created_ip, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            ("guest_old_1", "key1", 0.0, 1, abuse_ip, int(time.time()) - 100000)
        )
        cur.execute(
            "INSERT INTO users (username, api_key, credits, is_guest, created_ip, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            ("guest_old_2", "key2", 0.0, 1, abuse_ip, int(time.time()) - 100000)
        )
        conn.commit()
        conn.close()

        # 3rd lifetime guest from abuse_ip must receive 0.0 trial credits
        g_abuser = get_or_reuse_guest_user(ip=abuse_ip)
        self.assertEqual(
            g_abuser["credits"],
            0.0,
            f"Anti-Cheat failed: Abusive IP received {g_abuser['credits']} trial credits instead of 0.0!"
        )

    def test_guest_promoted_by_admin_gains_full_access(self):
        """
        When an admin assigns a plan to a guest user via admin_set_user_plan:
        - is_guest is set to 0
        - User receives plan quota credits
        - User can now view and use their API key without 403 guest restriction
        """
        uid = self.guest_user["id"]
        res = admin_set_user_plan(user_id=uid, plan="vince", duration_days=30)
        self.assertTrue(res.get("success"), f"admin_set_user_plan failed: {res.get('error')}")

        # Check DB state
        upgraded = get_user_by_id(uid)
        self.assertEqual(upgraded["is_guest"], 0, "is_guest must be 0 after admin plan assignment.")
        self.assertEqual(upgraded["plan"], "vince")
        self.assertGreater(upgraded["credits"], 10000)

        # Check /api/user/my-key now returns the permanent API key
        res_key = self.client.get(
            "/api/user/my-key",
            cookies={"xpk_uid": self.guest_cookie}
        )
        self.assertEqual(res_key.status_code, 200)
        key_data = res_key.json()
        self.assertFalse(key_data.get("is_guest"), "is_guest must be False after plan upgrade.")
        self.assertEqual(key_data.get("api_key"), upgraded["api_key"])

        # Check that user's API key can now authenticate without guest automation block
        auth_req = Mock()
        auth_req.cookies = {}
        auth_req.headers = {"x-api-key": upgraded["api_key"]}
        user_auth = authenticate_api_key(request=auth_req, x_api_key=upgraded["api_key"])
        self.assertEqual(user_auth["id"], uid)


if __name__ == "__main__":
    unittest.main()
