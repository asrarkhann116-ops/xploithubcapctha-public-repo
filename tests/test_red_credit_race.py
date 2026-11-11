"""
Adversarial Stress Test Suite: Credit Deduction TOCTOU Races, Async Concurrency Quotas & SQLite WAL Contention
Target Codebase: xploit-unblocker-api
Author: Red Team Challenger 2

Empirical Attack Surface & Invariant Verification:
1. Multi-Threaded Credit Overdrawing (TOCTOU Race Condition on deduct_credit):
   - Exact 1.0 credit under 20-thread simultaneous barrier release -> Exactly 1 success, 19 failures, balance == 0.0.
   - Zero credit balance under 20-thread barrier release -> 0 successes, 20 failures, balance == 0.0.
   - Multi-credit (3.0 credits) under 20-thread barrier release -> Exactly 3 successes, 17 failures, balance == 0.0.
   - Fractional credits (1.5 credits, 0.5 deduction) under 20-thread barrier -> Exactly 3 successes, 17 failures, balance == 0.0.
   - Negative / Zero amounts validation -> 0.0 returns True, negative returns False.
   - Admin user ID (0) -> Synthetic bypass, always returns True without balance mutation.

2. SQLite Multi-Threaded / Multi-Connection WAL Lock Contention:
   - 20 concurrent worker threads opening separate DB connections.
   - Burst of 100 concurrent write transactions (INSERT request_logs, UPDATE users).
   - Zero `OperationalError: database is locked` exceptions under WAL mode + busy timeout.
   - Active PRAGMA journal_mode == 'wal' and busy_timeout >= 5000 verification.
   - Concurrent readers executing during write transactions without blocking or lock errors.

3. Asynchronous Unlock Concurrency Quota Enforcement (/v1/unlock/async):
   - Burst of requests submitted by user with plan concurrency limit (Free plan: 3 slots).
   - In-flight tasks occupy slots: requests exceeding quota must return HTTP 429 Too Many Requests.
   - Verification that users cannot exceed plan concurrency quotas by submitting bursts of asynchronous requests.
"""

import os
import sys
import time
import sqlite3
import shutil
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor, as_completed
from unittest.mock import patch, MagicMock

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import core.db as db_mod
from core.db import (
    get_db,
    init_db,
    deduct_credit,
    add_credit,
    get_user_by_id,
    log_request,
    PLANS
)


