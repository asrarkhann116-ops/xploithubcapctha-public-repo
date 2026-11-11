import asyncio
import logging
import os
import shutil
import sqlite3
import time
from typing import Optional

import aiohttp

log = logging.getLogger("db_backup")

BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "")
OWNER_USER_ID = int(os.getenv("DB_BACKUP_OWNER_ID", "1104652354655113268"))
BACKUP_INTERVAL = int(os.getenv("DB_BACKUP_INTERVAL_SECONDS", str(25 * 60)))
DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "unblocker.db")
BACKUP_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "backups")
DISCORD_API = "https://discord.com/api/v10"
MAX_RETAINED_SNAPSHOTS = 10


def _headers() -> dict:
    return {"Authorization": f"Bot {BOT_TOKEN}"}


def _prune_old_snapshots(max_retained: int = MAX_RETAINED_SNAPSHOTS) -> None:
    if not os.path.exists(BACKUP_DIR):
        return
    snapshots = [
        os.path.join(BACKUP_DIR, f)
        for f in os.listdir(BACKUP_DIR)
        if f.startswith("unblocker_") and f.endswith(".db")
    ]
    snapshots.sort(key=os.path.getmtime)
    while len(snapshots) > max_retained:
        oldest = snapshots.pop(0)
        try:
            os.remove(oldest)
        except OSError:
            pass


def create_backup_snapshot(dest_path: Optional[str] = None) -> str:
    if not os.path.exists(DB_PATH):
        log.warning("[BACKUP] Source database does not exist: %s", DB_PATH)
        return ""

    os.makedirs(BACKUP_DIR, exist_ok=True)
    if not dest_path:
        ts = time.strftime("%Y%m%d_%H%M%S", time.gmtime())
        dest_path = os.path.join(BACKUP_DIR, f"unblocker_{ts}.db")

    tmp_path = f"{dest_path}.tmp"
    if os.path.exists(tmp_path):
        os.remove(tmp_path)

    source_conn = sqlite3.connect(DB_PATH, timeout=15.0)
    dest_conn = sqlite3.connect(tmp_path)
    try:
        source_conn.backup(dest_conn)
    finally:
        dest_conn.close()
        source_conn.close()

    shutil.move(tmp_path, dest_path)
    _prune_old_snapshots()
    log.info("[BACKUP] Consistent snapshot saved: %s (%d bytes)", dest_path, os.path.getsize(dest_path))
    return dest_path


def get_backup_snapshot_bytes() -> bytes:
    if not os.path.exists(DB_PATH):
        return b""

    source_conn = sqlite3.connect(DB_PATH, timeout=15.0)
    dest_conn = sqlite3.connect(":memory:")
    try:
        source_conn.backup(dest_conn)
        return dest_conn.serialize()
    finally:
        dest_conn.close()
        source_conn.close()


async def _get_dm_channel_id(session: aiohttp.ClientSession) -> Optional[str]:
    if not BOT_TOKEN:
        return None
    try:
        async with session.post(
            f"{DISCORD_API}/users/@me/channels",
            headers=_headers(),
            json={"recipient_id": str(OWNER_USER_ID)},
        ) as r:
            if r.status in (200, 201):
                data = await r.json()
                return data.get("id")
            return None
    except Exception as exc:
        log.warning("[BACKUP] Failed to obtain owner DM channel: %s", exc)
        return None


async def restore_db_from_discord() -> bool:
    if os.path.exists(DB_PATH) and os.path.getsize(DB_PATH) > 0:
        return False

    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

    if os.path.exists(BACKUP_DIR):
        snapshots = [
            os.path.join(BACKUP_DIR, f)
            for f in os.listdir(BACKUP_DIR)
            if f.startswith("unblocker_") and f.endswith(".db")
        ]
        if snapshots:
            snapshots.sort(key=os.path.getmtime)
            latest = snapshots[-1]
            src = sqlite3.connect(latest)
            dst = sqlite3.connect(DB_PATH, timeout=15.0)
            try:
                src.backup(dst)
                log.info("[BACKUP] Restored database from local snapshot: %s", latest)
                return True
            finally:
                dst.close()
                src.close()

    return False


async def send_db_backup(session: Optional[aiohttp.ClientSession] = None) -> bool:
    if not os.path.exists(DB_PATH):
        return False

    snapshot_path = create_backup_snapshot()
    if not snapshot_path:
        return False

    # Security policy: raw unencrypted database binaries are never transmitted over Discord DMs.
    if not BOT_TOKEN:
        return True

    try:
        close_session = False
        if session is None:
            session = aiohttp.ClientSession()
            close_session = True

        channel_id = await _get_dm_channel_id(session)
        if channel_id:
            ts = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
            size = os.path.getsize(snapshot_path)
            content = f"🛡️ **DB Snapshot Secured** — {ts} | {size:,} bytes saved safely to local storage."
            async with session.post(
                f"{DISCORD_API}/channels/{channel_id}/messages",
                headers=_headers(),
                json={"content": content},
            ) as r:
                if r.status not in (200, 201):
                    log.warning("[BACKUP] Discord DM notification status: %s", r.status)

        if close_session:
            await session.close()
        return True
    except Exception as exc:
        log.warning("[BACKUP] Discord notification skipped: %s", exc)
        return True


async def backup_loop():
    log.info("[BACKUP] Background loop active. Interval: %ds", BACKUP_INTERVAL)
    await asyncio.sleep(90)

    while True:
        try:
            create_backup_snapshot()
        except Exception as exc:
            log.exception("[BACKUP] Snapshot error in backup loop: %s", exc)
        await asyncio.sleep(BACKUP_INTERVAL)
