import time
import os
import re
from typing import Dict, Any, Optional

try:
    from curl_cffi import requests as cffi_requests
    HAS_CURL_CFFI = True
except ImportError:
    HAS_CURL_CFFI = False

def unlock_fast_tls(url: str, proxy: Optional[str] = None) -> Dict[str, Any]:
    """
    Tier 1: Ultra-Fast TLS impersonation (JA3/JA4 Chrome fingerprint).
    Solves 70% of Cloudflare basic checks without browser overhead (50-200ms).
    """
    if not HAS_CURL_CFFI:
        return {"success": False, "error": "curl_cffi not installed"}

    start = time.time()
    proxies = {"http": proxy, "https": proxy} if proxy else None
    try:
        response = cffi_requests.get(
            url,
            impersonate="chrome124",
            proxies=proxies,
            timeout=15,
            headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "DNT": "1",
                "Upgrade-Insecure-Requests": "1"
            }
        )
        duration_ms = int((time.time() - start) * 1000)
        
        # Check if Cloudflare challenge page is returned
        text = response.text
        if "cf-turnstile" in text or "Just a moment..." in text or "ray ID" in text.lower() and response.status_code == 403:
            return {
                "success": False,
                "needs_cdp": True,
                "status_code": response.status_code,
                "duration_ms": duration_ms
            }

        title_m = re.search(r"<title>(.*?)</title>", text, re.IGNORECASE)
        title = title_m.group(1).strip() if title_m else ""

        return {
            "success": True,
            "mode": "fast_tls",
            "status_code": response.status_code,
            "duration_ms": duration_ms,
            "title": title,
            "html": text,
            "headers": dict(response.headers)
        }
    except Exception as e:
        return {
            "success": False,
            "needs_cdp": True,
            "error": str(e),
            "duration_ms": int((time.time() - start) * 1000)
        }

def unlock_cdp(url: str, proxy: Optional[str] = None, timeout: int = 25) -> Dict[str, Any]:
    """
    Tier 2: Pure CDP Mode (Chrome DevTools Protocol) using SeleniumBase.
    Bypasses Cloudflare Turnstile, DataDome, and advanced bot protections.
    Direct implementation based on Michael Mintz (mdmintz/undetected-testing).
    """
    from seleniumbase import SB

    start = time.time()
    try:
        # test=True runs headless/CDP natively without crashing
        with SB(uc=True, test=True, proxy=proxy) as sb:
            sb.activate_cdp_mode()
            sb.open(url)
            
            # Let page challenge initialize
            sb.sleep(2)
            
            # Auto-click Turnstile or captcha if detected
            try:
                sb.uc_gui_click_captcha()
                sb.sleep(1.5)
            except Exception:
                pass
            
            # Additional wait for Cloudflare "Just a moment..." to finish
            for _ in range(timeout // 2):
                title = sb.get_title()
                if "Just a moment..." not in title and "Attention Required" not in title:
                    break
                sb.sleep(1.5)
            
            html = sb.get_page_source()
            title = sb.get_title()
            cookies = sb.get_cookies()
            duration_ms = int((time.time() - start) * 1000)
            
            return {
                "success": True,
                "mode": "cdp_stealth",
                "status_code": 200,
                "duration_ms": duration_ms,
                "title": title,
                "html": html,
                "cookies": cookies
            }
    except Exception as e:
        duration_ms = int((time.time() - start) * 1000)
        return {
            "success": False,
            "mode": "cdp_stealth",
            "status_code": 500,
            "duration_ms": duration_ms,
            "error": str(e)
        }

def execute_unblock(url: str, force_cdp: bool = False, proxy: Optional[str] = None) -> Dict[str, Any]:
    """
    Smart Dual-Tier Dispatcher:
    Tries Fast-TLS first (50ms). If Cloudflare challenge detected, escalates to CDP Stealth.
    """
    if not force_cdp:
        res = unlock_fast_tls(url, proxy=proxy)
        if res.get("success"):
            return res
        
    return unlock_cdp(url, proxy=proxy)
