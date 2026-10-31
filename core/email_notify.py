"""
core/email_notify.py — Resend-powered email notifications

Triggers:
  - welcome_email()        : new user registered (Discord OAuth or email signup)
  - deposit_confirmed()    : USDT deposit verified, credits added
  - low_credits_warning()  : credits drop below LOW_CREDITS_THRESHOLD
  - plan_activated()       : subscription plan started
"""

import os
import logging
import aiohttp
from typing import Optional

log = logging.getLogger("email_notify")

RESEND_API_KEY      = os.getenv("RESEND_API_KEY", "")
EMAIL_FROM          = os.getenv("EMAIL_FROM", "onboarding@resend.dev")
EMAIL_FROM_NAME     = os.getenv("EMAIL_FROM_NAME", "Xploit Unblocker")
BASE_URL            = os.getenv("BASE_URL", "https://xploithubcapctha.up.railway.app")
LOW_CREDITS_THRESHOLD = 50  # warn when credits fall below this

RESEND_ENDPOINT = "https://api.resend.com/emails"


# ── Internal sender ──────────────────────────────────────────────────────────

async def _send(to: str, subject: str, html: str) -> bool:
    """Send email via Resend REST API. Returns True on success."""
    if not RESEND_API_KEY:
        log.warning("[EMAIL] RESEND_API_KEY not set — email skipped.")
        return False
    if not to or "@" not in to:
        log.debug("[EMAIL] No valid email address for user — skipping.")
        return False

    payload = {
        "from": f"{EMAIL_FROM_NAME} <{EMAIL_FROM}>",
        "to": [to],
        "subject": subject,
        "html": html,
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                RESEND_ENDPOINT,
                headers={"Authorization": f"Bearer {RESEND_API_KEY}",
                         "Content-Type": "application/json"},
                json=payload,
            ) as r:
                if r.status in (200, 201):
                    log.info("[EMAIL] Sent '%s' to %s", subject, to)
                    return True
                body = await r.text()
                log.error("[EMAIL] Resend error %s: %s", r.status, body)
                return False
    except Exception as exc:
        log.exception("[EMAIL] Send failed: %s", exc)
        return False


# ── Email templates ──────────────────────────────────────────────────────────

def _base_html(content: str) -> str:
    """Wrap content in a dark-themed base template."""
    return f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Xploit Unblocker</title>
</head>
<body style="margin:0;padding:0;background:#0a0f1a;font-family:'Segoe UI',Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0">
    <tr>
      <td align="center" style="padding:40px 20px;">
        <table width="600" cellpadding="0" cellspacing="0" style="background:#111827;border-radius:12px;border:1px solid #1e293b;overflow:hidden;">
          <!-- Header -->
          <tr>
            <td style="background:linear-gradient(135deg,#0d9488,#0891b2);padding:28px 36px;">
              <h1 style="margin:0;color:#fff;font-size:22px;font-weight:700;letter-spacing:-0.5px;">
                ⚡ Xploit Unblocker
              </h1>
              <p style="margin:4px 0 0;color:rgba(255,255,255,0.75);font-size:13px;">
                Anti-Bot Bypass Infrastructure
              </p>
            </td>
          </tr>
          <!-- Body -->
          <tr>
            <td style="padding:32px 36px;color:#e2e8f0;">
              {content}
            </td>
          </tr>
          <!-- Footer -->
          <tr>
            <td style="padding:20px 36px;border-top:1px solid #1e293b;text-align:center;">
              <p style="margin:0;font-size:12px;color:#475569;">
                Xploit Unblocker · <a href="{BASE_URL}" style="color:#0d9488;text-decoration:none;">Dashboard</a> ·
                <a href="https://discord.gg/3fb9Q7ucSN" style="color:#0d9488;text-decoration:none;">Discord</a>
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""


# ── Public notification functions ─────────────────────────────────────────────

