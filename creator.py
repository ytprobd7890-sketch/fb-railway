#!/usr/bin/env python3
"""
FB Account Creator — Pure HTTP Engine (No Browser)
httpx + BeautifulSoup. No Playwright. No Chromium.
ratman4080 build v3
"""

import asyncio
import random
import string
import time
import logging
import re
import sys
from datetime import date
from typing import Optional, Tuple

from faker import Faker
from bs4 import BeautifulSoup
import httpx

from config import Config
from proxy_fetcher import ProxyFetcher

# ============================================================
# LOGGING
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout
)
log = logging.getLogger("fb-creator")

# ============================================================
# MOBILE USER AGENTS
# ============================================================
MOBILE_UAS = [
    "Mozilla/5.0 (Linux; Android 13; SM-G991B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 12; SM-A325F) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Mobile Safari/537.36",
]

# ============================================================
# IDENTITY GENERATOR
# ============================================================
class IdentityGen:
    def __init__(self):
        self.fk = Faker()

    def generate(self) -> dict:
        gender = random.choice(["male", "female"])
        first = self.fk.first_name_male() if gender == "male" else self.fk.first_name_female()
        last = self.fk.last_name()

        age = random.randint(22, 45)
        today = date.today()
        birth_date = today.replace(year=today.year - age)
        birth_date = birth_date.replace(
            month=random.randint(1, 12),
            day=random.randint(1, 28)
        )

        rand_chars = ''.join(random.choices(string.ascii_letters + string.digits, k=6))
        password = f"R@t#{rand_chars}{random.randint(0, 99)}"

        return {
            "first_name": first,
            "last_name": last,
            "birth_date": birth_date.strftime("%Y-%m-%d"),
            "birth_day": str(birth_date.day),
            "birth_month": str(birth_date.month),
            "birth_year": str(birth_date.year),
            "gender": gender,
            "password": password,
        }

# ============================================================
# TEMP EMAIL (mail.tm)
# ============================================================
class TempEmail:
    BASE = "https://api.mail.tm"

    def __init__(self):
        self.token = None
        self.address = None
        self.account_id = None
        self._password = None

    async def create(self, client: httpx.AsyncClient, max_retries: int = 3) -> str:
        for attempt in range(max_retries):
            try:
                resp = await client.get(f"{self.BASE}/domains")
                if resp.status_code == 429:
                    wait = 5 * (attempt + 1)
                    log.warning(f"mail.tm rate limited, waiting {wait}s")
                    await asyncio.sleep(wait)
                    continue
                resp.raise_for_status()
                domain = resp.json()["hydra:member"][0]["domain"]

                local = ''.join(random.choices(string.ascii_lowercase + string.digits, k=10))
                self.address = f"{local}@{domain}"
                self._password = ''.join(random.choices(string.ascii_letters + string.digits, k=16))

                resp = await client.post(
                    f"{self.BASE}/accounts",
                    json={"address": self.address, "password": self._password}
                )
                if resp.status_code == 429:
                    await asyncio.sleep(5 * (attempt + 1))
                    continue
                if resp.status_code not in (200, 201):
                    raise Exception(f"mail.tm create: {resp.status_code}")
                self.account_id = resp.json()["id"]

                resp = await client.post(
                    f"{self.BASE}/token",
                    json={"address": self.address, "password": self._password}
                )
                if resp.status_code == 429:
                    await asyncio.sleep(5 * (attempt + 1))
                    continue
                resp.raise_for_status()
                self.token = resp.json()["token"]
                return self.address

            except Exception as e:
                if attempt < max_retries - 1:
                    log.warning(f"mail.tm attempt {attempt+1}: {e}")
                    await asyncio.sleep(3)
                else:
                    raise

    async def wait_for_code(self, client: httpx.AsyncClient, timeout: int = 120) -> Optional[str]:
        if not self.token:
            return None
        start = time.time()
        while time.time() - start < timeout:
            try:
                resp = await client.get(
                    f"{self.BASE}/messages",
                    headers={"Authorization": f"Bearer {self.token}"}
                )
                if resp.status_code == 429:
                    await asyncio.sleep(10)
                    continue
                if resp.status_code == 200:
                    for msg in resp.json().get("hydra:member", []):
                        sender = msg.get("from", {}).get("address", "").lower()
                        if "facebook" in sender:
                            full = await client.get(
                                f"{self.BASE}/messages/{msg['id']}",
                                headers={"Authorization": f"Bearer {self.token}"}
                            )
                            if full.status_code == 200:
                                data = full.json()
                                body = data.get("text") or ""
                                if not body and data.get("html"):
                                    html_list = data["html"]
                                    body = html_list[0] if isinstance(html_list, list) and html_list else str(html_list)
                                code = self._extract_code(body)
                                if code:
                                    return code
            except Exception:
                pass
            await asyncio.sleep(5)
        return None

    @staticmethod
    def _extract_code(text: str) -> Optional[str]:
        match = re.search(r'\b(\d{5,6})\b', text)
        return match.group(1) if match else None

    async def cleanup(self, client: httpx.AsyncClient):
        if not self.token or not self.account_id:
            return
        try:
            await client.delete(
                f"{self.BASE}/accounts/{self.account_id}",
                headers={"Authorization": f"Bearer {self.token}"}
            )
        except Exception:
            pass

