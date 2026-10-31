import asyncio
import discord
from discord import app_commands
import os
import sys
import time
import aiohttp
from dotenv import load_dotenv

if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

load_dotenv()

from core.db import (
    get_or_create_user,
    get_user_by_discord_id,
    deduct_credit,
    get_platform_metrics,
    get_user_plan_meta,
    redeem_voucher,
    get_setting,
    set_setting,
)
from core.db_backup import backup_loop
from engine.unblocker import execute_unblock
from core.promo import verify_user_promo
from core.solana import verify_solana_deposit, SOLANA_WALLET

TOKEN    = os.getenv("DISCORD_BOT_TOKEN")
GUILD_ID = int(os.getenv("DISCORD_GUILD_ID", "1459402620199374872"))
BASE_URL = os.getenv("BASE_URL", "https://xploithubcapctha.up.railway.app")

# ─── DB setting keys ───────────────────────────────────────────────────────
CHANNEL_STATUS_KEY  = "discord_status_channel_id"
CHANNEL_UPDATES_KEY = "discord_updates_channel_id"
MSG_STATUS_KEY      = "discord_status_message_id"

STATUS_COLOR = 0x10b981


class UnblockerBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        guild = discord.Object(id=GUILD_ID)
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)
        print("[BOT] Slash commands synced to guild:", GUILD_ID)


client = UnblockerBot()


# ═══════════════════════════════════════════════════════
#  LIVE STATUS EMBED  (updates on startup + every 5 min)
# ═══════════════════════════════════════════════════════

def build_status_embed() -> discord.Embed:
    """Build the live telemetry embed with fresh platform metrics."""
    metrics = get_platform_metrics(7)
    now_ts  = int(time.time())
    embed   = discord.Embed(
        title="⚡ Xploit Unblocker · Live Platform Status",
        description=(
            "Real-time anti-bot bypass infrastructure telemetry.\n"
            f"> Last refreshed: <t:{now_ts}:R>"
        ),
        color=STATUS_COLOR,
    )
    embed.add_field(name="🟢 Status",           value="`OPERATIONAL`",                             inline=True)
    embed.add_field(name="🎯 Bypass Rate",       value=f"**{metrics['success_rate_percent']}%**",  inline=True)
    embed.add_field(name="⏱ Avg Latency",        value=f"**{metrics['avg_latency_ms']} ms**",      inline=True)
    embed.add_field(name="📈 Total Solves",       value=f"**{metrics['total_requests']:,}**",       inline=True)
    embed.add_field(name="👥 Active (24h)",       value=f"**{metrics['active_users_24h']:,}**",     inline=True)
    embed.add_field(name="🤖 Engine",            value="`X-Stealth CDP v2.4 + Fast-TLS`",          inline=True)
    embed.add_field(
        name="🛡️ Supported Defenses",
        value=(
            "• Cloudflare Turnstile & 5s Challenge\n"
            "• DataDome Interstitial\n"
            "• Akamai Bot Manager & Kasada"
        ),
        inline=False,
    )
    embed.add_field(
        name="🔗 Quick Links",
        value=f"[Web Console]({BASE_URL}) · [Docs]({BASE_URL}/guide) · [Status]({BASE_URL}/status.html)",
        inline=False,
    )
    embed.set_footer(text="Xploit Unblocker  ·  Auto-updates every 5 min")
    return embed


async def refresh_status_embed():
    """Edit (or create) the persistent status embed in the status channel."""
    channel_id_str = get_setting(CHANNEL_STATUS_KEY)
    if not channel_id_str:
        return  # not configured yet

    try:
        channel = client.get_channel(int(channel_id_str)) or await client.fetch_channel(int(channel_id_str))
    except Exception as e:
        print(f"[STATUS] Cannot fetch status channel: {e}")
        return

    embed      = build_status_embed()
    msg_id_str = get_setting(MSG_STATUS_KEY)

    if msg_id_str:
        try:
            msg = await channel.fetch_message(int(msg_id_str))
            await msg.edit(embed=embed)
            print("[STATUS] Live status embed updated.")
            return
        except discord.NotFound:
            pass  # deleted — fall through to re-post
        except Exception as e:
            print(f"[STATUS] Edit failed: {e}")

    # Post fresh and persist the message ID
    try:
        msg = await channel.send(embed=embed)
        set_setting(MSG_STATUS_KEY, str(msg.id))
        print(f"[STATUS] Status embed posted (id={msg.id})")
    except Exception as e:
        print(f"[STATUS] Post failed: {e}")


async def status_loop():
    """Background loop: refresh status embed every 5 minutes."""
    await client.wait_until_ready()
    while not client.is_closed():
        await refresh_status_embed()
        await asyncio.sleep(300)


# ═══════════════════════════════════════════════════════
#  ANNOUNCEMENT BRIDGE  (invoked by server.py admin route)
# ═══════════════════════════════════════════════════════

