"""
Adversarial Stress Test Suite: Solana Settlement Integrity
Focus:
  1. Counterfeit SPL Token Mint Rejection
  2. Transaction Theft / Front-Running (Memo / deposit_ref mismatch or missing)
  3. Double-Claim / Replay Attacks (Sequential & Concurrent Race Condition)
  4. Stale Transaction Rejection (> 24 hours) & Future Timestamp Tampering
  5. Negative & Error Handling (Reverted on-chain tx, invalid tx signature length)
  6. Positive Legitimate Settlement Baseline
"""

import asyncio
import os
import shutil
import sqlite3
import sys
import tempfile
import time
import unittest
from unittest.mock import patch, MagicMock

# Ensure project root is on sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import core.db as db_mod
import core.solana as solana_mod
from core.solana import verify_solana_deposit, SOLANA_WALLET, USDT_MINT


class MockAsyncResponse:
    """Mock aiohttp client response with async json() and status code."""
    def __init__(self, json_data, status=200):
        self._json_data = json_data
        self.status = status

    async def json(self):
        return self._json_data

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass


class MockClientSession:
    """Mock aiohttp.ClientSession context manager returning predefined JSON-RPC payloads."""
    def __init__(self, json_data, status=200):
        self.response = MockAsyncResponse(json_data, status)

    def post(self, url, **kwargs):
        return self.response

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass


def build_solana_tx_payload(
    tx_hash: str,
    amount_tokens: float,
    mint: str = USDT_MINT,
    owner: str = SOLANA_WALLET,
    memo: str = "",
    block_time: int = None,
    err: Any = None,
    account_index: int = 1
) -> dict:
    """
    Constructs a realistic Solana JSON-RPC `getTransaction` jsonParsed payload.
    """
    if block_time is None:
        block_time = int(time.time()) - 120  # 2 minutes ago by default

    instructions = []
    log_messages = [
        "Program 11111111111111111111111111111111 invoke [1]",
        "Program 11111111111111111111111111111111 success",
    ]

    if memo:
        instructions.append({
            "program": "spl-memo",
            "programId": "MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr",
            "parsed": memo
        })
        log_messages.append("Program MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr invoke [1]")
        log_messages.append(f'Program log: Memo (len {len(memo)}): "{memo}"')
        log_messages.append("Program MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr success")

    instructions.append({
        "program": "spl-token",
        "programId": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
        "parsed": {
            "type": "transferChecked",
            "info": {
                "amount": str(int(amount_tokens * 1_000_000)),
                "authority": "SenderWallet1111111111111111111111111111111",
                "destination": "TreasuryAccount111111111111111111111111111",
                "mint": mint,
                "tokenAmount": {
                    "amount": str(int(amount_tokens * 1_000_000)),
                    "decimals": 6,
                    "uiAmount": amount_tokens,
                    "uiAmountString": str(amount_tokens)
                }
            }
        }
    })

    return {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "slot": 250000000,
            "blockTime": block_time,
            "meta": {
                "err": err,
                "fee": 5000,
                "preTokenBalances": [
                    {
                        "accountIndex": account_index,
                        "mint": mint,
                        "owner": owner,
                        "uiTokenAmount": {
                            "amount": "0",
                            "decimals": 6,
                            "uiAmount": 0.0,
                            "uiAmountString": "0"
                        }
                    }
                ],
                "postTokenBalances": [
                    {
                        "accountIndex": account_index,
                        "mint": mint,
                        "owner": owner,
                        "uiTokenAmount": {
                            "amount": str(int(amount_tokens * 1_000_000)),
                            "decimals": 6,
                            "uiAmount": amount_tokens,
                            "uiAmountString": str(amount_tokens)
                        }
                    }
                ],
                "innerInstructions": [],
                "logMessages": log_messages
            },
            "transaction": {
                "signatures": [tx_hash],
                "message": {
                    "instructions": instructions
                }
            }
        }
    }