# ============================================================
# FORM PARSER
# ============================================================
def parse_form(html: str, match_keyword: str = "") -> Tuple[Optional[str], dict]:
    soup = BeautifulSoup(html, "lxml")

    target = None
    for form in soup.find_all("form"):
        action = form.get("action", "")
        inputs = {inp.get("name", "") for inp in form.find_all("input")}

        if match_keyword and match_keyword in action:
            target = form
            break
        if match_keyword and match_keyword in inputs:
            target = form
            break

    if not target and not match_keyword:
        target = soup.find("form", {"method": "post"}) or soup.find("form")

    if not target:
        return None, {}

    action = target.get("action", "")
    if action and not action.startswith("http"):
        action = "https://m.facebook.com" + action

    data = {}
    for inp in target.find_all("input"):
        name = inp.get("name")
        if name:
            data[name] = inp.get("value", "")

    return action, data

# ============================================================
# CAPSOLVER
# ============================================================
async def solve_captcha_api(cfg: Config, html: str, http_client: httpx.AsyncClient) -> Optional[str]:
    if not cfg.capsolver_key:
        return None

    try:
        soup = BeautifulSoup(html, "lxml")

        recaptcha_div = soup.find("div", {"class": "g-recaptcha"}) or \
                        soup.find(attrs={"data-sitekey": True})

        if recaptcha_div:
            site_key = recaptcha_div.get("data-sitekey")
            if not site_key:
                return None

            log.info(f"CapSolver: solving reCAPTCHA sitekey={site_key}")

            resp = await http_client.post("https://api.capsolver.com/createTask", json={
                "clientKey": cfg.capsolver_key,
                "task": {
                    "type": "ReCaptchaV2TaskProxyLess",
                    "websiteURL": "https://m.facebook.com/reg/",
                    "websiteKey": site_key,
                }
            })
            task_id = resp.json().get("taskId")
            if not task_id:
                log.error(f"CapSolver createTask fail: {resp.text}")
                return None

            for _ in range(40):
                await asyncio.sleep(3)
                resp = await http_client.post("https://api.capsolver.com/getTaskResult", json={
                    "clientKey": cfg.capsolver_key,
                    "taskId": task_id
                })
                data = resp.json()
                if data.get("status") == "ready":
                    token = data["solution"]["gRecaptchaResponse"]
                    log.info("CapSolver: solved")
                    return token
                if data.get("status") == "failed":
                    log.error("CapSolver: task failed")
                    return None

        return None
    except Exception as e:
        log.error(f"CapSolver error: {e}")
        return None