async def post_announcement_to_discord(title: str, message: str, version: str = "") -> bool:
    """Post a rich announcement embed to the api-updates channel.
    Returns True on success. Called from the FastAPI admin endpoint."""
    channel_id_str = get_setting(CHANNEL_UPDATES_KEY)
    if not channel_id_str:
        print("[ANNOUNCE] Updates channel not configured in DB settings.")
        return False

    try:
        channel = client.get_channel(int(channel_id_str)) or await client.fetch_channel(int(channel_id_str))
    except Exception as e:
        print(f"[ANNOUNCE] Cannot fetch updates channel: {e}")
        return False

    embed = discord.Embed(
        title=f"📢 {title}",
        description=message,
        color=0x06b6d4,
        timestamp=discord.utils.utcnow(),
    )
    if version:
        embed.add_field(name="Version", value=f"`{version}`", inline=True)
    embed.add_field(name="🔗 Website", value=f"[Open Console]({BASE_URL})", inline=True)
    embed.set_footer(text="Xploit Unblocker · Admin Broadcast")

    try:
        await channel.send(content="@here", embed=embed)
        print(f"[ANNOUNCE] Posted: {title}")
        return True
    except Exception as e:
        print(f"[ANNOUNCE] Failed: {e}")
        return False


# ═══════════════════════════════════════════════════════
#  BOT EVENTS
# ═══════════════════════════════════════════════════════

@client.event
async def on_ready():
    print(f"[BOT] Online as: {client.user} (ID: {client.user.id})")
    asyncio.create_task(backup_loop())
    asyncio.create_task(status_loop())
    print("[BOT] Status loop + DB backup loop started.")


# ═════════════════════════════════════════════════
#  /unblock <url>
# ═════════════════════════════════════════════════
@client.tree.command(name="unblock", description="⚡ Bypass Cloudflare / Turnstile on any URL & extract content")
@app_commands.describe(url="The target URL to unblock")
async def unblock_command(interaction: discord.Interaction, url: str):
    await interaction.response.defer(thinking=True)

    user = get_or_create_user(
        str(interaction.user.id),
        interaction.user.name,
        interaction.user.avatar.url if interaction.user.avatar else ""
    )

    if user["credits"] < 1.0:
        embed = discord.Embed(
            title="❌ Insufficient Credits",
            description=(
                "You need at least 1 credit ($0.1) to unblock a URL.\n\n"
                "• Use `/promo` to claim **500 FREE credits** (put server link in bio)\n"
                "• Use `/topup` to deposit Solana USDT"
            ),
            color=0xff0033,
        )
        return await interaction.followup.send(embed=embed, ephemeral=True)

    result = execute_unblock(url)

    if result.get("success"):
        deduct_credit(user["id"], 1.0)
        title     = result.get("title") or "Page Unlocked"
        dur       = result.get("duration_ms", 0)
        mode      = result.get("mode", "stealth")
        html_snip = result.get("html", "")[:400].replace("\n", " ")

        embed = discord.Embed(title=f"✅ Unblocked: {title[:80]}", url=url, color=0x00ff99)
        embed.add_field(name="⚡ Engine Mode",  value=f"`{mode}`",              inline=True)
        embed.add_field(name="⏱️ Duration",     value=f"`{dur}ms`",             inline=True)
        embed.add_field(name="💰 Cost",         value="`$0.1 (1 Credit)`",      inline=True)
        embed.add_field(name="📄 HTML Snippet", value=f"```{html_snip[:300]}...```", inline=False)
        embed.set_footer(text=f"Credits Remaining: {user['credits'] - 1.0:.1f} | Xploit Unblocker")
        await interaction.followup.send(embed=embed)
    else:
        err = result.get("error", "Challenge solve timeout")
        await interaction.followup.send(f"❌ **Failed to unblock target:** `{err}`", ephemeral=True)


# ═════════════════════════════════════════════════
#  /promo
# ═════════════════════════════════════════════════
@client.tree.command(name="promo", description="🎁 Claim 500 Free Credits by adding server link to your bio")
async def promo_command(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)

    user = get_or_create_user(
        str(interaction.user.id),
        interaction.user.name,
        interaction.user.avatar.url if interaction.user.avatar else ""
    )
    res = await verify_user_promo(str(interaction.user.id), user["id"])

    embed = discord.Embed(
        title="🛡️ Discord Promo Guard",
        description=res["message"],
        color=0x00ff99 if res.get("success") else 0xff0033,
    )
    embed.add_field(name="Required Link", value="`discord.gg/3fb9Q7ucSN`", inline=False)
    embed.add_field(
        name="⚠️ 5-Hour Penalty Rule",
        value="Removing the link after claiming triggers an automatic 5-hour timeout!",
        inline=False,
    )
    await interaction.followup.send(embed=embed, ephemeral=True)


# ═════════════════════════════════════════════════
#  /credits  (alias for /balance)
# ═════════════════════════════════════════════════
@client.tree.command(name="credits", description="🔑 View your credits balance and secret API key")
async def credits_command(interaction: discord.Interaction):
    await balance_command(interaction)


