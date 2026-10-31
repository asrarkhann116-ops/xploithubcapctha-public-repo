import os
import json
import asyncio
import websockets
import aiohttp
from typing import Tuple, Optional, Dict, Any

BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
GUILD_ID = os.getenv("DISCORD_GUILD_ID", "1459402620199374872")

async def get_presence_via_gateway(user_id: str, timeout: float = 3.5) -> Tuple[str, Optional[Dict[str, Any]]]:
    """
    Connects to Discord Gateway and requests presence & member data for user_id.
    Returns: (custom_status_text, member_dict)
    """
    if not BOT_TOKEN:
        return "", None
        
    uri = "wss://gateway.discord.gg/?v=10&encoding=json"
    custom_status = ""
    member_data = None
    
    try:
        async with asyncio.timeout(timeout):
            async with websockets.connect(uri, close_timeout=1) as ws:
                hello = json.loads(await ws.recv())
                # Intents: GUILDS (1) + GUILD_MEMBERS (2) + GUILD_PRESENCES (256) = 259
                identify = {
                    "op": 2,
                    "d": {
                        "token": BOT_TOKEN,
                        "intents": 259,
                        "properties": {"os": "linux", "browser": "xpk", "device": "xpk"}
                    }
                }
                await ws.send(json.dumps(identify))
                
                while True:
                    raw = await ws.recv()
                    msg = json.loads(raw)
                    t = msg.get("t")
                    if t == "READY":
                        # Request specific member + presence
                        req = {
                            "op": 8,
                            "d": {
                                "guild_id": GUILD_ID,
                                "user_ids": [str(user_id)],
                                "presences": True
                            }
                        }
                        await ws.send(json.dumps(req))
                    elif t == "GUILD_MEMBERS_CHUNK":
                        d = msg.get("d", {})
                        presences = d.get("presences", [])
                        members = d.get("members", [])
                        if members:
                            member_data = members[0]
                        for p in presences:
                            for a in p.get("activities", []):
                                if a.get("type") == 4: # Custom Status
                                    custom_status = a.get("state") or ""
                        break
    except Exception as e:
        print(f"Gateway presence error: {e}")
        
    return custom_status, member_data
