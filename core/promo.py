import aiohttp
import os
import time
from typing import Dict, Any, Tuple
from core.db import get_user_by_discord_id, get_user_by_id, add_credit, set_user_timeout, get_db
from core.discord_presence import get_presence_via_gateway
from core.anti_abuse import check_promo_ip_claimed

PROMO_DISPLAY_LINK = "discord.gg/3fb9Q7ucSN"
PROMO_KEYWORD = "3fb9q7ucsn"
FREE_CREDITS = float(os.getenv("PROMO_FREE_CREDITS", 500))
TIMEOUT_HOURS = int(os.getenv("PROMO_TIMEOUT_HOURS", 5))
BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
GUILD_ID = os.getenv("DISCORD_GUILD_ID", "1459402620199374872")

async def fetch_discord_member_profile(user_id: str, access_token: str = "") -> Tuple[bool, str, str, str]:
    """
    Fetches member info from the guild to inspect bio, nickname, and live presence/status.
    Returns: (is_in_guild, custom_status, bio, nick)
    """
    if not BOT_TOKEN:
        return False, "", "", ""
        
    headers = {"Authorization": f"Bot {BOT_TOKEN}"}
    nick = ""
    global_name = ""
    bio = ""

    async with aiohttp.ClientSession() as session:
        # 1. Fetch guild member details
        member_url = f"https://discord.com/api/v10/guilds/{GUILD_ID}/members/{user_id}"
        async with session.get(member_url, headers=headers) as resp:
            if resp.status != 200:
                return False, "", "", ""
            member_data = await resp.json()
            nick = member_data.get("nick") or ""
            user_obj = member_data.get("user", {})
            global_name = user_obj.get("global_name") or ""

        # 2. If access_token provided (from OAuth), fetch live @me profile which contains real bio
        if access_token:
            try:
                user_headers = {"Authorization": f"Bearer {access_token}"}
                async with session.get("https://discord.com/api/users/@me", headers=user_headers) as u_resp:
                    if u_resp.status == 200:
                        u_data = await u_resp.json()
                        bio = u_data.get("bio") or ""
            except Exception:
                pass

    # 3. Retrieve live real-time Custom Status via Discord Gateway Opcode 8
    custom_status = ""
    try:
        gw_status, gw_member = await get_presence_via_gateway(user_id, timeout=3.5)
        if gw_status:
            custom_status = gw_status
        if gw_member and not nick:
            nick = gw_member.get("nick") or ""
    except Exception:
        pass

    # Combined bio search string (includes global name, nick, and bio)
    combined_notes = f"{bio} {nick} {global_name}".strip()
    return True, custom_status, combined_notes, nick


async def verify_user_promo(user_id: str, db_user_id: int, client_ip: str = "") -> Dict[str, Any]:
    """
    Verifies promo status with full anti-cheat enforcement:
    - Verifies IP has not claimed promo on another account.
    - Inspects live Custom Status and Profile notes for the server invite.
    - Grants +500 credits if valid.
    - Enforces 5-hour timeout only upon verified removal.
    """
    db_user = get_user_by_id(db_user_id) or get_user_by_discord_id(user_id)
    now = int(time.time())
    
    # 1. Check if currently in penalty timeout
    if db_user and db_user.get("timeout_until", 0) > now:
        remaining_mins = (db_user["timeout_until"] - now) // 60
        return {
            "success": False,
            "timed_out": True,
            "message": f"⚠️ Penalty Active! You previously removed the server invite from your profile. Access timed out for {remaining_mins} more minutes.",
            "timeout_minutes": remaining_mins
        }

    # 2. Anti-Cheat: Check if this IP address already claimed promo credits on another account
    if client_ip and check_promo_ip_claimed(client_ip) and not db_user.get("has_promo"):
        return {
            "success": False,
            "message": f"🚨 Anti-Abuse Block: The +{FREE_CREDITS:,.0f} free Discord reward has already been claimed from your IP address ({client_ip}). Max 1 promo claim per household/network is permitted."
        }

    # 3. Check if this Discord ID was already used by another account in DB
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM users WHERE discord_id = ? AND has_promo = 1 AND id != ?", (user_id, db_user_id))
    duplicate_discord = cur.fetchone()
    if duplicate_discord:
        conn.close()
        return {
            "success": False,
            "message": "🚨 Anti-Abuse Block: This Discord account has already been used to claim promo credits on another account."
        }

    access_token = db_user.get("discord_token", "") if db_user else ""
    is_member, status, notes, nick = await fetch_discord_member_profile(user_id, access_token=access_token)
    
    if not is_member:
        conn.close()
        return {
            "success": False,
            "message": f"❌ You must be a member of our Discord server! Join here: https://{PROMO_DISPLAY_LINK}"
        }

    # Check case-insensitive keyword match in Custom Status or Profile/Nick
    has_link = (PROMO_KEYWORD in status.lower()) or (PROMO_KEYWORD in notes.lower())
    
    if has_link:
        if not db_user.get("has_promo"):
            # First-time claim: Grant free credits!
            add_credit(db_user_id, FREE_CREDITS)
            cur.execute("UPDATE users SET has_promo = 1, promo_last_verified = ? WHERE id = ?", (now, db_user_id))
            conn.commit()
            conn.close()
            return {
                "success": True,
                "credits_granted": FREE_CREDITS,
                "message": f"🎉 Verified! '{PROMO_DISPLAY_LINK}' detected in your Discord profile. +{FREE_CREDITS:,.0f} Free Solve Credits granted!"
            }
        else:
            cur.execute("UPDATE users SET promo_last_verified = ? WHERE id = ?", (now, db_user_id))
            conn.commit()
            conn.close()
            return {
                "success": True,
                "credits_granted": 0,
                "message": "✅ Promo link is active and verified in your Discord profile! Active promo status confirmed. 💖"
            }
    else:
        # Link not found!
        if db_user.get("has_promo"):
            # Confirmed removal after previous grant: Trigger 5 hours timeout
            set_user_timeout(db_user_id, hours=TIMEOUT_HOURS)
            conn.close()
            return {
                "success": False,
                "timed_out": True,
                "message": f"🚨 VIOLATION DETECTED! You removed '{PROMO_DISPLAY_LINK}' from your profile. 5 HOURS TIMEOUT ENFORCED! 💀"
            }
        
        conn.close()
        return {
            "success": False,
            "message": f"❌ Promo link not found! Put '{PROMO_DISPLAY_LINK}' in your Discord 'Custom Status' or 'About Me' (Bio) or Server Nickname, then click verify."
        }
