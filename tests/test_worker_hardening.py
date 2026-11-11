"""
Unit & Security Hardening Tests for worker.py and satellite-worker-template.yml
Verifies:
  1. Worker authentication & secret enforcement (rejection of insecure defaults in prod/CI).
  2. SSRF, scheme, and loopback filtering (including hex/decimal IP obfuscation).
  3. Hub redirection security guard (blocking untrusted cross-origin redirects).
  4. Resource disposal & memory cleanup.
  5. Error response sanitization (preventing information disclosure).
  6. Satellite worker YAML template integrity and secret placeholders.
"""

import os
import sys
import unittest
import tempfile
import yaml
from unittest.mock import patch, MagicMock

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import worker

class TestWorkerAuthenticationHardening(unittest.TestCase):
    """Verify that insecure default secrets and short secrets are prohibited in production/CI."""

    def test_empty_secret_raises_error(self):
        with self.assertRaises(RuntimeError):
            worker.validate_worker_secret("")
        with self.assertRaises(RuntimeError):
            worker.validate_worker_secret("   ")

    def test_insecure_default_secret_raises_in_production(self):
        with patch.dict(os.environ, {"ENVIRONMENT": "production"}):
            with self.assertRaises(RuntimeError) as ctx:
                worker.validate_worker_secret("xpk-worker-default-secret")
            self.assertIn("prohibited in production", str(ctx.exception))

    def test_insecure_default_secret_raises_in_github_actions(self):
        with patch.dict(os.environ, {"GITHUB_ACTIONS": "true"}):
            with self.assertRaises(RuntimeError) as ctx:
                worker.validate_worker_secret("secret")
            self.assertIn("prohibited in production/CI", str(ctx.exception))

    def test_short_secret_raises_in_production(self):
        with patch.dict(os.environ, {"ENVIRONMENT": "production"}):
            with self.assertRaises(RuntimeError) as ctx:
                worker.validate_worker_secret("short-sec-123")
            self.assertIn("at least 16 characters", str(ctx.exception))

    def test_strong_secret_passes(self):
        strong_token = "4f8a19b2c3d4e5f6a7b8c9d0e1f2a3b4"
        self.assertEqual(worker.validate_worker_secret(strong_token), strong_token)

    def test_validate_hub_url(self):
        self.assertEqual(worker.validate_hub_url("http://localhost:8000/"), "http://localhost:8000")
        self.assertEqual(worker.validate_hub_url("https://hub.example.com"), "https://hub.example.com")
        with self.assertRaises(ValueError):
            worker.validate_hub_url("ftp://untrusted.server")
        with self.assertRaises(ValueError):
            worker.validate_hub_url("file:///etc/passwd")


class TestWorkerSSRFGuard(unittest.TestCase):
    """Verify strict SSRF, cloud metadata, and loopback filtering in worker engine."""

    def test_reject_dangerous_schemes(self):
        bad_urls = [
            "file:///etc/passwd",
            "file:///C:/Windows/win.ini",
            "gopher://127.0.0.1:6379/_INFO",
            "ftp://ftp.example.com/test",
            "dict://127.0.0.1:11211/stat"
        ]
        for url in bad_urls:
            is_safe, reason = worker.is_safe_target_url(url)
            self.assertFalse(is_safe, f"Failed to block scheme in {url}")

    def test_reject_loopback_and_internal_hostnames(self):
        internal_hosts = [
            "http://localhost:8000/api/admin/overview",
            "http://localhost.localdomain/status",
            "http://127.0.0.1:8000/",
            "http://127.0.0.2/",
            "http://backend.internal/db",
            "http://api.local/v1"
        ]
        for url in internal_hosts:
            is_safe, reason = worker.is_safe_target_url(url)
            self.assertFalse(is_safe, f"Failed to block loopback/internal: {url}")

    def test_reject_cloud_metadata(self):
        metadata_urls = [
            "http://169.254.169.254/latest/meta-data/",
            "http://169.254.169.254/computeMetadata/v1/",
            "http://metadata.google.internal/computeMetadata/v1/",
            "http://instance-data/latest/meta-data/"
        ]
        for url in metadata_urls:
            is_safe, reason = worker.is_safe_target_url(url)
            self.assertFalse(is_safe, f"Failed to block metadata: {url}")

    def test_reject_obfuscated_loopback_encodings(self):
        obfuscated = [
            "http://2130706433/admin",    # Decimal for 127.0.0.1
            "http://0x7f000001/status"    # Hex for 127.0.0.1
        ]
        for url in obfuscated:
            is_safe, reason = worker.is_safe_target_url(url)
            self.assertFalse(is_safe, f"Failed to block obfuscated loopback: {url}")

    def test_reject_private_rfc1918_networks(self):
        private_urls = [
            "http://10.0.0.1/admin",
            "http://172.16.5.1/status",
            "http://192.168.1.1/router"
        ]
        for url in private_urls:
            is_safe, reason = worker.is_safe_target_url(url)
            self.assertFalse(is_safe, f"Failed to block private subnet: {url}")

    def test_allow_legitimate_public_urls(self):
        safe_urls = [
            "https://example.com/login",
            "https://httpbin.org/get"
        ]
        for url in safe_urls:
            is_safe, reason = worker.is_safe_target_url(url)
            self.assertTrue(is_safe, f"Wrongly blocked safe URL: {url} ({reason})")

    def test_proxy_validation(self):
        self.assertFalse(worker.is_safe_proxy("http://127.0.0.1:8080")[0])
        self.assertFalse(worker.is_safe_proxy("http://169.254.169.254:3128")[0])
        self.assertTrue(worker.is_safe_proxy("")[0])


