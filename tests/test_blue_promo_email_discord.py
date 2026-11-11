import unittest
import asyncio
import sqlite3
import time
import os
from unittest.mock import patch, AsyncMock

import core.promo as promo_mod
import core.email_notify as email_mod
import discord_bot as bot_mod
from core.db import init_db, get_db, register_user


class TestPromoHardening(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        init_db()
        self.conn = get_db()
        self.cur = self.conn.cursor()

    def tearDown(self):
        try:
            self.conn.close()
        except Exception:
            pass

    async def test_nonexistent_user_returns_error_without_attribute_error(self):
        """Fix NoneType AttributeError bug on db_user lookup."""
        non_existent_id = 999999999
        res = await promo_mod.verify_user_promo("nonexistent_discord_id", non_existent_id)
        self.assertFalse(res["success"])
        self.assertEqual(res.get("error"), "User record not found")

    async def test_atomic_promo_claim_race_condition(self):
        """
        Verify atomic promo claiming prevents race conditions and double credit awards.
        Simulate concurrent claim attempts on the same user.
        """
        now = int(time.time())
        uname = f"promo_race_{os.urandom(3).hex()}"
        test_ip = f"198.51.{os.urandom(1)[0]}.{os.urandom(1)[0]}"
        self.cur.execute(
            """INSERT INTO users (username, email, discord_id, credits, has_promo, created_at)
               VALUES (?, ?, ?, 10.0, 0, ?)""",
            (uname, f"{uname}@gmail.com", f"disc_{uname}", now)
        )
        self.conn.commit()
        user_id = self.cur.lastrowid

        # Mock fetch_discord_member_profile to simulate verified member with invite link in status
        with patch("core.promo.fetch_discord_member_profile", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = (True, promo_mod.PROMO_KEYWORD, "My bio", "MyNick")

            # Run 5 concurrent verify requests
            tasks = [
                promo_mod.verify_user_promo(f"disc_{uname}", user_id, client_ip=test_ip)
                for _ in range(5)
            ]
            results = await asyncio.gather(*tasks)

            # Check how many granted credits
            success_grants = [r for r in results if r.get("success") and r.get("credits_granted") == promo_mod.FREE_CREDITS]
            self.assertEqual(len(success_grants), 1, "Exactly one concurrent request must win the initial credit grant.")

            # Verify balance in database
            self.cur.execute("SELECT credits, has_promo FROM users WHERE id = ?", (user_id,))
            row = self.cur.fetchone()
            expected_credits = 10.0 + promo_mod.FREE_CREDITS
            self.assertEqual(row["credits"], expected_credits, "User credits must reflect exactly one promo addition.")
            self.assertEqual(row["has_promo"], 1)

    async def test_ip_anti_abuse_blocks_duplicate_ip(self):
        """Verify IP anti-abuse checks prevent multiple promo claims from the same IP."""
        now = int(time.time())
        abuse_ip = f"203.0.{os.urandom(1)[0]}.{os.urandom(1)[0]}"

        # User 1 who already claimed promo from abuse_ip
        u1 = f"ip_user1_{os.urandom(3).hex()}"
        self.cur.execute(
            """INSERT INTO users (username, email, discord_id, credits, has_promo, created_ip, last_ip, created_at)
               VALUES (?, ?, ?, 510.0, 1, ?, ?, ?)""",
            (u1, f"{u1}@gmail.com", f"disc_{u1}", abuse_ip, abuse_ip, now)
        )
        self.conn.commit()

        # User 2 attempting to claim promo from same abuse_ip
        u2 = f"ip_user2_{os.urandom(3).hex()}"
        self.cur.execute(
            """INSERT INTO users (username, email, discord_id, credits, has_promo, created_ip, created_at)
               VALUES (?, ?, ?, 10.0, 0, ?, ?)""",
            (u2, f"{u2}@gmail.com", f"disc_{u2}", abuse_ip, now)
        )
        self.conn.commit()
        u2_id = self.cur.lastrowid

        res = await promo_mod.verify_user_promo(f"disc_{u2}", u2_id, client_ip=abuse_ip)
        self.assertFalse(res["success"], "Promo should be blocked for duplicate IP claim.")
        self.assertIn("already been claimed", res.get("message", "").lower())

    async def test_promo_penalty_timeout_on_removal(self):
        """Verify removing promo link after previously claiming triggers 5-hour penalty."""
        now = int(time.time())
        uname = f"promo_penalty_{os.urandom(3).hex()}"
        self.cur.execute(
            """INSERT INTO users (username, email, discord_id, credits, has_promo, created_at)
               VALUES (?, ?, ?, 510.0, 1, ?)""",
            (uname, f"{uname}@gmail.com", f"disc_{uname}", now)
        )
        self.conn.commit()
        user_id = self.cur.lastrowid

        with patch("core.promo.fetch_discord_member_profile", new_callable=AsyncMock) as mock_fetch:
            # Member in guild, but link removed from status/bio
            mock_fetch.return_value = (True, "Playing games", "Clean bio without link", "CleanNick")
            res = await promo_mod.verify_user_promo(f"disc_{uname}", user_id)

            self.assertFalse(res["success"])
            self.assertTrue(res.get("timed_out"))
            self.assertIn("violation detected", res.get("message", "").lower())

            # Verify timeout set in DB
            self.cur.execute("SELECT timeout_until FROM users WHERE id = ?", (user_id,))
            timeout_until = self.cur.fetchone()["timeout_until"]
            self.assertGreater(timeout_until, now)

    async def test_promo_duplicate_discord_id_blocked(self):
        """Verify cannot claim promo if same discord_id already claimed on another account."""
        now = int(time.time())
        shared_discord_id = f"disc_dup_{os.urandom(3).hex()}"

        # Account 1 has claimed promo with this discord ID
        u1 = f"user1_{os.urandom(3).hex()}"
        self.cur.execute(
            """INSERT INTO users (username, email, discord_id, credits, has_promo, created_at)
               VALUES (?, ?, ?, 510.0, 1, ?)""",
            (u1, f"{u1}@gmail.com", shared_discord_id, now)
        )
        self.conn.commit()

        # Account 2 with no discord ID linked yet attempts to verify using shared_discord_id
        u2 = f"user2_{os.urandom(3).hex()}"
        self.cur.execute(
            """INSERT INTO users (username, email, discord_id, credits, has_promo, created_at)
               VALUES (?, ?, NULL, 10.0, 0, ?)""",
            (u2, f"{u2}@gmail.com", now)
        )
        self.conn.commit()
        u2_id = self.cur.lastrowid

        res = await promo_mod.verify_user_promo(shared_discord_id, u2_id)
        self.assertFalse(res["success"])
        self.assertIn("discord account already used", res.get("error", "").lower())


class TestEmailNotifyHardening(unittest.IsolatedAsyncioTestCase):
    def test_crlf_header_sanitization(self):
        """Verify subject and recipient inputs are stripped of CRLF injection chars."""
        malicious_subject = "Welcome to Service!\r\nBcc: evil_stealer@attacker.org\r\n"
        clean = email_mod.sanitize_email_header(malicious_subject)
        self.assertNotIn("\r", clean)
        self.assertNotIn("\n", clean)
        self.assertIn("evil_stealer@attacker.org", clean)

    def test_email_address_validation(self):
        """Verify regex and parsing validation of recipient email addresses."""
        self.assertTrue(email_mod.is_valid_email("alice@gmail.com"))
        self.assertTrue(email_mod.is_valid_email("bob.builder+test@subdomain.example.com"))

        # Injections and invalid formats
        self.assertFalse(email_mod.is_valid_email("victim@gmail.com\r\nBcc:hacker@evil.com"))
        self.assertFalse(email_mod.is_valid_email("<script>alert(1)</script>@domain.com"))
        self.assertFalse(email_mod.is_valid_email("plainaddress"))
        self.assertFalse(email_mod.is_valid_email("@missinguser.com"))
        self.assertFalse(email_mod.is_valid_email("missingdomain@"))
        self.assertFalse(email_mod.is_valid_email("a" * 255 + "@gmail.com"))

    @patch("core.email_notify._send", new_callable=AsyncMock)
    async def test_dynamic_html_escaping(self, mock_send):
        """Verify dynamic user data embedded in HTML email bodies is HTML-escaped."""
        xss_payload = "<img src=x onerror=alert('xss')><b>Admin</b>"
        await email_mod.welcome_email("victim@gmail.com", xss_payload, "key-123", 75)
        self.assertTrue(mock_send.called)
        html_body = mock_send.call_args[0][2]
        self.assertNotIn("<img src=x", html_body)
        self.assertIn("&lt;img src=x", html_body)

        # Deposit confirmed
        mock_send.reset_mock()
        await email_mod.deposit_confirmed("victim@gmail.com", xss_payload, 10.0, 10000.0, 10000.0, "tx_<script>")
        html_body = mock_send.call_args[0][2]
        self.assertNotIn("<img src=x", html_body)
        self.assertNotIn("<script>", html_body)
        self.assertIn("&lt;script&gt;", html_body)

        # Low credits warning
        mock_send.reset_mock()
        await email_mod.low_credits_warning("victim@gmail.com", xss_payload, 25.0)
        html_body = mock_send.call_args[0][2]
        self.assertNotIn("<img src=x", html_body)

        # Plan activated
        mock_send.reset_mock()
        await email_mod.plan_activated("victim@gmail.com", xss_payload, "<iframe src=evil>", 50000.0, 30, 50.0)
        html_body = mock_send.call_args[0][2]
        self.assertNotIn("<iframe", html_body)
        self.assertIn("&lt;iframe", html_body)

    @patch("core.email_notify.RESEND_API_KEY", "re_mock_key_12345")
    async def test_send_success_flow(self):
        """Verify _send completes successfully when Resend returns 200."""
        with patch("aiohttp.ClientSession.post") as mock_post:
            mock_resp = AsyncMock()
            mock_resp.status = 200
            mock_post.return_value.__aenter__.return_value = mock_resp

            result = await email_mod._send("good_user@gmail.com", "Test Subject", "<p>Hello</p>")
            self.assertTrue(result)
            self.assertTrue(mock_post.called)

    @patch("core.email_notify.RESEND_API_KEY", "re_mock_key_12345")
    async def test_send_rejects_crlf_recipient(self):
        """Verify _send rejects CRLF recipient without calling Resend API."""
        with patch("aiohttp.ClientSession.post") as mock_post:
            result = await email_mod._send("bad\r\nrecipient@evil.com", "Test Subject", "<p>Hello</p>")
            self.assertFalse(result)
            self.assertFalse(mock_post.called)


class TestDiscordBotHardening(unittest.TestCase):
    def test_sanitize_discord_text_neutralizes_mentions(self):
        """Verify @everyone, @here, and user/role mentions are neutralized."""
        evil_text = "Free nitro! @everyone @here <@&12345678> click now!"
        clean = bot_mod.sanitize_discord_text(evil_text)
        self.assertNotIn("@everyone", clean)
        self.assertNotIn("@here", clean)
        self.assertIn("@\u200beveryone", clean)
        self.assertIn("@\u200bhere", clean)
        self.assertNotIn("<@&12345678>", clean)
        self.assertIn("[mention]", clean)

    def test_sanitize_discord_text_neutralizes_codeblock_breakout(self):
        """Verify triple backticks are sanitized to prevent markdown code block breakout."""
        evil_markdown = "Snippet: ```\nError text\n``` Injection outside block"
        clean = bot_mod.sanitize_discord_text(evil_markdown)
        self.assertNotIn("```", clean)
        self.assertIn("'''", clean)

    def test_validate_target_url(self):
        """Verify target URL validation restricts schemes and enforces max length."""
        valid, _ = bot_mod.validate_target_url("https://example.com/login")
        self.assertTrue(valid)

        # Illegal schemes
        invalid_schemes = [
            "javascript:alert(1)",
            "file:///etc/passwd",
            "ftp://files.example.com",
            "gopher://ancient.service",
        ]
        for bad_url in invalid_schemes:
            valid, err = bot_mod.validate_target_url(bad_url)
            self.assertFalse(valid, f"Should reject scheme: {bad_url}")

        # Overly long URL
        long_url = "https://example.com/" + "a" * 2100
        valid, err = bot_mod.validate_target_url(long_url)
        self.assertFalse(valid)
        self.assertIn("exceeds maximum length", err)

    def test_validate_voucher_code(self):
        """Verify voucher code input validation."""
        valid, _ = bot_mod.validate_voucher_code("LAUNCH10")
        self.assertTrue(valid)

        valid, _ = bot_mod.validate_voucher_code("PROMO_2026-X")
        self.assertTrue(valid)

        # Injection characters
        bad_codes = ["LAUNCH' OR '1'='1", "PROMO;DROP TABLE users;", "CODE WITH SPACES", "A" * 65]
        for bad_code in bad_codes:
            valid, _ = bot_mod.validate_voucher_code(bad_code)
            self.assertFalse(valid, f"Should reject voucher code: {bad_code}")

    def test_validate_tx_hash(self):
        """Verify Solana transaction signature format and length validation."""
        valid_sol_sig = "5VerBQQu5yC4orQeDYbvGgy6Ys8WNmJ2Zp9qWvBwT7c1K4F2J3x8L9p0M1N2O3P4Q5R6S7T8U9V0W1X2Y3Z4"
        # Base58 valid characters, 64-88 chars
        valid, _ = bot_mod.validate_tx_hash("2xN8oB4X3X4jQpE3oQ6uUf7K9s9R6kM2P5vJ8yT4wL1eH7rA9bC3dF5gH6jK8mN9pQ")
        self.assertTrue(valid)

        # Invalid characters (0, O, I, l are not in base58)
        invalid_sigs = [
            "short_hash",
            "A" * 130,  # too long
            "2xN8oB4X3X4jQpE3oQ6uUf7K9s9R6kM2P5vJ8yT4wL1eH7rA9bC3dF5gH6jK8mN9p0",  # contains '0' (not base58)
            "2xN8oB4X3X4jQpE3oQ6uUf7K9s9R6kM2P5vJ8yT4wL1eH7rA9bC3dF5gH6jK8mN9pI",  # contains 'I' (not base58)
        ]
        for bad_sig in invalid_sigs:
            valid, _ = bot_mod.validate_tx_hash(bad_sig)
            self.assertFalse(valid, f"Should reject invalid tx hash: {bad_sig}")

    def test_format_discord_cost_field_moderato_plan(self):
        """Verify Moderato plan reflects effective rate $0.0012 and does not show stale $0.1."""
        user = {"plan": "moderato", "credits": 500.0}
        cost_str = bot_mod.format_discord_cost_field(user)
        self.assertIn("0.0012", cost_str)
        self.assertIn("Moderato", cost_str)
        self.assertNotIn("$0.1", cost_str)

    def test_format_discord_cost_field_all_tiers(self):
        """Verify all tier plans format cleanly without $0.1."""
        expected_rates = {
            "free": "Free Tier",
            "starter": "0.0025",
            "moderato": "0.0012",
            "vince": "0.0008",
            "enterprise": "0.0005",
            "pay_as_you_go": "0.0020",
        }
        for plan_id, exp_substr in expected_rates.items():
            # Test with 'plan' key
            user_plan = {"plan": plan_id, "credits": 100.0}
            formatted_plan = bot_mod.format_discord_cost_field(user_plan)
            self.assertIn(exp_substr, formatted_plan, f"Failed for plan key {plan_id}")
            self.assertNotIn("$0.1", formatted_plan)

            # Test with 'tier' key
            user_tier = {"tier": plan_id, "credits": 100.0}
            formatted_tier = bot_mod.format_discord_cost_field(user_tier)
            self.assertIn(exp_substr, formatted_tier, f"Failed for tier key {plan_id}")
            self.assertNotIn("$0.1", formatted_tier)

    def test_format_discord_cost_field_case_normalization(self):
        """Verify uppercase and mixed-case plan casing formats correctly without Free tier demotion."""
        user_upper = {"plan": "MODERATO"}
        cost_upper = bot_mod.format_discord_cost_field(user_upper)
        self.assertEqual(cost_upper, "1 Solve (≈ $0.0012 on Moderato)")

        user_title = {"plan": "Starter"}
        cost_title = bot_mod.format_discord_cost_field(user_title)
        self.assertEqual(cost_title, "1 Solve (≈ $0.0025 on Starter)")

        user_tier_upper = {"tier": "VINCE"}
        cost_tier_upper = bot_mod.format_discord_cost_field(user_tier_upper)
        self.assertEqual(cost_tier_upper, "1 Solve (≈ $0.0008 on Vince)")

    def test_discord_bot_source_has_zero_ten_cent_strings(self):
        """Enforce zero occurrences of '$0.1' in discord_bot.py."""
        import os
        bot_file = os.path.join(os.path.dirname(__file__), "..", "discord_bot.py")
        with open(bot_file, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertNotIn("$0.1", content, "Found stale '$0.1' string in discord_bot.py")


if __name__ == "__main__":
    unittest.main()
