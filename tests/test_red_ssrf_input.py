"""
Adversarial Stress Test Suite: SSRF, IP Spoofing, Turnstile Evasion & Input Fuzzing
Target Codebase: E:\\asrar\\projects\\xploit-unblocker-api
File: tests/test_red_ssrf_input.py
Challenger: Red Team Challenger 4

Empirical Attack Surface & Invariant Verification:
  1. SSRF & Dangerous Scheme Filtering (/v1/unlock & /v1/unlock/async):
     - Local File Disclosure (file:///etc/passwd, file:///C:/Windows/win.ini)
     - Cloud Instance Metadata Service (IMDS: http://169.254.169.254/latest/meta-data/)
     - Internal Loopback Services (http://127.0.0.1:8000/api/admin/overview)
     - Private RFC 1918 Subnets (10.0.0.1, 172.16.0.1, 192.168.1.1)
     - Dangerous Protocol Schemes (gopher://, ftp://, dict://)
     - Decimal & Hex Encoded Loopbacks (http://2130706433/, http://0x7f000001/)
     - Asynchronous Webhook SSRF Injection
  2. Cloudflare Turnstile Bot Evasion Attempts:
     - Missing cf_turnstile_response on /api/auth/register and /api/auth/login
     - Empty or whitespace-only cf_turnstile_response
     - Cryptographically invalid / forged turnstile tokens
  3. Client IP Header Spoofing Resistance:
     - Direct untrusted client host forging CF-Connecting-IP
     - Direct untrusted client host forging True-Client-IP, X-Forwarded-For, X-Real-IP
     - Header injection payload sanitization
     - Legitimate trusted proxy header extraction baseline
  4. CORS Wildcard Origin Rejection:
     - Subdomain wildcard abuse (*.railway.app, *.onrender.com)
     - Credential leakage prevention for unverified origins
     - Legitimate localhost baseline acceptance
"""

import os
import sys
import warnings
import unittest
from unittest.mock import patch, MagicMock

warnings.filterwarnings("ignore", category=DeprecationWarning)

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from starlette.testclient import TestClient

import server
from server import app, authenticate_api_key
import core.anti_abuse as anti_abuse_mod
import core.turnstile as turnstile_mod


MOCK_AUTHENTICATED_USER = {
    "id": 9999,
    "username": "pentest_red_user",
    "email": "redteam@internal.xploit",
    "is_guest": 0,
    "credits": 50000.0,
    "plan": "moderato",
    "concurrency_limit": 50,
    "timeout_until": 0,
    "has_deposited": 1,
    "deposit_ref": "RED_TEAM_AUDIT"
}

DUMMY_ENGINE_RESPONSE = {
    "success": False,
    "status_code": 502,
    "error": "Engine reached illegally - SSRF filter bypassed!",
    "mode": "failed",
    "title": "",
    "credits_remaining": 50000.0,
    "cf_clearance": None,
    "cf_bm": None,
    "user_agent": "mock",
    "captcha_detected": None,
    "html": "",
    "cookies": [],
    "headers": {}
}