# ═════════════════════════════════════════════════
#  /balance
# ═════════════════════════════════════════════════
@client.tree.command(name="balance", description="💳 Check your API credits balance, tier, and API key")
async def balance_command(interaction: discord.Interaction):
    user      = get_or_create_user(
        str(interaction.user.id),
        interaction.user.name,
        interaction.user.avatar.url if interaction.user.avatar else ""
    )
    plan_meta = get_user_plan_meta(user)
    embed     = discord.Embed(title="⚡ Xploit Unblocker Account Balance", color=0x06b6d4)
    embed.add_field(name="💰 Available Balance",  value=f"**{user['credits']:,.1f} Credits**",                                          inline=True)
    embed.add_field(name="🛡️ Tier Plan",         value=f"`{plan_meta['name']}`",                                                       inline=True)
    embed.add_field(name="⚡ Concurrency Limit",  value=f"`{user.get('concurrency_limit') or plan_meta.get('concurrency', 3)} threads`", inline=True)
    embed.add_field(name="🔑 API Key",            value=f"||`{user['api_key']}`|| *(Click to reveal)*",                                inline=False)
    embed.add_field(
        name="🔗 Quick Actions",
        value=f"• [Web Console & Playground]({BASE_URL})\n• Top up via Solana: `/topup`\n• Free credits voucher: `/voucher LAUNCH10`",
        inline=False,
    )
    embed.set_footer(text=f"User ID: {user['id']} · Xploit Unblocker")
    await interaction.response.send_message(embed=embed, ephemeral=True)


# ═════════════════════════════════════════════════
#  /status
# ═════════════════════════════════════════════════
@client.tree.command(name="status", description="📊 Live platform infrastructure status & success rates")
async def status_command(interaction: discord.Interaction):
    await interaction.response.send_message(embed=build_status_embed())


# ═════════════════════════════════════════════════
#  /voucher <code>
# ═════════════════════════════════════════════════
@client.tree.command(name="voucher", description="🎁 Redeem a promotional voucher code (e.g. LAUNCH10)")
@app_commands.describe(code="Promo or gift code to redeem")
async def voucher_command(interaction: discord.Interaction, code: str):
    await interaction.response.defer(ephemeral=True)
    user = get_or_create_user(
        str(interaction.user.id),
        interaction.user.name,
        interaction.user.avatar.url if interaction.user.avatar else ""
    )
    res = redeem_voucher(code.strip().upper(), user["id"])
    if res.get("success"):
        embed = discord.Embed(
            title="🎉 Voucher Claimed Successfully!",
            description=f"**+{res['credits_added']:,.0f} Free Credits** have been added to your account.",
            color=0x00ff99,
        )
        embed.add_field(name="New Balance", value=f"**{res['new_balance']:,.1f} Credits**", inline=True)
    else:
        embed = discord.Embed(
            title="❌ Voucher Error",
            description=res.get("error", "Invalid or already redeemed voucher code."),
            color=0xff0033,
        )
    await interaction.followup.send(embed=embed, ephemeral=True)


# ═════════════════════════════════════════════════
#  /topup
# ═════════════════════════════════════════════════
@client.tree.command(name="topup", description="💰 Deposit USDT via Solana to recharge your API balance")
async def topup_command(interaction: discord.Interaction):
    embed = discord.Embed(
        title="💎 Solana USDT Deposit",
        description="Recharge your unblocker API balance with instant on-chain verification.",
        color=0xffd700,
    )
    embed.add_field(name="Official Solana Wallet", value=f"`{SOLANA_WALLET}`",                                              inline=False)
    embed.add_field(name="Rates",                  value="• 1 USDT = 1,000 Unblock Requests\n• 5 USDT = 5,000 Unblock Requests", inline=False)
    embed.add_field(name="How to verify",          value="After sending, use `/redeem <tx_hash>` to instantly add credits!",     inline=False)
    await interaction.response.send_message(embed=embed)


# ═════════════════════════════════════════════════
#  /redeem <tx_hash>
# ═════════════════════════════════════════════════
@client.tree.command(name="redeem", description="⚡ Redeem a Solana transaction hash for instant credits")
@app_commands.describe(tx_hash="The 88-character Solana transaction signature")
async def redeem_command(interaction: discord.Interaction, tx_hash: str):
    await interaction.response.defer(ephemeral=True)
    user = get_or_create_user(
        str(interaction.user.id),
        interaction.user.name,
        interaction.user.avatar.url if interaction.user.avatar else ""
    )
    res = await verify_solana_deposit(tx_hash, user["id"])
    if res.get("success"):
        await interaction.followup.send(
            f"🎉 **{res['message']}**\nNew balance: **{res['new_balance']} credits**!", ephemeral=True
        )
    else:
        await interaction.followup.send(
            f"❌ **Deposit verification failed:** {res.get('error')}", ephemeral=True
        )


def start_bot():
    if TOKEN:
        client.run(TOKEN)
    else:
        print("[BOT] DISCORD_BOT_TOKEN missing in environment variables.")


if __name__ == "__main__":
    start_bot()