class BaseIsolatedDBTestCase(unittest.TestCase):
    """Hermetic test fixture ensuring disk-backed SQLite WAL database isolation per test."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="xpk_race_test_")
        self.test_db_path = os.path.join(self.test_dir, "test_unblocker.db")

        self.orig_db_path = db_mod.DB_PATH
        db_mod.DB_PATH = self.test_db_path

        def get_test_db():
            os.makedirs(os.path.dirname(self.test_db_path), exist_ok=True)
            conn = sqlite3.connect(self.test_db_path, timeout=15.0)
            conn.execute("PRAGMA journal_mode = WAL;")
            conn.execute("PRAGMA busy_timeout = 5000;")
            conn.execute("PRAGMA foreign_keys = ON;")
            conn.row_factory = sqlite3.Row
            return conn

        self.orig_get_db = db_mod.get_db
        db_mod.get_db = get_test_db

        # Initialize schema and verify WAL
        db_mod.init_db()

    def tearDown(self):
        db_mod.DB_PATH = self.orig_db_path
        db_mod.get_db = self.orig_get_db
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _create_test_user(self, username: str, credits: float, plan: str = "free", concurrency_limit: int = 3) -> dict:
        conn = db_mod.get_db()
        cur = conn.cursor()
        now = int(time.time())
        api_key = f"xpk_test_{username}_{os.urandom(4).hex()}"
        cur.execute(
            """INSERT INTO users (username, email, api_key, credits, plan, concurrency_limit, is_guest, created_at)
               VALUES (?, ?, ?, ?, ?, ?, 0, ?)""",
            (username, f"{username}@gmail.com", api_key, float(credits), plan, concurrency_limit, now)
        )
        conn.commit()
        uid = cur.lastrowid
        cur.execute("SELECT * FROM users WHERE id = ?", (uid,))
        user = dict(cur.fetchone())
        conn.close()
        return user


# ═════════════════════════════════════════════════════════════════════════════════
# 1. MULTI-THREADED CREDIT OVERDRAWING (TOCTOU RACE CONDITIONAL STRESS TESTS)
# ═════════════════════════════════════════════════════════════════════════════════

class TestCreditDeductionTOCTOURace(BaseIsolatedDBTestCase):
    """
    Stress-tests deduct_credit against Time-of-Check to Time-of-Use race conditions.
    Simulates high-concurrency bursts where multiple threads simultaneously attempt to
    deduct credits using barriers to align thread execution at the microsecond level.
    """

    def test_20_threads_race_on_single_credit(self):
        """
        Primary Mission Scenario:
        User has exactly 1.0 credit.
        20 parallel threads concurrently attempt deduct_credit(user_id, 1.0).
        Invariant: EXACTLY 1 thread succeeds (True), 19 threads fail (False),
        and the final credit balance is exactly 0.0 (never negative).
        """
        user = self._create_test_user("alice_race_1", credits=1.0)
        user_id = user["id"]
        num_threads = 20
        barrier = threading.Barrier(num_threads)
        results = [None] * num_threads

        def worker_task(thread_idx: int):
            # Synchronize threads so all fire simultaneously
            barrier.wait()
            res = deduct_credit(user_id, 1.0)
            results[thread_idx] = res

        threads = [
            threading.Thread(target=worker_task, args=(i,), name=f"TOCTOU-Worker-{i}")
            for i in range(num_threads)
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        successes = sum(1 for r in results if r is True)
        failures = sum(1 for r in results if r is False)

        final_user = get_user_by_id(user_id)
        final_balance = final_user["credits"]

        self.assertEqual(
            successes,
            1,
            f"TOCTOU OVERDRAW DETECTED: Expected exactly 1 successful deduction, but {successes} succeeded! Results: {results}"
        )
        self.assertEqual(
            failures,
            19,
            f"Expected exactly 19 blocked attempts, but found {failures} failures."
        )
        self.assertEqual(
            final_balance,
            0.0,
            f"Final balance corrupted! Expected 0.0, but got {final_balance}."
        )
        self.assertGreaterEqual(
            final_balance,
            0.0,
            f"CRITICAL VULNERABILITY: Balance went negative ({final_balance}) due to non-atomic deduction!"
        )

    def test_20_threads_race_on_zero_credit(self):
        """
        Adversarial Scenario:
        User has exactly 0.0 credits.
        20 parallel threads attempt to deduct 1.0 credit.
        Invariant: 0 threads succeed, 20 fail, balance remains 0.0.
        """
        user = self._create_test_user("bob_zero_cred", credits=0.0)
        user_id = user["id"]
        num_threads = 20
        barrier = threading.Barrier(num_threads)
        results = [None] * num_threads

        def worker_task(thread_idx: int):
            barrier.wait()
            results[thread_idx] = deduct_credit(user_id, 1.0)

        threads = [threading.Thread(target=worker_task, args=(i,)) for i in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        successes = sum(1 for r in results if r is True)
        failures = sum(1 for r in results if r is False)
        final_user = get_user_by_id(user_id)

        self.assertEqual(successes, 0, f"Expected 0 successes on zero balance, but {successes} succeeded.")
        self.assertEqual(failures, 20, f"Expected 20 failures on zero balance, got {failures}.")
        self.assertEqual(final_user["credits"], 0.0, "Balance must remain exactly 0.0.")

    def test_multi_credit_race_exact_quota(self):
        """
        User has 3.0 credits.
        20 parallel threads attempt to deduct 1.0 credit each.
        Invariant: EXACTLY 3 succeed, 17 fail, final balance == 0.0.
        """
        user = self._create_test_user("carol_multi_cred", credits=3.0)
        user_id = user["id"]
        num_threads = 20
        barrier = threading.Barrier(num_threads)
        results = [None] * num_threads

        def worker_task(idx: int):
            barrier.wait()
            results[idx] = deduct_credit(user_id, 1.0)

        threads = [threading.Thread(target=worker_task, args=(i,)) for i in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        successes = sum(1 for r in results if r is True)
        failures = sum(1 for r in results if r is False)
        final_user = get_user_by_id(user_id)

        self.assertEqual(
            successes,
            3,
            f"Expected exactly 3 deductions from 3.0 credits, but {successes} succeeded."
        )
        self.assertEqual(failures, 17, f"Expected 17 failed deductions, got {failures}.")
        self.assertEqual(final_user["credits"], 0.0, f"Expected final balance 0.0, got {final_user['credits']}.")

    def test_fractional_credit_race(self):
        """
        User has 1.5 credits.
        20 parallel threads attempt to deduct 0.5 credits each.
        Invariant: EXACTLY 3 succeed, 17 fail, final balance == 0.0.
        """
        user = self._create_test_user("dan_fractional", credits=1.5)
        user_id = user["id"]
        num_threads = 20
        barrier = threading.Barrier(num_threads)
        results = [None] * num_threads

        def worker_task(idx: int):
            barrier.wait()
            results[idx] = deduct_credit(user_id, 0.5)

        threads = [threading.Thread(target=worker_task, args=(i,)) for i in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        successes = sum(1 for r in results if r is True)
        failures = sum(1 for r in results if r is False)
        final_user = get_user_by_id(user_id)

        self.assertEqual(successes, 3, f"Expected 3 fractional deductions, got {successes}.")
        self.assertEqual(failures, 17, f"Expected 17 failed deductions, got {failures}.")
        self.assertAlmostEqual(final_user["credits"], 0.0, places=4)

    def test_admin_synthetic_user_credit_deduction_bypass(self):
        """
        Admin synthetic user (id=0) has infinite credits and must not be deducted or fail.
        """
        res = deduct_credit(0, 100.0)
        self.assertTrue(res, "Admin synthetic user (user_id=0) should always return True.")

    def test_invalid_negative_or_zero_deduction(self):
        """
        Edge Case:
        - 0.0 deduction returns True without modifying credits.
        - Negative deduction must return False (prevent credit injection via deduct_credit).
        """
        user = self._create_test_user("eve_negative", credits=10.0)
        user_id = user["id"]

        # Zero deduction
        res_zero = deduct_credit(user_id, 0.0)
        self.assertTrue(res_zero, "Zero deduction should return True.")
        self.assertEqual(get_user_by_id(user_id)["credits"], 10.0)

        # Negative deduction probe (credit injection attempt)
        res_neg = deduct_credit(user_id, -5.0)
        self.assertFalse(res_neg, "Negative deduction must return False.")
        self.assertEqual(get_user_by_id(user_id)["credits"], 10.0, "Negative deduction must not add credits.")


# ═════════════════════════════════════════════════════════════════════════════════
# 2. SQLITE MULTI-PROCESS / MULTI-CONNECTION WAL LOCK CONTENTION STRESS TESTS
# ═════════════════════════════════════════════════════════════════════════════════

class TestSQLiteWALConcurrencyContention(BaseIsolatedDBTestCase):
    """
    Stress-tests SQLite WAL mode and busy timeout under concurrent multi-connection writes.
    Validates that high-volume concurrent writes do NOT produce `OperationalError: database is locked`.
    """

    def test_wal_mode_active_and_busy_timeout_configured(self):
        """Verify database pragma configuration conforms to WAL hardening requirements."""
        conn = db_mod.get_db()
        cur = conn.cursor()
        journal_mode = cur.execute("PRAGMA journal_mode;").fetchone()[0]
        busy_timeout = cur.execute("PRAGMA busy_timeout;").fetchone()[0]
        conn.close()

        self.assertEqual(journal_mode.lower(), "wal", f"Expected WAL journal mode, got {journal_mode}.")
        self.assertGreaterEqual(busy_timeout, 5000, f"Expected busy_timeout >= 5000, got {busy_timeout}.")

    def test_20_threads_burst_writes_zero_database_locked_errors(self):
        """
        Fires 20 concurrent threads, each performing rapid write transactions across
        separate connections, simulating concurrent web API and Discord bot writes.
        Invariant: Zero `OperationalError: database is locked` exceptions occur.
        """
        num_threads = 20
        writes_per_thread = 5  # Total 100 concurrent write operations
        barrier = threading.Barrier(num_threads)
        errors = []
        completed_writes = [0] * num_threads

        def write_worker(thread_idx: int):
            barrier.wait()
            for op_idx in range(writes_per_thread):
                try:
                    conn = db_mod.get_db()
                    cur = conn.cursor()
                    now = int(time.time())
                    cur.execute(
                        """INSERT INTO request_logs 
                           (user_id, target_url, mode, status_code, duration_ms, cost, created_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (thread_idx + 1, f"https://example.com/test_{thread_idx}_{op_idx}", "fast_tls", 200, 150, 1.0, now)
                    )
                    conn.commit()
                    conn.close()
                    completed_writes[thread_idx] += 1
                except sqlite3.OperationalError as op_err:
                    if "locked" in str(op_err).lower():
                        errors.append(f"Thread {thread_idx} hit database lock: {op_err}")
                    else:
                        errors.append(f"Thread {thread_idx} OperationalError: {op_err}")
                except Exception as exc:
                    errors.append(f"Thread {thread_idx} unexpected error: {exc}")

        threads = [threading.Thread(target=write_worker, args=(i,)) for i in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(
            len(errors),
            0,
            f"LOCK CONTENTION FAILURE: Observed {len(errors)} database lock/operational errors under WAL mode: {errors}"
        )
        total_completed = sum(completed_writes)
        self.assertEqual(
            total_completed,
            num_threads * writes_per_thread,
            f"Expected {num_threads * writes_per_thread} committed writes, but only {total_completed} finished."
        )

        # Verify all rows exist in the DB
        conn = db_mod.get_db()
        cur = conn.cursor()
        count = cur.execute("SELECT COUNT(*) FROM request_logs").fetchone()[0]
        conn.close()
        self.assertEqual(count, num_threads * writes_per_thread, "Database row count mismatch after concurrent writes.")

    def test_concurrent_readers_and_writers_unblocked(self):
        """
        Validates WAL mode's core property: Readers do NOT block Writers,
        and Writers do NOT block Readers.
        """
        num_readers = 10
        num_writers = 10
        barrier = threading.Barrier(num_readers + num_writers)
        reader_errors = []
        writer_errors = []
        reads_count = [0] * num_readers
        writes_count = [0] * num_writers

        def reader_task(idx: int):
            barrier.wait()
            for _ in range(5):
                try:
                    conn = db_mod.get_db()
                    cur = conn.cursor()
                    cur.execute("SELECT COUNT(*) FROM users")
                    _ = cur.fetchone()[0]
                    conn.close()
                    reads_count[idx] += 1
                except Exception as e:
                    reader_errors.append(str(e))

        def writer_task(idx: int):
            barrier.wait()
            for step in range(5):
                try:
                    conn = db_mod.get_db()
                    cur = conn.cursor()
                    cur.execute(
                        "INSERT INTO users (username, credits, created_at) VALUES (?, 10.0, ?)",
                        (f"rw_user_{idx}_{step}", int(time.time()))
                    )
                    conn.commit()
                    conn.close()
                    writes_count[idx] += 1
                except Exception as e:
                    writer_errors.append(str(e))

        threads = []
        for i in range(num_readers):
            threads.append(threading.Thread(target=reader_task, args=(i,)))
        for i in range(num_writers):
            threads.append(threading.Thread(target=writer_task, args=(i,)))

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(reader_errors), 0, f"Reader errors under concurrent load: {reader_errors}")
        self.assertEqual(len(writer_errors), 0, f"Writer errors under concurrent load: {writer_errors}")
        self.assertEqual(sum(reads_count), num_readers * 5)
        self.assertEqual(sum(writes_count), num_writers * 5)