class TestSSRFAndDangerousSchemeFiltering(unittest.TestCase):
    """
    Adversarial verification that /v1/unlock and /v1/unlock/async immediately
    reject local files, cloud metadata, private CIDRs, and prohibited protocols
    with HTTP 400 Bad Request before attempting any network resolution or dispatch.
    """

    def setUp(self):
        self.client = TestClient(app, raise_server_exceptions=False)
        app.dependency_overrides[authenticate_api_key] = lambda: MOCK_AUTHENTICATED_USER

    def tearDown(self):
        app.dependency_overrides.clear()

    @patch("server.execute_unblock", return_value=DUMMY_ENGINE_RESPONSE)
    @patch("server.dispatch_to_worker", return_value=DUMMY_ENGINE_RESPONSE)
    def test_unlock_rejects_file_scheme_unix(self, mock_dispatch, mock_execute):
        """Attacker attempts Local File Disclosure (LFD) via file:///etc/passwd."""
        payload = {"url": "file:///etc/passwd", "mode": "auto"}
        resp = self.client.post("/v1/unlock", json=payload)
        
        self.assertEqual(resp.status_code, 400, f"Expected HTTP 400 Bad Request for file:// scheme, got {resp.status_code}: {resp.text}")
        mock_execute.assert_not_called()
        mock_dispatch.assert_not_called()

    @patch("server.execute_unblock", return_value=DUMMY_ENGINE_RESPONSE)
    @patch("server.dispatch_to_worker", return_value=DUMMY_ENGINE_RESPONSE)
    def test_unlock_rejects_file_scheme_windows(self, mock_dispatch, mock_execute):
        """Attacker attempts LFD via Windows win.ini path."""
        payload = {"url": "file:///C:/Windows/win.ini", "mode": "auto"}
        resp = self.client.post("/v1/unlock", json=payload)
        
        self.assertEqual(resp.status_code, 400, f"Expected HTTP 400 Bad Request for Windows file:// path, got {resp.status_code}: {resp.text}")
        mock_execute.assert_not_called()
        mock_dispatch.assert_not_called()

    @patch("server.execute_unblock", return_value=DUMMY_ENGINE_RESPONSE)
    @patch("server.dispatch_to_worker", return_value=DUMMY_ENGINE_RESPONSE)
    def test_unlock_rejects_cloud_metadata_imds(self, mock_dispatch, mock_execute):
        """Attacker attempts AWS/GCP/Azure link-local metadata exfiltration."""
        payload = {"url": "http://169.254.169.254/latest/meta-data/", "mode": "auto"}
        resp = self.client.post("/v1/unlock", json=payload)
        
        self.assertEqual(resp.status_code, 400, f"Expected HTTP 400 Bad Request for IMDS metadata IP, got {resp.status_code}: {resp.text}")
        mock_execute.assert_not_called()
        mock_dispatch.assert_not_called()

    @patch("server.execute_unblock", return_value=DUMMY_ENGINE_RESPONSE)
    @patch("server.dispatch_to_worker", return_value=DUMMY_ENGINE_RESPONSE)
    def test_unlock_rejects_loopback_ip(self, mock_dispatch, mock_execute):
        """Attacker attempts SSRF to internal loopback admin endpoint."""
        payload = {"url": "http://127.0.0.1:8000/api/admin/overview", "mode": "auto"}
        resp = self.client.post("/v1/unlock", json=payload)
        
        self.assertEqual(resp.status_code, 400, f"Expected HTTP 400 Bad Request for 127.0.0.1 loopback, got {resp.status_code}: {resp.text}")
        mock_execute.assert_not_called()
        mock_dispatch.assert_not_called()

    @patch("server.execute_unblock", return_value=DUMMY_ENGINE_RESPONSE)
    @patch("server.dispatch_to_worker", return_value=DUMMY_ENGINE_RESPONSE)
    def test_unlock_rejects_rfc1918_class_a(self, mock_dispatch, mock_execute):
        """Attacker attempts internal network reconnaissance on 10.0.0.1."""
        payload = {"url": "http://10.0.0.1/admin", "mode": "auto"}
        resp = self.client.post("/v1/unlock", json=payload)
        
        self.assertEqual(resp.status_code, 400, f"Expected HTTP 400 Bad Request for 10.0.0.0/8 private CIDR, got {resp.status_code}: {resp.text}")
        mock_execute.assert_not_called()
        mock_dispatch.assert_not_called()

    @patch("server.execute_unblock", return_value=DUMMY_ENGINE_RESPONSE)
    @patch("server.dispatch_to_worker", return_value=DUMMY_ENGINE_RESPONSE)
    def test_unlock_rejects_rfc1918_class_b(self, mock_dispatch, mock_execute):
        """Attacker attempts internal pivoting to 172.16.0.1."""
        payload = {"url": "http://172.16.0.1:8080/metrics", "mode": "auto"}
        resp = self.client.post("/v1/unlock", json=payload)
        
        self.assertEqual(resp.status_code, 400, f"Expected HTTP 400 Bad Request for 172.16.0.0/12 private CIDR, got {resp.status_code}: {resp.text}")
        mock_execute.assert_not_called()
        mock_dispatch.assert_not_called()

    @patch("server.execute_unblock", return_value=DUMMY_ENGINE_RESPONSE)
    @patch("server.dispatch_to_worker", return_value=DUMMY_ENGINE_RESPONSE)
    def test_unlock_rejects_rfc1918_class_c(self, mock_dispatch, mock_execute):
        """Attacker attempts internal pivoting to 192.168.1.1 gateway."""
        payload = {"url": "http://192.168.1.1/router-login", "mode": "auto"}
        resp = self.client.post("/v1/unlock", json=payload)
        
        self.assertEqual(resp.status_code, 400, f"Expected HTTP 400 Bad Request for 192.168.0.0/16 private CIDR, got {resp.status_code}: {resp.text}")
        mock_execute.assert_not_called()
        mock_dispatch.assert_not_called()

    @patch("server.execute_unblock", return_value=DUMMY_ENGINE_RESPONSE)
    @patch("server.dispatch_to_worker", return_value=DUMMY_ENGINE_RESPONSE)
    def test_unlock_rejects_dangerous_protocols(self, mock_dispatch, mock_execute):
        """Attacker tests dangerous protocol schemes (gopher, ftp, dict, data)."""
        schemes = [
            "gopher://127.0.0.1:6379/_flushall",
            "ftp://10.0.0.1/dump.sql",
            "dict://127.0.0.1:11211/stat",
            "data:text/html,<script>alert(1)</script>"
        ]
        for bad_url in schemes:
            with self.subTest(url=bad_url):
                mock_execute.reset_mock()
                mock_dispatch.reset_mock()
                resp = self.client.post("/v1/unlock", json={"url": bad_url, "mode": "auto"})
                self.assertEqual(resp.status_code, 400, f"Protocol '{bad_url}' was not rejected with 400; got {resp.status_code}")
                mock_execute.assert_not_called()
                mock_dispatch.assert_not_called()

    @patch("server.execute_unblock", return_value=DUMMY_ENGINE_RESPONSE)
    @patch("server.dispatch_to_worker", return_value=DUMMY_ENGINE_RESPONSE)
    def test_unlock_rejects_obfuscated_loopback_encodings(self, mock_dispatch, mock_execute):
        """Attacker attempts bypass via decimal IP, hex IP, and IPv6 loopback formats."""
        obfuscated = [
            "http://2130706433/admin",           # Decimal 127.0.0.1
            "http://0x7f000001/admin",          # Hex 127.0.0.1
            "http://[::1]/admin",               # IPv6 loopback
            "http://[::ffff:127.0.0.1]/admin",  # IPv4-mapped IPv6
            "http://localhost:8000/admin"       # localhost alias
        ]
        for bad_url in obfuscated:
            with self.subTest(url=bad_url):
                mock_execute.reset_mock()
                mock_dispatch.reset_mock()
                resp = self.client.post("/v1/unlock", json={"url": bad_url, "mode": "auto"})
                self.assertEqual(resp.status_code, 400, f"Obfuscated loopback '{bad_url}' must be rejected with 400; got {resp.status_code}")
                mock_execute.assert_not_called()
                mock_dispatch.assert_not_called()

    @patch("server.process_async_task")
    def test_unlock_async_rejects_dangerous_target_urls(self, mock_process_async):
        """Attacker attempts SSRF via asynchronous job dispatch."""
        dangerous_targets = [
            "file:///etc/passwd",
            "http://169.254.169.254/latest/meta-data/",
            "http://127.0.0.1:8000/api/admin/overview",
            "http://10.0.0.1/admin"
        ]
        for bad_url in dangerous_targets:
            with self.subTest(target=bad_url):
                mock_process_async.reset_mock()
                resp = self.client.post("/v1/unlock/async", json={"url": bad_url, "mode": "auto"})
                self.assertEqual(resp.status_code, 400, f"Async unlock target '{bad_url}' must be rejected with 400; got {resp.status_code}")
                mock_process_async.assert_not_called()

    @patch("server.process_async_task")
    def test_unlock_async_rejects_dangerous_webhook_urls(self, mock_process_async):
        """Attacker attempts SSRF by providing an internal IP in webhook_url."""
        dangerous_webhooks = [
            "http://169.254.169.254/latest/meta-data/",
            "http://127.0.0.1:8000/api/admin/overview",
            "http://10.0.0.1:9000/callback",
            "file:///etc/shadow"
        ]
        for bad_wh in dangerous_webhooks:
            with self.subTest(webhook=bad_wh):
                mock_process_async.reset_mock()
                resp = self.client.post("/v1/unlock/async", json={
                    "url": "https://example.com",
                    "webhook_url": bad_wh
                })
                self.assertEqual(resp.status_code, 400, f"Async webhook '{bad_wh}' must be rejected with 400; got {resp.status_code}")
                mock_process_async.assert_not_called()


