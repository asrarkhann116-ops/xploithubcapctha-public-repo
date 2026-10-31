"""
core/discord_webhook.py
─────────────────────────────────────────────────────────────────────────────
Direct Discord REST API helper — no bot process required.
Used by server.py to:
  1. Edit the persistent live-status embed in ╰୧．status・uptime (every solve)
  2. Post solve showcase entries to ╰୧．solve・showcase
  3. Post announcements to ╰୧．api・updates

All calls use the bot token with aiohttp so they work in FastAPI's event loop.
"""
import os
import time
import asyncio
import aiohttp
from typing import Optional

from core.db import (
    get_setting,
    set_setting,
    get_platform_metrics,
)

DISCORD_API = "https://discord.com/api/v10"
BOT_TOKEN   = os.getenv("DISCORD_BOT_TOKEN", "")
BASE_URL    = os.getenv("BASE_URL", "https://xploithubcapctha.up.railway.app")

# ─── DB keys ───────────────────────────────────────────────────────────────
CHANNEL_STATUS_KEY   = "discord_status_channel_id"
CHANNEL_UPDATES_KEY  = "discord_updates_channel_id"
CHANNEL_SHOWCASE_KEY = "discord_showcase_channel_id"
MSG_STATUS_KEY       = "discord_status_message_id"

STATUS_COLOR   = 0x10b981   # green
ANNOUNCE_COLOR = 0x06b6d4   # cyan
SHOWCASE_COLOR = 0x8b5cf6   # purple

# ─── Rate-limit guard ──────────────────────────────────────────────────────
_last_status_update: float = 0.0
STATUS_MIN_INTERVAL = 60    # seconds — don't edit embed more than once/min


# ───────────────────────────────────────────────────────────────────────────
#  LOW-LEVEL HELPERS
# ───────────────────────────────────────────────────────────────────────────

def _headers() -> dict:
    return {
        "Authorization": f"Bot {BOT_TOKEN}",
        "Content-Type":  "application/json",
    }


async def _patch_message(channel_id: str, message_id: str, payload: dict) -> bool:
    """PATCH (edit) an existing Discord message."""
    url = f"{DISCORD_API}/channels/{channel_id}/messages/{message_id}"
    async with aiohttp.ClientSession() as session:
        async with session.patch(url, json=payload, headers=_headers()) as r:
            if r.status == 404:
                return False   # message deleted
            return r.status in (200, 204)


async def _post_message(channel_id: str, payload: dict) -> Optional[str]:
    """POST a new message; returns message ID string or None on failure."""
    url = f"{DISCORD_API}/channels/{channel_id}/messages"
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload, headers=_headers()) as r:
            if r.status == 200:
                data = await r.json()
                return data.get("id")
            text = await r.text()
            print(f"[DISCORD] POST failed {r.status}: {text[:200]}")
            return None


# ───────────────────────────────────────────────────────────────────────────
#  STATUS EMBED  (called from server startup + after every solve)
# ───────────────────────────────────────────────────────────────────────────

def _build_status_payload() -> dict:
    """Build Discord embed payload for the live status message."""
    metrics = get_platform_metrics(7)
    now_ts  = int(time.time())
    embed   = {
        "title":       "⚡ Xploit Unblocker · Live Platform Status",
        "description": (
            "Real-time anti-bot bypass infrastructure telemetry.\n"
            f"> Last refreshed: <t:{now_ts}:R>"
        ),
        "color": STATUS_COLOR,
        "fields": [
            {"name": "🟢 Status",          "value": "`OPERATIONAL`",                               "inline": True},
            {"name": "🎯 Bypass Rate",      "value": f"**{metrics['success_rate_percent']}%**",    "inline": True},
            {"name": "⏱ Avg Latency",       "value": f"**{metrics['avg_latency_ms']} ms**",        "inline": True},
            {"name": "📈 Total Solves",      "value": f"**{metrics['total_requests']:,}**",         "inline": True},
            {"name": "👥 Active (24h)",      "value": f"**{metrics['active_users_24h']:,}**",       "inline": True},
            {"name": "🤖 Engine",           "value": "`X-Stealth CDP v2.4 + Fast-TLS`",            "inline": True},
            {
                "name":   "🛡️ Supported Defenses",
                "value":  "• Cloudflare Turnstile & 5s Challenge\n• DataDome Interstitial\n• Akamai & Kasada",
                "inline": False,
            },
            {
                "name":   "🔗 Quick Links",
                "value":  f"[Web Console]({BASE_URL}) · [Docs]({BASE_URL}/guide) · [Status]({BASE_URL}/status.html)",
                "inline": False,
            },
        ],
        "footer": {"text": "Xploit Unblocker  ·  Auto-updates every solve"},
        "timestamp": f"{time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime())}Z",
    }
    return {"embeds": [embed]}


