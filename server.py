import os
import time
import asyncio
import uuid
import secrets
import aiohttp
from typing import Optional, Any, Dict, List, Union
from collections import deque
from fastapi import FastAPI, Header, Query, HTTPException, Request, Response, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

from core.db import (
    get_user_by_api_key,
    get_user_by_discord_id,
    get_user_by_id,
    get_or_create_user,
    regenerate_user_api_key,
    register_user,
    authenticate_user,
    create_guest_user,
    deduct_credit,
    log_request,
    redeem_voucher,
    get_db,
    apply_daily_credits,
    get_request_cost,
    get_user_plan_meta,
    get_platform_metrics,
    get_user_metrics,
    get_admin_overview,
    admin_adjust_user_credits,
    admin_create_voucher,
    PLANS,
    FREE_DAILY_REQUESTS
)
from engine.unblocker import execute_unblock
from core.promo import verify_user_promo
from core.solana import verify_solana_deposit, SOLANA_WALLET
from core import email_notify

# Worker secret key for GitHub Actions runners to authenticate
WORKER_SECRET = os.getenv("WORKER_SECRET", "xpk-worker-default-secret")
ADMIN_SECRET = os.getenv("ADMIN_SECRET")  # Set ONLY via Railway env var — never hardcoded

# In-memory task queue: pending tasks waiting for a worker
task_queue = deque()
# Completed results keyed by task_id, with asyncio Events for waiting
task_results = {}
task_events = {}
# Active worker nodes registry {worker_id: {last_seen, tasks_completed}}
active_workers = {}
# Concurrency tracking per user {user_id: active_count}
active_user_concurrency = {}

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
    method: Optional[str] = "GET"
    headers: Optional[dict] = None
    body: Optional[Any] = None

class AsyncUnlockRequest(UnlockRequest):
    webhook_url: Optional[str] = None

class RegisterRequest(BaseModel):
    email: str
    username: Optional[str] = None
    password: str

class LoginRequest(BaseModel):
    identity: str
    password: str

class PromoVerifyRequest(BaseModel):
    discord_id: str

class DepositVerifyRequest(BaseModel):
    tx_hash: str
    plan_type: Optional[str] = None

class VoucherRedeemRequest(BaseModel):
    code: str

class AdminCreditAdjustRequest(BaseModel):
    user_id: int
    amount: float

class AdminVoucherCreateRequest(BaseModel):
    code: str
    credits: float

class CaptchaTokenSolveRequest(BaseModel):
    url: str
    type: Optional[str] = "auto"
    sitekey: Optional[str] = None
    proxy: Optional[str] = None

# Async tasks storage: {task_id: {"id": str, "status": str, "created_at": int, "result": dict, "error": str, "webhook_url": str}}
async_tasks = {}

def check_low_credits_and_notify(user_before: dict, fresh_user: Optional[dict]):
    """Send low-credits email warning when user balance drops below threshold."""
    if not fresh_user or not fresh_user.get("email"):
        return
    old_c = float(user_before.get("credits", 0) or 0)
    new_c = float(fresh_user.get("credits", 0) or 0)
    if old_c > email_notify.LOW_CREDITS_THRESHOLD >= new_c:
        asyncio.create_task(email_notify.low_credits_warning(
            to=fresh_user["email"],
            username=fresh_user.get("username", "there"),
            credits_remaining=new_c
        ))

# Synthetic unlimited admin user — returned when ADMIN_SECRET key is used
_ADMIN_USER = {
    "id": 0,
    "username": "admin",
    "email": None,
    "discord_id": None,
    "is_guest": 0,
    "is_admin": 1,
    "credits": 999_999_999.0,
    "plan": "admin",
    "has_deposited": 1,
    "timeout_until": 0,
    "concurrency_limit": 999,
    "deposit_ref": "ADMIN",
    "api_key": "<ADMIN_SECRET>",
}

