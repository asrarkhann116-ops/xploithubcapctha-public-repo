"""
core/db_backup.py - Discord DM-based SQLite persistence for Railway

Strategy:
  - On startup: fetch latest .db attachment from bot owner's DM, restore it
  - Background loop: every BACKUP_INTERVAL_SECONDS, send updated .db to DM
  - Owner DM is used as free, persistent "cloud storage"
"""

import asyncio
import io
import os
import shutil
import time
import logging
from typing import Optional

import aiohttp

log = logging.getLogger("db_backup")

# ── Config ───────────────────────────────────────────────────────────────────
BOT_TOKEN       = os.getenv("DISCORD_BOT_TOKEN", "")
OWNER_USER_ID   = int(os.getenv("DB_BACKUP_OWNER_ID", "1104652354655113268"))
BACKUP_INTERVAL = int(os.getenv("DB_BACKUP_INTERVAL_SECONDS", str(25 * 60)))  # 25 min default
DB_PATH         = os.path.join(os.path.dirname(__file__), "..", "data", "unblocker.db")
DISCORD_API     = "https://discord.com/api/v10"
BACKUP_FILENAME = "unblocker_backup.db"

# ── Helpers ───────────────────────────────────────────────────────────────────

def _headers() -> dict:
    return {"Authorization": f"Bot {BOT_TOKEN}"}


async def _get_dm_channel_id(session: aiohttp.ClientSession) -> Optional[str]:
    """Open / fetch the existing DM channel with the owner."""
    async with session.post(
        f"{DISCORD_API}/users/@me/channels",
        headers=_headers(),
        json={"recipient_id": str(OWNER_USER_ID)},
    ) as r:
        if r.status in (200, 201):
            data = await r.json()
            return data["id"]
        text = await r.text()
        log.error("[BACKUP] Could not open DM channel: %s %s", r.status, text)
        return None


async def _fetch_latest_db_attachment(
    session: aiohttp.ClientSession, channel_id: str
) -> Optional[bytes]:
    """
    Scan the last 100 messages in the DM for the most recent .db attachment.
    Returns raw bytes of the SQLite file, or None if not found.
    """
    async with session.get(
        f"{DISCORD_API}/channels/{channel_id}/messages",
        headers=_headers(),
        params={"limit": 100},
    ) as r:
        if r.status != 200:
            log.warning("[BACKUP] Could not fetch DM messages: %s", r.status)
            return None
        messages = await r.json()

    # Messages come newest-first, so first .db we find is the latest backup
    for msg in messages:
        for att in msg.get("attachments", []):
            if att.get("filename", "").endswith(".db"):
                async with session.get(att["url"]) as dl:
                    if dl.status == 200:
                        data = await dl.read()
                        log.info(
                            "[BACKUP] Found DB backup (%d bytes) from message %s",
                            len(data), msg["id"],
                        )
                        return data
    return None


async def restore_db_from_discord() -> bool:
    """
    Called at startup BEFORE the server starts.
    Downloads latest DB from owner DM and restores it.
    Returns True if a backup was restored, False if starting fresh.
    """
    if not BOT_TOKEN:
        log.warning("[BACKUP] No DISCORD_BOT_TOKEN — skipping restore.")
        return False

    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

    try:
        async with aiohttp.ClientSession() as session:
            channel_id = await _get_dm_channel_id(session)
            if not channel_id:
                return False

            db_bytes = await _fetch_latest_db_attachment(session, channel_id)
            if not db_bytes:
                log.info("[BACKUP] No previous DB backup found in DM — fresh start.")
                return False

            # Write to temp first to avoid corrupting an existing live DB
            tmp_path = DB_PATH + ".restore_tmp"
            with open(tmp_path, "wb") as f:
                f.write(db_bytes)

            # Sanity check: valid SQLite file starts with this exact magic header
            if db_bytes[:16] != b"SQLite format 3\x00":
                log.error("[BACKUP] Downloaded file is NOT a valid SQLite DB — ignoring.")
                os.remove(tmp_path)
                return False

            shutil.move(tmp_path, DB_PATH)
            log.info("[BACKUP] DB restored from Discord DM (%d bytes)", len(db_bytes))
            return True

    except Exception as exc:
        log.exception("[BACKUP] Restore failed: %s", exc)
        return False


async def send_db_backup(session: aiohttp.ClientSession) -> bool:
    """Send current DB snapshot as file attachment to owner DM."""
    if not BOT_TOKEN:
        return False

    if not os.path.exists(DB_PATH):
        log.warning("[BACKUP] DB file not found — nothing to back up yet.")
        return False

    try:
        channel_id = await _get_dm_channel_id(session)
        if not channel_id:
            return False

        with open(DB_PATH, "rb") as f:
            db_bytes = f.read()

        ts = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
        form = aiohttp.FormData()
        form.add_field(
            "payload_json",
            f'{{"content":"📦 **DB Backup** — {ts} | {len(db_bytes):,} bytes"}}',
            content_type="application/json",
        )
        form.add_field(
            "files[0]",
            io.BytesIO(db_bytes),
            filename=BACKUP_FILENAME,
            content_type="application/octet-stream",
        )

        async with session.post(
            f"{DISCORD_API}/channels/{channel_id}/messages",
            headers=_headers(),
            data=form,
        ) as r:
            if r.status in (200, 201):
                log.info("[BACKUP] DB backup sent to DM (%d bytes)", len(db_bytes))
                return True
            text = await r.text()
            log.error("[BACKUP] Failed to send backup: %s %s", r.status, text)
            return False

    except Exception as exc:
        log.exception("[BACKUP] Send backup failed: %s", exc)
        return False


async def backup_loop():
    """
    Infinite asyncio task — sleeps BACKUP_INTERVAL seconds then sends a DB snapshot.
    Kick off with: asyncio.create_task(backup_loop())
    """
    log.info("[BACKUP] Background loop started. Interval: %ds", BACKUP_INTERVAL)
    # Wait 90s after startup so the server can fully init and first writes land
    await asyncio.sleep(90)

    async with aiohttp.ClientSession() as session:
        while True:
            try:
                await send_db_backup(session)
            except Exception as exc:
                log.exception("[BACKUP] Loop iteration error: %s", exc)
            await asyncio.sleep(BACKUP_INTERVAL)