async def push_status_embed(force: bool = False) -> bool:
    """Edit the pinned status embed. Skips if updated < STATUS_MIN_INTERVAL ago.
    Set force=True to bypass the rate-limit guard (e.g. on startup)."""
    global _last_status_update

    if not force and (time.time() - _last_status_update) < STATUS_MIN_INTERVAL:
        return True   # too soon, skip

    if not BOT_TOKEN:
        return False

    channel_id = get_setting(CHANNEL_STATUS_KEY)
    if not channel_id:
        return False

    payload    = _build_status_payload()
    msg_id     = get_setting(MSG_STATUS_KEY)

    if msg_id:
        ok = await _patch_message(channel_id, msg_id, payload)
        if ok:
            _last_status_update = time.time()
            print(f"[STATUS] Embed edited (msg={msg_id})")
            return True
        # Message gone — fall through to re-post
        set_setting(MSG_STATUS_KEY, "")

    # Post fresh
    new_id = await _post_message(channel_id, payload)
    if new_id:
        set_setting(MSG_STATUS_KEY, new_id)
        _last_status_update = time.time()
        print(f"[STATUS] Embed posted fresh (msg={new_id})")
        return True

    return False


# ───────────────────────────────────────────────────────────────────────────
#  SOLVE SHOWCASE  (called after every successful API solve)
# ───────────────────────────────────────────────────────────────────────────

async def post_solve_showcase(
    target_url: str,
    mode: str,
    duration_ms: int,
    solver_type: str = "Cloudflare",
    token_preview: str = "",
    username: str = "",
) -> bool:
    """Post a solve showcase card to ╰୧．solve・showcase."""
    if not BOT_TOKEN:
        return False

    channel_id = get_setting(CHANNEL_SHOWCASE_KEY)
    if not channel_id:
        return False

    now_ts = int(time.time())
    # Shorten URL for display
    short_url = target_url[:60] + "…" if len(target_url) > 60 else target_url

    preview_field = []
    if token_preview:
        preview_field = [{
            "name":   "🔑 Extracted Token (preview)",
            "value":  f"```{token_preview[:120]}...```",
            "inline": False,
        }]

    user_field = []
    if username:
        user_field = [{"name": "👤 API User", "value": f"`{username}`", "inline": True}]

    embed = {
        "title":       f"🔥 Live Solve Milestone — {solver_type}",
        "description": f"Verified real-time challenge clearance on **{short_url}**",
        "color":       SHOWCASE_COLOR,
        "fields":      [
            {"name": "🎯 Target",        "value": f"`{short_url}`",           "inline": False},
            {"name": "⚡ Mode",          "value": f"`{mode}`",                 "inline": True},
            {"name": "⏱ Clearance Time", "value": f"`{duration_ms:,} ms`",    "inline": True},
            {"name": "✅ Result",         "value": "**200 OK — Clearance Solved!**", "inline": True},
            *user_field,
            *preview_field,
        ],
        "footer": {"text": "Xploit Solves Stream · Zero Fingerprint Clearance"},
        "timestamp": f"{time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime())}Z",
    }

    new_id = await _post_message(channel_id, {"embeds": [embed]})
    if new_id:
        print(f"[SHOWCASE] Posted solve for {short_url}")
        return True
    return False


# ───────────────────────────────────────────────────────────────────────────
#  ANNOUNCEMENTS  (called by admin API, works without bot process)
# ───────────────────────────────────────────────────────────────────────────

async def post_announcement(title: str, message: str, version: str = "") -> bool:
    """Post announcement embed to ╰୧．api・updates channel via REST."""
    if not BOT_TOKEN:
        return False

    channel_id = get_setting(CHANNEL_UPDATES_KEY)
    if not channel_id:
        print("[ANNOUNCE] Updates channel not configured.")
        return False

    embed = {
        "title":       f"📢 {title}",
        "description": message,
        "color":       ANNOUNCE_COLOR,
        "fields":      [],
        "footer":      {"text": "Xploit Unblocker · Admin Broadcast"},
        "timestamp":   f"{time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime())}Z",
    }
    if version:
        embed["fields"].append({"name": "Version", "value": f"`{version}`", "inline": True})
    embed["fields"].append({"name": "🔗 Website", "value": f"[Open Console]({BASE_URL})", "inline": True})

    # @here ping + embed
    payload = {"content": "@here", "embeds": [embed]}
    new_id = await _post_message(channel_id, payload)
    return new_id is not None


# ───────────────────────────────────────────────────────────────────────────
#  BACKGROUND STATUS LOOP  (started from FastAPI startup event)
# ───────────────────────────────────────────────────────────────────────────

async def status_background_loop():
    """Asyncio task: push status embed every 2 minutes.
    Attach to FastAPI lifespan or create_task in startup."""
    # Initial push on server start
    await asyncio.sleep(10)   # wait 10s for DB/Discord to settle
    await push_status_embed(force=True)
    while True:
        await asyncio.sleep(120)   # every 2 minutes
        try:
            await push_status_embed()
        except Exception as e:
            print(f"[STATUS_LOOP] Error: {e}")