# Helper to get user from API Key or Web Session
def authenticate_api_key(
    request: Request,
    x_api_key: Optional[str] = Header(None),
    authorization: Optional[str] = Header(None),
    api_key: Optional[str] = Query(None)
):
    key = x_api_key or api_key
    if not key and authorization:
        if authorization.lower().startswith("bearer "):
            key = authorization[7:].strip()
        else:
            key = authorization.strip()

    # Admin key (from Railway env only) — bypasses all limits
    if key and ADMIN_SECRET and key == ADMIN_SECRET:
        return _ADMIN_USER

    user = None
    if key:
        user = get_user_by_api_key(key)
        if not user:
            raise HTTPException(status_code=403, detail="Invalid API Key.")
        # Guest accounts cannot be used for external script automation
        if bool(user.get("is_guest", 0)):
            raise HTTPException(
                status_code=403,
                detail="Guest accounts are restricted to browser testing only. Please register an account to unlock your personal X-API-Key for automation."
            )
    else:
        # Check session cookie from web console
        user = get_session_user(request)
        if not user:
            raise HTTPException(status_code=401, detail="Authentication required. Pass X-API-Key header or sign in.")

    # Check 5-hour timeout restriction
    now = int(time.time())
    if user.get("timeout_until", 0) > now:
        remaining = (user["timeout_until"] - now) // 60
        raise HTTPException(
            status_code=403,
            detail=f"Account restricted! Removed promo link from Discord profile. Timeout active for {remaining} more minutes."
        )

    if user["credits"] < 1.0:
        if bool(user.get("is_guest", 0)):
            raise HTTPException(
                status_code=402,
                detail="Guest trial credits exhausted (5/5 used). Please Sign Up or Log In to get 10 free credits and permanent API access!"
            )
        is_paid = bool(user.get("has_deposited", 0))
        if is_paid:
            raise HTTPException(
                status_code=402,
                detail="Insufficient credits! Your daily $15 bonus has been applied. Top up via Solana USDT for more credits (charged at $0.01/req)."
            )
        raise HTTPException(
            status_code=402,
            detail="Insufficient credits! Free tier: $5 refreshes daily. Top up via Solana USDT to unlock $0.01/req rate and $15 daily bonus."
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

def get_or_create_session_user(request: Request, response: Response):
    """
    Ensures every visitor gets their OWN unique session account.
    Guests receive testing access only (API Key hidden until registration).
    """
    user = get_session_user(request)
    if not user:
        user = create_guest_user()
        response.set_cookie(
            key="xpk_uid",
            value=str(user["id"]),
            max_age=86400 * 365,
            httponly=False,
            samesite="lax"
        )
    return user



# ════════════════════════════════════════════
#  1. WEB INTERFACE (Developer Console)
# ════════════════════════════════════════════
@app.get("/", response_class=HTMLResponse)
async def index():
    html_file = os.path.join(PUBLIC_DIR, "index.html")
    if os.path.exists(html_file):
        with open(html_file, "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>Xploit Unblocker API</h1>"

# ════════════════════════════════════════════
#  2. CORE UNBLOCKER ENDPOINTS ($0.1/req)
# ════════════════════════════════════════════
async def dispatch_to_worker(
    url: str,
    mode: str,
    force_cdp: bool,
    proxy: str = None,
    method: str = "GET",
    headers: dict = None,
    body: Any = None,
    timeout: int = 35
):
    """Push a task onto the queue and wait for a worker to complete it."""
    task_id = str(uuid.uuid4())[:12]
    event = asyncio.Event()
    task_events[task_id] = event
    task_queue.append({
        "task_id": task_id,
        "url": url,
        "mode": mode,
        "force_cdp": force_cdp,
        "proxy": proxy,
        "method": method,
        "headers": headers,
        "body": body,
    })
    try:
        await asyncio.wait_for(event.wait(), timeout=timeout)
    except asyncio.TimeoutError:
        task_events.pop(task_id, None)
        task_results.pop(task_id, None)
        return None
    result = task_results.pop(task_id, None)
    task_events.pop(task_id, None)
    return result

def has_active_workers():
    """Check if any worker node sent a heartbeat in the last 90 seconds."""
    now = time.time()
    # Prune stale workers
    stale = [wid for wid, info in active_workers.items() if now - info["last_seen"] > 90]
    for wid in stale:
        active_workers.pop(wid, None)
    return len(active_workers) > 0

@app.post("/v1/unlock")
async def unlock_endpoint(req: UnlockRequest, user = Depends(authenticate_api_key)):
    user_id = user["id"]
    if float(user.get("credits", 0) or 0) < 1.0:
        raise HTTPException(
            status_code=402,
            detail="Insufficient solve credits. Your plan allocation is exhausted. Please upgrade or top up to continue unlocking."
        )

    plan_meta = get_user_plan_meta(user)
    concurrency_limit = int(user.get("concurrency_limit") or plan_meta.get("concurrency", 3))
    current_active = active_user_concurrency.get(user_id, 0)
    if current_active >= concurrency_limit:
        raise HTTPException(
            status_code=429,
            detail=f"Concurrency limit reached ({current_active}/{concurrency_limit} active slots for {plan_meta['name']} plan). Please wait for active jobs to finish or upgrade plan."
        )

    active_user_concurrency[user_id] = current_active + 1
    start_time = time.time()
    force_cdp = req.force_cdp or (req.mode == "stealth")

    try:
        # If remote workers are online, dispatch heavy CDP tasks to them
        if has_active_workers() and (force_cdp or req.mode in ("stealth", "auto", "cdp")):
            result = await dispatch_to_worker(
                url=req.url,
                mode=req.mode or "auto",
                force_cdp=force_cdp,
                proxy=req.proxy,
                method=req.method or "GET",
                headers=req.headers,
                body=req.body
            )
            if result and result.get("success"):
                duration_ms = int((time.time() - start_time) * 1000)
                cost = get_request_cost(user)
                deduct_credit(user_id, cost)
                fresh_user = get_user_by_id(user_id)
                check_low_credits_and_notify(user, fresh_user)
                credits_remaining = fresh_user["credits"] if fresh_user else (user["credits"] - cost)
                log_request(user_id, req.url, result.get("mode", "worker"), 200, duration_ms, cost)
                return {
                    "success": True,
                    "url": req.url,
                    "mode": result.get("mode", "worker_cdp"),
                    "status_code": 200,
                    "duration_ms": duration_ms,
                    "title": result.get("title", ""),
                    "credits_remaining": credits_remaining,
                    "cf_clearance": result.get("cf_clearance"),
                    "cf_bm": result.get("cf_bm"),
                    "user_agent": result.get("user_agent"),
                    "captcha_detected": result.get("captcha_detected"),
                    "html": result.get("html", ""),
                    "cookies": result.get("cookies", []),
                    "headers": result.get("headers", {}),
                    "worker_node": result.get("worker_id", "unknown")
                }
            elif result and not result.get("success"):
                # Worker returned failure - surface it cleanly
                duration_ms = int((time.time() - start_time) * 1000)
                log_request(user_id, req.url, "worker_failed", 400, duration_ms, 0.0)
                return JSONResponse(status_code=400, content={
                    "success": False,
                    "url": req.url,
                    "error": result.get("error", "Worker failed to bypass challenge"),
                    "duration_ms": duration_ms
                })

        # Fallback: execute locally on this server (fast_tls only - no browser on Railway)
        result = await asyncio.to_thread(
            execute_unblock,
            req.url,
            force_cdp=False,  # Never run local CDP on Railway (no Chrome) - use fast_tls only
            proxy=req.proxy,
            method=req.method or "GET",
            headers=req.headers,
            body=req.body
        )
        duration_ms = int((time.time() - start_time) * 1000)
        status_code = result.get("status_code", 200)

        if result.get("success"):
            cost = get_request_cost(user)
            deduct_credit(user_id, cost)
            fresh_user = get_user_by_id(user_id)
            check_low_credits_and_notify(user, fresh_user)
            credits_remaining = fresh_user["credits"] if fresh_user else (user["credits"] - cost)
            log_request(user_id, req.url, result.get("mode", "auto"), status_code, duration_ms, cost)
            return {
                "success": True,
                "url": req.url,
                "mode": result.get("mode"),
                "status_code": status_code,
                "duration_ms": duration_ms,
                "title": result.get("title", ""),
                "credits_remaining": credits_remaining,
                "cf_clearance": result.get("cf_clearance"),
                "cf_bm": result.get("cf_bm"),
                "user_agent": result.get("user_agent"),
                "captcha_detected": result.get("captcha_detected"),
                "html": result.get("html", ""),
                "cookies": result.get("cookies", []),
                "headers": result.get("headers", {})
            }
        elif result.get("needs_cdp") and has_active_workers():
            # Fast-TLS escalation needed but worker dispatch missed - re-try via worker
            result2 = await dispatch_to_worker(
                url=req.url,
                mode="cdp",
                force_cdp=True,
                proxy=req.proxy,
                method=req.method or "GET",
                headers=req.headers,
                body=req.body
            )
            if result2 and result2.get("success"):
                cost = get_request_cost(user)
                deduct_credit(user_id, cost)
                fresh_user = get_user_by_id(user_id)
                check_low_credits_and_notify(user, fresh_user)
                credits_remaining = fresh_user["credits"] if fresh_user else (user["credits"] - cost)
                log_request(user_id, req.url, "worker_cdp_escalated", 200, duration_ms, cost)
                return {
                    "success": True,
                    "url": req.url,
                    "mode": "worker_cdp_escalated",
                    "status_code": 200,
                    "duration_ms": int((time.time() - start_time) * 1000),
                    "title": result2.get("title", ""),
                    "credits_remaining": credits_remaining,
                    "cf_clearance": result2.get("cf_clearance"),
                    "cf_bm": result2.get("cf_bm"),
                    "user_agent": result2.get("user_agent"),
                    "captcha_detected": result2.get("captcha_detected"),
                    "html": result2.get("html", ""),
                    "cookies": result2.get("cookies", []),
                    "headers": result2.get("headers", {}),
                    "worker_node": result2.get("worker_id", "unknown")
                }

        # All tiers exhausted - return failure without charging
        log_request(user_id, req.url, result.get("mode", "failed"), status_code, duration_ms, 0.0)
        return JSONResponse(
            status_code=400,
            content={
                "success": False,
                "url": req.url,
                "error": result.get("error", "Failed to bypass target challenge"),
                "duration_ms": duration_ms
            }
        )
    except Exception as exc:
        duration_ms = int((time.time() - start_time) * 1000)
        print(f"[UNLOCK] Unhandled exception for {req.url}: {exc}")
        return JSONResponse(
            status_code=503,
            content={
                "success": False,
                "url": req.url,
                "error": f"Server error: {str(exc)}",
                "duration_ms": duration_ms,
                "hint": "CDP mode requires an active GitHub Actions worker. Check /api/workers/status"
            }
        )
    finally:
        active_user_concurrency[user_id] = max(0, active_user_concurrency.get(user_id, 1) - 1)

# ════════════════════════════════════════════
#  2.1 DIRECT CAPTCHA TOKEN SOLVER ENDPOINT
# ════════════════════════════════════════════
@app.post("/api/captcha/solve")
@app.post("/api/v1/solve")
async def solve_captcha_token_endpoint(
    req: CaptchaTokenSolveRequest,
    user: dict = Depends(authenticate_api_key)
):
    """
    Dedicated Captcha Token Solver API (CapSolver / 2Captcha alternative).
    Solves Cloudflare Turnstile, hCaptcha, and reCAPTCHA, and returns the verified token string.
    """
    user_id = user["id"]
    start_time = time.time()

    # Rate & timeout restrictions
    now = int(time.time())
    if user.get("timeout_until", 0) > now:
        remaining = (user["timeout_until"] - now) // 60
        raise HTTPException(status_code=403, detail=f"Account restricted. Timeout active for {remaining}m.")

    if user["credits"] < 1.0:
        raise HTTPException(status_code=402, detail="Insufficient credits. Top up or redeem a voucher.")

    result = None
    if has_active_workers():
        result = await dispatch_to_worker(
            url=req.url,
            mode="cdp",
            force_cdp=True,
            proxy=req.proxy,
            timeout=35
        )

    if not result or not result.get("success"):
        # Local fallback execution (run fast_tls - never run force_cdp on Railway container without display)
        result = await asyncio.to_thread(
            execute_unblock,
            req.url,
            force_cdp=False,
            proxy=req.proxy
        )

    duration_ms = int((time.time() - start_time) * 1000)
    if result and result.get("success"):
        cost = get_request_cost(user)
        deduct_credit(user_id, cost)
        fresh_user = get_user_by_id(user_id)
        check_low_credits_and_notify(user, fresh_user)
        credits_remaining = fresh_user["credits"] if fresh_user else (user["credits"] - cost)
        log_request(user_id, req.url, "token_solve", 200, duration_ms, cost)
        token = result.get("captcha_token") or result.get("token") or result.get("cf_clearance") or ""
        return {
            "success": True,
            "url": req.url,
            "captcha_type": result.get("captcha_detected") or req.type or "Turnstile",
            "token": token,
            "cf_clearance": result.get("cf_clearance"),
            "user_agent": result.get("user_agent"),
            "duration_ms": duration_ms,
            "credits_remaining": credits_remaining
        }
    else:
        log_request(user_id, req.url, "token_solve_failed", 400, duration_ms, 0.0)
        return JSONResponse(status_code=400, content={
            "success": False,
            "url": req.url,
            "error": result.get("error", "Failed to solve captcha challenge"),
            "duration_ms": duration_ms
        })

# ── Background Task Runner for Async Scrapes ───────────
async def process_async_task(task_id: str, req: AsyncUnlockRequest, user_id: int):
    """Processes an async unblock task in the background, updates status, and triggers webhook."""
    async_tasks[task_id]["status"] = "processing"
    start_time = time.time()
    force_cdp = req.force_cdp or (req.mode == "stealth")

    try:
        result = None
        # Try worker dispatch first if available
        if has_active_workers() and (force_cdp or req.mode in ("stealth", "auto")):
            result = await dispatch_to_worker(
                url=req.url,
                mode=req.mode or "auto",
                force_cdp=force_cdp,
                proxy=req.proxy,
                method=req.method or "GET",
                headers=req.headers,
                body=req.body,
                timeout=60
            )

        # Fallback to local execution (fast_tls only on server)
        if not result:
            result = await asyncio.to_thread(
                execute_unblock,
                req.url,
                force_cdp=False,  # Railway environment has no Chrome
                proxy=req.proxy,
                method=req.method or "GET",
                headers=req.headers,
                body=req.body
            )

        duration_ms = int((time.time() - start_time) * 1000)
        if result and result.get("success"):
            user_obj = get_user_by_id(user_id) or {"has_deposited": 0}
            cost = get_request_cost(user_obj)
            deduct_credit(user_id, cost)
            log_request(user_id, req.url, result.get("mode", "async"), 200, duration_ms, cost)
            async_tasks[task_id].update({
                "status": "completed",
                "completed_at": int(time.time()),
                "duration_ms": duration_ms,
                "result": {
                    "success": True,
                    "url": req.url,
                    "mode": result.get("mode"),
                    "title": result.get("title", ""),
                    "status_code": result.get("status_code", 200),
                    "cf_clearance": result.get("cf_clearance"),
                    "cf_bm": result.get("cf_bm"),
                    "user_agent": result.get("user_agent"),
                    "captcha_detected": result.get("captcha_detected"),
                    "cookies": result.get("cookies", []),
                    "headers": result.get("headers", {}),
                    "html": result.get("html", "")
                }
            })
        else:
            async_tasks[task_id].update({
                "status": "failed",
                "completed_at": int(time.time()),
                "duration_ms": duration_ms,
                "error": result.get("error", "Challenge resolution timed out or blocked") if result else "Execution failed"
            })
    except Exception as e:
        async_tasks[task_id].update({
            "status": "failed",
            "completed_at": int(time.time()),
            "error": str(e)
        })

    # Webhook Callback if provided
    if req.webhook_url:
        try:
            async with aiohttp.ClientSession() as session:
                payload = {
                    "task_id": task_id,
                    "status": async_tasks[task_id]["status"],
                    "data": async_tasks[task_id].get("result") or {"error": async_tasks[task_id].get("error")}
                }
                await session.post(req.webhook_url, json=payload, timeout=10)
        except Exception as wh_err:
            print(f"[ASYNC] Webhook callback failed for {task_id}: {wh_err}")

@app.post("/v1/unlock/async", status_code=202)
async def unlock_async_endpoint(req: AsyncUnlockRequest, user = Depends(authenticate_api_key)):
    """
    Submits an unblock job asynchronously.
    Returns task_id immediately. Client can poll /v1/tasks/{task_id} or receive webhook POST.
    """
    task_id = f"task_{uuid.uuid4().hex[:16]}"
    async_tasks[task_id] = {
        "task_id": task_id,
        "user_id": user["id"],
        "url": req.url,
        "mode": req.mode,
        "status": "queued",
        "created_at": int(time.time()),
        "webhook_url": req.webhook_url,
        "result": None,
        "error": None
    }

    # Launch background worker
    asyncio.create_task(process_async_task(task_id, req, user["id"]))

    return {
        "success": True,
        "task_id": task_id,
        "status": "queued",
        "poll_url": f"/v1/tasks/{task_id}",
        "webhook_url": req.webhook_url
    }

@app.get("/v1/tasks/{task_id}")
async def get_task_status(task_id: str):
    """Poll status of an asynchronous unblock job."""
    task = async_tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found or expired.")
    return task

@app.get("/v1/tasks")
async def list_recent_tasks():
    """Returns the most recent 25 async tasks in reverse chronological order."""
    sorted_tasks = sorted(
        [
            {
                "task_id": t["task_id"],
                "url": t["url"],
                "status": t["status"],
                "created_at": t["created_at"],
                "completed_at": t.get("completed_at")
            }
            for t in async_tasks.values()
        ],
        key=lambda x: x["created_at"],
        reverse=True
    )
    return {"tasks": sorted_tasks[:25]}


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
    # Match guest cookie expiry (365 days) so real user session persists properly
    redirect.set_cookie(
        key="xpk_uid",
        value=str(user["id"]),
        max_age=86400 * 365,
        httponly=False,
        samesite="lax"
    )
    return redirect

# ════════════════════════════════════════════
#  4. USER PROFILE & AUTHENTICATION
# ════════════════════════════════════════════
@app.get("/api/user/me")
async def get_current_user_profile(request: Request, response: Response):
    user = get_or_create_session_user(request, response)
    # Apply daily credit refresh (idempotent — only fires once per UTC day)
    if not bool(user.get("is_guest", 0)):
        user = apply_daily_credits(user["id"]) or user
    now = int(time.time())
    timeout_remaining = max(0, (user.get("timeout_until", 0) - now) // 60)
    is_guest = bool(user.get("is_guest", 0))
    plan_meta = get_user_plan_meta(user)
    plan_key = "guest" if is_guest else plan_meta["id"]
    concurrency_limit = 1 if is_guest else (user.get("concurrency_limit") or plan_meta.get("concurrency", 3))

    # Seconds until next UTC midnight
    next_reset_in = 86400 - (now % 86400)

    return {
        "id": user["id"],
        "discord_id": user.get("discord_id"),
        "username": user["username"],
        "email": user.get("email"),
        "is_guest": is_guest,
        "tier": plan_key,
        "plan_name": plan_meta["name"],
        "concurrency_limit": concurrency_limit,
        "overage_rate": plan_meta.get("overage_rate", 0.0),
        "included_credits": plan_meta.get("included_credits", 75),
        "plan_expires_at": user.get("plan_expires_at", 0),
        # GUEST PROTECTION: Never reveal key until registered
        "api_key": "" if is_guest else user["api_key"],
        "deposit_ref": "" if is_guest else user.get("deposit_ref", "XPK-REF"),
        "credits": user["credits"],
        "has_promo": bool(user["has_promo"]),
        "timeout_active": timeout_remaining > 0,
        "timeout_minutes": timeout_remaining,
        "solana_wallet": SOLANA_WALLET,
        "cost_per_request": 1.0,
        "daily_refresh": FREE_DAILY_REQUESTS if plan_key == "free" else 0,
        "next_reset_in_seconds": next_reset_in,
    }

@app.post("/api/auth/register")
async def auth_register(req: RegisterRequest, response: Response):
    """Register a new user account with email and password."""
    res = register_user(req.email, req.username or "", req.password)
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("error"))
    user = res["user"]
    response.set_cookie(key="xpk_uid", value=str(user["id"]), max_age=86400 * 365, httponly=False, samesite="lax")
    if user.get("email"):
        asyncio.create_task(email_notify.welcome_email(
            to=user["email"],
            username=user.get("username", "there"),
            api_key=user.get("api_key", ""),
            credits=float(user.get("credits", 75))
        ))
    return {
        "success": True,
        "message": f"Welcome aboard, {user['username']}! Your account and API key are now active.",
        "user": {
            "id": user["id"],
            "username": user["username"],
            "email": user["email"],
            "api_key": user["api_key"],
            "credits": user["credits"]
        }
    }

@app.post("/api/auth/login")
async def auth_login(req: LoginRequest, response: Response):
    """Authenticate existing user with email/username and password."""
    res = authenticate_user(req.identity, req.password)
    if not res.get("success"):
        raise HTTPException(status_code=401, detail=res.get("error"))
    user = res["user"]
    response.set_cookie(key="xpk_uid", value=str(user["id"]), max_age=86400 * 365, httponly=False, samesite="lax")
    return {
        "success": True,
        "message": f"Welcome back, {user['username']}!",
        "user": {
            "id": user["id"],
            "username": user["username"],
            "email": user.get("email"),
            "api_key": user["api_key"],
            "credits": user["credits"]
        }
    }

@app.post("/api/auth/logout")
async def auth_logout(response: Response):
    """Log out current session and create fresh guest tester."""
    response.delete_cookie("xpk_uid")
    return {"success": True, "message": "Signed out successfully."}

@app.get("/login", response_class=HTMLResponse)
@app.get("/register", response_class=HTMLResponse)
async def auth_html_page():
    auth_file = os.path.join(PUBLIC_DIR, "auth.html")
    if os.path.exists(auth_file):
        with open(auth_file, "r", encoding="utf-8") as f:
            return f.read()
    return RedirectResponse("/")

@app.post("/api/user/regenerate-key")
async def regenerate_api_key_endpoint(request: Request, response: Response):
    user = get_or_create_session_user(request, response)
    if bool(user.get("is_guest", 0)):
        raise HTTPException(status_code=403, detail="Please sign in or register to manage API keys.")
    new_key = regenerate_user_api_key(user["id"])
    return {
        "success": True,
        "api_key": new_key,
        "message": "New API Key generated and committed to database."
    }

@app.get("/api/user/my-key")
async def get_my_api_key(request: Request, response: Response):
    """Returns the real API key for the currently logged-in session user (for debugging key mismatch)."""
    user = get_or_create_session_user(request, response)
    is_guest = bool(user.get("is_guest", 0))
    if is_guest:
        return {
            "is_guest": True,
            "user_id": user["id"],
            "username": user["username"],
            "message": "You are on a guest session. Log in with Discord or register to get your permanent API key.",
            "api_key": None
        }
    return {
        "is_guest": False,
        "user_id": user["id"],
        "username": user["username"],
        "api_key": user["api_key"],
        "credits": user["credits"]
    }

@app.get("/plans", response_class=HTMLResponse)
@app.get("/plans/", response_class=HTMLResponse)
@app.get("/pricing", response_class=HTMLResponse)
async def plans_html_page():
    plans_file = os.path.join(PUBLIC_DIR, "plans.html")
    if os.path.exists(plans_file):
        with open(plans_file, "r", encoding="utf-8") as f:
            return f.read()
    return RedirectResponse("/")

@app.get("/guide", response_class=HTMLResponse)
@app.get("/guide/", response_class=HTMLResponse)
@app.get("/docs", response_class=HTMLResponse)
@app.get("/developer/api-key/guide", response_class=HTMLResponse)
async def guide_html_page():
    guide_file = os.path.join(PUBLIC_DIR, "guide.html")
    if os.path.exists(guide_file):
        with open(guide_file, "r", encoding="utf-8") as f:
            return f.read()
    return RedirectResponse("/")

@app.get("/status", response_class=HTMLResponse)
@app.get("/status/", response_class=HTMLResponse)
async def status_html_page():
    f = os.path.join(PUBLIC_DIR, "status.html")
    return open(f, "r", encoding="utf-8").read() if os.path.exists(f) else RedirectResponse("/")

@app.get("/legal", response_class=HTMLResponse)
@app.get("/legal/", response_class=HTMLResponse)
@app.get("/privacy", response_class=HTMLResponse)
@app.get("/terms", response_class=HTMLResponse)
async def legal_html_page():
    f = os.path.join(PUBLIC_DIR, "legal.html")
    return open(f, "r", encoding="utf-8").read() if os.path.exists(f) else RedirectResponse("/")

@app.get("/404", response_class=HTMLResponse)
async def not_found_page():
    f = os.path.join(PUBLIC_DIR, "404.html")
    return open(f, "r", encoding="utf-8").read() if os.path.exists(f) else RedirectResponse("/")

@app.exception_handler(404)
async def custom_404_handler(request: Request, exc):
    f = os.path.join(PUBLIC_DIR, "404.html")
    if os.path.exists(f):
        content = open(f, "r", encoding="utf-8").read()
        return HTMLResponse(content=content, status_code=404)
    return HTMLResponse(content="<h1>404 Not Found</h1>", status_code=404)

@app.get("/favicon.ico", include_in_schema=False)
@app.get("/favicon.svg", include_in_schema=False)
async def favicon_route():
    f = os.path.join(PUBLIC_DIR, "favicon.svg")
    if os.path.exists(f):
        return FileResponse(f, media_type="image/svg+xml")
    raise HTTPException(status_code=404)



# ════════════════════════════════════════════
#  5. PROMO VERIFICATION, SOLANA & VOUCHERS
# ════════════════════════════════════════════

@app.post("/api/user/promo/verify")
async def claim_promo(request: Request, response: Response):
    user = get_or_create_session_user(request, response)
    if not user.get("discord_id"):
        return {"success": False, "message": "Promo verification is only available for Discord-linked accounts."}
    res = await verify_user_promo(user["discord_id"], user["id"])
    return res

@app.post("/api/deposit/verify")
async def verify_deposit(req: DepositVerifyRequest, request: Request, response: Response):
    user = get_or_create_session_user(request, response)
    if bool(user.get("is_guest", 0)):
        raise HTTPException(status_code=403, detail="Please sign in or register an account to verify deposits.")
    res = await verify_solana_deposit(req.tx_hash, user["id"], plan_type=req.plan_type)
    # Send email notification on successful deposit
    if res.get("success") and user.get("email"):
        asyncio.create_task(email_notify.deposit_confirmed(
            to=user["email"],
            username=user.get("username", "there"),
            amount_usdt=res.get("amount_usdt", 0),
            credits_added=res.get("credits_added", 0),
            new_balance=res.get("new_balance", 0),
            tx_hash=req.tx_hash,
        ))
    return res

@app.post("/api/voucher/redeem")
async def redeem_voucher_endpoint(req: VoucherRedeemRequest, request: Request, response: Response):
    user = get_or_create_session_user(request, response)
    if bool(user.get("is_guest", 0)):
        raise HTTPException(status_code=403, detail="Please sign in or register an account to redeem vouchers.")
    res = redeem_voucher(req.code, user["id"])
    return res

@app.get("/api/analytics/metrics")
async def platform_analytics_metrics(days: int = 7):
    """Public platform metrics: total requests, success rates, latency, trends."""
    # Bound days between 1 and 30
    days = max(1, min(30, days))
    metrics = get_platform_metrics(days=days)
    return {
        "success": True,
        "metrics": metrics
    }

@app.get("/api/user/analytics")
async def user_personal_analytics(request: Request, response: Response):
    """Personal analytics and request history for current authenticated user."""
    user = get_or_create_session_user(request, response)
    metrics = get_user_metrics(user["id"])
    return {
        "success": True,
        "user_id": user["id"],
        "metrics": metrics
    }

# ════════════════════════════════════════════
#  5.5 ADMIN CONTROL PANEL & ENDPOINTS
# ════════════════════════════════════════════

def verify_admin_key(
    x_admin_key: Optional[str] = Header(None),
    admin_key: Optional[str] = Query(None)
):
    key = x_admin_key or admin_key
    if not key or key != ADMIN_SECRET:
        raise HTTPException(status_code=403, detail="Unauthorized: Invalid admin secret key.")
    return True

@app.get("/admin", response_class=HTMLResponse)
@app.get("/admin/", response_class=HTMLResponse)
async def admin_html_page():
    admin_file = os.path.join(PUBLIC_DIR, "admin.html")
    if os.path.exists(admin_file):
        with open(admin_file, "r", encoding="utf-8") as f:
            return f.read()
    return RedirectResponse("/")

@app.get("/api/admin/overview")
async def admin_overview_api(
    x_admin_key: Optional[str] = Header(None),
    key: Optional[str] = Query(None)
):
    verify_admin_key(x_admin_key, key)
    data = get_admin_overview()
    now = time.time()
    active_worker_count = len([w for w in active_workers.values() if now - w.get("last_seen", 0) < 60])
    data["stats"]["active_solvers"] = active_worker_count
    return {"success": True, "data": data}

@app.post("/api/admin/users/credits")
async def admin_adjust_user_credits_api(
    req: AdminCreditAdjustRequest,
    x_admin_key: Optional[str] = Header(None),
    key: Optional[str] = Query(None)
):
    verify_admin_key(x_admin_key, key)
    res = admin_adjust_user_credits(req.user_id, req.amount)
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("error"))
    return res

@app.post("/api/admin/vouchers/create")
async def admin_create_voucher_api(
    req: AdminVoucherCreateRequest,
    x_admin_key: Optional[str] = Header(None),
    key: Optional[str] = Query(None)
):
    verify_admin_key(x_admin_key, key)
    res = admin_create_voucher(req.code, req.credits)
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("error"))
    return res