class TestSolanaSettlementAdversarial(unittest.IsolatedAsyncioTestCase):
    """Hermetic adversarial test cases for Solana settlement integrity."""

    def setUp(self):
        # Create an isolated temporary SQLite database for every test method
        self.test_dir = tempfile.mkdtemp()
        self.test_db_path = os.path.join(self.test_dir, "test_unblocker.db")

        # Monkeypatch db paths
        self.orig_db_path = db_mod.DB_PATH
        db_mod.DB_PATH = self.test_db_path

        # Helper to get test db connection
        def get_test_db():
            conn = sqlite3.connect(self.test_db_path, timeout=60.0)
            conn.row_factory = sqlite3.Row
            return conn

        self.orig_get_db = db_mod.get_db
        db_mod.get_db = get_test_db
        solana_mod.get_db = get_test_db

        # Initialize fresh DB schema
        db_mod.init_db()

        # Seed legitimate user (Alice)
        self.alice_id = self._create_user(
            email="alice@gmail.com",
            username="alice_tester",
            deposit_ref="xpk_dep_alice_sec123"
        )

        # Seed attacker user (Eve)
        self.eve_id = self._create_user(
            email="eve@gmail.com",
            username="eve_attacker",
            deposit_ref="xpk_dep_eve_hack456"
        )

        # Generate a valid-length simulated Solana transaction signature (88 chars base58)
        self.valid_tx_hash = "5Kk4F9hNms7J9e7B8aP4K6L8x1Y2Z3a4B5c6D7e8F9g0A1b2C3d4E5f6G7h8J9k0L1m2N3p4Q5r6S7t8U9v0W1x2"
        self.counterfeit_tx_hash = "4Mm3D8gLlr6H8d6A7zN3J5K7w0X1Y2z3A4b5C6d7E8f9Z0a1B2c3D4e5F6g7H8j9K0l1M2n3P4q5R6s7T8u9V0w1"
        self.replay_tx_hash = "3Ll2C7fKkq5G7c5Z6yM2H4J6v9W0X1y2Z3a4B5c6D7e8Y9z0A1b2C3d4E5f6G7h8J9k0L1m2N3p4Q5r6S7t8U9v0"

    def tearDown(self):
        # Restore monkeypatches
        db_mod.DB_PATH = self.orig_db_path
        db_mod.get_db = self.orig_get_db
        solana_mod.get_db = self.orig_get_db

        # Purge temporary test directory
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _create_user(self, email: str, username: str, deposit_ref: str) -> int:
        """Helper to insert an isolated user row."""
        conn = db_mod.get_db()
        cur = conn.cursor()
        now = int(time.time())
        cur.execute(
            """INSERT INTO users (username, email, password_hash, credits, plan, plan_expires_at, concurrency_limit, has_deposited, is_guest, deposit_ref, created_at)
               VALUES (?, ?, 'dummy_hash', 0.0, 'free', 0, 3, 0, 0, ?, ?)""",
            (username, email, deposit_ref, now)
        )
        user_id = cur.lastrowid
        conn.commit()
        conn.close()
        return user_id

    def _get_user(self, user_id: int) -> dict:
        conn = db_mod.get_db()
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        row = cur.fetchone()
        conn.close()
        return dict(row) if row else {}

    def _get_deposits_count(self, tx_hash: str) -> int:
        conn = db_mod.get_db()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) as cnt FROM deposits WHERE tx_hash = ?", (tx_hash,))
        cnt = cur.fetchone()["cnt"]
        conn.close()
        return cnt

    # ──────────────────────────────────────────────────────────────────────────
    # ATTACK 1: COUNTERFEIT SPL MINT SPOOFING
    # ──────────────────────────────────────────────────────────────────────────
    async def test_attack_counterfeit_spl_mint_rejected(self):
        """
        Adversarial Test: Attacker deploys a worthless fake SPL token and transfers 949
        counterfeit tokens with Alice's memo reference. System must detect and reject fake mint.
        """
        counterfeit_mint = "FakeMint111111111111111111111111111111111111"
        payload = build_solana_tx_payload(
            tx_hash=self.counterfeit_tx_hash,
            amount_tokens=949.0,
            mint=counterfeit_mint,
            owner=SOLANA_WALLET,
            memo="xpk_dep_alice_sec123"
        )

        with patch("aiohttp.ClientSession", return_value=MockClientSession(payload)):
            result = await verify_solana_deposit(self.counterfeit_tx_hash, self.alice_id)

        # Assertion: Attack must fail
        self.assertFalse(result["success"], "VULNERABILITY DETECTED: Counterfeit SPL token mint was accepted!")
        self.assertIn("counterfeit", result["error"].lower(), "Expected error message indicating counterfeit token.")

        # Verify database state remained unaltered
        alice = self._get_user(self.alice_id)
        self.assertEqual(alice["credits"], 0.0, "Credits were illicitly added for counterfeit token!")
        self.assertEqual(alice["plan"], "free", "Plan was illicitly upgraded on counterfeit token!")
        self.assertEqual(self._get_deposits_count(self.counterfeit_tx_hash), 0, "Counterfeit tx was logged in deposits!")

    async def test_attack_counterfeit_mixed_with_zero_usdt_rejected(self):
        """
        Adversarial Test: Attacker includes counterfeit token balance alongside zero USDT balance.
        """
        counterfeit_mint = "ScamToken22222222222222222222222222222222222"
        now = int(time.time()) - 60
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "slot": 250000001,
                "blockTime": now,
                "meta": {
                    "err": None,
                    "preTokenBalances": [
                        {"accountIndex": 1, "mint": counterfeit_mint, "owner": SOLANA_WALLET, "uiTokenAmount": {"uiAmount": 0.0}},
                        {"accountIndex": 2, "mint": USDT_MINT, "owner": SOLANA_WALLET, "uiTokenAmount": {"uiAmount": 10.0}}
                    ],
                    "postTokenBalances": [
                        {"accountIndex": 1, "mint": counterfeit_mint, "owner": SOLANA_WALLET, "uiTokenAmount": {"uiAmount": 99.0}},
                        {"accountIndex": 2, "mint": USDT_MINT, "owner": SOLANA_WALLET, "uiTokenAmount": {"uiAmount": 10.0}}  # diff = 0
                    ],
                    "innerInstructions": [],
                    "logMessages": []
                },
                "transaction": {
                    "signatures": [self.counterfeit_tx_hash],
                    "message": {
                        "instructions": [
                            {"program": "spl-memo", "parsed": "xpk_dep_alice_sec123"}
                        ]
                    }
                }
            }
        }

        with patch("aiohttp.ClientSession", return_value=MockClientSession(payload)):
            result = await verify_solana_deposit(self.counterfeit_tx_hash, self.alice_id)

        self.assertFalse(result["success"])
        alice = self._get_user(self.alice_id)
        self.assertEqual(alice["credits"], 0.0)

    # ──────────────────────────────────────────────────────────────────────────
    # ATTACK 2: TRANSACTION THEFT & FRONT-RUNNING (MEMO / REF TAMPERING)
    # ──────────────────────────────────────────────────────────────────────────
    async def test_attack_front_running_mismatched_memo_rejected(self):
        """
        Adversarial Test: Alice sends legitimate 99 USDT with memo `xpk_dep_alice_sec123`.
        Eve scrapes the public transaction signature from the mempool/explorer and submits it
        under her own account (`xpk_dep_eve_hack456`). System must block transaction theft.
        """
        payload = build_solana_tx_payload(
            tx_hash=self.valid_tx_hash,
            amount_tokens=99.0,
            mint=USDT_MINT,
            owner=SOLANA_WALLET,
            memo="xpk_dep_alice_sec123"  # Alice's ref, not Eve's!
        )

        with patch("aiohttp.ClientSession", return_value=MockClientSession(payload)):
            result = await verify_solana_deposit(self.valid_tx_hash, self.eve_id)

        # Assertion: Attack must fail
        self.assertFalse(result["success"], "VULNERABILITY DETECTED: Eve was able to hijack Alice's transaction!")
        self.assertTrue(
            "memo" in result["error"].lower() or "reference" in result["error"].lower(),
            f"Expected error regarding memo mismatch, got: {result.get('error')}"
        )

        # Verify Eve received zero credits and plan remained 'free'
        eve = self._get_user(self.eve_id)
        self.assertEqual(eve["credits"], 0.0, "Attacker was credited from hijacked transaction!")
        self.assertEqual(eve["plan"], "free")
        self.assertEqual(self._get_deposits_count(self.valid_tx_hash), 0)

    async def test_attack_missing_memo_instruction_rejected(self):
        """
        Adversarial Test: Valid USDT transfer on-chain, but transaction completely lacks
        the SPL Memo program instruction. System must reject unreferenced transfers.
        """
        payload = build_solana_tx_payload(
            tx_hash=self.valid_tx_hash,
            amount_tokens=99.0,
            mint=USDT_MINT,
            owner=SOLANA_WALLET,
            memo=""  # No memo attached
        )

        with patch("aiohttp.ClientSession", return_value=MockClientSession(payload)):
            result = await verify_solana_deposit(self.valid_tx_hash, self.alice_id)

        self.assertFalse(result["success"], "VULNERABILITY DETECTED: Transaction with missing memo was accepted!")
        alice = self._get_user(self.alice_id)
        self.assertEqual(alice["credits"], 0.0)

    # ──────────────────────────────────────────────────────────────────────────
    # ATTACK 3: DOUBLE-CLAIM & SIGNATURE REPLAY ATTACKS
    # ──────────────────────────────────────────────────────────────────────────
    async def test_attack_double_claim_sequential_replay_rejected(self):
        """
        Adversarial Test: Alice claims a legitimate 99 USDT deposit. Then Alice (or another user)
        resubmits the same transaction hash. The second request must be rejected.
        """
        payload = build_solana_tx_payload(
            tx_hash=self.replay_tx_hash,
            amount_tokens=99.0,
            mint=USDT_MINT,
            owner=SOLANA_WALLET,
            memo="xpk_dep_alice_sec123"
        )

        with patch("aiohttp.ClientSession", return_value=MockClientSession(payload)):
            # Claim 1: Legitimate claim
            res1 = await verify_solana_deposit(self.replay_tx_hash, self.alice_id)
            self.assertTrue(res1["success"], f"Initial legitimate claim failed: {res1.get('error')}")

            # Verify initial crediting (Monthly Vince = 150,000 solves)
            alice_after_res1 = self._get_user(self.alice_id)
            initial_credits = alice_after_res1["credits"]
            self.assertGreater(initial_credits, 0)
            self.assertEqual(self._get_deposits_count(self.replay_tx_hash), 1)

            # Claim 2: Replay attack submission
            res2 = await verify_solana_deposit(self.replay_tx_hash, self.alice_id)
            self.assertFalse(res2["success"], "VULNERABILITY DETECTED: Replay attack succeeded on duplicate signature!")
            self.assertIn("already been claimed", res2["error"].lower())

            # Verify balance did NOT double
            alice_after_res2 = self._get_user(self.alice_id)
            self.assertEqual(
                alice_after_res2["credits"],
                initial_credits,
                "Double-claim replay illicitly doubled credits!"
            )
            self.assertEqual(self._get_deposits_count(self.replay_tx_hash), 1)

    async def test_attack_concurrent_race_condition_replay_rejected(self):
        """
        Adversarial Test: Simulate concurrent racing requests claiming the exact same tx signature
        simultaneously using asyncio.gather. Only exactly 1 request may succeed.
        """
        payload = build_solana_tx_payload(
            tx_hash=self.replay_tx_hash,
            amount_tokens=29.0,  # Moderato
            mint=USDT_MINT,
            owner=SOLANA_WALLET,
            memo="xpk_dep_alice_sec123"
        )

        with patch("aiohttp.ClientSession", return_value=MockClientSession(payload)):
            # Dispatch 5 simultaneous claims with identical signature
            tasks = [verify_solana_deposit(self.replay_tx_hash, self.alice_id) for _ in range(5)]
            results = await asyncio.gather(*tasks)

        success_count = sum(1 for r in results if r.get("success") is True)
        fail_count = sum(1 for r in results if r.get("success") is False)

        self.assertEqual(success_count, 1, f"Expected exactly 1 success under concurrent race, got {success_count}!")
        self.assertEqual(fail_count, 4, f"Expected 4 rejections under concurrent race, got {fail_count}!")

        alice = self._get_user(self.alice_id)
        # Moderato monthly adds 30,000 solves
        self.assertEqual(alice["credits"], 30000.0, "Credits were multiplied by concurrent race condition!")
        self.assertEqual(self._get_deposits_count(self.replay_tx_hash), 1)

    # ──────────────────────────────────────────────────────────────────────────
    # ATTACK 4: STALE TRANSACTIONS (> 24 HOURS) & TIMESTAMP TAMPERING
    # ──────────────────────────────────────────────────────────────────────────
    async def test_attack_stale_transaction_older_than_24h_rejected(self):
        """
        Adversarial Test: Attacker finds a 3-day-old valid deposit transaction.
        System must reject transactions confirmed > 24 hours ago.
        """
        now = int(time.time())
        stale_block_time = now - (86400 * 3)  # 72 hours ago
        payload = build_solana_tx_payload(
            tx_hash=self.valid_tx_hash,
            amount_tokens=99.0,
            mint=USDT_MINT,
            owner=SOLANA_WALLET,
            memo="xpk_dep_alice_sec123",
            block_time=stale_block_time
        )

        with patch("aiohttp.ClientSession", return_value=MockClientSession(payload)):
            result = await verify_solana_deposit(self.valid_tx_hash, self.alice_id)

        self.assertFalse(result["success"], "VULNERABILITY DETECTED: Stale transaction older than 24h was accepted!")
        self.assertTrue(
            "24 hours" in result["error"].lower() or "older" in result["error"].lower(),
            f"Expected error regarding 24 hours age, got: {result.get('error')}"
        )
        alice = self._get_user(self.alice_id)
        self.assertEqual(alice["credits"], 0.0)

    async def test_attack_future_timestamp_manipulation_rejected(self):
        """
        Adversarial Test: RPC payload forged with timestamp far in the future (> 5 mins ahead).
        """
        now = int(time.time())
        future_block_time = now + 3600  # 1 hour in future
        payload = build_solana_tx_payload(
            tx_hash=self.valid_tx_hash,
            amount_tokens=99.0,
            mint=USDT_MINT,
            owner=SOLANA_WALLET,
            memo="xpk_dep_alice_sec123",
            block_time=future_block_time
        )

        with patch("aiohttp.ClientSession", return_value=MockClientSession(payload)):
            result = await verify_solana_deposit(self.valid_tx_hash, self.alice_id)

        self.assertFalse(result["success"], "Future timestamp transaction should be rejected!")
        self.assertIn("future", result["error"].lower())

    # ──────────────────────────────────────────────────────────────────────────
    # ATTACK 5: ERROR HANDLING & IRREVERSIBLE REVERT HANDLING
    # ──────────────────────────────────────────────────────────────────────────
    async def test_attack_reverted_on_chain_transaction_rejected(self):
        """
        Adversarial Test: Attacker submits a transaction that reverted or encountered
        an error on Solana (meta.err != null).
        """
        payload = build_solana_tx_payload(
            tx_hash=self.valid_tx_hash,
            amount_tokens=99.0,
            mint=USDT_MINT,
            owner=SOLANA_WALLET,
            memo="xpk_dep_alice_sec123",
            err={"InstructionError": [0, "Custom: 1"]}
        )

        with patch("aiohttp.ClientSession", return_value=MockClientSession(payload)):
            result = await verify_solana_deposit(self.valid_tx_hash, self.alice_id)

        self.assertFalse(result["success"])
        self.assertIn("failed or reverted", result["error"].lower())
        alice = self._get_user(self.alice_id)
        self.assertEqual(alice["credits"], 0.0)

    async def test_invalid_tx_signature_length_rejected(self):
        """
        Adversarial Test: Submitting garbage or truncated tx_hash must be rejected immediately.
        """
        result = await verify_solana_deposit("too_short_tx_hash", self.alice_id)
        self.assertFalse(result["success"])
        self.assertIn("invalid", result["error"].lower())

    # ──────────────────────────────────────────────────────────────────────────
    # BASELINE VERIFICATION: LEGITIMATE DEPOSIT SUCCESS
    # ──────────────────────────────────────────────────────────────────────────
    async def test_legitimate_usdt_deposit_verified_and_credited(self):
        """
        Control Baseline: Verify that a genuine, fresh USDT transaction with correct SPL mint,
        treasury wallet recipient, and matching user deposit_ref correctly activates the tier.
        """
        now = int(time.time()) - 180  # 3 minutes ago
        payload = build_solana_tx_payload(
            tx_hash=self.valid_tx_hash,
            amount_tokens=99.0,  # Monthly Vince
            mint=USDT_MINT,
            owner=SOLANA_WALLET,
            memo="xpk_dep_alice_sec123",
            block_time=now
        )

        with patch("aiohttp.ClientSession", return_value=MockClientSession(payload)):
            result = await verify_solana_deposit(self.valid_tx_hash, self.alice_id)

        self.assertTrue(result["success"], f"Legitimate deposit failed: {result.get('error')}")
        self.assertEqual(result["amount_usdt"], 99.0)
        self.assertEqual(result["plan_activated"], "vince")
        self.assertEqual(result["credits_added"], 150000.0)

        # Confirm DB persistence
        alice = self._get_user(self.alice_id)
        self.assertEqual(alice["credits"], 150000.0)
        self.assertEqual(alice["plan"], "vince")
        self.assertEqual(alice["concurrency_limit"], 150)
        self.assertEqual(alice["has_deposited"], 1)
        self.assertEqual(self._get_deposits_count(self.valid_tx_hash), 1)


if __name__ == "__main__":
    unittest.main()