class TestTurnstileEvasionAttempts(unittest.TestCase):
    """
    Adversarial verification that when bot protection is configured,
    unauthenticated requests omitting or falsifying Cloudflare Turnstile
    tokens are strictly rejected.
    """

    def setUp(self):
        self.client = TestClient(app, raise_server_exceptions=False)

    def test_register_missing_turnstile_response_rejected_when_configured(self):
        """Attacker attempts automated registration omitting cf_turnstile_response."""
        with patch("server.TURNSTILE_SECRET_KEY", "0x4AAAAAAFu_TEST_SECRET"):
            with patch.object(turnstile_mod, "TURNSTILE_SECRET_KEY", "0x4AAAAAAFu_TEST_SECRET"):
                payload = {
                    "email": "bot_farmer@evil.org",
                    "username": "botfarmer01",
                    "password": "ValidPassword123!"
                }
                resp = self.client.post("/api/auth/register", json=payload)
                self.assertIn(resp.status_code, (400, 403), f"Missing Turnstile token on register should return 400/403, got {resp.status_code}: {resp.text}")

    def test_register_empty_turnstile_response_rejected_when_configured(self):
        """Attacker provides whitespace or empty string for cf_turnstile_response."""
        with patch("server.TURNSTILE_SECRET_KEY", "0x4AAAAAAFu_TEST_SECRET"):
            with patch.object(turnstile_mod, "TURNSTILE_SECRET_KEY", "0x4AAAAAAFu_TEST_SECRET"):
                payload = {
                    "email": "bot_farmer2@evil.org",
                    "username": "botfarmer02",
                    "password": "ValidPassword123!",
                    "cf_turnstile_response": "   "
                }
                resp = self.client.post("/api/auth/register", json=payload)
                self.assertIn(resp.status_code, (400, 403), f"Empty Turnstile token on register should return 400/403, got {resp.status_code}: {resp.text}")

    def test_login_missing_turnstile_response_rejected_when_configured(self):
        """Attacker attempts credential-stuffing login omitting cf_turnstile_response."""
        with patch("server.TURNSTILE_SECRET_KEY", "0x4AAAAAAFu_TEST_SECRET"):
            with patch.object(turnstile_mod, "TURNSTILE_SECRET_KEY", "0x4AAAAAAFu_TEST_SECRET"):
                payload = {
                    "identity": "admin",
                    "password": "Password123!"
                }
                resp = self.client.post("/api/auth/login", json=payload)
                self.assertIn(resp.status_code, (400, 403), f"Missing Turnstile token on login should return 400/403, got {resp.status_code}: {resp.text}")

    def test_login_forged_turnstile_response_rejected(self):
        """Attacker provides an invalid forged turnstile token."""
        with patch("server.TURNSTILE_SECRET_KEY", "0x4AAAAAAFu_TEST_SECRET"):
            with patch.object(turnstile_mod, "TURNSTILE_SECRET_KEY", "0x4AAAAAAFu_TEST_SECRET"):
                with patch("server.verify_turnstile_token", return_value=(False, "Invalid captcha token")):
                    payload = {
                        "identity": "admin",
                        "password": "Password123!",
                        "cf_turnstile_response": "forged_turnstile_token_xyz"
                    }
                    resp = self.client.post("/api/auth/login", json=payload)
                    self.assertEqual(resp.status_code, 403, f"Forged Turnstile token must return HTTP 403 Forbidden, got {resp.status_code}")