# ════════════════════════════════════════════
#  6. GITHUB ACTIONS WORKER NODE ENDPOINTS
#     Workers long-poll for tasks, submit
#     results, and send heartbeats.
# ════════════════════════════════════════════

def verify_worker_auth(x_worker_secret: Optional[str] = Header(None)):
    """Authenticate worker nodes via shared secret."""
    if not x_worker_secret or x_worker_secret != WORKER_SECRET:
        raise HTTPException(status_code=403, detail="Invalid worker secret.")
    return True

@app.post("/api/worker/heartbeat")
async def worker_heartbeat(request: Request, _auth = Depends(verify_worker_auth)):
    """Worker sends heartbeat every 30s to stay in the active pool."""
    body = await request.json()
    worker_id = body.get("worker_id", "unknown")
    active_workers[worker_id] = {
        "last_seen": time.time(),
        "tasks_completed": body.get("tasks_completed", 0),
    }
    return {"status": "ok", "registered": True, "queue_depth": len(task_queue)}

@app.get("/api/worker/poll")
async def worker_poll_task(_auth = Depends(verify_worker_auth)):
    """Worker long-polls for a task. Returns a task or empty after 25s."""
    deadline = time.time() + 25
    while time.time() < deadline:
        if task_queue:
            task = task_queue.popleft()
            return {"task": task}
        await asyncio.sleep(0.5)
    return {"task": None}

