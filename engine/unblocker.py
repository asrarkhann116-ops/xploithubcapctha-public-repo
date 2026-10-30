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
        # Check if Cloudflare, hCaptcha, or bot challenge page is returned
        text_lower = text.lower()
        if (
            "cf-turnstile" in text_lower or
            "just a moment..." in text_lower or
            "hcaptcha.com" in text_lower or
            "data-sitekey" in text_lower or
            "g-recaptcha" in text_lower or
            ("ray id" in text_lower and response.status_code in (403, 503))
        ):
            return {
                "success": False,
                "needs_cdp": True,
                "status_code": response.status_code,
                "duration_ms": duration_ms
            }

        title_m = re.search(r"<title>(.*?)</title>", text, re.IGNORECASE)
        title = title_m.group(1).strip() if title_m else ""

        cookies_list = [{"name": k, "value": v} for k, v in response.cookies.items()]
        cf_clearance = response.cookies.get("cf_clearance")
        cf_bm = response.cookies.get("__cf_bm")

        report_proxy_result(resolved_proxy, success=True)
        return {
            "success": True,
            "mode": "fast_tls",
            "status_code": response.status_code,
            "duration_ms": duration_ms,
            "title": title,
            "html": text,
            "headers": dict(response.headers),
            "cookies": cookies_list,
            "cf_clearance": cf_clearance,
            "cf_bm": cf_bm,
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
    Tier 2: Pure CDP Mode (Chrome DevTools Protocol) using SeleniumBase 5th Edition.
    Bypasses Cloudflare Turnstile, hCaptcha, reCAPTCHA, Friendly Captcha, and DataDome sliders
    using sb.solve_captcha(), Bezier mouse trajectories, and strategic human pacing.
    Captures and returns the cf_clearance security token for reusable high-speed scraping.
    """
    from seleniumbase import SB

    resolved_proxy = get_next_proxy(proxy)
    start = time.time()
    try:
        with SB(uc=True, test=True, proxy=resolved_proxy) as sb:
            sb.activate_cdp_mode()

            # Set custom headers & User-Agent emulation if provided
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

            # Strategic human observation delay (jitter between 1.8s - 2.8s)
            sb.sleep(random.uniform(1.8, 2.8))

            # Simulate natural human cursor entry onto page with Bezier curve
            apply_human_mouse_move(sb, random.uniform(300, 700), random.uniform(250, 450), steps=20)

            # Detect specific CAPTCHA types before solving
            detected_captcha = None

            # 1. Check for hCaptcha
            hcaptcha_selectors = [
                "iframe[src*='hcaptcha.com']",
                "iframe[title*='hCaptcha']",
                "div.h-captcha",
                "[data-hcaptcha-widget-id]",
                "[data-sitekey][class*='h-captcha']"
            ]
            for sel in hcaptcha_selectors:
                try:
                    if sb.is_element_visible(sel):
                        detected_captcha = "hCaptcha"
                        break
                except Exception:
                    pass

            # 2. Check for Cloudflare Turnstile / Challenge
            if not detected_captcha:
                turnstile_selectors = [
                    "iframe[src*='challenges.cloudflare.com']",
                    "div.cf-turnstile",
                    "#turnstile-wrapper",
                    "[data-turnstile-sitekey]"
                ]
                for sel in turnstile_selectors:
                    try:
                        if sb.is_element_visible(sel):
                            detected_captcha = "Cloudflare Turnstile"
                            break
                    except Exception:
                        pass

            # 3. Check for Google reCAPTCHA
            if not detected_captcha:
                recaptcha_selectors = [
                    "iframe[src*='recaptcha']",
                    "iframe[src*='google.com/recaptcha']",
                    ".g-recaptcha"
                ]
                for sel in recaptcha_selectors:
                    try:
                        if sb.is_element_visible(sel):
                            detected_captcha = "reCAPTCHA"
                            break
                    except Exception:
                        pass

            # 4. Check for Friendly Captcha
            friendly_selectors = [
                ".frc-captcha",
                "#frc-captcha",
                ".frc-button"
            ]
            for sel in friendly_selectors:
                try:
                    if sb.is_element_visible(sel):
                        detected_captcha = "Friendly Captcha"
                        break
                except Exception:
                    pass

            # Universal solve using SeleniumBase 5th Edition CDP engine (sb.solve_captcha)
            try:
                if hasattr(sb, "solve_captcha"):
                    print(f"[CDP] Calling sb.solve_captcha() (Detected: {detected_captcha or 'Auto'})...")
                    sb.solve_captcha()
                else:
                    sb.uc_gui_click_captcha()
                sb.sleep(random.uniform(1.4, 2.2))
            except Exception as e:
                # Secondary fallback to uc_gui_click_captcha
                try:
                    sb.uc_gui_click_captcha()
                    sb.sleep(random.uniform(1.2, 1.8))
                except Exception:
                    pass

            # Friendly Captcha trigger button if present
            for f_sel in [".frc-button", "button.frc-button", "[class*='frc-button']"]:
                try:
                    if sb.is_element_visible(f_sel):
                        sb.click(f_sel)
                        sb.sleep(2.0)
                        break
                except Exception:
                    pass

            # Detect & solve horizontal slider puzzles (GeeTest / DataDome / Slider)
            slider_selectors = [
                ".geetest_slider_button",
                ".slider-btn",
                "#nc_1_n1z",
                "[class*='slider'][class*='btn']",
                "[class*='captcha_slider']",
                "#sec-cpt-content",
                "iframe[src*='geo.captcha-delivery.com']",
                "div.slider"
            ]
            for sel in slider_selectors:
                try:
                    if sb.is_element_visible(sel):
                        detected_captcha = detected_captcha or "DataDome/GeeTest Slider"
                        print(f"[CDP] Slider puzzle detected ({sel}), applying human trajectory drag...")
                        human_drag_slider(sb, sel, distance_px=random.randint(220, 265))
                        sb.sleep(random.uniform(1.4, 2.0))
                        break
                except Exception:
                    pass

            # Wait for clearance with periodic re-solve checks
            for _ in range(timeout // 2):
                title = sb.get_title()
                if "Just a moment..." not in title and "Attention Required" not in title:
                    break
                # Re-attempt solve if challenge persists
                try:
                    if hasattr(sb, "solve_captcha"):
                        sb.solve_captcha()
                except Exception:
                    pass
                sb.sleep(1.2)

            html = sb.get_page_source()
            title = sb.get_title()
            cookies = sb.get_cookies()
            duration_ms = int((time.time() - start) * 1000)

            # Extract cf_clearance security token for reusable high-speed scraping
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

            report_proxy_result(resolved_proxy, success=True)
            return {
                "success": True,
                "mode": "cdp_stealth",
                "status_code": 200,
                "duration_ms": duration_ms,
                "title": title,
                "html": html,
                "cookies": cookies,
                "cf_clearance": cf_clearance,
                "cf_bm": cf_bm,
                "user_agent": user_agent,
                "captcha_detected": detected_captcha,
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

