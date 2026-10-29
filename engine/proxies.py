"""
Xploit Unblocker — Smart Proxy Manager & Rotation Pool
Manages rotating proxy pools (HTTP / SOCKS5 / Residential), handles
failover, health scoring, and automatic round-robin selection.
"""

import os
import time
import random
from typing import Optional, List, Dict, Any

class ProxyPoolManager:
    def __init__(self):
        self.proxies: List[str] = []
        self.stats: Dict[str, Dict[str, Any]] = {}
        self.index = 0
        self.reload_proxies()

    def reload_proxies(self):
        """Load proxies from environment variable or local proxies.txt file."""
        loaded = []

        # 1. Check PROXY_LIST env var (comma or newline-separated)
        env_proxies = os.getenv("PROXY_LIST", "").strip()
        if env_proxies:
            for line in env_proxies.replace(";", ",").replace("\n", ",").split(","):
                clean = line.strip()
                if clean and not clean.startswith("#"):
                    loaded.append(self.normalize_proxy(clean))

        # 2. Check proxies.txt in root or data directory
        for filename in ["proxies.txt", "data/proxies.txt"]:
            if os.path.exists(filename):
                try:
                    with open(filename, "r", encoding="utf-8") as f:
                        for line in f:
                            clean = line.strip()
                            if clean and not clean.startswith("#"):
                                loaded.append(self.normalize_proxy(clean))
                except Exception:
                    pass

        # Deduplicate while preserving order
        seen = set()
        self.proxies = [p for p in loaded if p and not (p in seen or seen.add(p))]

        for p in self.proxies:
            if p not in self.stats:
                self.stats[p] = {"successes": 0, "failures": 0, "last_used": 0, "backoff_until": 0}

    @staticmethod
    def normalize_proxy(proxy_str: str) -> str:
        """
        Normalize formats into valid requests/SeleniumBase proxy URLs.
        e.g.
          host:port -> http://host:port
          user:pass@host:port -> http://user:pass@host:port
          host:port:user:pass -> http://user:pass@host:port
        """
        proxy_str = proxy_str.strip()
        if not proxy_str:
            return ""

        # Check if 4-segment ip:port:user:pass format
        parts = proxy_str.split(":")
        if len(parts) == 4 and "@" not in proxy_str and not proxy_str.startswith("http"):
            ip, port, user, pwd = parts
            return f"http://{user}:{pwd}@{ip}:{port}"

        if not (proxy_str.startswith("http://") or proxy_str.startswith("https://") or proxy_str.startswith("socks5://")):
            return f"http://{proxy_str}"

        return proxy_str

    def get_proxy(self, override: Optional[str] = None) -> Optional[str]:
        """
        Returns the best proxy:
        1. If override is provided in request, returns normalized override.
        2. Otherwise picks the next healthy proxy from the rotation pool.
        """
        if override:
            return self.normalize_proxy(override)

        if not self.proxies:
            return None

        now = time.time()
        # Find candidates not currently in failure backoff
        healthy = [p for p in self.proxies if self.stats.get(p, {}).get("backoff_until", 0) <= now]

        pool = healthy if healthy else self.proxies

        # Round-robin selection
        selected = pool[self.index % len(pool)]
        self.index = (self.index + 1) % len(pool)

        if selected in self.stats:
            self.stats[selected]["last_used"] = now

        return selected

    def report_result(self, proxy: Optional[str], success: bool):
        """Record success/failure to adaptively penalize bad IPs."""
        if not proxy or proxy not in self.stats:
            return

        now = time.time()
        st = self.stats[proxy]
        if success:
            st["successes"] += 1
            st["backoff_until"] = 0
        else:
            st["failures"] += 1
            # Exponential backoff (30s, 60s, 120s...)
            cooldown = min(300, 30 * (2 ** min(st["failures"] - 1, 4)))
            st["backoff_until"] = now + cooldown

    def get_stats(self) -> Dict[str, Any]:
        """Return pool health summary for telemetry / API status."""
        now = time.time()
        active = sum(1 for p in self.proxies if self.stats.get(p, {}).get("backoff_until", 0) <= now)
        return {
            "total_configured": len(self.proxies),
            "healthy_active": active,
            "proxies": [
                {
                    "proxy": p.split("@")[-1], # Mask credentials in telemetry
                    "successes": st["successes"],
                    "failures": st["failures"],
                    "status": "ready" if st["backoff_until"] <= now else f"cooldown_{int(st['backoff_until'] - now)}s"
                }
                for p, st in self.stats.items()
            ]
        }

# Global singleton proxy manager
proxy_manager = ProxyPoolManager()

def get_next_proxy(override: Optional[str] = None) -> Optional[str]:
    return proxy_manager.get_proxy(override)

def report_proxy_result(proxy: Optional[str], success: bool):
    proxy_manager.report_result(proxy, success)

def get_proxy_stats() -> Dict[str, Any]:
    return proxy_manager.get_stats()