class WorkerResultPayload(BaseModel):
    task_id: str
    worker_id: Optional[str] = "unknown"
    success: bool
    mode: Optional[str] = "worker_cdp"
    title: Optional[str] = ""
    html: Optional[str] = ""
    cookies: Optional[list] = []
    headers: Optional[dict] = {}
    cf_clearance: Optional[str] = None
    cf_bm: Optional[str] = None
    captcha_token: Optional[str] = None
    token: Optional[str] = None
    user_agent: Optional[str] = None
    captcha_detected: Optional[Any] = None
    duration_ms: Optional[int] = 0
    status_code: Optional[int] = 200
    error: Optional[str] = None

@app.post("/api/worker/result")
async def worker_submit_result(payload: WorkerResultPayload, _auth = Depends(verify_worker_auth)):
    """Worker submits completed task result."""
    task_id = payload.task_id
    task_results[task_id] = payload.dict()
    event = task_events.get(task_id)
    if event:
        event.set()
    return {"status": "accepted", "task_id": task_id}

@app.get("/api/workers/status")
async def get_workers_status():
    """Public endpoint: shows how many worker nodes are online."""
    now = time.time()
    online = {wid: info for wid, info in active_workers.items() if now - info["last_seen"] < 90}
    return {
        "workers_online": len(online),
        "queue_depth": len(task_queue),
        "nodes": [
            {"id": wid, "tasks_completed": info["tasks_completed"], "last_seen_ago": int(now - info["last_seen"])}
            for wid, info in online.items()
        ]
    }