async def welcome_email(to: str, username: str, api_key: str, credits: float = 75) -> bool:
    """Send welcome email to newly registered user."""
    content = f"""
      <h2 style="margin:0 0 16px;color:#f1f5f9;font-size:20px;">Welcome, {username}! 🎉</h2>
      <p style="margin:0 0 20px;color:#94a3b8;line-height:1.6;">
        Your Xploit Unblocker account is ready. You start with
        <strong style="color:#0d9488;">{credits:.0f} free credits</strong> — no card needed.
      </p>

      <table width="100%" cellpadding="0" cellspacing="0" style="margin:0 0 24px;">
        <tr>
          <td style="background:#0f172a;border-radius:8px;padding:20px;border:1px solid #1e293b;">
            <p style="margin:0 0 8px;font-size:12px;color:#64748b;text-transform:uppercase;letter-spacing:1px;">Your API Key</p>
            <code style="font-size:13px;color:#0d9488;word-break:break-all;">{api_key}</code>
            <p style="margin:10px 0 0;font-size:12px;color:#475569;">Keep this private — it authorizes all API requests.</p>
          </td>
        </tr>
      </table>

      <table width="100%" cellpadding="0" cellspacing="0" style="margin:0 0 24px;">
        <tr>
          <td width="33%" style="padding:12px;background:#0f172a;border-radius:8px;text-align:center;border:1px solid #1e293b;">
            <p style="margin:0;font-size:22px;font-weight:700;color:#f1f5f9;">{credits:.0f}</p>
            <p style="margin:4px 0 0;font-size:11px;color:#64748b;">Free Credits</p>
          </td>
          <td width="4%"></td>
          <td width="63%" style="padding:16px;background:#0f172a;border-radius:8px;border:1px solid #1e293b;">
            <p style="margin:0 0 6px;font-size:13px;color:#94a3b8;">Quick Start:</p>
            <code style="font-size:12px;color:#0d9488;">curl -X POST {BASE_URL}/api/unblock \\<br>&nbsp;&nbsp;-H "X-API-Key: YOUR_KEY" \\<br>&nbsp;&nbsp;-d '{{"url":"https://example.com"}}'</code>
          </td>
        </tr>
      </table>

      <a href="{BASE_URL}" style="display:inline-block;background:linear-gradient(135deg,#0d9488,#0891b2);color:#fff;text-decoration:none;padding:12px 28px;border-radius:8px;font-weight:600;font-size:14px;">
        Open Dashboard →
      </a>
    """
    return await _send(to, "⚡ Welcome to Xploit Unblocker — Your API Key is Ready", _base_html(content))


async def deposit_confirmed(
    to: str, username: str, amount_usdt: float,
    credits_added: float, new_balance: float, tx_hash: str
) -> bool:
    """Send deposit confirmation email."""
    content = f"""
      <h2 style="margin:0 0 16px;color:#f1f5f9;font-size:20px;">Deposit Confirmed ✅</h2>
      <p style="margin:0 0 20px;color:#94a3b8;line-height:1.6;">
        Hey {username}, your Solana USDT deposit has been verified and credits added instantly.
      </p>

      <table width="100%" cellpadding="12" cellspacing="0" style="margin:0 0 24px;background:#0f172a;border-radius:8px;border:1px solid #1e293b;">
        <tr>
          <td style="color:#64748b;font-size:13px;">Amount Deposited</td>
          <td style="color:#f1f5f9;font-weight:700;text-align:right;">{amount_usdt:.2f} USDT</td>
        </tr>
        <tr style="border-top:1px solid #1e293b;">
          <td style="color:#64748b;font-size:13px;">Credits Added</td>
          <td style="color:#0d9488;font-weight:700;text-align:right;">+{credits_added:,.0f} credits</td>
        </tr>
        <tr style="border-top:1px solid #1e293b;">
          <td style="color:#64748b;font-size:13px;">New Balance</td>
          <td style="color:#f1f5f9;font-weight:700;text-align:right;">{new_balance:,.0f} credits</td>
        </tr>
        <tr style="border-top:1px solid #1e293b;">
          <td style="color:#64748b;font-size:13px;">TX Hash</td>
          <td style="text-align:right;"><code style="font-size:11px;color:#475569;">{tx_hash[:24]}...</code></td>
        </tr>
      </table>

      <a href="{BASE_URL}" style="display:inline-block;background:linear-gradient(135deg,#0d9488,#0891b2);color:#fff;text-decoration:none;padding:12px 28px;border-radius:8px;font-weight:600;font-size:14px;">
        View Dashboard →
      </a>
    """
    return await _send(to, f"✅ {amount_usdt:.0f} USDT Deposit Confirmed — {credits_added:,.0f} Credits Added", _base_html(content))


