from __future__ import annotations

import abc
import asyncio
import json
import re
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from app.core.config import Settings
from app.core.logging_setup import logger
from app.core.models import (
    ImageKind,
    ImageRef,
    MatchCandidate,
    Platform,
    ProductPage,
)
from app.platforms.browser import (
    BrowserManager,
    LoginRequired,
    RiskDetected,
    detect_risk,
    scroll_page,
)
from app.services.urls import goods_id, normalize_url, original_url

JUNK_URL_RE = re.compile(
    r"(logo|icon|avatar|sprite|qrcode|qr_code|placeholder|loading|blank|favicon|"
    r"default|empty|grey\.|gray\.|spacer|1x1|pixel)",
    re.I,
)
IMAGE_URL_RE = re.compile(r"\.(?:jpg|jpeg|png|gif|webp|bmp)(?:[?#]|$)", re.I)

DOM_IMAGES_JS = """
(spec) => {
  const out = [];
  const seen = new Set();
  for (const [kind, selectors] of spec) {
    for (const sel of selectors) {
      let nodes;
      try { nodes = document.querySelectorAll(sel); } catch (e) { continue; }
      nodes.forEach((node) => {
        let url = "";
        if (node.tagName === "IMG") {
          url = node.currentSrc || node.src ||
                node.getAttribute("data-src") || node.getAttribute("data-lazy-img") ||
                node.getAttribute("data-url") || node.getAttribute("data-ks-lazyload") || "";
        } else {
          const bg = getComputedStyle(node).backgroundImage || "";
          const match = bg.match(/url\\(["']?([^"')]+)["']?\\)/);
          if (match) url = match[1];
        }
        if (!url || url.startsWith("data:")) return;
        const img = node.tagName === "IMG" ? node : (node.querySelector("img") || node);
        const key = kind + "|" + url;
        if (seen.has(key)) return;
        seen.add(key);
        out.push({ url, kind, w: img.naturalWidth || 0, h: img.naturalHeight || 0 });
      });
    }
  }
  return out;
}
"""


class ImageCollector:
    """在页面导航前挂载，记录所有图片响应。"""

    def __init__(self, cdn_hosts: Sequence[str] = ()) -> None:
        self.cdn_hosts = tuple(cdn_hosts)
        self.items: List[Tuple[str, int, int]] = []
        self._seen = set()

    def attach(self, page) -> None:
        page.on("response", self._handle_response)

    def _handle_response(self, response) -> None:
        try:
            url = response.url
            content_type = (response.headers or {}).get("content-type", "")
        except Exception:  # noqa: BLE001
            return
        if not url or url.startswith("data:"):
            return
        if not content_type.lower().startswith("image/"):
            return
        if self.cdn_hosts and not any(host in url for host in self.cdn_hosts):
            return
        if url in self._seen:
            return
        self._seen.add(url)
        self.items.append((url, 0, 0))