# ============================================================
# FB CREATOR
# ============================================================
class FBCreator:
    def __init__(self, cfg: Config, proxy_fetcher: ProxyFetcher):
        self.cfg = cfg
        self.pf = proxy_fetcher
        self.identity = IdentityGen()

    def _build_client(self, proxy_url: Optional[str]) -> httpx.AsyncClient:
        headers = {
            "User-Agent": random.choice(MOBILE_UAS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
        }
        kwargs = {
            "headers": headers,
            "timeout": self.cfg.http_timeout,
            "follow_redirects": True,
            "max_redirects": self.cfg.max_redirects,
        }
        if proxy_url:
            kwargs["proxy"] = proxy_url
        return httpx.AsyncClient(**kwargs)

    async def create_account(self) -> Optional[dict]:
        proxy = self.pf.random()
        if not proxy:
            log.error("No proxies available — skipping")
            return None

        identity = self.identity.generate()
        log.info(f"Starting: {identity['first_name']} {identity['last_name']} via {proxy}")

        async with self._build_client(proxy) as client:
            # Phase 1: GET /reg/
            try:
                resp = await client.get(f"{self.cfg.fb_base}/reg/")
            except Exception as e:
                log.error(f"GET /reg/ fail: {e}")
                return None

            if resp.status_code not in (200, 301, 302):
                log.error(f"GET /reg/ status={resp.status_code}")
                return None

            reg_html = resp.text
            log.info(f"GET /reg/ OK, html len={len(reg_html)}")

            # Phase 2: Parse form
            action, form_data = parse_form(reg_html, match_keyword="reg")

            if not action:
                log.error("No registration form found")
                return None

            log.info(f"Form action: {action}")
            log.info(f"Hidden fields: {list(form_data.keys())}")

            # Phase 3: Temp email
            temp_mail = TempEmail()
            try:
                email_addr = await temp_mail.create(client, max_retries=self.cfg.mail_tm_retry)
                if not email_addr:
                    log.error("mail.tm create failed")
                    return None
                log.info(f"Temp email: {email_addr}")
            except Exception as e:
                log.error(f"mail.tm error: {e}")
                return None

            # Phase 4: Build POST payload
            gender_val = "1" if identity["gender"] == "female" else "2"

            payload = dict(form_data)
            payload.update({
                "firstname": identity["first_name"],
                "lastname": identity["last_name"],
                "reg_email__": email_addr,
                "reg_passwd__": identity["password"],
                "birth_day": identity["birth_day"],
                "birth_month": identity["birth_month"],
                "birth_year": identity["birth_year"],
                "sex": gender_val,
                "websubmit": "1",
                "lsd": form_data.get("lsd", ""),
                "jazoest": form_data.get("jazoest", ""),
            })

            # Phase 5: Captcha solve
            captcha_token = await solve_captcha_api(self.cfg, reg_html, client)
            if captcha_token:
                payload["g-recaptcha-response"] = captcha_token
                log.info("Captcha token attached to payload")
            else:
                log.warning("No captcha token — submitting anyway")

            # Phase 6: POST /reg/
            post_headers = {
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": "https://m.facebook.com",
                "Referer": f"{self.cfg.fb_base}/reg/",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "same-origin",
                "Sec-Fetch-User": "?1",
                "Upgrade-Insecure-Requests": "1",
            }

            try:
                resp = await client.post(action, data=payload, headers=post_headers)
            except Exception as e:
                log.error(f"POST /reg/ fail: {e}")
                await temp_mail.cleanup(client)
                return None

            post_html = resp.text
            final_url = str(resp.url)
            log.info(f"POST /reg/ status={resp.status_code} url={final_url}")

            # Phase 7: Check success
            c_user = None
            xs = None
            for cookie in client.cookies.jar:
                if cookie.name == "c_user":
                    c_user = cookie.value
                elif cookie.name == "xs":
                    xs = cookie.value

            success = False
            if c_user:
                success = True
                log.info(f"c_user={c_user} — account created")
            elif "/login/" in final_url or "checkpoint" in final_url:
                log.warning(f"Redirected to {final_url} — may need verification")
                if "checkpoint" in final_url:
                    log.warning("Checkpoint hit — attempting email verification bypass")
            elif "reg_error" in post_html or "registration error" in post_html.lower():
                soup = BeautifulSoup(post_html, "lxml")
                err_msg = soup.find(class_="msg_box") or soup.find(id="reg_error")
                if err_msg:
                    log.error(f"FB reg error: {err_msg.get_text(strip=True)}")
                else:
                    log.error("Registration error (unknown)")
                await temp_mail.cleanup(client)
                return None
            else:
                has_datr = any(c.name == "datr" for c in client.cookies.jar)
                if has_datr and len(post_html) > 5000:
                    log.info("Ambiguous response — checking for account indicators")
                    if "logout" in post_html.lower() or "home.php" in final_url:
                        success = True

            if not success:
                log.error(f"Registration failed. Final URL: {final_url}")
                await temp_mail.cleanup(client)
                return None

            # Phase 8: Email verification
            email_verified = False
            try:
                code = await temp_mail.wait_for_code(client, timeout=self.cfg.email_timeout)
                if code:
                    log.info(f"Verification code received: {code}")
                    verified = await self._submit_verification_code(
                        client, code, post_html, final_url
                    )
                    email_verified = verified
                else:
                    log.warning("No verification email received within timeout")
            except Exception as e:
                log.warning(f"Email verification error: {e}")

            # Phase 9: Build result
            result = {
                "email": email_addr,
                "password": identity["password"],
                "first_name": identity["first_name"],
                "last_name": identity["last_name"],
                "gender": identity["gender"],
                "birth_date": identity["birth_date"],
                "email_verified": email_verified,
                "c_user": c_user or "N/A",
                "xs": xs or "N/A",
                "proxy": proxy,
                "created_at": int(time.time()),
            }

            await temp_mail.cleanup(client)
            return result

    async def _submit_verification_code(
        self, client: httpx.AsyncClient, code: str, html: str, current_url: str
    ) -> bool:
        try:
            action, form_data = parse_form(html, match_keyword="code")

            if not action:
                action = f"{self.cfg.fb_base}/checkpoint/"
                form_data = {}

            form_data["code"] = code
            form_data["submit[Continue]"] = "Continue"

            post_headers = {
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": current_url,
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "same-origin",
            }

            resp = await client.post(action, data=form_data, headers=post_headers)
            resp_html = resp.text.lower()

            if resp.status_code in (200, 301, 302):
                if "checkpoint" not in str(resp.url) and "code" not in resp_html:
                    log.info("Verification code accepted")
                    return True
                if "saved" in resp_html or "success" in resp_html:
                    log.info("Verification appears successful")
                    return True

            log.warning(f"Verification submit status={resp.status_code}")
            return False
        except Exception as e:
            log.error(f"Verification submit error: {e}")
            return False
