import asyncio
import email as email_lib
import imaplib
import json
import os
import random
import re
import string
import ssl
import subprocess
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Any, Optional
from loguru import logger
from playwright.async_api import async_playwright, Page

ssl._create_default_https_context = ssl._create_unverified_context

KEEP_OPEN = False  

logger.remove()
logger.add(
    lambda msg: print(msg, end=""),
    level="INFO",
    colorize=True,
    format="<level>{message}</level>",
)
logger.add(
    "registration.log",
    level="INFO",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
)


@dataclass
class Config:
    accounts_filename: str = "acc.txt"
    proxies_filename: str = "proxies.txt"
    mail_filename: str = "mail.txt"
    anti_captcha_api_key: str = "e1f72ea3d76556d76c225779d33d2ca5"

    max_browsers: int = 10
    browser_headless: bool = False

    page_load_timeout: int = 15
    action_delay: float = 0.2

    delay_min: int = 60
    delay_max: int = 180
    threads: int = 1

    browser_args: List[str] = field(
        default_factory=lambda: [
            "--no-sandbox",
            "--disable-gpu",
            "--disable-dev-shm-usage",
            "--disable-extensions",
            "--disable-setuid-sandbox",
            "--disable-infobars",
            "--disable-web-security",
            "--disable-features=IsolateOrigins,site-per-process",
            "--disable-site-isolation-trials",
            "--ignore-certificate-errors",
            "--disable-accelerated-2d-canvas",
            "--disable-browser-side-navigation",
            "--disable-default-apps",
            "--no-first-run",
        ]
    )

    browser_context_options: Dict[str, Any] = field(
        default_factory=lambda: {
            "viewport": {"width": 1920, "height": 1080},
            "locale": "ru-RU",
            "timezone_id": "Europe/Moscow",
            "ignore_https_errors": True,
            "java_script_enabled": True,
        }
    )

    ads_power_api_base: str = "http://localhost:50325"
    ads_power_api_key: str = "e4cf1cac956e81436db4d85148785714009587733954aaac"
    ads_power_path: str = r"C:\Program Files\AdsPower Global"
    ads_power_group_id: str = "0"
    delete_profile_after_use: bool = True


