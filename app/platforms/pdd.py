from __future__ import annotations

import asyncio
from typing import List, Optional, Sequence, Tuple

from app.core.models import ImageKind, MatchCandidate, Platform
from app.platforms.base import PlatformAdapter, parse_sales
from app.services.matcher import is_flagship_store
from app.services.urls import goods_id, normalize_url

PDD_SEARCH_JS = """
() => {
  const anchors = document.querySelectorAll('a[href*="goods.html"], a[href*="goods_id="]');
  const out = [];
  const seen = new Set();
  anchors.forEach((anchor) => {
    const url = anchor.href || "";
    if (!url) return;
    const key = url.split("&")[0];
    if (seen.has(key)) return;
    seen.add(key);
    let node = anchor;
    let card = null;
    for (let i = 0; i < 7 && node; i++) {
      node = node.parentElement;
      if (!node) break;
      const text = node.innerText || "";
      if (text.length > 20) { card = node; break; }
    }
    const text = card ? card.innerText : "";
    const storeMatch = text.match(/[^\\n]{0,30}(旗舰店|专卖店|专营店|官方店|企业店)/);
    const salesMatch = text.match(/([\\d.]+\\+?\\s*(?:万)?)\\s*(?:人已拼|人拼过|已拼|人付款)/);
    let title = (anchor.innerText || "").trim();
    if (!title) {
      const img = anchor.querySelector("img");
      title = img ? (img.alt || "").trim() : "";
    }
    out.push({
      url,
      title,
      store: storeMatch ? storeMatch[0].replace(/^[^\\u4e00-\\u9fa5A-Za-z0-9]+/, "").trim() : "",
      sales: salesMatch ? salesMatch[1] : "",
    });
  });
  return out;
}
"""


async def _first_text(page, selectors: Sequence[str]) -> str:
    for selector in selectors:
        try:
            element = await page.query_selector(selector)
        except Exception:  # noqa: BLE001
            continue
        if element is None:
            continue
        try:
            text = (await element.inner_text()).strip()
        except Exception:  # noqa: BLE001
            continue
        if text:
            return text
    return ""


class PDDAdapter(PlatformAdapter):
    platform = Platform.PDD
    label = "拼多多"
    home_url = "https://mobile.yangkeduo.com"
    login_url = "https://mobile.yangkeduo.com/login.html"
    search_url_template = "https://mobile.yangkeduo.com/search_result.html?search_key={query}"
    cdn_hosts = ("pddpic.com", "yangkeduo.com", "pinduoduo.com")
    login_cookie_names = ("PDDAccessToken", "pdd_user_id", "pdd_user_uin", "pdd_user_id")
    network_default_kind = ImageKind.DETAIL
    scroll_steps = 20

    def dom_groups(self) -> Sequence[Tuple[ImageKind, Sequence[str]]]:
        return (
            (
                ImageKind.MAIN,
                (
                    "[class*='goodsPic'] img",
                    "[class*='GoodsPic'] img",
                    "[class*='banner'] img",
                    "[class*='Banner'] img",
                    "[class*='swiper'] img",
                ),
            ),
            (
                ImageKind.SKU,
                (
                    "[class*='sku'] img",
                    "[class*='Sku'] img",
                    "[class*='spec'] img",
                ),
            ),
            (
                ImageKind.DETAIL,
                (
                    "[class*='detail'] img",
                    "[class*='Detail'] img",
                    "[class*='desc'] img",
                ),
            ),
        )

    async def parse_search_results(self, page) -> List[MatchCandidate]:
        rows = await page.evaluate(PDD_SEARCH_JS)
        candidates: List[MatchCandidate] = []
        for row in rows or []:
            url = normalize_url(str(row.get("url") or ""))
            if not url:
                continue
            store = str(row.get("store") or "").strip()
            candidates.append(
                MatchCandidate(
                    platform=Platform.PDD,
                    title=str(row.get("title") or "").strip(),
                    url=url,
                    store=store,
                    is_flagship=is_flagship_store(store),
                    sales=parse_sales(str(row.get("sales") or "")),
                    goods_id=goods_id(url, Platform.PDD),
                )
            )
        return candidates

    async def extract_meta(self, page, url: str) -> Tuple[str, str, str]:
        title = await _first_text(
            page,
            (
                "[class*='goodsName']",
                "[class*='GoodsName']",
                "[class*='goods-name']",
                "h1",
            ),
        )
        if not title:
            fallback_title, _, _ = await super().extract_meta(page, url)
            title = fallback_title
        store = await _first_text(
            page,
            (
                "[class*='mallName']",
                "[class*='MallName']",
                "[class*='mall-name']",
                "[class*='shopName']",
            ),
        )
        return title.strip(), store.strip(), goods_id(url, Platform.PDD)

    async def manual_pick(self, query: str, timeout: float = 600.0) -> Optional[str]:
        """半自动兜底：打开可见浏览器，由人工点选目标商品。"""
        self.emit(
            "supervision",
            f"拼多多半自动模式：请在弹出的浏览器中选择「{query}」的目标商品",
            platform=self.platform.value,
        )
        page = await self.browser.new_page(self.platform, force_visible=True)
        try:
            await page.goto(
                self.search_url_template.format(query=query),
                wait_until="domcontentloaded",
            )
            loop = asyncio.get_running_loop()
            deadline = loop.time() + timeout
            while loop.time() < deadline:
                await asyncio.sleep(1.5)
                current = page.url or ""
                if "goods_id=" in current:
                    self.emit(
                        "supervision",
                        "已获取人工选择的商品链接，继续自动抓取",
                        platform=self.platform.value,
                    )
                    return current
            self.emit(
                "supervision",
                "等待人工选择超时",
                level="warning",
                platform=self.platform.value,
            )
            return None
        finally:
            try:
                await page.close()
            except Exception:  # noqa: BLE001
                pass
