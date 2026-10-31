import os
import aiohttp
import asyncio
import dotenv

dotenv.load_dotenv()
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
GUILD_ID = os.getenv("DISCORD_GUILD_ID", "1459402620199374872")
CATEGORY_ID = "1566182225538715718"

CHANNELS_TO_CREATE = [
    {"name": "╰୧．api・updates", "type": 0, "topic": "Official Xploit Unblocker updates, patch notes & announcements."},
    {"name": "╰୧．quick・start・guide", "type": 0, "topic": "How to get started, API keys, documentation & code examples."},
    {"name": "╰୧．get・free・credits", "type": 0, "topic": "Instructions to claim +500 free credits via Discord bio/status promo."},
    {"name": "╰୧．status・uptime", "type": 0, "topic": "Live automated system health, solver fleets & uptime telemetry."},
    {"name": "╰୧．solve・showcase", "type": 0, "topic": "Live Cloudflare, Turnstile & Captcha bypass logs and solves."},
    {"name": "╰୧．bot・commands", "type": 0, "topic": "Xploit bot testing commands and sandbox testing."},
    {"name": "╰୧．bugs・support", "type": 0, "topic": "Report issues, API integration questions & customer support."}
]

async def create_channels():
    headers = {
        "Authorization": f"Bot {TOKEN}",
        "Content-Type": "application/json"
    }
    
    async with aiohttp.ClientSession() as session:
        # Fetch existing channels
        async with session.get(f"https://discord.com/api/v10/guilds/{GUILD_ID}/channels", headers=headers) as resp:
            existing = await resp.json()
            existing_names = {c.get("name"): c.get("id") for c in existing if str(c.get("parent_id")) == CATEGORY_ID}

        created_map = {}
        for chan in CHANNELS_TO_CREATE:
            name = chan["name"]
            if name in existing_names:
                chan_id = existing_names[name]
                created_map[name] = chan_id
                print(f"[EXISTS] Channel ID: {chan_id}")
                continue

            payload = {
                "name": name,
                "type": chan["type"],
                "parent_id": CATEGORY_ID,
                "topic": chan.get("topic", "")
            }

            async with session.post(f"https://discord.com/api/v10/guilds/{GUILD_ID}/channels", headers=headers, json=payload) as post_resp:
                if post_resp.status in (200, 201):
                    res = await post_resp.json()
                    cid = res.get("id")
                    created_map[name] = cid
                    print(f"[CREATED] Channel ID: {cid}")
                else:
                    err_txt = await post_resp.text()
                    print(f"[ERROR] Status: {post_resp.status} - {err_txt}")

            await asyncio.sleep(0.5)

        print("\nSUMMARY OF CHANNEL IDS:")
        for k, v in created_map.items():
            print(f"Channel ID: {v}")

        return created_map

if __name__ == "__main__":
    asyncio.run(create_channels())
