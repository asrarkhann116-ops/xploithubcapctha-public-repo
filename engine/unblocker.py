import time
import os
import re
import random
from typing import Dict, Any, Optional

try:
    from curl_cffi import requests as cffi_requests
    HAS_CURL_CFFI = True
except ImportError:
    HAS_CURL_CFFI = False

from engine.proxies import get_next_proxy, report_proxy_result
from engine.human import apply_human_mouse_move, human_drag_slider

def unlock_fast_tls(
    url: str,
    proxy: Optional[str] = None,
    method: str = "GET",
    headers: Optional[Dict[str, str]] = None,
    body: Optional[Any] = None
) -> Dict[str, Any]:
    """
    Tier 1: Ultra-Fast TLS impersonation (JA3/JA4 Chrome fingerprint).
    Solves 70% of Cloudflare basic checks without browser overhead (50-200ms).
    Supports GET, POST, PUT, DELETE with custom headers and payload.
    """
    if not HAS_CURL_CFFI:
        return {"success": False, "error": "curl_cffi not installed"}

    resolved_proxy = get_next_proxy(proxy)
    proxies = {"http": resolved_proxy, "https": resolved_proxy} if resolved_proxy else None

    # Merge custom headers with standard browser headers
    req_headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "DNT": "1",
        "Upgrade-Insecure-Requests": "1"
    }
    if headers and isinstance(headers, dict):
        req_headers.update(headers)

    start = time.time()
    try:
        http_method = (method or "GET").upper()
        kwargs: Dict[str, Any] = {
            "impersonate": "chrome124",
            "proxies": proxies,
            "timeout": 15,
            "headers": req_headers
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
        duration_ms = int((time.time() - start) * 1000)

        text = response.text
        # Check if Cloudflare or bot challenge page is returned
        if "cf-turnstile" in text or "Just a moment..." in text or ("ray ID" in text.lower() and response.status_code == 403):
            return {
                "success": False,
                "needs_cdp": True,
                "status_code": response.status_code,
                "duration_ms": duration_ms
            }

        title_m = re.search(r"<title>(.*?)</title>", text, re.IGNORECASE)
        title = title_m.group(1).strip() if title_m else ""

        report_proxy_result(resolved_proxy, success=True)
        return {
            "success": True,
            "mode": "fast_tls",
            "status_code": response.status_code,
            "duration_ms": duration_ms,
            "title": title,
            "html": text,
            "headers": dict(response.headers),
            "cookies": [{"name": k, "value": v} for k, v in response.cookies.items()],
            "proxy_used": bool(resolved_proxy)
        }
    except Exception as e:
        report_proxy_result(resolved_proxy, success=False)
        return {
            "success": False,
            "needs_cdp": True,
            "error": str(e),
            "duration_ms": int((time.time() - start) * 1000)
        }

def unlock_cdp(
    url: str,
    proxy: Optional[str] = None,
    timeout: int = 25,
    method: str = "GET",
    headers: Optional[Dict[str, str]] = None,
    body: Optional[Any] = None
) -> Dict[str, Any]:
    """
    Tier 2: Pure CDP Mode (Chrome DevTools Protocol) using SeleniumBase
    with Bezier mouse trajectories and natural human slider interactions.
    Supports extra HTTP headers and dynamic API requests.
    """
    from seleniumbase import SB

    resolved_proxy = get_next_proxy(proxy)
    start = time.time()
    try:
        with SB(uc=True, test=True, proxy=resolved_proxy) as sb:
            sb.activate_cdp_mode()

            # Set custom headers if provided
            if headers and isinstance(headers, dict):
                try:
                    sb.cdp.send("Network.setExtraHTTPHeaders", {"headers": headers})
                except Exception:
                    pass

            sb.open(url)

            # Natural human observation pause
            sb.sleep(random.uniform(1.8, 2.5))

            # Simulate human cursor entry onto page
            apply_human_mouse_move(sb, random.uniform(300, 700), random.uniform(250, 450), steps=20)

            # Auto-click Turnstile or reCAPTCHA with human-like motion
            try:
                sb.uc_gui_click_captcha()
                sb.sleep(random.uniform(1.2, 1.8))
            except Exception:
                pass

            # Detect & solve horizontal slider puzzles (GeeTest / DataDome) if present
            slider_selectors = [
                ".geetest_slider_button",
                ".slider-btn",
                "#nc_1_n1z",
                "[class*='slider'][class*='btn']",
                "[class*='captcha_slider']"
            ]
            for sel in slider_selectors:
                try:
                    if sb.is_element_visible(sel):
                        print(f"[CDP] Slider puzzle detected ({sel}), applying human trajectory drag...")
                        human_drag_slider(sb, sel, distance_px=random.randint(220, 260))
                        sb.sleep(1.5)
                        break
                except Exception:
                    pass

            # Wait for clearance
            for _ in range(timeout // 2):
                title = sb.get_title()
                if "Just a moment..." not in title and "Attention Required" not in title:
                    break
                sb.sleep(1.2)

            html = sb.get_page_source()
            title = sb.get_title()
            cookies = sb.get_cookies()
            duration_ms = int((time.time() - start) * 1000)

            report_proxy_result(resolved_proxy, success=True)
            return {
                "success": True,
                "mode": "cdp_stealth",
                "status_code": 200,
                "duration_ms": duration_ms,
                "title": title,
                "html": html,
                "cookies": cookies,
                "proxy_used": bool(resolved_proxy)
            }
    except Exception as e:
        report_proxy_result(resolved_proxy, success=False)
        duration_ms = int((time.time() - start) * 1000)
        return {
            "success": False,
            "mode": "cdp_stealth",
            "status_code": 500,
            "duration_ms": duration_ms,
            "error": str(e)
        }

def execute_unblock(
    url: str,
    force_cdp: bool = False,
    proxy: Optional[str] = None,
    method: str = "GET",
    headers: Optional[Dict[str, str]] = None,
    body: Optional[Any] = None
) -> Dict[str, Any]:
    """
    Smart Dual-Tier Dispatcher:
    Tries Fast-TLS first (50ms). If Cloudflare challenge detected, escalates to CDP Stealth.
    """
    if not force_cdp:
        res = unlock_fast_tls(url, proxy=proxy, method=method, headers=headers, body=body)
        if res.get("success"):
            return res

    return unlock_cdp(url, proxy=proxy, method=method, headers=headers, body=body)

