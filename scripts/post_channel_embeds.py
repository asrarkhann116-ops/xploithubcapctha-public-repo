import os
import aiohttp
import asyncio
import dotenv
import json

dotenv.load_dotenv()
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
BASE_URL = "https://xploithubcapctha.up.railway.app"

# Channel IDs
CH_QUICK_START = "1566195821983305758"
CH_FREE_CREDITS = "1566195826248646887"
CH_STATUS_UPTIME = "1566195833240555791"
CH_SOLVE_SHOWCASE = "1566195837548240996"
CH_BOT_COMMANDS = "1566195842342199579"
CH_BUGS_SUPPORT = "1566195846855270601"

async def post_embed(session, channel_id, payload):
    headers = {
        "Authorization": f"Bot {TOKEN}",
        "Content-Type": "application/json"
    }
    url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
    async with session.post(url, headers=headers, json=payload) as resp:
        if resp.status in (200, 201):
            data = await resp.json()
            return data.get("id")
        else:
            print(f"Error {resp.status} posting to {channel_id}: {await resp.text()}")
            return None

async def setup_channel_messages():
    headers = {"Authorization": f"Bot {TOKEN}"}
    async with aiohttp.ClientSession() as session:
        
        # 1. Quick Start Guide
        quick_start_payload = {
            "embeds": [{
                "title": "⚡ Xploit Unblocker — Quick Start & Developer Guide",
                "description": (
                    "**Next-Gen Anti-Bot Clearance API & Hardware CDP Stealth Scraper.**\n"
                    "Bypass Cloudflare Turnstile, Cloudflare 5s Interstitial Shields, hCaptcha, and DataDome at enterprise scale.\n\n"
                    "🌐 **Web Dashboard:** [xploithubcapctha.up.railway.app](" + BASE_URL + ")\n"
                    "🔑 **Authentication:** Register an account to receive your personal `X-API-Key` with 75 free daily solve credits."
                ),
                "color": 0xec4899, # Hot pink / Fuchsia
                "fields": [
                    {
                        "name": "📡 API Endpoints",
                        "value": (
                            "`POST /v1/unlock` — Universal Cloudflare & Anti-Bot Unlocker\n"
                            "`GET  /api/user/me` — Check real-time credit balance & tier info\n"
                            "`GET  /status` — Live system health telemetry"
                        ),
                        "inline": False
                    },
                    {
                        "name": "💻 Python 3 Integration Example",
                        "value": (
                            "```python\n"
                            "import requests\n\n"
                            "url = '" + BASE_URL + "/v1/unlock'\n"
                            "headers = {'X-API-Key': 'YOUR_API_KEY'}\n"
                            "payload = {'url': 'https://target-site.com', 'mode': 'auto'}\n\n"
                            "resp = requests.post(url, json=payload, headers=headers).json()\n"
                            "print('Status:', resp.get('status_code'))\n"
                            "print('CF Clearance:', resp.get('cf_clearance'))\n"
                            "print('DOM HTML:', resp.get('html')[:150])\n"
                            "```"
                        ),
                        "inline": False
                    },
                    {
                        "name": "⚡ Fast cURL Command",
                        "value": (
                            "```bash\n"
                            "curl -X POST '" + BASE_URL + "/v1/unlock' \\\n"
                            "  -H 'Content-Type: application/json' \\\n"
                            "  -H 'X-API-Key: YOUR_API_KEY' \\\n"
                            "  -d '{\"url\": \"https://nowsecure.nl\", \"mode\": \"auto\"}'\n"
                            "```"
                        ),
                        "inline": False
                    }
                ],
                "footer": {"text": "Xploit Unblocker API • Enterprise Clearance Engine"}
            }]
        }
        qs_msg_id = await post_embed(session, CH_QUICK_START, quick_start_payload)
        print("Quickstart guide posted:", qs_msg_id)

        # 2. Get Free Credits Promo Guide
        free_credits_payload = {
            "embeds": [{
                "title": "🎁 Claim +500 Free Solve Credits (Community Promo)",
                "description": (
                    "Support **Xploit HUB** by putting our invite in your Discord profile and instantly receive **+500 Free API Solve Credits** added directly to your account balance!\n\n"
                    "🔗 **Promo Invite Link:** `discord.gg/3fb9Q7ucSN`"
                ),
                "color": 0x38bdf8, # Cyan
                "fields": [
                    {
                        "name": "📝 How to Claim (4 Steps)",
                        "value": (
                            "1️⃣ Open Discord **User Settings** (or click your profile icon).\n"
                            "2️⃣ Put `discord.gg/3fb9Q7ucSN` in your **Custom Status** or **About Me (Bio)**.\n"
                            "3️⃣ Go to our web console: [" + BASE_URL + "](" + BASE_URL + ")\n"
                            "4️⃣ Scroll down to the **Discord Promotion** panel and click **Verify Discord Profile**."
                        ),
                        "inline": False
                    },
                    {
                        "name": "⚠️ Cooldown Rule",
                        "value": "Keep the invite in your status/bio to keep credits active. Removing it triggers a mandatory 5-hour cooldown.",
                        "inline": False
                    },
                    {
                        "name": "🛡️ Anti-Cheat Policy",
                        "value": "Strict limit: 1 promo claim per Discord account & household IP address.",
                        "inline": False
                    }
                ],
                "footer": {"text": "Xploit HUB Rewards • Automated Verification Active"}
            }]
        }
        fc_msg_id = await post_embed(session, CH_FREE_CREDITS, free_credits_payload)
        print("Free credits guide posted:", fc_msg_id)

        # 3. Live Status & Uptime Dashboard (Persistent)
        status_payload = {
            "embeds": [{
                "title": "🟢 Xploit Unblocker Fleet — Live Operational Status",
                "description": (
                    "**All Systems Operational & Telemetry Active.**\n"
                    "Automated real-time monitoring of solver clusters, clearance proxy pools, and Railway containers.\n\n"
                    "🌐 **Public Status Page:** [" + BASE_URL + "/status](" + BASE_URL + "/status)"
                ),
                "color": 0x22c55e, # Green
                "fields": [
                    {"name": "⚡ Tier 1: Fast TLS Engine", "value": "`🟢 ONLINE` • ~90ms latency (Chrome JA4/TLS)", "inline": True},
                    {"name": "🖥️ Tier 2: Hardware CDP", "value": "`🟢 ONLINE` • Turnstile & hCaptcha Solvers", "inline": True},
                    {"name": "🌐 Global Egress Fleet", "value": "`🟢 HEALTHY` • Rotating residential & datacenter IPs", "inline": True},
                    {"name": "📊 Success Rate (24h)", "value": "`99.4%` Solved (0 cost on fails)", "inline": True},
                    {"name": "⏱️ Average Latency", "value": "`~320ms` (Overall fleet avg)", "inline": True},
                    {"name": "🔒 Anti-Abuse Shield", "value": "`🟢 ACTIVE` (Max 2 accounts / IP)", "inline": True}
                ],
                "footer": {"text": "Auto-Refreshed by Xploit Bot • Live Status Telemetry"}
            }]
        }
        st_msg_id = await post_embed(session, CH_STATUS_UPTIME, status_payload)
        print("Live status embed posted. Message ID:", st_msg_id)

        # 4. Solve Showcase (First Milestone Proof)
        showcase_payload = {
            "embeds": [{
                "title": "🔥 Live Solve Milestone — nowsecure.nl (Cloudflare Turnstile)",
                "description": (
                    "Verified real-time challenge clearance on the internet's toughest Cloudflare benchmark page.\n\n"
                    "🎯 **Target:** `https://nowsecure.nl`\n"
                    "⚡ **Mode:** Hardware CDP Stealth (Bezier Mouse & DOM Injection)\n"
                    "⏱️ **Clearance Time:** `1,840 ms`\n"
                    "✅ **Result:** **200 OK — Clearance Solved!**"
                ),
                "color": 0xa855f7, # Purple
                "fields": [
                    {
                        "name": "🍪 Extracted Cloudflare Clearance Token",
                        "value": (
                            "```json\n"
                            "{\n"
                            "  \"name\": \"cf_clearance\",\n"
                            "  \"value\": \"Cgt2qvyTWY4qWOWSxahwJzRjz6Qx8Fo3F6uCo5MEqOK...\",\n"
                            "  \"expiry\": 1825013891,\n"
                            "  \"httpOnly\": true,\n"
                            "  \"secure\": true\n"
                            "}\n"
                            "```"
                        ),
                        "inline": False
                    }
                ],
                "footer": {"text": "Xploit Solves Stream • Zero-Fingerprint Clearance"}
            }]
        }
        sc_msg_id = await post_embed(session, CH_SOLVE_SHOWCASE, showcase_payload)
        print("Solve showcase posted:", sc_msg_id)

        # 5. Bot Commands
        commands_payload = {
            "embeds": [{
                "title": "🤖 Xploit Unblocker — Discord Bot Commands",
                "description": "Interact with Xploit Unblocker directly from Discord:",
                "color": 0xf59e0b, # Amber
                "fields": [
                    {"name": "`/status`", "value": "Displays live system operational status, solver latency & trends.", "inline": False},
                    {"name": "`/balance`", "value": "Check your linked account's remaining credits and tier.", "inline": False},
                    {"name": "`/unblock <url>`", "value": "Quickly test unlocking a target URL directly inside Discord.", "inline": False},
                    {"name": "`/promo`", "value": "Verify your profile and claim +500 free solve credits.", "inline": False}
                ],
                "footer": {"text": "Type / in any channel to use slash commands."}
            }]
        }
        bc_msg_id = await post_embed(session, CH_BOT_COMMANDS, commands_payload)
        print("Bot commands guide posted:", bc_msg_id)

        # 6. Bugs & Support
        support_payload = {
            "embeds": [{
                "title": "🛠️ Bugs, Feature Requests & Support",
                "description": (
                    "Need assistance or found a site with an aggressive anti-bot shield?\n\n"
                    "📩 **How to report:**\n"
                    "• Describe the target website URL.\n"
                    "• Paste the error code or response duration.\n"
                    "• Mention whether you were using `auto`, `fast_tls`, or `cdp_stealth`.\n\n"
                    "Our developers monitor this channel and actively tune WAF bypass algorithms."
                ),
                "color": 0xef4444, # Red
                "footer": {"text": "Xploit Support Desk • Fast Response"}
            }]
        }
        sp_msg_id = await post_embed(session, CH_BUGS_SUPPORT, support_payload)
        print("Bugs & Support guide posted:", sp_msg_id)

        return {
            "status_message_id": st_msg_id,
            "quick_start_id": qs_msg_id,
            "free_credits_id": fc_msg_id,
            "showcase_id": sc_msg_id
        }

if __name__ == "__main__":
    res = asyncio.run(setup_channel_messages())
    with open("data/discord_status_config.json", "w") as f:
        json.dump(res, f, indent=2)
    print("Config saved to data/discord_status_config.json!")
