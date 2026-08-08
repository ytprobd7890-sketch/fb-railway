"""
Live Free Public Proxy Fetcher — Pure HTTP validation
ratman4080 build
"""

import asyncio
import logging
import random
import time
from typing import List, Optional

import httpx

log = logging.getLogger("proxy-fetcher")

PROXY_SOURCES = {
    "proxyscrape": "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=5000&country=all&ssl=all&anonymity=all",
    "monosans": "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt",
    "thespeedx": "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
    "clarketm": "https://raw.githubusercontent.com/clarketm/proxy-list/master/proxy-list-raw.txt",
    "openproxylist": "https://api.openproxylist.xyz/http.txt",
}


class ProxyFetcher:
    def __init__(self, cfg):
        self.cfg = cfg
        self.validated: List[str] = []
        self._idx = 0
        self._last_fetch = 0
        self._lock = asyncio.Lock()

    async def fetch_all_sources(self) -> List[str]:
        raw_proxies = set()

        async def fetch_one(name: str, url: str):
            try:
                async with httpx.AsyncClient(timeout=15) as c:
                    resp = await c.get(url)
                    if resp.status_code != 200:
                        return
                    for line in resp.text.splitlines():
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        parts = line.split()
                        candidate = parts[0] if parts else line
                        if self._is_valid_ip_port(candidate):
                            raw_proxies.add(candidate)
            except Exception as e:
                log.warning(f"[{name}] fetch error: {e}")

        tasks = [fetch_one(n, u) for n, u in PROXY_SOURCES.items()]
        await asyncio.gather(*tasks, return_exceptions=True)

        log.info(f"Total unique raw proxies: {len(raw_proxies)}")
        return list(raw_proxies)

    @staticmethod
    def _is_valid_ip_port(s: str) -> bool:
        parts = s.split(":")
        if len(parts) != 2:
            return False
        ip, port = parts
        octets = ip.split(".")
        if len(octets) != 4:
            return False
        try:
            for o in octets:
                v = int(o)
                if v < 0 or v > 255:
                    return False
            p = int(port)
            if p < 1 or p > 65535:
                return False
        except ValueError:
            return False
        return True

    async def validate_proxy(self, ip_port: str) -> Optional[str]:
        proxy_url = f"http://{ip_port}"
        try:
            async with httpx.AsyncClient(
                proxy=proxy_url,
                timeout=self.cfg.proxy_validate_timeout,
                follow_redirects=True
            ) as c:
                resp = await c.get(f"{self.cfg.fb_base}/reg/")
                if resp.status_code in (200, 301, 302):
                    return proxy_url
        except Exception:
            pass
        return None

    async def validate_batch(self, proxies: List[str], max_concurrent: int = 50) -> List[str]:
        semaphore = asyncio.Semaphore(max_concurrent)
        validated = []

        async def check_one(ip_port: str):
            async with semaphore:
                result = await self.validate_proxy(ip_port)
                if result:
                    validated.append(result)

        await asyncio.gather(
            *[check_one(p) for p in proxies],
            return_exceptions=True
        )
        log.info(f"Validated: {len(validated)}/{len(proxies)} working")
        return validated

    async def refresh(self):
        async with self._lock:
            log.info("=== Proxy refresh starting ===")

            static = self.cfg.get_static_proxies()
            raw = await self.fetch_all_sources()
            all_raw = list(set(raw + [s.replace("http://", "") for s in static if "http://" in s]))
            random.shuffle(all_raw)

            to_validate = all_raw[:200]
            log.info(f"Validating {len(to_validate)} proxies...")

            validated_live = await self.validate_batch(to_validate, max_concurrent=50)

            static_urls = []
            for s in static:
                if s.startswith("http://") or s.startswith("socks5://"):
                    static_urls.append(s)
                else:
                    static_urls.append(f"http://{s}")

            self.validated = list(set(validated_live + static_urls))
            random.shuffle(self.validated)
            self._last_fetch = time.time()
            log.info(f"=== Proxy pool: {len(self.validated)} ===")

    async def auto_refresh_loop(self):
        while True:
            await self.refresh()
            await asyncio.sleep(self.cfg.proxy_refresh_interval)

    def next(self) -> Optional[str]:
        if not self.validated:
            return None
        proxy = self.validated[self._idx % len(self.validated)]
        self._idx += 1
        return proxy

    def random(self) -> Optional[str]:
        if not self.validated:
            return None
        return random.choice(self.validated)

    def count(self) -> int:
        return len(self.validated)
