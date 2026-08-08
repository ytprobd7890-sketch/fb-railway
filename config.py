import os
from dataclasses import dataclass
from typing import List


@dataclass
class Config:
    # Telegram
    tg_bot_token: str = os.getenv("TG_BOT_TOKEN", "")
    tg_chat_id: str = os.getenv("TG_CHAT_ID", "")

    # Proxy
    proxies: str = os.getenv("PROXIES", "")
    auto_fetch_proxies: bool = os.getenv("AUTO_FETCH_PROXIES", "true").lower() == "true"
    proxy_validate_timeout: int = int(os.getenv("PROXY_VALIDATE_TIMEOUT", "8"))
    proxy_refresh_interval: int = int(os.getenv("PROXY_REFRESH_INTERVAL", "600"))

    # Account
    max_accounts: int = int(os.getenv("MAX_ACCOUNTS", "0"))
    max_concurrent: int = int(os.getenv("MAX_CONCURRENT", "3"))
    delay_min: int = int(os.getenv("DELAY_MIN", "5"))
    delay_max: int = int(os.getenv("DELAY_MAX", "15"))
    retry_attempts: int = int(os.getenv("RETRY_ATTEMPTS", "3"))

    # Email
    email_timeout: int = int(os.getenv("EMAIL_TIMEOUT", "120"))
    mail_tm_retry: int = int(os.getenv("MAIL_TM_RETRY", "3"))

    # FB endpoint
    fb_base: str = os.getenv("FB_BASE", "https://m.facebook.com")

    # HTTP
    http_timeout: int = int(os.getenv("HTTP_TIMEOUT", "30"))
    max_redirects: int = int(os.getenv("MAX_REDIRECTS", "10"))

    # Captcha
    capsolver_key: str = os.getenv("CAPSOLVER_KEY", "")

    def get_static_proxies(self) -> List[str]:
        """Return raw ip:port or scheme://user:pass@ip:port strings."""
        if not self.proxies:
            return []
        return [p.strip() for p in self.proxies.split(",") if p.strip()]