class PlatformAdapter(abc.ABC):
    platform: Platform = Platform.JD
    label: str = ""
    home_url: str = ""
    login_url: str = ""
    search_url_template: str = ""
    cdn_hosts: Tuple[str, ...] = ()
    login_cookie_names: Tuple[str, ...] = ()
    network_default_kind: ImageKind = ImageKind.DETAIL
    scroll_steps: int = 14
    max_images: int = 400
    min_side: int = 50

    def __init__(
        self,
        browser: BrowserManager,
        settings: Settings,
        on_event: Optional[Callable[..., None]] = None,
    ) -> None:
        self.browser = browser
        self.settings = settings
        self.on_event = on_event

    def emit(self, event_type: str, message: str = "", level: str = "info", **payload) -> None:
        if self.on_event:
            try:
                self.on_event(event_type, message=message, level=level, **payload)
            except TypeError:
                pass

    # ------------------------------------------------------------------ login
    async def is_logged_in(self) -> bool:
        cookies = await self.browser.cookies(self.platform)
        if not cookies:
            return False
        return any(name in cookies for name in self.login_cookie_names)

    async def login_required(self) -> bool:
        return not await self.is_logged_in()

    async def ensure_login(self, timeout: float = 300.0) -> bool:
        if not await self.login_required():
            return True
        self.emit(
            "login_required",
            f"{self.label} 需要登录，请在弹出的浏览器窗口中完成登录",
            platform=self.platform.value,
            url=self.login_url,
        )
        page = await self.browser.open_visible_page(self.platform, self.login_url)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        try:
            while loop.time() < deadline:
                await asyncio.sleep(2.0)
                if await self.is_logged_in():
                    self.emit(
                        "login_done", f"{self.label} 登录成功", platform=self.platform.value
                    )
                    return True
        finally:
            try:
                await page.close()
            except Exception:  # noqa: BLE001
                pass
        self.emit(
            "login_required",
            f"{self.label} 登录超时，请重试",
            level="warning",
            platform=self.platform.value,
        )
        return False

    async def resolve_risk(self, url: str = "", timeout: float = 600.0) -> bool:
        """监督程序：打开可见浏览器等待人工完成验证。"""
        target = url or self.home_url
        self.emit(
            "risk",
            f"{self.label} 遇到风控验证，请在弹出的浏览器中完成验证",
            level="warning",
            platform=self.platform.value,
            url=target,
        )
        page = await self.browser.open_visible_page(self.platform, target)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        try:
            while loop.time() < deadline:
                await asyncio.sleep(2.0)
                reason = await detect_risk(page)
                if not reason:
                    self.emit(
                        "risk_resolved",
                        f"{self.label} 验证已通过，继续任务",
                        platform=self.platform.value,
                    )
                    return True
            self.emit(
                "risk",
                f"{self.label} 验证等待超时，跳过后续任务",
                level="error",
                platform=self.platform.value,
            )
            return False
        finally:
            try:
                await page.close()
            except Exception:  # noqa: BLE001
                pass

    # --------------------------------------------------------------- crawling
    async def _goto(self, page, url: str) -> None:
        await page.goto(url, wait_until="domcontentloaded", timeout=self.settings.timeout * 1000)
        try:
            await page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:  # noqa: BLE001
            pass

    async def run_search(
        self, page, query: str, limit: int = 10
    ) -> List[MatchCandidate]:
        await self._goto(page, self.search_url_template.format(query=query))
        reason = await detect_risk(page)
        if reason:
            raise RiskDetected(self.platform, reason)
        await scroll_page(page, steps=4, pause_ms=300)
        candidates = await self.parse_search_results(page)
        return candidates[:limit]

    async def fetch(self, url: str) -> ProductPage:
        page = await self.browser.new_page(self.platform)
        collector = ImageCollector(self.cdn_hosts)
        collector.attach(page)
        try:
            await self._goto(page, url)
            reason = await detect_risk(page)
            if reason:
                if reason.startswith("页面跳转到风控地址") and "login" in reason:
                    raise LoginRequired(self.platform)
                raise RiskDetected(self.platform, reason)
            title, store, page_goods_id = await self.extract_meta(page, url)
            await scroll_page(page, steps=self.scroll_steps)
            images = await self.collect_images(page, collector)
            return ProductPage(
                platform=self.platform,
                url=url,
                title=title,
                store=store,
                goods_id=page_goods_id or goods_id(url, self.platform),
                images=images,
            )
        finally:
            try:
                await page.close()
            except Exception:  # noqa: BLE001
                pass

    def dom_groups(self) -> Sequence[Tuple[ImageKind, Sequence[str]]]:
        return ()

    async def collect_images(self, page, collector: ImageCollector) -> List[ImageRef]:
        entries: List[Dict] = []
        groups = self.dom_groups()
        if groups:
            spec = [[kind.value, list(selectors)] for kind, selectors in groups]
            try:
                entries = await page.evaluate(DOM_IMAGES_JS, spec)
            except Exception as exc:  # noqa: BLE001
                logger.debug("DOM 图片提取失败: {}", exc)
        ordered: List[Tuple[str, ImageKind, int, int]] = []
        index: Dict[str, Tuple[str, ImageKind, int, int]] = {}
        for entry in entries or []:
            url = normalize_url(str(entry.get("url") or ""))
            if not self.accept_url(url):
                continue
            try:
                kind = ImageKind(entry.get("kind") or ImageKind.DETAIL.value)
            except ValueError:
                kind = ImageKind.DETAIL
            width = int(entry.get("w") or 0)
            height = int(entry.get("h") or 0)
            if not self.accept_size(width, height, kind):
                continue
            key = self.canonical_url(url)
            if key in index:
                continue
            item = (url, kind, width, height)
            index[key] = item
            ordered.append(item)
        main_keys = {self.canonical_url(u) for u, k, _, _ in ordered if k is ImageKind.MAIN}
        for raw_url, width, height in collector.items:
            url = normalize_url(raw_url)
            if not self.accept_url(url):
                continue
            key = self.canonical_url(url)
            if key in index:
                continue
            kind = self.classify_network_url(url, key in main_keys)
            if kind is None:
                continue
            if not self.accept_size(width, height, kind):
                continue
            item = (url, kind, width, height)
            index[key] = item
            ordered.append(item)
        priority = {ImageKind.MAIN: 0, ImageKind.SKU: 1, ImageKind.DETAIL: 2}
        ordered.sort(key=lambda item: priority.get(item[1], 3))
        return [
            ImageRef(url=url, kind=kind, width=width, height=height)
            for url, kind, width, height in ordered[: self.max_images]
        ]

    # ---------------------------------------------------------------- helpers
    def canonical_url(self, url: str) -> str:
        try:
            return original_url(url, self.platform)
        except Exception:  # noqa: BLE001
            return url

    def classify_network_url(self, url: str, in_main_set: bool) -> Optional[ImageKind]:
        if in_main_set:
            return ImageKind.MAIN
        return self.network_default_kind

    def accept_url(self, url: str) -> bool:
        if not url or len(url) > 2000:
            return False
        lowered = url.lower()
        if lowered.startswith(("data:", "javascript:", "blob:")):
            return False
        if not IMAGE_URL_RE.search(lowered):
            return False
        if JUNK_URL_RE.search(url):
            return False
        return True

    def accept_size(self, width: int, height: int, kind: ImageKind) -> bool:
        if width <= 0 or height <= 0:
            return True
        if width == 1 or height == 1:
            return False
        return min(width, height) >= self.min_side

    # ------------------------------------------------------------------- meta
    async def extract_meta(self, page, url: str) -> Tuple[str, str, str]:
        try:
            title = (await page.title()) or ""
        except Exception:  # noqa: BLE001
            title = ""
        return title.strip(), "", goods_id(url, self.platform)

    # -------------------------------------------------------------- abstract
    @abc.abstractmethod
    async def parse_search_results(self, page) -> List[MatchCandidate]:
        raise NotImplementedError

    async def close(self) -> None:  # pragma: no cover - hook for adapters
        return None


def parse_sales(text: str) -> int:
    text = (text or "").strip().replace(",", "")
    match = re.search(r"([\d.]+)\s*(万|w|W)?", text)
    if not match:
        return 0
    try:
        value = float(match.group(1))
    except ValueError:
        return 0
    if match.group(2):
        value *= 10000
    return int(value)
