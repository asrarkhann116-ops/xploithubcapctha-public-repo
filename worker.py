"""
Xploit Unblocker — GitHub Actions Worker Node
Connects to the Railway hub, long-polls for scrape tasks,
executes them locally with SeleniumBase CDP, and posts results back.
"""
import os
import sys
import time
import json
import uuid
import threading
import requests

# Ensure UTF-8 output
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

HUB_URL = os.getenv("HUB_URL", "http://localhost:8000")
WORKER_SECRET = os.getenv("WORKER_SECRET", "xpk-worker-default-secret")
WORKER_ID = os.getenv("WORKER_ID", f"gh-{uuid.uuid4().hex[:8]}")
DURATION_MINUTES = int(os.getenv("DURATION_MINUTES", "350"))

HEADERS = {
    "X-Worker-Secret": WORKER_SECRET,
    "Content-Type": "application/json"
}

tasks_completed = 0

# ── Heartbeat Thread ──────────────────────────
def heartbeat_loop():
    """Send heartbeat every 30 seconds so the hub knows we're alive."""
    global tasks_completed
    while True:
        try:
            resp = requests.post(
                f"{HUB_URL}/api/worker/heartbeat",
                headers=HEADERS,
                json={"worker_id": WORKER_ID, "tasks_completed": tasks_completed},
                timeout=10
            )
            data = resp.json()
            queue_depth = data.get("queue_depth", 0)
            print(f"[HEARTBEAT] OK | Queue: {queue_depth} | Completed: {tasks_completed}")
        except Exception as e:
            print(f"[HEARTBEAT] Failed: {e}")
        time.sleep(30)


# ── CDP Bypass Engine ─────────────────────────
def execute_cdp_bypass(url, force_cdp=False, proxy=None):
    """
    Run the full dual-tier bypass locally.
    Tier 1: Fast TLS via curl_cffi
    Tier 2: SeleniumBase CDP stealth mode
    """
    import re

    # Tier 1: Fast TLS attempt (unless forced CDP)
    if not force_cdp:
        try:
            from curl_cffi import requests as cffi_requests
            start = time.time()
            response = cffi_requests.get(
                url, impersonate="chrome130", timeout=15,
                headers={
                    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9",
                    "DNT": "1",
                    "Upgrade-Insecure-Requests": "1"
                }
            )
            text = response.text
            duration = int((time.time() - start) * 1000)

            is_challenge = (
                "cf-turnstile" in text or
                "Just a moment..." in text or
                ("ray ID" in text.lower() and response.status_code == 403)
            )
            if not is_challenge:
                title_m = re.search(r"<title>(.*?)</title>", text, re.IGNORECASE)
                title = title_m.group(1).strip() if title_m else ""
                return {
                    "success": True,
                    "mode": "worker_fast_tls",
                    "title": title,
                    "html": text,
                    "cookies": [],
                    "duration_ms": duration,
                }
            print(f"[FAST-TLS] Challenge detected, escalating to CDP...")
        except Exception as e:
            print(f"[FAST-TLS] Skipped: {e}")

    # Tier 2: SeleniumBase CDP
    from seleniumbase import SB
    start = time.time()
    try:
        with SB(uc=True, test=True, headed=False) as sb:
            sb.activate_cdp_mode()
            sb.open(url)
            sb.sleep(2)
            try:
                sb.uc_gui_click_captcha()
                sb.sleep(1.5)
            except Exception:
                pass
            for _ in range(12):
                title = sb.get_title()
                if "Just a moment" not in title and "Attention Required" not in title:
                    break
                sb.sleep(1.5)

            html = sb.get_page_source()
            title = sb.get_title()
            cookies = sb.get_cookies()
            duration = int((time.time() - start) * 1000)
            return {
                "success": True,
                "mode": "worker_cdp",
                "title": title,
                "html": html,
                "cookies": cookies,
                "duration_ms": duration,
            }
    except Exception as e:
        duration = int((time.time() - start) * 1000)
        return {
            "success": False,
            "mode": "worker_cdp",
            "error": str(e),
            "duration_ms": duration,
        }


# ── Main Worker Loop ──────────────────────────
def main():
    global tasks_completed

    print("=" * 56)
    print("  XPLOIT UNBLOCKER — GITHUB ACTIONS WORKER NODE")
    print("=" * 56)
    print(f"  Worker ID   : {WORKER_ID}")
    print(f"  Hub URL     : {HUB_URL}")
    print(f"  Duration    : {DURATION_MINUTES} minutes")
    print("=" * 56)

    # Start heartbeat thread
    hb_thread = threading.Thread(target=heartbeat_loop, daemon=True)
    hb_thread.start()

    # Send initial registration heartbeat
    try:
        requests.post(
            f"{HUB_URL}/api/worker/heartbeat",
            headers=HEADERS,
            json={"worker_id": WORKER_ID, "tasks_completed": 0},
            timeout=10
        )
        print("[INIT] Registered with hub successfully.")
    except Exception as e:
        print(f"[INIT] Warning: Could not reach hub: {e}")

    deadline = time.time() + (DURATION_MINUTES * 60)

    while time.time() < deadline:
        remaining = int((deadline - time.time()) / 60)
        print(f"[POLL] Waiting for task... ({remaining} min remaining)")

        try:
            resp = requests.get(
                f"{HUB_URL}/api/worker/poll",
                headers=HEADERS,
                timeout=30
            )
            data = resp.json()
            task = data.get("task")

            if not task:
                continue

            task_id = task["task_id"]
            url = task["url"]
            force_cdp = task.get("force_cdp", False)
            proxy = task.get("proxy")
            print(f"[TASK] Received {task_id}: {url}")

            # Execute the bypass
            result = execute_cdp_bypass(url, force_cdp=force_cdp, proxy=proxy)
            result["task_id"] = task_id
            result["worker_id"] = WORKER_ID

            # Submit result back to hub
            submit_resp = requests.post(
                f"{HUB_URL}/api/worker/result",
                headers=HEADERS,
                json=result,
                timeout=15
            )
            tasks_completed += 1
            print(f"[DONE] Task {task_id} completed. Mode: {result.get('mode')} | Success: {result.get('success')}")

        except requests.exceptions.Timeout:
            continue
        except Exception as e:
            print(f"[ERROR] Poll/execute error: {e}")
            time.sleep(2)

    print(f"[EXIT] Duration expired. Total tasks completed: {tasks_completed}")


if __name__ == "__main__":
    main()
