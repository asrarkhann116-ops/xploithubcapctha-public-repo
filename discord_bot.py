import discord
from discord import app_commands
import os
import sys
import aiohttp
from dotenv import load_dotenv

if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

load_dotenv()

from core.db import get_or_create_user, get_user_by_discord_id, deduct_credit
from engine.unblocker import execute_unblock
from core.promo import verify_user_promo
from core.solana import verify_solana_deposit, SOLANA_WALLET

TOKEN = os.getenv("DISCORD_BOT_TOKEN")
GUILD_ID = int(os.getenv("DISCORD_GUILD_ID", "1459402620199374872"))

class UnblockerBot(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        guild = discord.Object(id=GUILD_ID)
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)
        print("✅ Discord Unblocker Slash Commands Synced to Guild:", GUILD_ID)

client = UnblockerBot()

@client.event
async def on_ready():
    print(f"🤖 Xploit Unblocker Bot online as: {client.user} (ID: {client.user.id})")

# ═════════════════════════════════════════════════
#  COMMAND 1: /unblock <url>
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
            description="You need at least 1 credit ($0.001) to unblock a URL.\n\n"
                        "• Use `/promo` to claim **500 FREE credits** (put server link in bio)\n"
                        "• Use `/topup` to deposit Solana USDT",
            color=0xff0033
        )
        return await interaction.followup.send(embed=embed, ephemeral=True)
        
    result = execute_unblock(url)
    
    if result.get("success"):
        deduct_credit(user["id"], 1.0)
        title = result.get("title") or "Page Unlocked"
        dur = result.get("duration_ms", 0)
        mode = result.get("mode", "stealth")
        html_snip = result.get("html", "")[:400].replace("\n", " ")
        
        embed = discord.Embed(
            title=f"✅ Unblocked: {title[:80]}",
            url=url,
            color=0x00ff99
        )
        embed.add_field(name="⚡ Engine Mode", value=f"`{mode}`", inline=True)
        embed.add_field(name="⏱️ Duration", value=f"`{dur}ms`", inline=True)
        embed.add_field(name="💰 Cost", value="`$0.001 (1 Credit)`", inline=True)
        embed.add_field(name="📄 HTML Snippet", value=f"```{html_snip[:300]}...```", inline=False)
        embed.set_footer(text=f"Credits Remaining: {user['credits'] - 1.0:.1f} | Xploit Unblocker 95")
        await interaction.followup.send(embed=embed)
    else:
        err = result.get("error", "Challenge solve timeout")
        await interaction.followup.send(f"❌ **Failed to unblock target:** `{err}`", ephemeral=True)

# ═════════════════════════════════════════════════
#  COMMAND 2: /promo (Free 500 Credits)
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
        color=0x00ff99 if res.get("success") else 0xff0033
    )
    embed.add_field(name="Required Link", value="`discord.gg/3fb9Q7ucSN`", inline=False)
    embed.add_field(name="⚠️ 5-Hour Penalty Rule", value="Removing the link after claiming triggers an automatic 5-hour timeout!", inline=False)
    await interaction.followup.send(embed=embed, ephemeral=True)

# ═════════════════════════════════════════════════
#  COMMAND 3: /credits
# ═════════════════════════════════════════════════
@client.tree.command(name="credits", description="🔑 View your credits balance and secret API key")
async def credits_command(interaction: discord.Interaction):
    user = get_or_create_user(
        str(interaction.user.id),
        interaction.user.name,
        interaction.user.avatar.url if interaction.user.avatar else ""
    )
    
    embed = discord.Embed(title="🔑 Your Xploit Unblocker Account", color=0x008080)
    embed.add_field(name="💰 Credits Balance", value=f"**{user['credits']:.1f} Requests** ($0.001/ea)", inline=False)
    embed.add_field(name="🔑 API Key (Keep Private)", value=f"`{user['api_key']}`", inline=False)
    embed.add_field(name="🌐 Web Dashboard", value="Login at your unblocker web portal with Discord OAuth2", inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)

# ═════════════════════════════════════════════════
#  COMMAND 4: /topup
# ═════════════════════════════════════════════════
@client.tree.command(name="topup", description="💰 Deposit USDT via Solana to recharge your API balance")
async def topup_command(interaction: discord.Interaction):
    embed = discord.Embed(
        title="💎 Solana USDT Deposit",
        description="Recharge your unblocker API balance with instant on-chain verification.",
        color=0xffd700
    )
    embed.add_field(name="Official Solana Wallet", value=f"`{SOLANA_WALLET}`", inline=False)
    embed.add_field(name="Rates", value="• 1 USDT = 1,000 Unblock Requests\n• 5 USDT = 5,000 Unblock Requests", inline=False)
    embed.add_field(name="How to verify", value="After sending, use `/redeem <tx_hash>` to instantly add credits!", inline=False)
    await interaction.response.send_message(embed=embed)

# ═════════════════════════════════════════════════
#  COMMAND 5: /redeem <tx_hash>
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
        await interaction.followup.send(f"🎉 **{res['message']}**\nNew balance: **{res['new_balance']} credits**!", ephemeral=True)
    else:
        await interaction.followup.send(f"❌ **Deposit verification failed:** {res.get('error')}", ephemeral=True)

if __name__ == "__main__":
    if TOKEN:
        client.run(TOKEN)
    else:
        print("DISCORD_BOT_TOKEN missing in .env")
