from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Callable, Dict, List, Optional

from app.core.config import Settings
from app.core.logging_setup import logger
from app.core.models import Platform

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

RISK_URL_PATTERNS = (
    "x5sec",
    "punish",
    "captcha",
    "verify",
    "safecheck",
    "security",
    "nocaptcha",
    "/risk",
    "login.taobao.com",
)

RISK_TEXT_PATTERNS = (
    "滑动验证",
    "安全验证",
    "请完成验证",
    "访问过于频繁",
    "操作太频繁",
    "验证码",
    "异常流量",
)

RISK_SELECTORS = (
    "#nocaptcha",
    ".nc-container",
    ".J_MIDDLEWARE_FRAME_WIDGET",
    "iframe[src*='captcha']",
    "iframe[src*='punish']",
    "iframe[src*='x5sec']",
    "#captcha",
    "[class*='captcha']",
)


class RiskDetected(Exception):
    def __init__(self, platform: Platform, reason: str) -> None:
        super().__init__(reason)
        self.platform = platform
        self.reason = reason


class LoginRequired(Exception):
    def __init__(self, platform: Platform) -> None:
        super().__init__(f"{platform.label} 需要登录")
        self.platform = platform


class BrowserManager:
    """Playwright 持久化上下文管理，每个平台独立 profile。"""

    def __init__(
        self,
        settings: Settings,
        on_event: Optional[Callable[..., None]] = None,
    ) -> None:
        self.settings = settings
        self.on_event = on_event
        self._playwright = None
        self._contexts: Dict[Platform, object] = {}
        self._headless_state: Dict[Platform, bool] = {}
        self._locks: Dict[Platform, asyncio.Lock] = {
            platform: asyncio.Lock() for platform in Platform
        }

    # -------------------------------------------------------------- lifecycle
    async def start(self) -> None:
        if self._playwright is not None:
            return
        from playwright.async_api import async_playwright

        self._playwright = await async_playwright().start()

    async def close(self) -> None:
        for platform in list(self._contexts):
            await self.close_platform(platform)
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None

    def _headless(self, platform: Platform, force_visible: bool = False) -> bool:
        if force_visible:
            return False
        if platform is Platform.PDD and self.settings.pdd_visible:
            return False
        return self.settings.headless

    async def context(self, platform: Platform, force_visible: bool = False):
        await self.start()
        async with self._locks[platform]:
            context = self._contexts.get(platform)
            if (
                context is not None
                and force_visible
                and self._headless_state.get(platform)
            ):
                await context.close()
                self._contexts.pop(platform, None)
                context = None
            if context is not None:
                return context
            profile_dir = self.settings.profiles_dir / platform.value
            profile_dir.mkdir(parents=True, exist_ok=True)
            headless = self._headless(platform, force_visible)
            options: Dict[str, object] = {
                "user_data_dir": str(profile_dir),
                "headless": headless,
                "locale": "zh-CN",
                "timezone_id": "Asia/Shanghai",
                "viewport": {"width": 1440, "height": 900},
                "user_agent": USER_AGENT,
                "args": [
                    "--disable-blink-features=AutomationControlled",
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--disable-popup-blocking",
                ],
                "ignore_default_args": ["--enable-automation"],
            }
            if self.settings.proxy:
                options["proxy"] = {"server": self.settings.proxy}
            context = await self._playwright.chromium.launch_persistent_context(
                str(profile_dir), **options
            )
            try:
                context.set_default_timeout(self.settings.timeout * 1000)
            except Exception:  # noqa: BLE001
                pass
            self._headless_state[platform] = headless
            self._contexts[platform] = context
            logger.info("启动 {} 浏览器 (headless={})", platform.value, headless)
            return context

    async def close_platform(self, platform: Platform) -> None:
        async with self._locks[platform]:
            context = self._contexts.pop(platform, None)
            if context is not None:
                try:
                    await context.close()
                except Exception as exc:  # noqa: BLE001
                    logger.warning("关闭 {} 浏览器出错: {}", platform.value, exc)

    async def new_page(self, platform: Platform, force_visible: bool = False):
        context = await self.context(platform, force_visible=force_visible)
        page = await context.new_page()
        return page

    async def cookies(self, platform: Platform) -> Dict[str, str]:
        try:
            context = await self.context(platform)
        except Exception:  # noqa: BLE001
            return {}
        try:
            items = await context.cookies()
        except Exception:  # noqa: BLE001
            return {}
        return {item.get("name", ""): item.get("value", "") for item in items if item.get("name")}

    async def open_visible_page(self, platform: Platform, url: str):
        page = await self.new_page(platform, force_visible=True)
        await page.goto(url, wait_until="domcontentloaded")
        await page.bring_to_front()
        return page


async def detect_risk(page) -> Optional[str]:
    try:
        url = (page.url or "").lower()
    except Exception:  # noqa: BLE001
        url = ""
    for pattern in RISK_URL_PATTERNS:
        if pattern in url:
            return f"页面跳转到风控地址: {pattern}"
    for selector in RISK_SELECTORS:
        try:
            element = await page.query_selector(selector)
        except Exception:  # noqa: BLE001
            continue
        if element is not None:
            return f"出现验证组件: {selector}"
    try:
        text = await page.inner_text("body")
    except Exception:  # noqa: BLE001
        text = ""
    for pattern in RISK_TEXT_PATTERNS:
        if pattern in text:
            return f"页面提示: {pattern}"
    return None


async def scroll_page(page, steps: int = 12, pause_ms: int = 350) -> None:
    for _ in range(steps):
        try:
            await page.evaluate("window.scrollBy(0, Math.max(window.innerHeight, 800))")
        except Exception:  # noqa: BLE001
            return
        try:
            await page.wait_for_timeout(pause_ms)
        except Exception:  # noqa: BLE001
            return
    try:
        await page.evaluate("window.scrollTo(0, 0)")
        await page.wait_for_timeout(200)
    except Exception:  # noqa: BLE001
        pass