class TestClientIPSpoofingResistance(unittest.TestCase):
    """
    Adversarial verification that untrusted clients cannot spoof
    anti-abuse or rate limits by sending arbitrary proxy headers.
    """

    def _create_mock_request(self, client_host: str, headers: dict) -> MagicMock:
        req = MagicMock()
        req.client.host = client_host
        req.headers = {k.lower(): v for k, v in headers.items()}
        return req

    def test_untrusted_client_cannot_spoof_cf_connecting_ip(self):
        """Direct connection from public host 198.51.100.25 sends spoofed CF-Connecting-IP."""
        mock_req = self._create_mock_request(
            client_host="198.51.100.25",
            headers={"cf-connecting-ip": "1.2.3.4"}
        )
        resolved_ip = anti_abuse_mod.get_client_ip(mock_req)
        self.assertEqual(resolved_ip, "198.51.100.25", f"Blindly trusted spoofed CF-Connecting-IP: got {resolved_ip}")

    def test_untrusted_client_cannot_spoof_loopback_bypass(self):
        """Direct connection from public host attempts to claim 127.0.0.1 to bypass limits."""
        mock_req = self._create_mock_request(
            client_host="203.0.113.19",
            headers={"cf-connecting-ip": "127.0.0.1"}
        )
        resolved_ip = anti_abuse_mod.get_client_ip(mock_req)
        self.assertEqual(resolved_ip, "203.0.113.19", f"Attacker spoofed loopback status: got {resolved_ip}")

    def test_untrusted_client_cannot_spoof_true_client_ip(self):
        """Direct connection sends spoofed True-Client-IP."""
        mock_req = self._create_mock_request(
            client_host="198.51.100.50",
            headers={"true-client-ip": "8.8.8.8"}
        )
        resolved_ip = anti_abuse_mod.get_client_ip(mock_req)
        self.assertEqual(resolved_ip, "198.51.100.50", f"Blindly trusted True-Client-IP from untrusted client: got {resolved_ip}")

    def test_untrusted_client_cannot_spoof_x_forwarded_for(self):
        """Direct connection sends spoofed X-Forwarded-For list."""
        mock_req = self._create_mock_request(
            client_host="198.51.100.99",
            headers={"x-forwarded-for": "1.1.1.1, 10.0.0.1, 192.168.1.1"}
        )
        resolved_ip = anti_abuse_mod.get_client_ip(mock_req)
        self.assertEqual(resolved_ip, "198.51.100.99", f"Blindly trusted X-Forwarded-For: got {resolved_ip}")

    def test_trusted_proxy_correctly_relays_cf_connecting_ip(self):
        """When connection originates from trusted proxy (127.0.0.1), header is honored."""
        mock_req = self._create_mock_request(
            client_host="127.0.0.1",
            headers={"cf-connecting-ip": "198.51.100.77"}
        )
        resolved_ip = anti_abuse_mod.get_client_ip(mock_req)
        self.assertEqual(resolved_ip, "198.51.100.77", f"Trusted proxy failed to extract client IP: got {resolved_ip}")

    def test_header_injection_sanitization(self):
        """Attacker injects XSS/malicious string in IP header through trusted proxy."""
        mock_req = self._create_mock_request(
            client_host="127.0.0.1",
            headers={"cf-connecting-ip": "<script>alert('xss')</script>"}
        )
        resolved_ip = anti_abuse_mod.get_client_ip(mock_req)
        self.assertNotIn("<script>", resolved_ip, "XSS payload preserved in resolved IP")


