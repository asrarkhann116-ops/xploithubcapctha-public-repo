# Xploit Unblocker API & Developer Console

> Enterprise anti-bot clearance infrastructure. Automated Cloudflare Turnstile, DataDome, and Akamai challenge bypass with dual-tier Chrome DevTools Protocol emulation.

---

## Architecture Overview

1. **Dual-Tier Unblocker Engine:**
   - **Tier 1 (Fast-TLS):** `curl_cffi` impersonating modern Chrome browser TLS fingerprints (JA4, HTTP/2 frame parameters). Resolves standard anti-bot checks in **30-50ms**.
   - **Tier 2 (Stealth CDP Mode):** Reverse-engineered from `SeleniumBase` (`undetected-testing`). Controls Chrome DevTools Protocol directly, executes human bezier cursor dynamics, and resolves Cloudflare Turnstile interactive checkboxes in **2-3 seconds**.

2. **Discord Promo Incentive Loop:**
   - Web console supports Discord OAuth2 authentication.
   - **Free 500 Credits Promo:** Users place `discord.gg/3fb9Q7ucSN` in their Discord Bio (About Me) or Custom Status.
   - **5-Hour Cooldown Rule:** If an operator removes the server invite link after claiming, the account enters an automated **5-Hour Cooldown**.

3. **Solana USDT Micro-Settlement ($0.001 / request):**
   - Official Treasury Wallet: `6p9wToN1W8xQQFASCAjbXX9anvv216S5s5v1GZbi9n3u`
   - Replay defense: Each transaction signature is checked against the database.
   - Solana Mainnet RPC verification: Confirms on-chain token transfer to the treasury wallet.
   - Unique deposit reference IDs and voucher code redemption supported.
   - Settlement Rate: **1 USDT = 1,000 requests**.

4. **Discord Bot Slash Commands:**
   - `/unblock <url>` — Bypass challenges and return response metadata.
   - `/promo` — Scan profile and claim 500 promotional credits.
   - `/credits` — Retrieve balance and API token.
   - `/topup` — Display Solana treasury address and memo instructions.
   - `/redeem <tx_hash>` — Verify on-chain deposit.

---

## Deployment (Railway / Docker)

### Environment Variables
Configure the following in Railway or your `.env` file:
```ini
DISCORD_BOT_TOKEN=your_bot_token_here
DISCORD_CLIENT_ID=your_client_id_here
DISCORD_CLIENT_SECRET=your_client_secret_here
DISCORD_GUILD_ID=1459402620199374872
BASE_URL=https://your-app-domain.up.railway.app
SOLANA_WALLET=6p9wToN1W8xQQFASCAjbXX9anvv216S5s5v1GZbi9n3u
USDT_MINT=Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB
```

### Local Setup
```bash
pip install -r requirements.txt
python run_all.py
```
Access the console at `http://localhost:8000`.