# ═════════════════════════════════════════════════════════════════════════════════
# 3. ASYNC UNLOCK CONCURRENCY QUOTA STRESS TESTS (/v1/unlock/async)
# ═════════════════════════════════════════════════════════════════════════════════

class TestAsyncUnlockConcurrencyQuota(BaseIsolatedDBTestCase):
    """
    Adversarial Stress Test: Verify that users cannot exceed their plan concurrency quotas
    by submitting bursts of asynchronous requests to `/v1/unlock/async`.
    """

    def setUp(self):
        super().setUp()
        from starlette.testclient import TestClient
        import server
        self.server_mod = server
        self.client = TestClient(server.app)

        # Seed test user on Free plan with concurrency limit = 3
        self.user = self._create_test_user("async_concurrency_tester", credits=50.0, plan="free", concurrency_limit=3)
        self.api_key = self.user["api_key"]
        self.user_id = self.user["id"]

    def test_sync_unlock_enforces_concurrency_limit_baseline(self):
        """
        Verify that synchronous /v1/unlock properly enforces concurrency limits (baseline check).
        When active_user_concurrency >= concurrency_limit, HTTP 429 must be returned.
        """
        # Artificially saturate user's active concurrency slots
        self.server_mod.active_user_concurrency[self.user_id] = 3

        try:
            res = self.client.post(
                "/v1/unlock",
                json={"url": "https://httpbin.org/get", "mode": "fast"},
                headers={"X-API-Key": self.api_key}
            )
            self.assertEqual(
                res.status_code,
                429,
                f"Expected HTTP 429 when concurrency slots are saturated, got {res.status_code}: {res.text}"
            )
            self.assertIn("concurrency limit", res.json().get("detail", "").lower())
        finally:
            self.server_mod.active_user_concurrency[self.user_id] = 0

    def test_async_unlock_concurrency_quota_burst_stress(self):
        """
        Adversarial Test:
        User has plan concurrency quota = 3 slots.
        Attacker fires a burst of 10 rapid asynchronous unblock requests to /v1/unlock/async.
        Invariant: The server MUST NOT allow more concurrent active tasks than the user's plan limit.
        Requests beyond the concurrency quota must be rejected with HTTP 429 Too Many Requests.
        """
        concurrency_limit = self.user["concurrency_limit"]  # 3
        burst_size = 10

        # Simulate that the user already has active in-flight tasks occupying their quota
        self.server_mod.active_user_concurrency[self.user_id] = concurrency_limit

        try:
            # Attempt to submit an async unblock request while quota is saturated
            res = self.client.post(
                "/v1/unlock/async",
                json={"url": "https://httpbin.org/get", "mode": "auto"},
                headers={"X-API-Key": self.api_key}
            )

            # In a hardened system, this request MUST be rejected with HTTP 429
            # If the endpoint lacks concurrency enforcement (TOCTOU / rate bypass), it returns 202 Accepted.
            self.assertEqual(
                res.status_code,
                429,
                f"VULNERABILITY DETECTED: /v1/unlock/async permitted task submission while concurrency "
                f"slots ({concurrency_limit}/{concurrency_limit}) were fully saturated! Status: {res.status_code}. "
                f"Endpoint must enforce user plan concurrency limits and return HTTP 429."
            )
            self.assertIn("concurrency", res.json().get("detail", "").lower())
        finally:
            self.server_mod.active_user_concurrency[self.user_id] = 0

    def test_async_unlock_accepts_within_quota(self):
        """
        Verification of legitimate async request flow:
        When active concurrency is 0 (< concurrency_limit), request should be accepted (HTTP 202).
        """
        self.server_mod.active_user_concurrency[self.user_id] = 0

        with patch.object(self.server_mod, "process_async_task", return_value=None):
            res = self.client.post(
                "/v1/unlock/async",
                json={"url": "https://httpbin.org/get", "mode": "auto"},
                headers={"X-API-Key": self.api_key}
            )
            self.assertEqual(res.status_code, 202, f"Expected 202 Accepted within quota, got {res.status_code}")
            data = res.json()
            self.assertTrue(data.get("success"))
            self.assertIn("task_id", data)

    def test_async_unlock_burst_quota_rejection(self):
        """
        Simulate rapid sequential/concurrent burst of 8 requests from a user with concurrency limit = 3
        while in-flight tasks hold concurrency slots.
        Invariant: Exactly 3 requests are accepted (202), and subsequent 5 requests are rejected (429).
        """
        self.server_mod.active_user_concurrency[self.user_id] = 0
        statuses = []

        # Prevent process_async_task from immediately decrementing active_user_concurrency
        with patch.object(self.server_mod, "process_async_task", return_value=None):
            try:
                for i in range(8):
                    res = self.client.post(
                        "/v1/unlock/async",
                        json={"url": f"https://httpbin.org/get?q={i}", "mode": "auto"},
                        headers={"X-API-Key": self.api_key}
                    )
                    statuses.append(res.status_code)
            finally:
                self.server_mod.active_user_concurrency[self.user_id] = 0

        accepted = sum(1 for s in statuses if s == 202)
        rejected = sum(1 for s in statuses if s == 429)

        self.assertEqual(
            accepted,
            3,
            f"Expected exactly 3 requests accepted (matching limit 3), but got {accepted}. Statuses: {statuses}"
        )
        self.assertEqual(
            rejected,
            5,
            f"Expected exactly 5 requests rejected with 429, but got {rejected}. Statuses: {statuses}"
        )


if __name__ == "__main__":
    unittest.main()
