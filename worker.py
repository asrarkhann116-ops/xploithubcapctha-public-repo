"""
Xploit Unblocker — Hardened Distributed Worker Node
Connects to the central API hub, polls for scrape tasks over hardened HTTP,
validates targets against SSRF/redirect attacks, executes tasks via dual-tier engine,
and cleanly disposes of browser and memory resources.
"""
import os
import sys
import time
import json
import uuid
import threading
import re
import socket
import ipaddress
import tempfile
import shutil
import gc
from urllib.parse import urlsplit
from typing import Optional, Dict, Any, Tuple, Set, List
import requests

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

# Ensure UTF-8 output
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

INSECURE_DEFAULT_SECRETS = {
    "xpk-worker-default-secret",
    "xpk-secure-session-key-sign-2026-prod",
    "secret",
    "password",
    "admin",
    "123456",
    "default",
    "changeme"
}

def validate_worker_secret(secret: Optional[str]) -> str:
    """Audit and enforce minimum security standard for worker node secret."""
    if not secret or not secret.strip():
        raise RuntimeError("Worker authentication failed: WORKER_SECRET must be configured with a non-empty secret.")

    clean_secret = secret.strip()
    is_prod_or_ci = (
        os.getenv("ENVIRONMENT", "").lower() == "production"
        or bool(os.getenv("RAILWAY_ENVIRONMENT"))
        or os.getenv("GITHUB_ACTIONS", "").lower() == "true"
        or os.getenv("STRICT_WORKER_AUTH", "").lower() == "true"
    )

    if clean_secret.lower() in INSECURE_DEFAULT_SECRETS:
        if is_prod_or_ci:
            raise RuntimeError(
                f"Security Violation: Insecure default WORKER_SECRET ('{clean_secret}') is prohibited in production/CI."
            )
        sys.stderr.write(
            "[SECURITY WARNING] WORKER_SECRET uses an insecure default string. Set a cryptographically strong secret.\n"
        )
    elif len(clean_secret) < 16:
        if is_prod_or_ci:
            raise RuntimeError("Security Violation: WORKER_SECRET must be at least 16 characters long in production/CI.")
        sys.stderr.write(
            "[SECURITY WARNING] WORKER_SECRET is shorter than 16 characters.\n"
        )

    return clean_secret

def validate_hub_url(url: Optional[str]) -> str:
    """Validate hub URL protocol and presence."""
    if not url or not isinstance(url, str):
        raise ValueError("HUB_URL must be a non-empty string.")
    clean = url.strip()
    parsed = urlsplit(clean)
    if parsed.scheme.lower() not in ("http", "https"):
        raise ValueError(f"Invalid HUB_URL protocol '{parsed.scheme}'. Only HTTP and HTTPS are permitted.")
    if not parsed.hostname:
        raise ValueError("HUB_URL must include a valid hostname.")
    return clean.rstrip("/")

HUB_URL = validate_hub_url(os.getenv("HUB_URL", "http://localhost:8000"))
WORKER_SECRET = validate_worker_secret(os.getenv("WORKER_SECRET", "xpk-worker-default-secret"))
WORKER_ID = os.getenv("WORKER_ID", f"gh-{uuid.uuid4().hex[:8]}")
DURATION_MINUTES = int(os.getenv("DURATION_MINUTES", "350"))
ENGINE_VERSION = 2

HEADERS = {
    "X-Worker-Secret": WORKER_SECRET,
    "Content-Type": "application/json"
}

tasks_completed = 0