class AdsPowerManager:
    def __init__(self, config: Config):
        self.config = config
        self.created_profile_ids: List[str] = []
        self._headers = {}
        if config.ads_power_api_key:
            self._headers["Authorization"] = f"Bearer {config.ads_power_api_key}"

    def _api_get(self, endpoint: str, params: dict = None) -> dict:
        url = f"{self.config.ads_power_api_base}{endpoint}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers=self._headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _api_post(self, endpoint: str, body: dict = None) -> dict:
        url = f"{self.config.ads_power_api_base}{endpoint}"
        data = json.dumps(body).encode("utf-8") if body else None
        req = urllib.request.Request(url, data=data, headers=self._headers, method="POST")
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))

    async def ensure_ads_power_running(self) -> bool:
        loop = asyncio.get_event_loop()
        try:
            result = await loop.run_in_executor(None, self._api_get, "/status")
            if result.get("code") == 0:
                return True
        except Exception:
            pass
        exe_path = os.path.join(self.config.ads_power_path, "AdsPower Global.exe")
        if not os.path.exists(exe_path):
            return False
        try:
            subprocess.Popen([exe_path], shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            return False
        for _ in range(60):
            await asyncio.sleep(1)
            try:
                result = await loop.run_in_executor(None, self._api_get, "/status")
                if result.get("code") == 0:
                    return True
            except Exception:
                continue
        return False

    async def delete_profiles(self, profile_ids: List[str]):
        if not profile_ids:
            return
        loop = asyncio.get_event_loop()
        try:
            result = await loop.run_in_executor(None, self._api_post, "/api/v1/user/delete", {"user_ids": profile_ids})
            if result.get("code") == 0:
                logger.info(f"Deleted {len(profile_ids)} profiles")
        except Exception as e:
            logger.warning(f"Delete error: {e}")

    def _default_fingerprint(self) -> dict:
        return {
            "automatic_timezone": "1",
            "language": ["ru-RU", "ru"],
            "ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            "resolution": "1920x1080",
            "fonts": ["all"],
            "webrtc": "disabled",
            "canvas": "1",
            "webgl": "1",
            "location": "allow",
            "popups_blocker": "1",
        }

    async def create_profile(self, name: str = None, proxy: dict = None) -> Optional[str]:
        if not name:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            rand = random.randint(1000, 9999)
            name = f"funpay_{ts}_{rand}"
        body: dict = {
            "name": name,
            "group_id": self.config.ads_power_group_id,
            "domain_name": "funpay.com",
            "fingerprint_config": self._default_fingerprint(),
        }
        if proxy:
            server = proxy.get("server", "")
            detected_type = "http"
            if server.startswith("socks5://"):
                detected_type = "socks5"
            proxy_type = proxy.get("proxy_type", detected_type)
            server_clean = server.replace("http://", "").replace("https://", "").replace("socks5://", "")
            if ":" in server_clean:
                ip_part, port_part = server_clean.split(":", 1)
                proxy_cfg = {
                    "proxy_type": proxy_type,
                    "proxy_host": ip_part,
                    "proxy_port": port_part,
                    "proxy_soft": "other",
                }
                if proxy.get("username"):
                    proxy_cfg["proxy_user"] = proxy["username"]
                if proxy.get("password"):
                    proxy_cfg["proxy_password"] = proxy["password"]
                body["user_proxy_config"] = proxy_cfg
        loop = asyncio.get_event_loop()
        try:
            result = await loop.run_in_executor(None, self._api_post, "/api/v2/browser-profile/create", body)
            if result.get("code") == 0:
                profile_id = result["data"]["profile_id"]
                self.created_profile_ids.append(profile_id)
                return profile_id
            else:
                logger.error(f"Create profile error: {result.get('msg', result)}")
                return None
        except Exception as e:
            logger.error(f"Create profile error: {e}")
            return None

    async def start_profile(self, profile_id: str) -> Optional[str]:
        payload = {
            "profile_id": profile_id,
            "open_urls": "https://funpay.com/en/account/register",
            "ip_tab": "0",
            "launch_args": ["--lang=ru-RU", "--accept-lang=ru-RU,ru;q=0.9"],
        }
        loop = asyncio.get_event_loop()
        for attempt in range(5):
            try:
                result = await loop.run_in_executor(None, self._api_post, "/api/v2/browser-profile/start", payload)
                if result.get("code") == 0:
                    cdp_url = result["data"]["ws"]["puppeteer"]
                    logger.success(f"🔗 CDP: {cdp_url}")
                    await asyncio.sleep(3)
                    return cdp_url
                logger.warning(f"Start attempt {attempt+1}: {result.get('msg')}")
            except Exception as e:
                logger.warning(f"Start attempt {attempt+1}: {e}")
            await asyncio.sleep(2)
        return None

    async def stop_profile(self, profile_id: str):
        loop = asyncio.get_event_loop()
        try:
            await loop.run_in_executor(None, self._api_get, "/api/v1/browser/stop", {"user_id": profile_id})
        except Exception:
            pass

    async def cleanup(self):
        for pid in self.created_profile_ids:
            await self.stop_profile(pid)
            if self.config.delete_profile_after_use:
                await self.delete_profiles([pid])
        self.created_profile_ids.clear()


class IMAPMailManager:
    """Управление почтой через IMAP (imap.rambler.ru).
    Аккаунты читаются из mail.txt в формате login:pass"""

    def __init__(self, config: Config):
        self.config = config
        self._lock = asyncio.Lock()
        self._accounts: List[Dict[str, str]] = []
        self._account_index = 0
        self._load_accounts()

    def _load_accounts(self):
        filename = self.config.mail_filename
        try:
            with open(filename, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and ":" in line:
                        login, password = line.split(":", 1)
                        self._accounts.append({"login": login.strip(), "password": password.strip()})
            logger.success(f"📧 Загружено {len(self._accounts)} аккаунтов из {filename}")
            if not self._accounts:
                logger.error(f"❌ Файл {filename} пуст!")
        except FileNotFoundError:
            logger.error(f"❌ Файл {filename} не найден!")
        except Exception as e:
            logger.error(f"❌ Ошибка загрузки {filename}: {e}")

    async def create_email(self) -> Optional[Dict[str, Any]]:
        """Берёт следующий аккаунт из пула без IMAP проверки."""
        async with self._lock:
            if not self._accounts:
                logger.error("Нет аккаунтов в mail.txt!")
                return None

            acc = self._accounts[self._account_index]
            self._account_index = (self._account_index + 1) % len(self._accounts)

            return {
                "email": acc["login"],
                "password": acc["password"],
                "jwt": acc["login"],
            }

    async def get_verification_code(self, email_login: str) -> Optional[str]:
        """Получает код подтверждения через IMAP"""
        password = ""
        for acc in self._accounts:
            if acc["login"] == email_login:
                password = acc["password"]
                break

        if not password:
            logger.error(f"Пароль для {email_login} не найден в mail.txt!")
            return None

        logger.info(f"📩 IMAP: imap.rambler.ru для {email_login}")
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._fetch_code_imap, email_login, password)

    def _fetch_code_imap(self, email: str, password: str) -> Optional[str]:
        for attempt in range(24):
            try:
                mail = imaplib.IMAP4_SSL("imap.rambler.ru", 993)
                mail.login(email, password)
                mail.select("INBOX")

                status, messages = mail.search(None, "UNSEEN")
                if status != "OK":
                    mail.logout()
                    time.sleep(5)
                    continue

                message_ids = messages[0].split() if messages[0] else []
                if not message_ids:
                    logger.info(f"📭 Новых писем нет (попытка {attempt+1}/24)")
                    status, all_msgs = mail.search(None, "ALL")
                    if status == "OK":
                        all_ids = all_msgs[0].split() if all_msgs[0] else []
                        if all_ids:
                            message_ids = all_ids[-3:]

                if not message_ids:
                    mail.logout()
                    time.sleep(5)
                    continue

                logger.info(f"📬 Проверяем {len(message_ids)} писем (попытка {attempt+1}/24)")

                for mid in reversed(message_ids):
                    status, msg_data = mail.fetch(mid, "(RFC822)")
                    if status != "OK":
                        continue

                    for response_part in msg_data:
                        if not isinstance(response_part, tuple):
                            continue

                        try:
                            msg = email_lib.message_from_bytes(response_part[1])
                            subject = msg.get("Subject", "").lower()
                            sender = msg.get("From", "").lower()
                            logger.info(f"   From: {sender}, Subject: {subject[:80]}")

                            if not any(kw in subject + sender for kw in
                                       ["funpay", "registration", "verify", "confirm", "noreply", "регистрац"]):
                                logger.info(f"   ⏭️ Пропускаем")
                                continue

                            body = ""
                            try:
                                if msg.is_multipart():
                                    for part in msg.walk():
                                        ct = part.get_content_type()
                                        if ct in ("text/plain", "text/html"):
                                            try:
                                                body += part.get_payload(decode=True).decode("utf-8", errors="ignore")
                                            except Exception:
                                                pass
                                else:
                                    body = msg.get_payload(decode=True).decode("utf-8", errors="ignore")
                            except Exception:
                                pass

                            logger.info(f"   📄 Тело: {body[:300]}")

                            matches = re.findall(r"\b(\d{6,8})\b", body)
                            for match in matches:
                                if match.isdigit() and len(match) >= 6:
                                    logger.success(f"✅ Код найден: {match}")
                                    mail.logout()
                                    return match

                        except Exception as e:
                            logger.warning(f"Ошибка парсинга: {e}")
                            continue

                mail.logout()

            except imaplib.IMAP4.error as e:
                logger.warning(f"IMAP ошибка (попытка {attempt+1}/24): {e}")
            except Exception as e:
                logger.warning(f"Ошибка IMAP (попытка {attempt+1}/24): {type(e).__name__}: {e}")

            time.sleep(5)

        logger.warning("Код не получен за 2 минуты")
        return None


class ProxyManager:
    def __init__(self, config: Config):
        self.proxies = []
        self.current_index = 0
        self.load_proxies(config.proxies_filename)

    def load_proxies(self, filename: str):
        try:
            with open(filename, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and ":" in line:
                        parts = line.split(":")
                        if len(parts) == 4:
                            ip, port, username, password = parts
                            self.proxies.append({
                                "server": f"http://{ip}:{port}",
                                "username": username,
                                "password": password,
                            })
            logger.success(f"🌍 Загружено {len(self.proxies)} прокси из {filename}")
        except FileNotFoundError:
            logger.error(f"Файл {filename} не найден!")
        except Exception as e:
            logger.error(f"Ошибка загрузки прокси: {e}")

    def get_next_proxy(self) -> Optional[Dict]:
        if not self.proxies:
            return None
        proxy = self.proxies[self.current_index]
        self.current_index = (self.current_index + 1) % len(self.proxies)
        return proxy


class DataGenerator:
    @staticmethod
    def generate_username() -> str:
        adjectives = ["cool", "fast", "pro", "mega", "super", "ultra", "best", "top", "nice", "gold"]
        nouns = ["player", "gamer", "user", "hero", "star", "king", "ace", "pro", "wolf", "fox"]
        adj = random.choice(adjectives)
        noun = random.choice(nouns)
        num = random.randint(10, 9999)
        return f"{adj}{noun}{num}"

    @staticmethod
    def generate_password(length: int = 12) -> str:
        chars = string.ascii_letters + string.digits + "_"
        return ''.join(random.choices(chars, k=length))


class AntiCaptchaSolver:
    """Решение капчи через anti-captcha.com API.
    Поддерживает: Cloudflare Turnstile, reCAPTCHA v2, hCaptcha"""

    BASE_URL = "https://api.anti-captcha.com"

    def __init__(self, api_key: str):
        self.api_key = api_key

    def _post(self, endpoint: str, body: dict) -> dict:
        url = f"{self.BASE_URL}/{endpoint}"
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            return {"errorId": 1, "errorDescription": str(e)}

    def solve_turnstile(self, website_url: str, sitekey: str, proxy: Optional[Dict] = None) -> Optional[str]:
        """Решает Cloudflare Turnstile через anti-captcha.com.
        Сначала пробует с прокси (если есть), при ошибке прокси — Proxyless."""
        if not self.api_key or self.api_key == "твой_ключ_сюда":
            logger.warning("Anti-Captcha API ключ не настроен")
            return None

        attempts = []
        if proxy:
            attempts.append(("TurnstileTask", proxy))
        attempts.append(("TurnstileTaskProxyless", None))

        for task_type, used_proxy in attempts:
            task_body = {
                "type": task_type,
                "websiteURL": website_url,
                "websiteKey": sitekey,
            }

            if used_proxy:
                server = used_proxy.get("server", "")
                username = used_proxy.get("username", "")
                password = used_proxy.get("password", "")
                server_clean = server.replace("http://", "").replace("https://", "").replace("socks5://", "")
                parts = server_clean.split(":") if ":" in server_clean else [server_clean, "80"]
                ip_part = parts[0].strip()
                port_part = parts[1].strip() if len(parts) > 1 else "80"
                proxy_cfg = {
                    "proxyType": "http",
                    "proxyAddress": ip_part,
                    "proxyPort": int(port_part),
                }
                if username and password:
                    proxy_cfg["proxyLogin"] = username
                    proxy_cfg["proxyPassword"] = password
                task_body.update(proxy_cfg)
                logger.info(f"🤖 Попытка {task_type} с прокси {ip_part}:{port_part}")
            else:
                logger.info(f"🤖 Попытка {task_type}")

            task = self._post("createTask", {"clientKey": self.api_key, "task": task_body})
            task_id = task.get("taskId")
            err_desc = task.get("errorDescription", "")

            if task_id:
                logger.info(f"🤖 Задача #{task_id} создана, ждём...")
                for _ in range(60):
                    time.sleep(3)
                    result = self._post("getTaskResult", {"clientKey": self.api_key, "taskId": task_id})
                    if result.get("status") == "ready":
                        token = result.get("solution", {}).get("token", "")
                        if token:
                            logger.success(f"🤖 Токен получен ({len(token)} символов)")
                            return token
                        logger.error("Anti-Captcha: токен пустой")
                        return None
                    if result.get("errorId", 0) != 0:
                        logger.error(f"Anti-Captcha: {result.get('errorDescription', result)}")
                        break
                    if _ % 5 == 0:
                        logger.info(f"🤖 Ждём... ({_*3}с)")

            proxy_keywords = ["proxy", "connection", "refused", "slow", "timeout", "unreachable"]
            if used_proxy and any(kw in err_desc.lower() for kw in proxy_keywords):
                logger.warning(f"🤖 Прокси не работает ({err_desc[:60]}), пробуем Proxyless...")
                continue

            if not task_id:
                logger.warning(f"Anti-Captcha: {err_desc}")
                continue

            break  

        return None

        task_id = task.get("taskId")
        if not task_id:
            logger.error(f"Anti-Captcha: ошибка создания задачи: {task.get('errorDescription', task)}")
            return None

        logger.info(f"🤖 Anti-Captcha: задача #{task_id} создана, ждём результат...")
        for _ in range(60):
            time.sleep(3)
            result = self._post("getTaskResult", {
                "clientKey": self.api_key,
                "taskId": task_id,
            })
            status = result.get("status", "")
            if status == "ready":
                token = result.get("solution", {}).get("token", "")
                if token:
                    logger.success(f"🤖 Anti-Captcha: токен получен ({len(token)} символов)")
                    return token
                logger.error("Anti-Captcha: токен пустой")
                return None
            if result.get("errorId", 0) != 0:
                logger.error(f"Anti-Captcha: ошибка: {result.get('errorDescription', result)}")
                return None
            if _ % 5 == 0:
                logger.info(f"🤖 Anti-Captcha: ждём... ({_*3}с)")

        logger.warning("Anti-Captcha: таймаут ожидания результата")
        return None

    def solve_recaptcha_v2(self, website_url: str, sitekey: str) -> Optional[str]:
        """Решает reCAPTCHA v2"""
        if not self.api_key or self.api_key == "твой_ключ_сюда":
            return None

        logger.info(f"🤖 Anti-Captcha: reCAPTCHA v2 для {sitekey[:20]}...")
        task = self._post("createTask", {
            "clientKey": self.api_key,
            "task": {
                "type": "NoCaptchaTaskProxyless",
                "websiteURL": website_url,
                "websiteKey": sitekey,
            }
        })

        task_id = task.get("taskId")
        if not task_id:
            logger.error(f"Anti-Captcha: ошибка: {task.get('errorDescription', task)}")
            return None

        logger.info(f"🤖 Задача #{task_id} создана, ждём...")
        for _ in range(60):
            time.sleep(3)
            result = self._post("getTaskResult", {
                "clientKey": self.api_key,
                "taskId": task_id,
            })
            if result.get("status") == "ready":
                token = result.get("solution", {}).get("gRecaptchaResponse", "")
                if token:
                    logger.success("🤖 reCAPTCHA токен получен")
                    return token
                return None
            if result.get("errorId", 0) != 0:
                logger.error(f"Anti-Captcha: ошибка: {result.get('errorDescription')}")
                return None

        return None


class FunPayRegistration:
    def __init__(self, config: Config, output_folder: str = "accounts"):
        self.config = config
        self.proxy_manager = ProxyManager(config)
        self.data_generator = DataGenerator()
        self.mail_manager = IMAPMailManager(config)
        self.ads_power = AdsPowerManager(config)
        self.captcha_solver = AntiCaptchaSolver(config.anti_captcha_api_key)
        self.current_proxy = None
        self.successful_accounts = []
        self.failed_count = 0
        self.accounts_output_folder = output_folder
        self._account_counter = 0
        self._counter_lock = None
        os.makedirs(self.accounts_output_folder, exist_ok=True)

    async def register_account(self) -> bool:
        mail_data = await self.mail_manager.create_email()
        if not mail_data:
            logger.error("Нет почтовых аккаунтов в mail.txt!")
            return False

        mail_email = mail_data["email"]
        mail_password = mail_data["password"]

        username = self.data_generator.generate_username()
        password = self.data_generator.generate_password()

        for mail_attempt in range(max(len(self.mail_manager._accounts), 1) if self.mail_manager._accounts else 5):
            try:
                result = await self._try_register(
                    username, mail_email, mail_password, password
                )
                return result
            except Exception as e:
                logger.warning(f"Ошибка регистрации: {e}")
                logger.info("Пробуем следующий email...")
                mail_data = await self.mail_manager.create_email()
                if not mail_data:
                    return False
                mail_email = mail_data["email"]
                mail_password = mail_data["password"]
                username = self.data_generator.generate_username()
                password = self.data_generator.generate_password()
                continue

        return False

    async def _try_register(
        self,
        username: str,
        email: str,
        mail_password: str,
        password: str,
    ) -> bool:
        proxy = self.proxy_manager.get_next_proxy()
        self.current_proxy = proxy  
        logger.info(f"🌍 Прокси: {proxy.get('server', 'N/A') if proxy else 'N/A'}")

        profile_id = await self.ads_power.create_profile(proxy=proxy)
        if not profile_id:
            self.failed_count += 1
            return False

        logger.success(f"✅ Профиль создан: {profile_id}")

        cdp_url = await self.ads_power.start_profile(profile_id)
        if not cdp_url:
            await self.ads_power.stop_profile(profile_id)
            await self.ads_power.delete_profiles([profile_id])
            self.failed_count += 1
            return False

        try:
            async with async_playwright() as p:
                browser = await p.chromium.connect_over_cdp(cdp_url)
                context = browser.contexts[0] if browser.contexts else await browser.new_context()
                page = await context.new_page()
                page.set_default_timeout(self.config.page_load_timeout * 1000)

                try:
                    logger.info("Открываем страницу регистрации FunPay")
                    await page.goto(
                        "https://funpay.com/en/account/register",
                        timeout=60000,
                    )
                    await asyncio.sleep(3)

                    success = await self._fill_registration_form(
                        page, username, email, password
                    )

                    if success:
                        logger.success("✅ Форма отправлена! Сохраняем аккаунт...")
                        await self._save_cookies_json(page, email, password, email, mail_password)
                        self._save_account(f"{username}:{password}:{email}:{mail_password}")

                        await asyncio.sleep(3)
                        try:
                            page_content = await page.content()
                            content_lower = page_content.lower()

                            if any(kw in content_lower for kw in [
                                "требуется активация", "отправлено письмо", "активируйте",
                                "подтвердите", "confirm your email", "verify",
                                "activation", "check your email"
                            ]):
                                logger.info("📧 Нужна активация email — обрабатываем...")
                                activated = await self._handle_email_verification(page, email, mail_password)
                                if activated:
                                    logger.success("✅ Email активирован!")
                                else:
                                    logger.warning("⚠️ Email не активирован, но аккаунт создан")
                            else:
                                logger.success("✅ Активация не требуется")
                        except Exception as e:
                            logger.warning(f"Ошибка проверки активации: {e}")

                        logger.success(f"✅ Регистрация завершена! {username}:{password}:{email}:{mail_password}")

                        try:
                            with open(self.config.mail_filename, "r", encoding="utf-8") as f:
                                lines = f.readlines()
                            with open(self.config.mail_filename, "w", encoding="utf-8") as f:
                                for line in lines:
                                    if line.strip() and email not in line:
                                        f.write(line)
                            self.mail_manager._accounts = [a for a in self.mail_manager._accounts if a["login"] != email]
                            logger.info(f"📧 {email} удалена из {self.config.mail_filename}")
                        except Exception:
                            pass

                        if KEEP_OPEN:
                            logger.info("🔓 Браузер открыт. Нажми Enter чтобы закрыть...")
                            loop = asyncio.get_event_loop()
                            await loop.run_in_executor(None, input)

                        return True
                    else:
                        self.failed_count += 1
                        return False

                except Exception as e:
                    logger.error(f"Ошибка: {type(e).__name__}: {str(e)}")
                    self.failed_count += 1
                    return False
                finally:
                    if not KEEP_OPEN:
                        await browser.close()
                    else:
                        try:
                            await browser.close()
                        except Exception:
                            pass

        except Exception as e:
            logger.error(f"Critical: {type(e).__name__}: {str(e)}")
            self.failed_count += 1
            return False
        finally:
            await self.ads_power.stop_profile(profile_id)
            if self.config.delete_profile_after_use:
                await self.ads_power.delete_profiles([profile_id])

    async def _detect_captcha(self, page: Page) -> Dict[str, Any]:
        """Ищет капчу на странице и логирует её тип, ID, фреймы."""
        result = {"found": False, "type": None, "sitekey": "", "ids": [], "details": ""}
        details = []

        recaptcha = await page.query_selector('iframe[src*="recaptcha"]')
        if recaptcha:
            src = await recaptcha.get_attribute("src") or ""
            sitekey = ""
            if "k=" in src:
                sitekey = src.split("k=")[1].split("&")[0]
            cid = await recaptcha.get_attribute("id") or ""
            result["found"] = True
            result["type"] = "reCAPTCHA v2"
            result["ids"].append(f"reCAPTCHA: id={cid}, sitekey={sitekey[:20]}..")
            details.append(f"reCAPTCHA_v2 sitekey={sitekey[:20]}..")

        recaptcha_v3 = await page.query_selector('script[src*="recaptcha/api.js"]')
        if recaptcha_v3:
            result["found"] = True
            result["type"] = result["type"] or "reCAPTCHA v3"
            details.append("reCAPTCHA_v3 (невидимая)")

        hcaptcha = await page.query_selector('iframe[src*="hcaptcha"]')
        if hcaptcha:
            src = await hcaptcha.get_attribute("src") or ""
            sitekey = ""
            if "sitekey=" in src:
                sitekey = src.split("sitekey=")[1].split("&")[0]
            cid = await hcaptcha.get_attribute("id") or ""
            result["found"] = True
            result["type"] = "hCaptcha"
            result["ids"].append(f"hCaptcha: id={cid}, sitekey={sitekey[:20]}..")
            details.append(f"hCaptcha sitekey={sitekey[:20]}..")

        turnstile_sitekey = ""
        turnstile = await page.query_selector('iframe[src*="turnstile"]')
        if not turnstile:
            turnstile = await page.query_selector('[class*="cf-turnstile"]')
        if turnstile:
            sitekey = await turnstile.get_attribute("data-sitekey") or ""
            if not sitekey:
                inner = await turnstile.query_selector('[data-sitekey]')
                if inner:
                    sitekey = await inner.get_attribute("data-sitekey") or ""
            if not sitekey:
                try:
                    sitekey = await page.evaluate("""
                        () => document.querySelector('[data-sitekey]')?.getAttribute('data-sitekey')
                            || window.turnstile?.getSiteKey?.()
                            || ''
                    """) or ""
                except Exception:
                    pass
            turnstile_sitekey = sitekey
            result["found"] = True
            result["type"] = "Cloudflare Turnstile"
            result["sitekey"] = sitekey
            cid = await turnstile.get_attribute("id") or "cf-turnstile"
            result["ids"].append(f"Turnstile: id={cid}, sitekey={sitekey[:20] if sitekey else 'N/A'}")
            details.append(f"Cloudflare Turnstile sitekey={sitekey[:20] if sitekey else 'N/A'}..")

        for sel in [
            '.captcha',
            '[data-testid="captcha"]',
            'div[class*="captcha"]',
            'div[class*="recaptcha"]',
            'div[class*="hcaptcha"]',
            'div[class*="turnstile"]',
            '[id*="captcha"]',
            '[id*="recaptcha"]',
        ]:
            try:
                els = await page.query_selector_all(sel)
                for el in els:
                    if await el.is_visible():
                        eid = await el.get_attribute("id") or ""
                        eclass = await el.get_attribute("class") or ""
                        result["found"] = True
                        result["type"] = result["type"] or "Generic"
                        result["ids"].append(f"{sel}: id={eid}, class={eclass[:50]}")
                        details.append(f"Generic captcha: {sel}")
                        break
            except Exception:
                continue

        try:
            content = await page.content()
            content_lower = content.lower()
            for kw in ["recaptcha", "hcaptcha", "turnstile", "captcha", "i am not a robot", "я не робот"]:
                if kw in content_lower:
                    if kw not in [d.lower() for d in details]:
                        details.append(f"Найдено в DOM: '{kw}'")
                        result["found"] = True
                        if not result["type"]:
                            result["type"] = kw
        except Exception:
            pass

        if details:
            result["details"] = " | ".join(details)
            logger.warning(f"⚠️ Капча обнаружена: {result['details']}")
        else:
            logger.success("✅ Капча не обнаружена")

        return result

    async def _handle_email_verification(self, page: Page, email: str, mail_password: str) -> bool:
        """Подтверждает email через ссылку активации из письма FunPay."""
        logger.info("📧 Ждём письмо активации от FunPay на почте...")

        activation_url = await self._get_activation_link(email, mail_password)
        if not activation_url:
            logger.warning("Ссылка активации не получена")
            return False

        logger.success(f"📧 Ссылка активации: {activation_url}")

        try:
            await page.goto(activation_url, timeout=30000)
            await asyncio.sleep(5)
            logger.success(f"✅ Страница активации открыта: {page.url}")
        except Exception as e:
            logger.warning(f"Ошибка перехода по ссылке: {e}")
            return False

        for i in range(10):
            await asyncio.sleep(2)
            try:
                content = (await page.content()).lower()
                for ok_text in [
                    "учетная запись активирована",
                    "активация прошла успешно",
                    "account activated",
                    "activation successful",
                    "successfully activated",
                    "activated",
                    "добро пожаловать",
                    "welcome",
                ]:
                    if ok_text in content:
                        logger.success(f"✅ Активация успешна! Найдено: '{ok_text}'")
                        return True
            except Exception:
                pass

        logger.info("Страница активации открыта, продолжаем...")
        return True

    async def _get_activation_link(self, email: str, password: str) -> Optional[str]:
        """Достаёт ссылку активации из письма FunPay через IMAP."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._fetch_activation_link, email, password)

    def _fetch_activation_link(self, email: str, password: str) -> Optional[str]:
        """IMAP: ищет письмо от FunPay и достаёт ссылку активации."""
        for attempt in range(30):   
            try:
                mail = imaplib.IMAP4_SSL("imap.rambler.ru", 993, timeout=15)
                mail.login(email, password)
                mail.select("INBOX")

                status, ids = mail.search(None, "UNSEEN")
                msg_ids = ids[0].split() if ids[0] else []

                if not msg_ids:
                    status, all_ids = mail.search(None, "ALL")
                    msg_ids = all_ids[0].split()[-5:] if all_ids[0] else []

                if msg_ids:
                    logger.info(f"📬 Писем: {len(msg_ids)} (попытка {attempt+1}/30)")

                for mid in reversed(msg_ids):
                    status, data = mail.fetch(mid, "(RFC822)")
                    if status != "OK":
                        continue
                    for part in data:
                        if not isinstance(part, tuple):
                            continue
                        try:
                            msg = email_lib.message_from_bytes(part[1])
                            subject = (msg.get("Subject", "") or "").lower()
                            sender = (msg.get("From", "") or "").lower()
                            logger.info(f"   From: {sender[:40]}, Subject: {subject[:60]}")

                            if "funpay" not in sender and "funpay" not in subject and "активац" not in subject:
                                continue

                            body = ""
                            if msg.is_multipart():
                                for p in msg.walk():
                                    ct = p.get_content_type()
                                    if ct in ("text/plain", "text/html"):
                                        try:
                                            body += p.get_payload(decode=True).decode("utf-8", errors="ignore")
                                        except Exception:
                                            pass
                            else:
                                body = msg.get_payload(decode=True).decode("utf-8", errors="ignore")

                            urls = re.findall(r'https?://[^\s"\'<>]+', body)
                            for url in urls:
                                url_clean = url.split("&")[0].rstrip(".)")
                                if "funpay.com" in url_clean and ("activate" in url_clean or "confirm" in url_clean or "reg" in url_clean):
                                    logger.success(f"✅ Найдена ссылка активации: {url_clean}")
                                    mail.logout()
                                    return url_clean

                            for url in urls:
                                url_clean = url.split("&")[0].rstrip(".)")
                                if "funpay.com" in url_clean and "account" in url_clean:
                                    logger.success(f"✅ Найдена ссылка: {url_clean}")
                                    mail.logout()
                                    return url_clean

                        except Exception:
                            continue

                mail.logout()

            except imaplib.IMAP4.error as e:
                logger.warning(f"IMAP: {e}")
            except Exception as e:
                logger.warning(f"Ошибка IMAP: {type(e).__name__}: {e}")

            time.sleep(5)

        logger.warning("Ссылка активации не найдена за 2.5 мин")
        return None

    async def _fill_registration_form(
        self,
        page: Page,
        username: str,
        email: str,
        password: str,
    ) -> bool:
        try:
            await asyncio.sleep(2)

            logger.info("Обработка cookie consent...")
            for sel in [
                'button:has-text("Agree to all")',
                'button:has-text("Accept all")',
                'button:has-text("Accept")',
                'button:has-text("Принять")',
                'button:has-text("OK")',
                'button:has-text("Got it")',
                '#cookie-notice button',
                '.cookie-consent button',
                '[data-cookie="accept"]',
            ]:
                try:
                    btn = await page.query_selector(sel)
                    if btn and await btn.is_visible():
                        await btn.click()
                        logger.success("Cookie consent принят")
                        await asyncio.sleep(1)
                        break
                except Exception:
                    continue

            logger.info(f"Заполняем форму: username={username}, email={email}")

            username_filled = False
            
            for sel in [
                '.register-form input[name="login"]',
                '.register-form input:not([name="query"])',
                '#registerForm input[name="login"]',
                '#registerForm input:not([name="query"])',
                'form input[name="login"]',
                'form input:not([type="hidden"]):not([name="query"])',
                'input[name="username"]',
                'input#username',
                'input[name="login"]',
                'input#login',
                'input[autocomplete="username"]',
                'input[placeholder*="name" i]',
                'input[placeholder*="nick" i]',
                'input[placeholder*="login" i]',
                'input[name="nick"]',
                'input[name="nickname"]',
                'input[name="user"]',
                'input[autocomplete="nickname"]',
            ]:
                try:
                    inp = await page.query_selector(sel)
                    if inp and await inp.is_visible():
                        inp_name = await inp.get_attribute("name") or ""
                        inp_ph = await inp.get_attribute("placeholder") or ""
                        if inp_name == "query" or "поиск" in inp_ph.lower():
                            continue
                        await inp.click()
                        await asyncio.sleep(0.1)
                        await inp.type(username, delay=random.randint(50, 80))
                        username_filled = True
                        logger.success(f"Username введён ({sel}): {username}")
                        await asyncio.sleep(0.3)
                        break
                except Exception:
                    continue

            if not username_filled:
                try:
                    all_inputs = await page.query_selector_all(
                        'input:not([type="email"]):not([type="password"]):not([type="checkbox"]):not([type="hidden"]):not([type="submit"]):not([type="search"])'
                    )
                    for inp in all_inputs:
                        if await inp.is_visible():
                            inp_name = await inp.get_attribute("name") or ""
                            inp_ph = await inp.get_attribute("placeholder") or ""
                            skip_kw = ["email", "checkbox", "submit", "search", "поиск", "query", "search"]
                            if any(kw in inp_name.lower() or kw in inp_ph.lower() for kw in skip_kw):
                                continue
                            await inp.click()
                            await asyncio.sleep(0.1)
                            await inp.type(username, delay=random.randint(50, 80))
                            username_filled = True
                            logger.success(f"Username введён (fallback): name={inp_name}, placeholder={inp_ph}")
                            await asyncio.sleep(0.3)
                            break
                except Exception as e:
                    logger.warning(f"Ошибка fallback: {e}")

            if not username_filled:
                logger.warning("Поле username не найдено — пропускаем")

            email_filled = False
            for sel in [
                'input[name="email"]',
                'input[type="email"]',
                'input#email',
                'input[placeholder*="email"]',
                'input[placeholder*="Email"]',
            ]:
                try:
                    inp = await page.query_selector(sel)
                    if inp and await inp.is_visible():
                        await inp.click()
                        await asyncio.sleep(0.1)
                        await inp.type(email, delay=random.randint(50, 80))
                        email_filled = True
                        logger.success(f"Email введён: {email}")
                        await asyncio.sleep(0.3)
                        break
                except Exception:
                    continue

            if not email_filled:
                logger.error("Поле email не найдено!")
                return False

            pw_filled = False
            for sel in [
                'input[name="password"]',
                'input[type="password"]',
                'input#password',
                'input[placeholder*="password"]',
                'input[placeholder*="Password"]',
                'input[placeholder*="пароль"]',
            ]:
                try:
                    inp = await page.query_selector(sel)
                    if inp and await inp.is_visible():
                        await inp.click()
                        await asyncio.sleep(0.1)
                        await inp.type(password, delay=random.randint(50, 80))
                        pw_filled = True
                        logger.success(f"Пароль введён")
                        await asyncio.sleep(0.3)
                        break
                except Exception:
                    continue

            if not pw_filled:
                logger.error("Поле пароля не найдено!")
                return False

            await asyncio.sleep(0.5)

            logger.info("Ищем чекбокс соглашения...")
            checkbox_clicked = False
            for sel in [
                'label:has-text("User agreement")',
                'label:has-text("agree")',
                'label:has-text("rules")',
                'label:has-text("согласен")',
                '.checkbox label',
                '.agreement input',
                '.terms input',
                'input[type="checkbox"]',
            ]:
                try:
                    el = await page.query_selector(sel)
                    if not el:
                        continue

                    tag = await el.evaluate("el => el.tagName.toLowerCase()")
                    if tag == "input":
                        if not await el.is_checked():
                            await el.click()
                            logger.success("Чекбокс отмечен (input)")
                            checkbox_clicked = True
                            await asyncio.sleep(0.3)
                            break
                    else:
                        await el.click()
                        logger.success("Чекбокс отмечен (label)")
                        checkbox_clicked = True
                        await asyncio.sleep(0.3)
                        break
                except Exception:
                    continue

            if not checkbox_clicked:
                try:
                    checkboxes = await page.query_selector_all('input[type="checkbox"]')
                    for cb in checkboxes:
                        if await cb.is_visible():
                            if not await cb.is_checked():
                                await cb.click()
                                logger.success("Чекбокс отмечен (первый)")
                                await asyncio.sleep(0.3)
                                break
                except Exception:
                    pass

            await asyncio.sleep(0.5)

            logger.info("Ищем кнопку регистрации...")
            signup_clicked = False
            for sel in [
                'button[type="submit"]',
                'button:has-text("Зарегистрироваться")',
                'button:has-text("Sign Up")',
                'button:has-text("Register")',
                'button:has-text("Create account")',
                'button:has-text("Регистрация")',
                'button:has-text("Зарегистрировать")',
                'input[type="submit"]',
            ]:
                try:
                    btn = await page.query_selector(sel)
                    if btn and await btn.is_visible() and await btn.is_enabled():
                        await btn.click()
                        signup_clicked = True
                        logger.success("Sign Up нажата")
                        await asyncio.sleep(3)
                        break
                except Exception:
                    continue

            if not signup_clicked:
                try:
                    buttons = await page.query_selector_all("button")
                    for btn in buttons:
                        txt = await btn.inner_text()
                        if await btn.is_visible() and await btn.is_enabled():
                            await btn.click()
                            signup_clicked = True
                            logger.success(f"Нажата кнопка: {txt.strip()}")
                            await asyncio.sleep(3)
                            break
                except Exception:
                    pass

            if not signup_clicked:
                logger.error("Не найдена кнопка регистрации!")
                return False

            await asyncio.sleep(2)
            captcha_info = await self._detect_captcha(page)
            if captcha_info["found"]:
                solved = False

                if captcha_info.get("sitekey"):
                    logger.info(f"🤖 Пробуем Anti-Captcha: {captcha_info['type']} sitekey={captcha_info['sitekey'][:20]}...")
                    token = None
                    api_key = self.config.anti_captcha_api_key
                    if api_key and api_key != "твой_ключ_сюда":
                        if "turnstile" in captcha_info["type"].lower():
                            token = self.captcha_solver.solve_turnstile(
                                "https://funpay.com/en/account/register",
                                captcha_info["sitekey"],
                                self.current_proxy
                            )
                        elif "recaptcha" in captcha_info["type"].lower():
                            token = self.captcha_solver.solve_recaptcha_v2(
                                "https://funpay.com/en/account/register",
                                captcha_info["sitekey"]
                            )

                    if token:
                        try:
                            if "turnstile" in captcha_info["type"].lower():
                                logger.info("🤖 Инжектим Turnstile токен и пробуем сабмит...")
                                await page.evaluate(f"""
                                    () => {{
                                        // 1. Ставим токен в скрытое поле
                                        const inp = document.querySelector('[name="cf-turnstile-response"]');
                                        if (inp) {{
                                            Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(inp, '{token}');
                                            inp.dispatchEvent(new Event('input', {{ bubbles: true }}));
                                            inp.dispatchEvent(new Event('change', {{ bubbles: true }}));
                                        }}
                                        // 2. Пробуем callback
                                        const el = document.querySelector('[class*="cf-turnstile"]');
                                        if (el) {{
                                            const cb = el.getAttribute('data-callback');
                                            if (cb && window[cb]) window[cb]('{token}');
                                        }}
                                        // 3. Триггерим submit формы
                                        const form = document.querySelector('form');
                                        if (form) {{
                                            form.dispatchEvent(new Event('submit', {{ bubbles: true }}));
                                            form.querySelector('button[type="submit"]')?.click();
                                        }}
                                    }}
                                """)
                                logger.success("🤖 Turnstile токен инжектирован + сабмит!")
                                await asyncio.sleep(3)
                                if "register" not in page.url:
                                    solved = True
                                else:
                                    logger.info("Пробуем повторный сабмит...")
                                    for btn_sel in ['button[type="submit"]', 'button:has-text("Зарегистрироваться")', 'button:has-text("Sign Up")', 'button:has-text("Register")']:
                                        try:
                                            btn = await page.query_selector(btn_sel)
                                            if btn and await btn.is_visible() and await btn.is_enabled():
                                                await btn.click()
                                                await asyncio.sleep(3)
                                                if "register" not in page.url:
                                                    solved = True
                                                    break
                                        except:
                                            pass
                            elif "recaptcha" in captcha_info["type"].lower():
                                await page.evaluate(f"""
                                    () => {{
                                        document.getElementById('g-recaptcha-response')?.innerHTML = '';
                                        __recaptcha_callback?.();
                                        grecaptcha?.getResponse?.();
                                    }}
                                """)
                                logger.success("🤖 reCAPTCHA токен инжектирован!")
                                await asyncio.sleep(2)
                                solved = True
                        except Exception as e:
                            logger.warning(f"Ошибка инжекта: {e}")

                if not solved:
                    logger.warning(f"⚠️ Капча: {captcha_info['type']} — ждём 60 сек для ручного решения")
                    for ss in range(60):
                        await asyncio.sleep(1)
                        check = await self._detect_captcha(page)
                        if not check["found"]:
                            logger.success("Капча решена, продолжаем...")
                            break
                        try:
                            body_text = await page.evaluate("() => document.body?.innerText?.substring(0,2000) || ''")
                            if any(kw in body_text.lower() for kw in [
                                "требуется активация", "отправлено письмо", "активируйте",
                                "успешно зарегистрированы", "добро пожаловать", "activation"
                            ]):
                                logger.success("✅ Регистрация прошла (текст успеха)!")
                                solved = True
                                break
                        except Exception:
                            pass

            logger.info("Ожидаем результат...")
            success_keywords = [
                "требуется активация", "отправлено письмо", "активируйте",
                "успешно зарегистрированы", "добро пожаловать",
                "регистрация завершена", "activation", "подтвердите email",
                "check your email", "confirm your email", "successfully",
            ]
            error_keywords = [
                "already taken", "already exists", "уже используется",
                "error", "ошибка", "invalid", "неверный",
            ]

            for i in range(30):
                await asyncio.sleep(2)
                await asyncio.sleep(0.5)
                try:
                    page_text = await page.evaluate("() => document.body?.innerText?.substring(0,5000) || ''")
                    page_text_lower = page_text.lower()
                except Exception:
                    page_text_lower = ""

                matched = [kw for kw in success_keywords if kw in page_text_lower]
                if matched:
                    logger.success(f"✅ Регистрация успешна! Найдено: {matched[0]}")
                    return True

                matched_err = [kw for kw in error_keywords if kw in page_text_lower]
                if matched_err:
                    logger.warning(f"❌ Ошибка: {matched_err[0]}")
                    return False

                if i % 3 == 0:
                    logger.info(f"⏳ Ждём... ({i*2+2}с)")

            try:
                page_text = await page.evaluate("() => document.body?.innerText?.substring(0,3000) || ''")
                if any(kw in page_text.lower() for kw in success_keywords):
                    logger.success(f"✅ Регистрация успешна (финальная проверка)")
                    return True
            except Exception:
                pass

            logger.warning("Не дождались результата")
            return False

        except Exception as e:
            logger.error(f"Ошибка формы: {type(e).__name__}: {str(e)}")
            return False

    def _save_account(self, login_pass: str):
        try:
            filename = self.config.accounts_filename
            with open(filename, "a", encoding="utf-8") as f:
                f.write(login_pass + "\n")
            logger.success(f"✅ Аккаунт сохранён в {filename}")
        except Exception as e:
            logger.error(f"Ошибка записи: {e}")

    async def _save_cookies_json(
        self, page, funpay_email: str = "", funpay_password: str = "",
        mail_login: str = "", mail_password: str = "",
    ) -> str:
        if self._counter_lock is None:
            self._counter_lock = asyncio.Lock()

        async with self._counter_lock:
            self._account_counter += 1
            file_number = self._account_counter

        try:
            os.makedirs(self.accounts_output_folder, exist_ok=True)
            filepath = os.path.join(self.accounts_output_folder, f"{file_number}.json")

            raw_cookies = await page.context.cookies()
            formatted = [{
                "domain": c.get("domain", ""),
                "name": c.get("name", ""),
                "value": c.get("value", ""),
                "path": c.get("path", "/"),
                "secure": c.get("secure", True),
                "httpOnly": c.get("httpOnly", False),
                "sameSite": "unspecified",
                "expirationDate": c.get("expires", 2147483647),
            } for c in raw_cookies]

            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(formatted, f, ensure_ascii=False, indent=2)

            logger.success(f"🍪 Куки: {filepath} ({len(formatted)} cookies)")
            return filepath
        except Exception as e:
            logger.error(f"Ошибка сохранения кук: {e}")
            return ""


def main():
    config = Config()

    print("=" * 60)
    print("  FunPay Auto Registration")
    print("=" * 60)

    if not os.path.exists(config.proxies_filename):
        print(f"❌ Файл {config.proxies_filename} не найден!")
        print("   Формат: ip:port:username:password")
        return

    if not os.path.exists(config.mail_filename):
        print(f"❌ Файл {config.mail_filename} не найден!")
        print("   Формат: login:pass")
        return

    mail_count = 0
    try:
        with open(config.mail_filename, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip() and ":" in line:
                    mail_count += 1
    except Exception:
        pass

    print(f"📧 Доступно почт: {mail_count}")

    try:
        count = int(input("Сколько аккаунтов регать? ") or "1")
    except ValueError:
        count = 1
    if count > mail_count:
        print(f"⚠️ Аккаунтов не может быть больше чем почт. Ставлю {mail_count}")
        count = mail_count

    parallel = 1

    print("   Ctrl+C для остановки\n")

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.set_exception_handler(lambda loop, ctx: (
        None if "TargetClosedError" in type(ctx.get("exception", "")).__name__
        else loop.default_exception_handler(ctx)
    ))

    registrator = FunPayRegistration(config, "accounts")

    try:
        print(f"\n{'=' * 60}")
        print(f"  Регистрируем {count} аккаунтов по очереди")
        print(f"{'=' * 60}")

        successful = 0
        for i in range(count):
            print(f"\n--- Аккаунт #{i+1}/{count} ---")
            result = loop.run_until_complete(registrator.register_account())
            if result:
                successful += 1

        print(f"\n{'=' * 60}")
        print(f"  Результат: успешно={successful}, ошибок={count - successful}")
        print(f"{'=' * 60}")

    except KeyboardInterrupt:
        print("\n\n⏹ Остановка пользователем. Очищаем профили...")
        try:
            loop.run_until_complete(registrator.ads_power.cleanup())
        except Exception:
            pass
        print("✅ Очистка завершена")
    except Exception as e:
        print(f"\nОшибка: {e}")
        try:
            loop.run_until_complete(registrator.ads_power.cleanup())
        except Exception:
            pass
    finally:
        loop.close()


if __name__ == "__main__":
    main()
