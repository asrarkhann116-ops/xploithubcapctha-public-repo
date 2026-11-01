import os
import aiohttp
from typing import Tuple, Optional

TURNSTILE_SECRET_KEY = os.getenv("CLOUDFLARE_TURNSTILE_SECRET_KEY", "0x4AAAAAAFu_f_7HZXUgmdKtG6tw8idcdZQ")
VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"

async def verify_turnstile_token(token: Optional[str], remote_ip: Optional[str] = None) -> Tuple[bool, str]:
    """
    Validates Cloudflare Turnstile captcha token.
    Blocks automated bots, headless scripts, and reverse-engineering toolkits.
    """
    if not token or not token.strip():
        return False, "Captcha validation required. Please complete the security check."

    # In local testing without secret key, allow bypass only if explicitly disabled
    if not TURNSTILE_SECRET_KEY:
        return True, ""

    data = {
        "secret": TURNSTILE_SECRET_KEY,
        "response": token.strip(),
    }
    if remote_ip and remote_ip not in ("127.0.0.1", "::1", "localhost"):
        data["remoteip"] = remote_ip

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(VERIFY_URL, data=data, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                if resp.status != 200:
                    return False, f"Cloudflare verification server returned status {resp.status}."
                result = await resp.json()
                if result.get("success"):
                    return True, ""
                error_codes = result.get("error-codes", [])
                err_msg = ", ".join(error_codes) if error_codes else "Verification failed."
                return False, f"Security challenge failed ({err_msg}). Please try again."
    except Exception as e:
        # Fail closed on network failure to maintain security
        return False, f"Security challenge service unreachable: {str(e)}"
