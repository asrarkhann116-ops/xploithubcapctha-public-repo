import os
import time
import aiohttp
from typing import Optional
from fastapi import FastAPI, Header, Query, HTTPException, Request, Response, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

from core.db import (
    get_user_by_api_key,
    get_user_by_discord_id,
    get_or_create_user,
    deduct_credit,
    log_request,
    redeem_voucher,
    get_db
)
from engine.unblocker import execute_unblock
from core.promo import verify_user_promo
from core.solana import verify_solana_deposit, SOLANA_WALLET

app = FastAPI(title="Xploit Unblocker API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files
PUBLIC_DIR = os.path.join(os.path.dirname(__file__), "public")
os.makedirs(PUBLIC_DIR, exist_ok=True)
app.mount("/static", StaticFiles(directory=PUBLIC_DIR), name="static")

# Models
class UnlockRequest(BaseModel):
    url: str
    mode: Optional[str] = "auto" # "auto", "fast", "stealth"
    proxy: Optional[str] = None
    force_cdp: Optional[bool] = False

class PromoVerifyRequest(BaseModel):
    discord_id: str

class DepositVerifyRequest(BaseModel):
    tx_hash: str

class VoucherRedeemRequest(BaseModel):
    code: str

# Helper to get user from API Key
def authenticate_api_key(
    x_api_key: Optional[str] = Header(None),
    api_key: Optional[str] = Query(None)
):
    key = x_api_key or api_key
    if not key:
        raise HTTPException(status_code=401, detail="API Key required. Pass via 'X-API-Key' header or '?api_key=' param.")
    
    user = get_user_by_api_key(key)
    if not user:
        raise HTTPException(status_code=403, detail="Invalid API Key.")
    
    # Check 5-hour timeout restriction
    now = int(time.time())
    if user.get("timeout_until", 0) > now:
        remaining = (user["timeout_until"] - now) // 60
        raise HTTPException(
            status_code=403,
            detail=f"Account restricted! Removed promo link from Discord profile. Timeout active for {remaining} more minutes."
        )

    if user["credits"] < 1.0:
        raise HTTPException(
            status_code=402,
            detail="Insufficient credits! $0.001 (1 credit) required per request. Top up via Solana USDT or claim free credits with Discord promo."
        )

    return user

# Helper to get current web session user from cookie
def get_session_user(request: Request):
    user_id = request.cookies.get("xpk_uid")
    if not user_id:
        return None
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None

# ════════════════════════════════════════════
#  1. WEB INTERFACE (Win95 Aesthetic)
# ════════════════════════════════════════════
@app.get("/", response_class=HTMLResponse)
async def index():
    html_file = os.path.join(PUBLIC_DIR, "index.html")
    if os.path.exists(html_file):
        with open(html_file, "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>Xploit Unblocker 95</h1>"

# ════════════════════════════════════════════
#  2. CORE UNBLOCKER ENDPOINT ($0.001/req)
# ════════════════════════════════════════════
@app.post("/v1/unlock")
async def unlock_endpoint(req: UnlockRequest, user = Depends(authenticate_api_key)):
    start_time = time.time()
    
    # Execute dual-tier unblocker
    force_cdp = req.force_cdp or (req.mode == "stealth")
    result = execute_unblock(req.url, force_cdp=force_cdp, proxy=req.proxy)
    duration_ms = int((time.time() - start_time) * 1000)
    
    status_code = result.get("status_code", 200)
    
    if result.get("success"):
        # Deduct 1 credit ($0.001)
        deduct_credit(user["id"], 1.0)
        log_request(user["id"], req.url, result.get("mode", "auto"), status_code, duration_ms, 0.001)
        
        return {
            "success": True,
            "url": req.url,
            "mode": result.get("mode"),
            "status_code": status_code,
            "duration_ms": duration_ms,
            "title": result.get("title", ""),
            "credits_remaining": user["credits"] - 1.0,
            "html": result.get("html", ""),
            "cookies": result.get("cookies", [])
        }
    else:
        log_request(user["id"], req.url, result.get("mode", "failed"), status_code, duration_ms, 0.0)
        return JSONResponse(
            status_code=400,
            content={
                "success": False,
                "url": req.url,
                "error": result.get("error", "Failed to bypass target challenge"),
                "duration_ms": duration_ms
            }
        )

# ════════════════════════════════════════════
#  3. DISCORD OAUTH2 AUTHENTICATION
# ════════════════════════════════════════════
DISCORD_CLIENT_ID = os.getenv("DISCORD_CLIENT_ID", "")
DISCORD_CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET", "")
BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")
REDIRECT_URI = f"{BASE_URL}/api/auth/discord/callback"

@app.get("/api/auth/discord/login")
async def discord_login():
    if not DISCORD_CLIENT_ID:
        # Demo / Guest mode fallback if client secret not yet configured
        return RedirectResponse("/?guest_login=true")
        
    scope = "identify"
    url = f"https://discord.com/api/oauth2/authorize?client_id={DISCORD_CLIENT_ID}&redirect_uri={REDIRECT_URI}&response_type=code&scope={scope}"
    return RedirectResponse(url)

@app.get("/api/auth/discord/callback")
async def discord_callback(code: str, response: Response):
    data = {
        "client_id": DISCORD_CLIENT_ID,
        "client_secret": DISCORD_CLIENT_SECRET,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    async with aiohttp.ClientSession() as session:
        async with session.post("https://discord.com/api/oauth2/token", data=data, headers=headers) as token_resp:
            if token_resp.status != 200:
                raise HTTPException(status_code=400, detail="Discord OAuth failed to get token.")
            token_json = await token_resp.json()
            access_token = token_json.get("access_token")

        user_headers = {"Authorization": f"Bearer {access_token}"}
        async with session.get("https://discord.com/api/users/@me", headers=user_headers) as user_resp:
            user_data = await user_resp.json()

    user = get_or_create_user(
        discord_id=user_data["id"],
        username=user_data.get("username", "User"),
        avatar=user_data.get("avatar", "") or ""
    )

    redirect = RedirectResponse(url="/", status_code=302)
    redirect.set_cookie(key="xpk_uid", value=str(user["id"]), max_age=86400 * 30)
    return redirect

# ════════════════════════════════════════════
#  4. USER PROFILE & DEMO AUTH
# ════════════════════════════════════════════
@app.get("/api/user/me")
async def get_current_user_profile(request: Request):
    user = get_session_user(request)
    if not user:
        # Default guest / demo profile so frontend works immediately out of the box!
        user = get_or_create_user("demo_guest_95", "RetroPilot95", "")
    
    now = int(time.time())
    timeout_remaining = max(0, (user.get("timeout_until", 0) - now) // 60)
    
    return {
        "id": user["id"],
        "discord_id": user["discord_id"],
        "username": user["username"],
        "api_key": user["api_key"],
        "deposit_ref": user.get("deposit_ref", "XPK-REF"),
        "credits": user["credits"],
        "has_promo": bool(user["has_promo"]),
        "timeout_active": timeout_remaining > 0,
        "timeout_minutes": timeout_remaining,
        "solana_wallet": SOLANA_WALLET,
        "cost_per_request": 0.001
    }

# ════════════════════════════════════════════
#  5. PROMO VERIFICATION, SOLANA & VOUCHERS
# ════════════════════════════════════════════
@app.post("/api/user/promo/verify")
async def claim_promo(request: Request):
    user = get_session_user(request)
    if not user:
        user = get_or_create_user("demo_guest_95", "RetroPilot95", "")
        
    res = await verify_user_promo(user["discord_id"], user["id"])
    return res

@app.post("/api/deposit/verify")
async def verify_deposit(req: DepositVerifyRequest, request: Request):
    user = get_session_user(request)
    if not user:
        user = get_or_create_user("demo_guest_95", "RetroPilot95", "")
        
    res = await verify_solana_deposit(req.tx_hash, user["id"])
    return res

@app.post("/api/voucher/redeem")
async def redeem_voucher_endpoint(req: VoucherRedeemRequest, request: Request):
    user = get_session_user(request)
    if not user:
        user = get_or_create_user("demo_guest_95", "RetroPilot95", "")
        
    res = redeem_voucher(req.code, user["id"])
    return res

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