@app.get("/api/proxies/status")
async def get_proxies_status_endpoint():
    """Returns proxy pool configuration and health stats."""
    from engine.proxies import get_proxy_stats
    return get_proxy_stats()

# ════════════════════════════════════════════
#  7. PUBLIC ANALYTICS METRICS (for hero stats & status page)
# ════════════════════════════════════════════
@app.get("/api/analytics/metrics")
async def public_metrics():
    """Public metrics endpoint for frontend hero numbers and status page live data."""
    now = time.time()
    online_workers = [w for w in active_workers.values() if now - w.get("last_seen", 0) < 90]
    metrics = get_platform_metrics()
    total_completed = sum(w.get("tasks_completed", 0) for w in online_workers)
    return {
        "success": True,
        "workers_online": len(online_workers),
        "queue_depth": len(task_queue),
        "total_requests": metrics.get("total_requests", 0),
        "success_rate_percent": metrics.get("success_rate_percent", 100.0),
        "registered_users": metrics.get("total_registered_users", 0),
        "avg_latency_ms": metrics.get("avg_duration_ms", 0),
        "cost_per_solve_usd": 0.01,
        "credits_per_usdt": 100,
        "free_daily_credits": 75,
        "status": "operational" if len(online_workers) > 0 else "degraded"
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)