class TestHubRedirectProtection(unittest.TestCase):
    """Verify worker does not follow untrusted or cross-origin redirects from hub."""

    def test_same_origin_relative_redirect_allowed(self):
        session = MagicMock()
        resp_redirect = MagicMock()
        resp_redirect.is_redirect = True
        resp_redirect.headers = {"Location": "/api/worker/heartbeat_v2"}

        resp_final = MagicMock()
        resp_final.is_redirect = False
        resp_final.status_code = 200

        session.request.side_effect = [resp_redirect, resp_final]

        result = worker.send_hub_request(session, "POST", "/api/worker/heartbeat", "https://hub.xploit.org")
        self.assertEqual(result, resp_final)
        self.assertEqual(session.request.call_count, 2)

    def test_cross_origin_redirect_rejected(self):
        session = MagicMock()
        resp_redirect = MagicMock()
        resp_redirect.is_redirect = True
        resp_redirect.headers = {"Location": "http://169.254.169.254/latest/meta-data/"}
        session.request.return_value = resp_redirect

        with self.assertRaises(Exception) as ctx:
            worker.send_hub_request(session, "POST", "/api/worker/heartbeat", "https://hub.xploit.org")
        self.assertIn("Blocked untrusted cross-origin redirect", str(ctx.exception))


class TestResourceDisposal(unittest.TestCase):
    """Verify temporary profile wiping and process cleanup functions execute reliably."""

    def test_cleanup_temp_directories(self):
        temp_dir = tempfile.gettempdir()
        dummy_profile = os.path.join(temp_dir, "undetected_chromedriver_test_cleanup_123")
        os.makedirs(dummy_profile, exist_ok=True)
        self.assertTrue(os.path.exists(dummy_profile))

        worker.cleanup_worker_resources()
        self.assertFalse(os.path.exists(dummy_profile), "Temporary browser profile was not deleted.")


class TestErrorSanitization(unittest.TestCase):
    """Verify task error sanitization stops credential and filesystem leaks."""

    def test_sanitize_credentials_in_url(self):
        err = "Failed to connect to http://admin_user:secret_password@proxy.example.com:8080"
        sanitized = worker.sanitize_error(err)
        self.assertNotIn("secret_password", sanitized)
        self.assertIn("://***:***@", sanitized)

    def test_sanitize_windows_paths(self):
        err = "Error reading configuration file C:\\Users\\Administrator\\AppData\\Local\\secret.json: file not found"
        sanitized = worker.sanitize_error(err)
        self.assertNotIn("Administrator", sanitized)
        self.assertIn("[REDACTED_PATH]", sanitized)

    def test_sanitize_unix_paths(self):
        err = "FileNotFoundError: /home/runner/work/xploit/keys/id_rsa: No such file or directory"
        sanitized = worker.sanitize_error(err)
        self.assertNotIn("/home/runner", sanitized)
        self.assertIn("[REDACTED_PATH]", sanitized)

    def test_sanitize_tokens_and_auth(self):
        err = "Connection failed with Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.e30.signature"
        sanitized = worker.sanitize_error(err)
        self.assertNotIn("eyJhbGci", sanitized)
        self.assertIn("[REDACTED_AUTH]", sanitized)

    def test_clean_timeout_translation(self):
        err = "requests.exceptions.ConnectTimeout: HTTPSConnectionPool(host='example.com', port=443): Max retries exceeded"
        sanitized = worker.sanitize_error(err)
        self.assertEqual(sanitized, "Execution timed out while processing target page.")


class TestSatelliteWorkerTemplate(unittest.TestCase):
    """Verify satellite worker template adheres to secret hygiene and container hardening."""

    def setUp(self):
        self.template_path = os.path.join(PROJECT_ROOT, "satellite-worker-template.yml")

    def test_template_valid_yaml(self):
        with open(self.template_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        self.assertIsInstance(data, dict)
        self.assertIn("jobs", data)
        self.assertIn("solver", data["jobs"])

    def test_no_hardcoded_plaintext_secrets(self):
        with open(self.template_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertNotIn("WORKER_SECRET: \"xpk-worker-default-secret\"", content)
        self.assertNotIn("WORKER_SECRET: 'xpk-worker-default-secret'", content)
        self.assertIn("HUB_URL: ${{ secrets.HUB_URL }}", content)
        self.assertIn("WORKER_SECRET: ${{ secrets.WORKER_SECRET }}", content)

    def test_preflight_validation_and_masking_present(self):
        with open(self.template_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("::add-mask::$WORKER_SECRET", content)
        self.assertIn("Pre-Flight Security Check", content)
        self.assertIn("Cleanup Lingering Processes", content)


if __name__ == "__main__":
    unittest.main()
