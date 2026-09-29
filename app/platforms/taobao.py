from __future__ import annotations

from typing import List, Sequence, Tuple

from app.core.models import ImageKind, MatchCandidate, Platform
from app.platforms.base import PlatformAdapter, parse_sales
from app.services.matcher import is_flagship_store
from app.services.urls import goods_id, normalize_url

TB_SEARCH_JS = """
() => {
  const anchors = document.querySelectorAll(
    'a[href*="item.taobao.com/item.htm"], a[href*="detail.tmall.com/item.htm"],' +
    'a[href*="item.tmall.com/item.htm"], a[href*="chaoshi.detail.tmall.com"]'
  );
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
      if (text.length > 30) { card = node; break; }
    }
    const text = card ? card.innerText : "";
    const storeMatch = text.match(/[^\\n]{0,30}(旗舰店|专卖店|专营店|官方店|企业店)/);
    const salesMatch = text.match(/([\\d.]+\\+?\\s*(?:万)?)\\s*(?:人付款|人已买|人收货|\\+?条评价)/);
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


class TaobaoAdapter(PlatformAdapter):
    platform = Platform.TAOBAO
    label = "淘宝/天猫"
    home_url = "https://www.taobao.com"
    login_url = "https://login.taobao.com/member/login.jhtml"
    search_url_template = "https://s.taobao.com/search?q={query}"
    cdn_hosts = ("alicdn.com",)
    login_cookie_names = ("_l_g_", "cookie2", "_tb_token_", "unb")
    network_default_kind = ImageKind.DETAIL
    scroll_steps = 16

    async def is_logged_in(self) -> bool:
        cookies = await self.browser.cookies(self.platform)
        if not cookies:
            return False
        if cookies.get("_l_g_"):
            return True
        return bool(cookies.get("unb") and cookies.get("cookie2") and cookies.get("_tb_token_"))

    def dom_groups(self) -> Sequence[Tuple[ImageKind, Sequence[str]]]:
        return (
            (
                ImageKind.MAIN,
                (
                    "#J_UlThumb img",
                    ".tb-thumb img",
                    "[class*='thumbnails'] img",
                    "[class*='PicGallery'] img",
                    "[class*='mainPic'] img",
                    "[class*='MainPic'] img",
                ),
            ),
            (
                ImageKind.SKU,
                (
                    "#J_isku img",
                    ".tb-sku img",
                    "[class*='Sku'] img",
                    "[class*='sku'] img",
                ),
            ),
            (
                ImageKind.DETAIL,
                (
                    "#J_DivItemDesc img",
                    "#detail img",
                    "#J_DetailMeta img",
                    "[class*='detail'] img",
                    "[class*='Detail'] img",
                ),
            ),
        )

    async def parse_search_results(self, page) -> List[MatchCandidate]:
        rows = await page.evaluate(TB_SEARCH_JS)
        candidates: List[MatchCandidate] = []
        for row in rows or []:
            url = normalize_url(str(row.get("url") or ""))
            if not url:
                continue
            store = str(row.get("store") or "").strip()
            candidates.append(
                MatchCandidate(
                    platform=Platform.TAOBAO,
                    title=str(row.get("title") or "").strip(),
                    url=url,
                    store=store,
                    is_flagship=is_flagship_store(store),
                    sales=parse_sales(str(row.get("sales") or "")),
                    goods_id=goods_id(url, Platform.TAOBAO),
                )
            )
        return candidates

    async def extract_meta(self, page, url: str) -> Tuple[str, str, str]:
        title = await _first_text(
            page,
            (
                "h1",
                "[class*='ItemHeader'] h1",
                "[class*='itemTitle']",
                "[class*='ItemTitle']",
            ),
        )
        if not title:
            fallback_title, _, _ = await super().extract_meta(page, url)
            title = fallback_title
        store = await _first_text(
            page,
            (
                "[class*='ShopHeader'] a",
                ".shop-name",
                "#J_ShopInfo a",
                "[class*='shopName']",
                "[class*='ShopName']",
            ),
        )
        return title.strip(), store.strip(), goods_id(url, Platform.TAOBAO)
