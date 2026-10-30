import os
import time
import asyncio
import uuid
import secrets
import aiohttp
from typing import Optional, Any, Dict, List, Union
from collections import deque
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
    regenerate_user_api_key,
    deduct_credit,
    log_request,
    redeem_voucher,
    get_db
)
from engine.unblocker import execute_unblock
from core.promo import verify_user_promo
from core.solana import verify_solana_deposit, SOLANA_WALLET

# Worker secret key for GitHub Actions runners to authenticate
WORKER_SECRET = os.getenv("WORKER_SECRET", "xpk-worker-default-secret")

# In-memory task queue: pending tasks waiting for a worker
task_queue = deque()
# Completed results keyed by task_id, with asyncio Events for waiting
task_results = {}
task_events = {}
# Active worker nodes registry {worker_id: {last_seen, tasks_completed}}
active_workers = {}

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

class PromoVerifyRequest(BaseModel):
    discord_id: str

class DepositVerifyRequest(BaseModel):
    tx_hash: str

class VoucherRedeemRequest(BaseModel):
    code: str

# Async tasks storage: {task_id: {"id": str, "status": str, "created_at": int, "result": dict, "error": str, "webhook_url": str}}
async_tasks = {}

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

def get_or_create_session_user(request: Request, response: Response):
    """
    Ensures every visitor gets their OWN unique database record,
    unique API key, unique Solana deposit memo reference, and 10 credits.
    """
    user = get_session_user(request)
    if not user:
        anon_id = f"guest_{secrets.token_hex(6)}"
        anon_name = f"Operator-{secrets.token_hex(2).upper()}"
        user = get_or_create_user(anon_id, anon_name, "")
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
#  2. CORE UNBLOCKER ENDPOINTS ($0.001/req)
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
    start_time = time.time()
    force_cdp = req.force_cdp or (req.mode == "stealth")

    # If remote workers are online, dispatch heavy CDP tasks to them
    if has_active_workers() and (force_cdp or req.mode in ("stealth", "auto")):
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
            deduct_credit(user["id"], 1.0)
            log_request(user["id"], req.url, result.get("mode", "worker"), 200, duration_ms, 0.001)
            return {
                "success": True,
                "url": req.url,
                "mode": result.get("mode", "worker_cdp"),
                "status_code": 200,
                "duration_ms": duration_ms,
                "title": result.get("title", ""),
                "credits_remaining": user["credits"] - 1.0,
                "html": result.get("html", ""),
                "cookies": result.get("cookies", []),
                "headers": result.get("headers", {}),
                "worker_node": result.get("worker_id", "unknown")
            }

    # Fallback: execute locally on this server
    result = execute_unblock(
        url=req.url,
        force_cdp=force_cdp,
        proxy=req.proxy,
        method=req.method or "GET",
        headers=req.headers,
        body=req.body
    )
    duration_ms = int((time.time() - start_time) * 1000)
    status_code = result.get("status_code", 200)
    
    if result.get("success"):
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
            "cookies": result.get("cookies", []),
            "headers": result.get("headers", {})
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

        # Fallback to local execution
        if not result:
            result = await asyncio.to_thread(
                execute_unblock,
                req.url,
                force_cdp=force_cdp,
                proxy=req.proxy,
                method=req.method or "GET",
                headers=req.headers,
                body=req.body
            )

        duration_ms = int((time.time() - start_time) * 1000)
        if result and result.get("success"):
            deduct_credit(user_id, 1.0)
            log_request(user_id, req.url, result.get("mode", "async"), 200, duration_ms, 0.001)
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
    redirect.set_cookie(key="xpk_uid", value=str(user["id"]), max_age=86400 * 30)
    return redirect

# ════════════════════════════════════════════
#  4. USER PROFILE & AUTH
# ════════════════════════════════════════════
@app.get("/api/user/me")
async def get_current_user_profile(request: Request, response: Response):
    user = get_or_create_session_user(request, response)
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

@app.post("/api/user/regenerate-key")
async def regenerate_api_key_endpoint(request: Request, response: Response):
    user = get_or_create_session_user(request, response)
    new_key = regenerate_user_api_key(user["id"])
    return {
        "success": True,
        "api_key": new_key,
        "message": "New API Key generated and committed to database."
    }

@app.get("/developer/api-key/guide", response_class=HTMLResponse)
async def developer_api_key_guide_page():
    guide_file = os.path.join(PUBLIC_DIR, "guide.html")
    if os.path.exists(guide_file):
        with open(guide_file, "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>Developer API Key Guide</h1><p>Guide file not found.</p>"

# ════════════════════════════════════════════
#  5. PROMO VERIFICATION, SOLANA & VOUCHERS
# ════════════════════════════════════════════
@app.post("/api/user/promo/verify")
async def claim_promo(request: Request, response: Response):
    user = get_or_create_session_user(request, response)
    res = await verify_user_promo(user["discord_id"], user["id"])
    return res

@app.post("/api/deposit/verify")
async def verify_deposit(req: DepositVerifyRequest, request: Request, response: Response):
    user = get_or_create_session_user(request, response)
    res = await verify_solana_deposit(req.tx_hash, user["id"])
    return res

@app.post("/api/voucher/redeem")
async def redeem_voucher_endpoint(req: VoucherRedeemRequest, request: Request, response: Response):
    user = get_or_create_session_user(request, response)
    res = redeem_voucher(req.code, user["id"])
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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)