# ── SSRF Firewall & Target Validation ─────────
BLOCKED_NETWORKS = [
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.0.0.0/24"),
    ipaddress.ip_network("192.0.2.0/24"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("198.18.0.0/15"),
    ipaddress.ip_network("198.51.100.0/24"),
    ipaddress.ip_network("203.0.113.0/24"),
    ipaddress.ip_network("224.0.0.0/4"),
    ipaddress.ip_network("240.0.0.0/4"),
    ipaddress.ip_network("255.255.255.255/32"),
    ipaddress.ip_network("::/128"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("::ffff:0:0/96"),
    ipaddress.ip_network("64:ff9b::/96"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
    ipaddress.ip_network("ff00::/8"),
]

BLOCKED_HOSTNAMES = {
    "localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback",
    "metadata.google.internal", "metadata", "instance-data"
}

def is_safe_target_url(url: Optional[str]) -> Tuple[bool, str]:
    """Validate target URL against SSRF, cloud metadata, and loopback exploits."""
    if not url or not isinstance(url, str):
        return False, "Target URL must be a non-empty string"
    clean = url.strip()
    try:
        parsed = urlsplit(clean)
    except Exception as e:
        return False, f"Malformed URL: {e}"

    scheme = (parsed.scheme or "").lower()
    if scheme not in ("http", "https"):
        return False, f"Scheme '{scheme}' prohibited; only HTTP/HTTPS allowed"

    hostname = parsed.hostname
    if not hostname:
        return False, "URL must contain a valid hostname"

    host_lower = hostname.lower()
    if host_lower in BLOCKED_HOSTNAMES or host_lower.endswith(".internal") or host_lower.endswith(".local") or host_lower.endswith(".localhost"):
        return False, f"Host '{hostname}' is restricted"

    ip_candidates = []
    try:
        if host_lower.startswith("0x"):
            ip_candidates.append(ipaddress.IPv4Address(int(host_lower, 16)))
        elif host_lower.isdigit():
            ip_candidates.append(ipaddress.IPv4Address(int(host_lower)))
    except Exception:
        pass

    if not ip_candidates:
        try:
            ip_candidates.append(ipaddress.ip_address(host_lower.strip("[]")))
        except ValueError:
            try:
                resolved = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
                for r in resolved:
                    ip_candidates.append(ipaddress.ip_address(r[4][0]))
            except Exception as e:
                return False, f"DNS resolution failed for '{hostname}': {e}"

    if not ip_candidates:
        return False, f"Could not resolve valid IP for '{hostname}'"

    for ip in ip_candidates:
        check_ip = getattr(ip, "ipv4_mapped", None) or ip
        if (check_ip.is_loopback or check_ip.is_private or check_ip.is_link_local or
            check_ip.is_reserved or check_ip.is_multicast or check_ip.is_unspecified):
            return False, f"Resolves to restricted IP: {ip}"
        for net in BLOCKED_NETWORKS:
            if check_ip in net:
                return False, f"Resolves to restricted network ({net})"

    return True, ""

def is_safe_proxy(proxy: Optional[str]) -> Tuple[bool, str]:
    """Validate proxy URL against internal pivoting and metadata theft."""
    if not proxy:
        return True, ""
    clean = proxy.strip()
    test_url = clean if "://" in clean else f"http://{clean}"
    try:
        parsed = urlsplit(test_url)
    except Exception as e:
        return False, f"Malformed proxy URL: {e}"

    if parsed.scheme.lower() not in ("http", "https", "socks5", "socks5h"):
        return False, f"Proxy scheme '{parsed.scheme}' not allowed"

    host = parsed.hostname
    port = parsed.port or 80
    return is_safe_target_url(f"http://{host}:{port}")

# ── Redirection Guard for Hub Communication ───
def send_hub_request(
    session: requests.Session,
    method: str,
    endpoint: str,
    hub_url: str,
    **kwargs
) -> requests.Response:
    """Execute hub HTTP request with strict anti-redirect protections."""
    target_url = f"{hub_url}{endpoint}"
    kwargs["allow_redirects"] = False
    resp = session.request(method=method, url=target_url, **kwargs)

    if resp.is_redirect:
        redirect_to = resp.headers.get("Location", "")
        if redirect_to:
            orig_parsed = urlsplit(hub_url)
            redir_parsed = urlsplit(redirect_to)
            is_same_origin = (
                (not redir_parsed.netloc or redir_parsed.netloc == orig_parsed.netloc)
                and redir_parsed.scheme in ("", orig_parsed.scheme)
            )
            if is_same_origin:
                safe_url = redirect_to if redir_parsed.netloc else f"{hub_url.rstrip('/')}/{redirect_to.lstrip('/')}"
                resp = session.request(method=method, url=safe_url, **kwargs)
            else:
                raise requests.RequestException(
                    f"Blocked untrusted cross-origin redirect from Hub to: {redirect_to}"
                )
    return resp

# ── Resource Cleanup & Memory Management ──────
def get_browser_child_pids() -> Set[int]:
    """Return set of browser/driver child PIDs belonging to current process."""
    pids: Set[int] = set()
    if not HAS_PSUTIL:
        return pids
    try:
        current_proc = psutil.Process()
        for child in current_proc.children(recursive=True):
            try:
                name = child.name().lower()
                if any(x in name for x in ("chrome", "chromedriver", "chromium")):
                    pids.add(child.pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
    except Exception:
        pass
    return pids

def cleanup_worker_resources(baseline_pids: Optional[Set[int]] = None):
    """Terminate orphan browser instances, wipe temp profiles, and reclaim memory."""
    # 1. Terminate spawned Chrome / driver processes
    if HAS_PSUTIL:
        try:
            current_proc = psutil.Process()
            for child in current_proc.children(recursive=True):
                try:
                    name = child.name().lower()
                    if any(x in name for x in ("chrome", "chromedriver", "chromium")):
                        if baseline_pids is None or child.pid not in baseline_pids:
                            child.terminate()
                            try:
                                child.wait(timeout=1.5)
                            except psutil.TimeoutExpired:
                                child.kill()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        except Exception:
            pass

    # 2. Delete temporary browser profiles
    try:
        temp_dir = tempfile.gettempdir()
        prefixes = ("undetected_chromedriver", ".org.chromium.Chromium", "scoped_dir", "sb_")
        for entry in os.listdir(temp_dir):
            if any(entry.startswith(p) for p in prefixes):
                full_path = os.path.join(temp_dir, entry)
                try:
                    if os.path.isdir(full_path):
                        shutil.rmtree(full_path, ignore_errors=True)
                    elif os.path.isfile(full_path):
                        os.remove(full_path)
                except Exception:
                    pass
    except Exception:
        pass

    # 3. Explicit garbage collection
    gc.collect()

# ── Error Sanitizer ───────────────────────────
_CREDENTIALS_RE = re.compile(r"://([^:@]+):([^@]+)@", re.IGNORECASE)
_WIN_PATH_RE = re.compile(r"[A-Za-z]:\\[^:\s<>\"\']+", re.IGNORECASE)
_UNIX_PATH_RE = re.compile(r"/(?:home|usr|tmp|var|etc|root|opt)/[^\s<>\"\']+", re.IGNORECASE)
_JWT_RE = re.compile(r"eyJ[a-zA-Z0-9_\-]{8,}\.[a-zA-Z0-9_\-]{8,}\.[a-zA-Z0-9_\-]{8,}", re.IGNORECASE)
_AUTH_HEADER_RE = re.compile(r"\b(Bearer|Secret|Key|Password|Token)\s*[:=\s]\s*['\"]?[a-zA-Z0-9_\-\.\~]{4,}['\"]?", re.IGNORECASE)

def sanitize_error(error_val: Any) -> str:
    """Sanitize error outputs before returning to the central hub."""
    if not error_val:
        return "Unknown worker execution error"

    msg = str(error_val).strip()
    msg = _CREDENTIALS_RE.sub("://***:***@", msg)
    msg = _JWT_RE.sub("[REDACTED_JWT]", msg)
    msg = _AUTH_HEADER_RE.sub(r"\1 [REDACTED_AUTH]", msg)
    msg = _WIN_PATH_RE.sub("[REDACTED_PATH]", msg)
    msg = _UNIX_PATH_RE.sub("[REDACTED_PATH]", msg)

    msg_lower = msg.lower()
    if "timed out" in msg_lower or "timeout" in msg_lower:
        return "Execution timed out while processing target page."
    if "connection refused" in msg_lower:
        return "Connection to destination host was refused."
    if "name or service not known" in msg_lower or "nodename nor servname" in msg_lower or "getaddrinfo failed" in msg_lower:
        return "DNS resolution failed for destination host."
    if "blocked" in msg_lower and ("ssrf" in msg_lower or "restricted" in msg_lower or "prohibited" in msg_lower):
        return "Target blocked by worker security policy: restricted destination."
    if "chrome not reachable" in msg_lower or "session not created" in msg_lower:
        return "Browser automation engine was unable to initialize browser session."
    if "err_name_not_resolved" in msg_lower:
        return "DNS resolution failed in browser engine."
    if "err_connection_reset" in msg_lower:
        return "Connection reset by destination peer."

    if len(msg) > 250:
        return msg[:250] + "... [truncated]"
    return msg

# ── Standalone Module Fallbacks ───────────────
try:
    from engine.proxies import get_next_proxy, report_proxy_result
except ImportError:
    def get_next_proxy(proxy=None):
        return proxy
    def report_proxy_result(proxy, success):
        pass

try:
    from engine.human import apply_human_mouse_move, human_drag_slider
except ImportError:
    def apply_human_mouse_move(sb, x, y, steps=20):
        pass
    def human_drag_slider(sb, sel, distance_px=260):
        return False

# ── Heartbeat Thread ──────────────────────────
def heartbeat_loop(session: requests.Session):
    """Send heartbeat every 30 seconds so the hub knows we're alive."""
    global tasks_completed
    while True:
        try:
            resp = send_hub_request(
                session,
                "POST",
                "/api/worker/heartbeat",
                HUB_URL,
                headers=HEADERS,
                json={
                    "worker_id": WORKER_ID,
                    "tasks_completed": tasks_completed,
                    "engine_version": ENGINE_VERSION
                },
                timeout=10
            )
            data = resp.json()
            queue_depth = data.get("queue_depth", 0)
            print(f"[HEARTBEAT] OK | Queue: {queue_depth} | Completed: {tasks_completed}")

            min_ver = data.get("min_engine_version", 1)
            if min_ver > ENGINE_VERSION:
                print(f"[HOT-RELOAD] Newer engine version requested by Hub (Hub requires v{min_ver}, local is v{ENGINE_VERSION}).")
                print("[HOT-RELOAD] Gracefully exiting so runner restarts with fresh code...")
                os._exit(0)
        except Exception as e:
            print(f"[HEARTBEAT] Warning: {sanitize_error(e)}")
        time.sleep(30)

# ── CDP Bypass Engine ─────────────────────────
def execute_cdp_bypass(url, force_cdp=False, proxy=None, method="GET", headers=None, body=None):
    """
    Run dual-tier bypass with automated cleanup and error protection.
    Tier 1: Fast TLS via curl_cffi with Chrome 124 fingerprint.
    Tier 2: SeleniumBase CDP stealth mode with Bezier curve trajectories.
    """
    import random
    baseline_pids = get_browser_child_pids()
    resolved_proxy = get_next_proxy(proxy)

    try:
        # Tier 1: Fast TLS attempt
        if not force_cdp:
            try:
                from curl_cffi import requests as cffi_requests
                start = time.time()
                proxies = {"http": resolved_proxy, "https": resolved_proxy} if resolved_proxy else None
                req_headers = {
                    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9",
                    "DNT": "1",
                    "Upgrade-Insecure-Requests": "1"
                }
                if headers and isinstance(headers, dict):
                    req_headers.update(headers)

                http_method = (method or "GET").upper()
                kwargs = {
                    "impersonate": "chrome124",
                    "proxies": proxies,
                    "timeout": 15,
                    "headers": req_headers,
                    "max_redirects": 5
                }
                if body is not None:
                    if isinstance(body, (dict, list)):
                        kwargs["json"] = body
                    else:
                        kwargs["data"] = str(body)

                response = cffi_requests.request(
                    method=http_method,
                    url=url,
                    **kwargs
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
                    report_proxy_result(resolved_proxy, success=True)
                    return {
                        "success": True,
                        "mode": "worker_fast_tls",
                        "title": title,
                        "html": text,
                        "cookies": [{"name": k, "value": v} for k, v in response.cookies.items()],
                        "headers": dict(response.headers),
                        "duration_ms": duration,
                        "proxy_used": bool(resolved_proxy)
                    }
                print("[FAST-TLS] Challenge detected, escalating to CDP...")
            except Exception as e:
                report_proxy_result(resolved_proxy, success=False)
                print(f"[FAST-TLS] Escalating: {sanitize_error(e)}")

        # Tier 2: SeleniumBase CDP Stealth Mode
        from seleniumbase import SB
        start = time.time()
        with SB(uc=True, test=True, headed=False, proxy=resolved_proxy) as sb:
            sb.activate_cdp_mode()

            if headers and isinstance(headers, dict):
                try:
                    sb.cdp.send("Network.setExtraHTTPHeaders", {"headers": headers})
                except Exception:
                    pass
                if "User-Agent" in headers:
                    try:
                        sb.cdp.send("Network.setUserAgentOverride", {"userAgent": headers["User-Agent"]})
                    except Exception:
                        pass

            sb.open(url)
            sb.sleep(random.uniform(1.8, 2.8))
            apply_human_mouse_move(sb, random.uniform(300, 750), random.uniform(250, 500), steps=20)

            detected_captcha = None
            page_html = ""
            try:
                page_html = sb.get_page_source().lower()
            except Exception:
                pass

            if "hcaptcha.com" in page_html or "h-captcha" in page_html:
                detected_captcha = "hCaptcha"
            elif "challenges.cloudflare.com" in page_html or "cf-turnstile" in page_html or "just a moment" in page_html:
                detected_captcha = "Cloudflare Turnstile"
            elif "recaptcha" in page_html or "google.com/recaptcha" in page_html:
                detected_captcha = "reCAPTCHA"
            elif "frc-captcha" in page_html:
                detected_captcha = "Friendly Captcha"

            try:
                if hasattr(sb, "solve_captcha"):
                    print(f"[WORKER-CDP] Calling sb.solve_captcha() (Detected: {detected_captcha or 'Auto'})...")
                    sb.solve_captcha()
                else:
                    sb.uc_gui_click_captcha()
                sb.sleep(random.uniform(1.2, 1.8))
            except Exception:
                try:
                    sb.uc_gui_click_captcha()
                    sb.sleep(random.uniform(1.0, 1.5))
                except Exception:
                    pass

            if detected_captcha == "Friendly Captcha" or "frc-button" in page_html:
                for f_sel in [".frc-button", "button.frc-button", "[class*='frc-button']"]:
                    try:
                        if sb.is_element_visible(f_sel):
                            sb.click(f_sel)
                            sb.sleep(1.5)
                            break
                    except Exception:
                        pass

            if any(k in page_html for k in ("slider", "geetest", "datadome", "captcha-delivery")):
                slider_selectors = [
                    ".geetest_slider_button",
                    ".slider-btn",
                    "#nc_1_n1z",
                    "[class*='slider'][class*='btn']",
                    "[class*='captcha_slider']",
                    "#sec-cpt-content",
                    "div.slider"
                ]
                for sel in slider_selectors:
                    try:
                        if sb.is_element_visible(sel):
                            detected_captcha = detected_captcha or "DataDome/GeeTest Slider"
                            print(f"[WORKER] Slider puzzle detected ({sel}), solving via Bezier drag trajectory...")
                            human_drag_slider(sb, sel, distance_px=random.randint(220, 265))
                            sb.sleep(random.uniform(1.4, 2.0))
                            break
                    except Exception:
                        pass

            initial_title = sb.get_title()
            is_cf_shield = any(k in initial_title.lower() for k in ("just a moment", "attention required", "cloudflare"))

            for i in range(14):
                if is_cf_shield:
                    current_title = sb.get_title()
                    if "just a moment" not in current_title.lower() and "attention required" not in current_title.lower():
                        break
                else:
                    token_found = False
                    try:
                        token_found = sb.cdp.evaluate("""
                            (() => {
                                let h = document.querySelector('[name="h-captcha-response"]');
                                if (h && h.value && h.value.length > 5) return true;
                                let c = document.querySelector('[name="cf-turnstile-response"]');
                                if (c && c.value && c.value.length > 5) return true;
                                let g = document.querySelector('[name="g-recaptcha-response"]');
                                if (g && g.value && g.value.length > 5) return true;
                                let s = document.querySelector('.hcaptcha-success');
                                if (s && s.textContent && s.textContent.trim().length > 0) return true;
                                return false;
                            })()
                        """)
                    except Exception:
                        pass

                    if token_found:
                        print("[WORKER-CDP] On-page CAPTCHA solved successfully (Token verified)!")
                        break

                    if i in (1, 3):
                        try:
                            if hasattr(sb, "solve_captcha"):
                                sb.solve_captcha()
                        except Exception:
                            pass

                sb.sleep(1.2)

            html = sb.get_page_source()
            title = sb.get_title()
            cookies = sb.get_cookies()
            duration = int((time.time() - start) * 1000)

            cf_clearance = None
            cf_bm = None
            if cookies:
                for c in cookies:
                    if c.get("name") == "cf_clearance":
                        cf_clearance = c.get("value")
                    elif c.get("name") == "__cf_bm":
                        cf_bm = c.get("value")

            user_agent = None
            try:
                user_agent = sb.get_user_agent()
            except Exception:
                pass

            captcha_token = None
            try:
                captcha_token = sb.cdp.evaluate("""
                    (() => {
                        let c = document.querySelector('[name="cf-turnstile-response"]');
                        if (c && c.value && c.value.length > 5) return c.value;
                        let h = document.querySelector('[name="h-captcha-response"]');
                        if (h && h.value && h.value.length > 5) return h.value;
                        let g = document.querySelector('[name="g-recaptcha-response"]');
                        if (g && g.value && g.value.length > 5) return g.value;
                        return null;
                    })()
                """)
            except Exception:
                pass

            report_proxy_result(resolved_proxy, success=True)
            return {
                "success": True,
                "mode": "worker_cdp",
                "title": title,
                "html": html,
                "cookies": cookies,
                "cf_clearance": cf_clearance,
                "cf_bm": cf_bm,
                "captcha_token": captcha_token,
                "token": captcha_token or cf_clearance,
                "user_agent": user_agent,
                "captcha_detected": detected_captcha,
                "duration_ms": duration,
                "proxy_used": bool(resolved_proxy)
            }
    except Exception as e:
        report_proxy_result(resolved_proxy, success=False)
        duration = int((time.time() - start) * 1000)
        return {
            "success": False,
            "mode": "worker_cdp",
            "error": sanitize_error(e),
            "duration_ms": duration,
        }
    finally:
        cleanup_worker_resources(baseline_pids)

# ── Main Worker Loop ──────────────────────────
def main():
    global tasks_completed

    print("=" * 56)
    print("  XPLOIT UNBLOCKER — HARDENED WORKER ENGINE")
    print("=" * 56)
    print(f"  Worker ID   : {WORKER_ID}")
    print(f"  Hub URL     : {HUB_URL}")
    print(f"  Duration    : {DURATION_MINUTES} minutes")
    print("=" * 56)

    session = requests.Session()

    hb_thread = threading.Thread(target=heartbeat_loop, args=(session,), daemon=True)
    hb_thread.start()

    try:
        send_hub_request(
            session,
            "POST",
            "/api/worker/heartbeat",
            HUB_URL,
            headers=HEADERS,
            json={"worker_id": WORKER_ID, "tasks_completed": 0, "engine_version": ENGINE_VERSION},
            timeout=10
        )
        print("[INIT] Registered with hub successfully.")
    except Exception as e:
        print(f"[INIT] Warning: Could not register with hub: {sanitize_error(e)}")

    deadline = time.time() + (DURATION_MINUTES * 60)

    while time.time() < deadline:
        remaining = int((deadline - time.time()) / 60)
        print(f"[POLL] Waiting for task... ({remaining} min remaining)")

        try:
            resp = send_hub_request(
                session,
                "GET",
                "/api/worker/poll",
                HUB_URL,
                headers=HEADERS,
                timeout=30
            )
            data = resp.json()
            task = data.get("task")

            if not task:
                continue

            task_id = task.get("task_id")
            url = task.get("url")
            force_cdp = task.get("force_cdp", False)
            proxy = task.get("proxy")
            method = task.get("method", "GET")
            headers = task.get("headers")
            body = task.get("body")

            if not task_id or not isinstance(task_id, str):
                continue

            # Validate target URL against SSRF
            is_safe, ssrf_reason = is_safe_target_url(url)
            if not is_safe:
                print(f"[SECURITY] Blocked SSRF attempt on task {task_id}: {ssrf_reason}")
                err_result = {
                    "task_id": task_id,
                    "worker_id": WORKER_ID,
                    "success": False,
                    "mode": "worker_security_guard",
                    "error": sanitize_error(f"Security filter: {ssrf_reason}"),
                    "duration_ms": 0,
                    "proxy_used": False
                }
                send_hub_request(
                    session,
                    "POST",
                    "/api/worker/result",
                    HUB_URL,
                    headers=HEADERS,
                    json=err_result,
                    timeout=15
                )
                continue

            # Validate proxy override against internal pivoting
            if proxy:
                proxy_safe, proxy_reason = is_safe_proxy(proxy)
                if not proxy_safe:
                    print(f"[SECURITY] Dropped unsafe proxy override on task {task_id}: {proxy_reason}")
                    proxy = None

            print(f"[TASK] Received {task_id} [{method}]: {url}")

            result = execute_cdp_bypass(
                url,
                force_cdp=force_cdp,
                proxy=proxy,
                method=method,
                headers=headers,
                body=body
            )
            result["task_id"] = task_id
            result["worker_id"] = WORKER_ID

            if result.get("error"):
                result["error"] = sanitize_error(result["error"])

            send_hub_request(
                session,
                "POST",
                "/api/worker/result",
                HUB_URL,
                headers=HEADERS,
                json=result,
                timeout=15
            )
            tasks_completed += 1
            print(f"[DONE] Task {task_id} completed. Mode: {result.get('mode')} | Success: {result.get('success')}")

        except requests.exceptions.Timeout:
            continue
        except Exception as e:
            print(f"[ERROR] Polling loop error: {sanitize_error(e)}")
            time.sleep(2)

    print(f"[EXIT] Duration expired. Total tasks completed: {tasks_completed}")

if __name__ == "__main__":
    main()
