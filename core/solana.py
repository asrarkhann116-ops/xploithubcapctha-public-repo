import aiohttp
import os
import sqlite3
import time
from typing import Dict, Any, Optional
from core.db import get_db, add_credit

SOLANA_WALLET = os.getenv("SOLANA_WALLET", "6p9wToN1W8xQQFASCAjbXX9anvv216S5s5v1GZbi9n3u")
USDT_MINT = os.getenv("USDT_MINT", "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB")
SOLANA_RPC = "https://api.mainnet-beta.solana.com"

# $0.1 per request = 10 credits per 1 USDT
CREDITS_PER_USDT = 10.0

async def verify_solana_deposit(tx_hash: str, user_id: int, plan_type: Optional[str] = None) -> Dict[str, Any]:
    """
    Verifies an on-chain transaction on Solana mainnet.
    1. Prevents duplicate replay attacks via database check.
    2. Queries Solana RPC getTransaction with jsonParsed.
    3. Confirms transaction confirmed, err is null, and age <= 24 hours.
    4. Validates SPL Memo instruction matches user deposit_ref.
    5. Enforces SPL USDT mint verification (rejects counterfeit tokens).
    6. Credits user account and activates plan using atomic SQLite transaction.
    """
    tx_hash = tx_hash.strip()
    if not tx_hash or len(tx_hash) < 60:
        return {"success": False, "error": "Invalid Solana transaction signature length."}

    conn = get_db()
    cur = conn.cursor()

    try:
        # Check if already redeemed
        cur.execute("SELECT id FROM deposits WHERE tx_hash = ?", (tx_hash,))
        if cur.fetchone():
            return {"success": False, "error": "This transaction signature has already been claimed!"}

        # Fetch user for deposit_ref
        cur.execute("SELECT id, deposit_ref, plan, plan_expires_at, concurrency_limit FROM users WHERE id = ?", (user_id,))
        user = cur.fetchone()
        if not user:
            return {"success": False, "error": "User record not found."}

        user_ref = user['deposit_ref'] if 'deposit_ref' in user.keys() and user['deposit_ref'] else ""
        if not user_ref:
            return {"success": False, "error": "User does not have an assigned deposit reference. Please register an account first."}

        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getTransaction",
            "params": [
                tx_hash,
                {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0, "commitment": "confirmed"}
            ]
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(SOLANA_RPC, json=payload, timeout=12) as resp:
                    if resp.status != 200:
                        return {"success": False, "error": f"Solana RPC returned HTTP {resp.status}"}
                    data = await resp.json()
        except Exception as e:
            return {"success": False, "error": f"RPC Network timeout: {str(e)}"}

        result = data.get("result")
        if not result:
            return {"success": False, "error": "Transaction not found on Solana mainnet. Wait 10-15s for confirmation and retry."}

        meta = result.get("meta")
        if not meta or meta.get("err") is not None:
            return {"success": False, "error": "Transaction failed or reverted on the Solana blockchain."}

        # Enforce transaction freshness: reject transactions older than 24 hours
        now = int(time.time())
        block_time = result.get("blockTime")
        if block_time is not None:
            if now - int(block_time) > 86400:
                return {"success": False, "error": "Transaction is older than 24 hours and cannot be claimed."}
            if int(block_time) > now + 300:
                return {"success": False, "error": "Transaction timestamp is in the future."}

        # Enforce memo reference verification: match user deposit_ref in transaction instructions/logs
        transaction_data = result.get("transaction", {})
        message_data = transaction_data.get("message", {}) if isinstance(transaction_data, dict) else {}
        instructions = message_data.get("instructions", []) if isinstance(message_data, dict) else []

        memo_texts = []
        for ix in instructions:
            if isinstance(ix, dict):
                parsed = ix.get("parsed")
                if isinstance(parsed, str):
                    memo_texts.append(parsed)
                elif isinstance(parsed, dict) and "memo" in parsed and isinstance(parsed["memo"], str):
                    memo_texts.append(parsed["memo"])
                prog = ix.get("program") or ""
                prog_id = ix.get("programId") or ""
                if prog in ("spl-memo", "memo") or prog_id in (
                    "MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr",
                    "Memo1UhkJRfHyvLMcVucJwxXeuD728EqVDDwQDxFMNo"
                ):
                    if isinstance(parsed, str):
                        memo_texts.append(parsed)
                    elif "data" in ix and isinstance(ix["data"], str):
                        memo_texts.append(ix["data"])

        for inner in meta.get("innerInstructions", []):
            for ix in inner.get("instructions", []):
                if isinstance(ix, dict):
                    parsed = ix.get("parsed")
                    if isinstance(parsed, str):
                        memo_texts.append(parsed)
                    elif isinstance(parsed, dict) and "memo" in parsed and isinstance(parsed["memo"], str):
                        memo_texts.append(str(parsed["memo"]))

        for log in meta.get("logMessages", []):
            if isinstance(log, str):
                memo_texts.append(log)

        memo_matched = any(user_ref.upper() in text.upper() for text in memo_texts)
        if not memo_matched:
            return {
                "success": False,
                "error": f"Transaction memo does not match your user reference ({user_ref}). Replay/theft rejected."
            }

        # Verify recipient received official USDT tokens (enforce SPL token mint)
        deposit_amount = 0.0
        post_tokens = meta.get("postTokenBalances", [])
        pre_tokens = meta.get("preTokenBalances", [])
        has_counterfeit = False

        for post in post_tokens:
            owner = post.get("owner", "")
            if owner == SOLANA_WALLET:
                mint = post.get("mint", "")
                if mint != USDT_MINT:
                    has_counterfeit = True
                    continue

                account_idx = post.get("accountIndex")
                post_amount = float(post.get("uiTokenAmount", {}).get("uiAmount") or 0.0)

                pre_amount = 0.0
                for pre in pre_tokens:
                    if pre.get("accountIndex") == account_idx and pre.get("mint") == USDT_MINT:
                        pre_amount = float(pre.get("uiTokenAmount", {}).get("uiAmount") or 0.0)
                        break
                diff = post_amount - pre_amount
                if diff > 0:
                    deposit_amount += diff

        if deposit_amount <= 0:
            if has_counterfeit:
                return {"success": False, "error": "Counterfeit SPL token detected. Only official Solana USDT (SPL) is accepted."}
            return {"success": False, "error": "Could not detect valid USDT SPL deposit amount. Please ensure you sent USDT (SPL) to the designated treasury wallet."}

        new_plan = None
        plan_duration_days = 0
        concurrency_limit = 10
        is_explicit_payg = (plan_type == "pay_as_you_go")

        # Subscription exact match checks (allow +- 0.50 USDT variance for exchange fee rounding)
        # Annual Vince: ~949 USDT
        if not is_explicit_payg and (948.0 <= deposit_amount <= 950.0 or plan_type == "vince_annual"):
            new_plan = "vince"
            plan_duration_days = 365
            concurrency_limit = 150
            credits_to_add = 150000.0 * 12  # 1.8M solves
            plan_desc = "Annual Vince Plan (1.8M solves • 150+ workers • 365 Days)"
        # Annual Moderato: ~279 USDT
        elif not is_explicit_payg and (278.0 <= deposit_amount <= 280.0 or plan_type == "moderato_annual"):
            new_plan = "moderato"
            plan_duration_days = 365
            concurrency_limit = 50
            credits_to_add = 30000.0 * 12   # 360k solves
            plan_desc = "Annual Moderato Plan (360k solves • 50 workers • 365 Days)"
        # Annual Starter: ~89 USDT
        elif not is_explicit_payg and (88.0 <= deposit_amount <= 90.0 or plan_type == "starter_annual"):
            new_plan = "starter"
            plan_duration_days = 365
            concurrency_limit = 10
            credits_to_add = 5000.0 * 12    # 60k solves
            plan_desc = "Annual Starter Plan (60k solves • 10 workers • 365 Days)"
        # Monthly Vince: ~99 USDT
        elif not is_explicit_payg and (98.0 <= deposit_amount <= 100.0 or plan_type == "vince"):
            new_plan = "vince"
            plan_duration_days = 30
            concurrency_limit = 150
            credits_to_add = 150000.0
            plan_desc = "Monthly Vince Plan (150,000 solves/mo • 150+ workers • 30 Days)"
        # Monthly Moderato: ~29 USDT
        elif not is_explicit_payg and (28.5 <= deposit_amount <= 29.5 or plan_type == "moderato"):
            new_plan = "moderato"
            plan_duration_days = 30
            concurrency_limit = 50
            credits_to_add = 30000.0
            plan_desc = "Monthly Moderato Plan (30,000 solves/mo • 50 workers • 30 Days)"
        # Monthly Starter: ~9 USDT
        elif not is_explicit_payg and (8.5 <= deposit_amount <= 9.5 or plan_type == "starter"):
            new_plan = "starter"
            plan_duration_days = 30
            concurrency_limit = 10
            credits_to_add = 5000.0
            plan_desc = "Monthly Starter Plan (5,000 solves/mo • 10 workers • 30 Days)"
        else:
            # PAY-AS-YOU-GO TOP-UP: Credits NEVER EXPIRE!
            curr_plan = user['plan'] if 'plan' in user.keys() and user['plan'] else 'free'
            curr_expires = user['plan_expires_at'] if 'plan_expires_at' in user.keys() and user['plan_expires_at'] else 0
            curr_concurrency = user['concurrency_limit'] if 'concurrency_limit' in user.keys() and user['concurrency_limit'] else 3

            # Active subscribers receive their tier's discounted overage rate
            if curr_plan == 'vince' and curr_expires > now:
                rate = 0.0008
                credits_to_add = round(deposit_amount / rate, 0)
                new_plan = curr_plan
                concurrency_limit = max(curr_concurrency, 150)
                plan_duration_days = 0
            elif curr_plan == 'moderato' and curr_expires > now:
                rate = 0.0012
                credits_to_add = round(deposit_amount / rate, 0)
                new_plan = curr_plan
                concurrency_limit = max(curr_concurrency, 50)
                plan_duration_days = 0
            elif curr_plan == 'starter' and curr_expires > now:
                rate = 0.0025
                credits_to_add = round(deposit_amount / rate, 0)
                new_plan = curr_plan
                concurrency_limit = max(curr_concurrency, 10)
                plan_duration_days = 0
            else:
                rate = 0.0020
                credits_to_add = round(deposit_amount / rate, 0)
                new_plan = "pay_as_you_go"
                concurrency_limit = 10
                plan_duration_days = 0

            plan_desc = f"Pay-as-you-go Balance (+{credits_to_add:,.0f} solves • NEVER EXPIRES)"

        # Atomic SQLite transaction for credit increment, deposit history and plan update
        try:
            with conn:
                cur.execute("UPDATE users SET credits = credits + ? WHERE id = ?", (credits_to_add, user_id))
                cur.execute(
                    "INSERT INTO deposits (user_id, tx_hash, amount_usdt, credits_added, status, created_at) VALUES (?, ?, ?, ?, 'confirmed', ?)",
                    (user_id, tx_hash, deposit_amount, credits_to_add, now)
                )

                if new_plan:
                    if plan_duration_days > 0:
                        plan_expires = now + (plan_duration_days * 86400)
                        cur.execute(
                            "UPDATE users SET has_deposited = 1, is_guest = 0, plan = ?, plan_expires_at = ?, concurrency_limit = ? WHERE id = ?",
                            (new_plan, plan_expires, concurrency_limit, user_id)
                        )
                    else:
                        cur.execute(
                            """UPDATE users SET has_deposited = 1, is_guest = 0,
                               plan = CASE WHEN plan IN ('vince', 'moderato', 'starter') AND plan_expires_at > ? THEN plan ELSE ? END,
                               concurrency_limit = MAX(concurrency_limit, ?)
                               WHERE id = ?""",
                            (now, new_plan, concurrency_limit, user_id)
                        )
                else:
                    cur.execute("UPDATE users SET has_deposited = 1, is_guest = 0 WHERE id = ?", (user_id,))

                cur.execute("SELECT credits FROM users WHERE id = ?", (user_id,))
                new_balance_row = cur.fetchone()
                new_balance = new_balance_row['credits'] if new_balance_row else 0.0
        except sqlite3.IntegrityError:
            return {"success": False, "error": "This transaction signature has already been claimed!"}
        except Exception as e:
            return {"success": False, "error": f"Database transaction failed: {str(e)}"}

        return {
            "success": True,
            "amount_usdt": deposit_amount,
            "credits_added": credits_to_add,
            "new_balance": new_balance,
            "plan_activated": new_plan,
            "message": f"Verified on-chain! Activated {plan_desc}. Added {credits_to_add:,.0f} solves."
        }
    finally:
        try:
            conn.close()
        except Exception:
            pass