async def low_credits_warning(to: str, username: str, credits_remaining: float) -> bool:
    """Warn user when credits are running low."""
    content = f"""
      <h2 style="margin:0 0 16px;color:#f1f5f9;font-size:20px;">⚠️ Low Credits Warning</h2>
      <p style="margin:0 0 20px;color:#94a3b8;line-height:1.6;">
        Hey {username}, you only have <strong style="color:#f59e0b;">{credits_remaining:.0f} credits</strong> remaining.
        Top up now to avoid service interruption.
      </p>

      <table width="100%" cellpadding="0" cellspacing="0" style="margin:0 0 24px;">
        <tr>
          <td style="background:#431407;border-left:4px solid #f59e0b;border-radius:4px;padding:16px;">
            <p style="margin:0;color:#fcd34d;font-size:14px;">
              At your current usage rate, credits will run out soon.
              Send USDT to your deposit address to top up instantly.
            </p>
          </td>
        </tr>
      </table>

      <a href="{BASE_URL}/plans" style="display:inline-block;background:linear-gradient(135deg,#d97706,#f59e0b);color:#fff;text-decoration:none;padding:12px 28px;border-radius:8px;font-weight:600;font-size:14px;">
        Top Up Now →
      </a>
    """
    return await _send(to, f"⚠️ Only {credits_remaining:.0f} Credits Remaining — Top Up Now", _base_html(content))


async def plan_activated(
    to: str, username: str, plan_name: str,
    credits: float, expires_days: int, amount_usdt: float
) -> bool:
    """Notify user that a subscription plan was activated."""
    content = f"""
      <h2 style="margin:0 0 16px;color:#f1f5f9;font-size:20px;">Plan Activated 🚀</h2>
      <p style="margin:0 0 20px;color:#94a3b8;line-height:1.6;">
        Hey {username}, your <strong style="color:#0d9488;">{plan_name}</strong> plan is now active!
      </p>

      <table width="100%" cellpadding="12" cellspacing="0" style="margin:0 0 24px;background:#0f172a;border-radius:8px;border:1px solid #1e293b;">
        <tr>
          <td style="color:#64748b;font-size:13px;">Plan</td>
          <td style="color:#0d9488;font-weight:700;text-align:right;">{plan_name}</td>
        </tr>
        <tr style="border-top:1px solid #1e293b;">
          <td style="color:#64748b;font-size:13px;">Credits Included</td>
          <td style="color:#f1f5f9;font-weight:700;text-align:right;">{credits:,.0f}</td>
        </tr>
        <tr style="border-top:1px solid #1e293b;">
          <td style="color:#64748b;font-size:13px;">Valid For</td>
          <td style="color:#f1f5f9;font-weight:700;text-align:right;">{expires_days} days</td>
        </tr>
        <tr style="border-top:1px solid #1e293b;">
          <td style="color:#64748b;font-size:13px;">Amount Paid</td>
          <td style="color:#f1f5f9;font-weight:700;text-align:right;">{amount_usdt:.0f} USDT</td>
        </tr>
      </table>

      <a href="{BASE_URL}" style="display:inline-block;background:linear-gradient(135deg,#0d9488,#0891b2);color:#fff;text-decoration:none;padding:12px 28px;border-radius:8px;font-weight:600;font-size:14px;">
        Open Dashboard →
      </a>
    """
    return await _send(to, f"🚀 {plan_name} Plan Activated — {credits:,.0f} Credits Ready", _base_html(content))