class TestCORSWildcardRejection(unittest.TestCase):
    """
    Adversarial verification that arbitrary Railway and Render subdomains
    cannot perform cross-origin authenticated requests via wildcard regex.
    """

    def setUp(self):
        self.client = TestClient(app, raise_server_exceptions=False)

    def test_cors_rejects_attacker_railway_origin(self):
        """Attacker hosts malicious app on https://attacker.up.railway.app."""
        headers = {
            "Origin": "https://attacker.up.railway.app",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type"
        }
        resp = self.client.options("/api/user/me", headers=headers)
        allow_origin = resp.headers.get("access-control-allow-origin")
        self.assertNotEqual(
            allow_origin,
            "https://attacker.up.railway.app",
            f"CORS granted wildcard origin to untrusted Railway subdomain: {allow_origin}"
        )

    def test_cors_rejects_attacker_render_origin(self):
        """Attacker hosts malicious app on https://evil.onrender.com."""
        headers = {
            "Origin": "https://evil.onrender.com",
            "Access-Control-Request-Method": "GET"
        }
        resp = self.client.options("/healthz", headers=headers)
        allow_origin = resp.headers.get("access-control-allow-origin")
        self.assertNotEqual(
            allow_origin,
            "https://evil.onrender.com",
            f"CORS granted wildcard origin to untrusted Render subdomain: {allow_origin}"
        )

    def test_cors_rejects_arbitrary_unlisted_origin(self):
        """Attacker attempts preflight from completely external domain."""
        headers = {
            "Origin": "https://arbitrary-attacker.com",
            "Access-Control-Request-Method": "POST"
        }
        resp = self.client.options("/v1/unlock", headers=headers)
        allow_origin = resp.headers.get("access-control-allow-origin")
        self.assertNotEqual(
            allow_origin,
            "https://arbitrary-attacker.com",
            "CORS permitted arbitrary unlisted domain"
        )

    def test_cors_allows_legitimate_local_origins(self):
        """Baseline check: Localhost development origin is accepted."""
        headers = {
            "Origin": "http://localhost:8000",
            "Access-Control-Request-Method": "GET"
        }
        resp = self.client.options("/healthz", headers=headers)
        allow_origin = resp.headers.get("access-control-allow-origin")
        self.assertEqual(allow_origin, "http://localhost:8000")


if __name__ == "__main__":
    unittest.main()
