import aiohttp
import os
import time
from typing import Dict, Any, Tuple
from core.db import get_user_by_discord_id, add_credit, set_user_timeout, get_db

PROMO_LINK = "discord.gg/3fb9Q7ucSN"
FREE_CREDITS = float(os.getenv("PROMO_FREE_CREDITS", 500))
TIMEOUT_HOURS = int(os.getenv("PROMO_TIMEOUT_HOURS", 5))
BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
GUILD_ID = os.getenv("DISCORD_GUILD_ID", "1459402620199374872")

async def fetch_discord_member_profile(user_id: str) -> Tuple[bool, str, str]:
    """
    Fetches member info from the guild to inspect bio and presence/status.
    Returns: (is_in_guild, custom_status, bio)
    """
    if not BOT_TOKEN:
        return False, "", ""
        
    headers = {"Authorization": f"Bot {BOT_TOKEN}"}
    async with aiohttp.ClientSession() as session:
        # 1. Fetch guild member details
        member_url = f"https://discord.com/api/v10/guilds/{GUILD_ID}/members/{user_id}"
        async with session.get(member_url, headers=headers) as resp:
            if resp.status != 200:
                return False, "", ""
            member_data = await resp.json()

        # 2. Fetch full user object (contains bio)
        user_url = f"https://discord.com/api/v10/users/{user_id}"
        bio = ""
        async with session.get(user_url, headers=headers) as resp:
            if resp.status == 200:
                user_data = await resp.json()
                bio = user_data.get("bio", "") or ""

        # Member custom status or nickname notes
        custom_status = ""
        # In Discord API v10, presence requires gateway or member profile notes
        # Check bio and user's username/nick or about me
        return True, custom_status, bio

async def verify_user_promo(user_id: str, db_user_id: int) -> Dict[str, Any]:
    """
    Verifies promo status.
    - If link present: grants credits and marks has_promo = 1.
    - If user previously had promo but removed it: triggers 5-hour timeout!
    """
    user = get_user_by_discord_id(user_id)
    now = int(time.time())
    
    # Check if currently in timeout
    if user and user.get("timeout_until", 0) > now:
        remaining_mins = (user["timeout_until"] - now) // 60
        return {
            "success": False,
            "timed_out": True,
            "message": f"⚠️ Penalty Active! You removed the server invite from your bio. Access timed out for {remaining_mins} more minutes.",
            "timeout_minutes": remaining_mins
        }

    is_member, status, bio = await fetch_discord_member_profile(user_id)
    if not is_member:
        return {
            "success": False,
            "message": f"❌ You must be a member of our Discord server! Join here: https://discord.gg/3fb9Q7ucSN"
        }

    has_link = (PROMO_LINK in bio.lower()) or (PROMO_LINK in status.lower())
    
    conn = get_db()
    cur = conn.cursor()

    if has_link:
        if not user.get("has_promo"):
            # First time or re-eligible: Grant free credits!
            add_credit(db_user_id, FREE_CREDITS)
            cur.execute("UPDATE users SET has_promo = 1, promo_last_verified = ? WHERE id = ?", (now, db_user_id))
            conn.commit()
            conn.close()
            return {
                "success": True,
                "credits_granted": FREE_CREDITS,
                "message": f"🎉 Verified! '{PROMO_LINK}' found in your profile. +{FREE_CREDITS} Free Credits granted!"
            }
        else:
            cur.execute("UPDATE users SET promo_last_verified = ? WHERE id = ?", (now, db_user_id))
            conn.commit()
            conn.close()
            return {
                "success": True,
                "credits_granted": 0,
                "message": "✅ Promo link is still active in your profile. Good vibes only! 💖"
            }
    else:
        # Link not found!
        if user.get("has_promo"):
            # User had promo previously and REMOVED it! Trigger 5 hours timeout!
            set_user_timeout(db_user_id, hours=TIMEOUT_HOURS)
            conn.close()
            return {
                "success": False,
                "timed_out": True,
                "message": f"🚨 VIOLATION DETECTED! You removed '{PROMO_LINK}' from your profile. 5 HOURS TIMEOUT ENFORCED! 💀"
            }
        
        conn.close()
        return {
            "success": False,
            "message": f"❌ Promo link not found! Put '{PROMO_LINK}' in your Discord 'About Me' (Bio) or Custom Status, then click verify."
        }
