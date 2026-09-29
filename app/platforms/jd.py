from __future__ import annotations

from typing import List, Sequence, Tuple

from app.core.models import ImageKind, MatchCandidate, Platform
from app.platforms.base import PlatformAdapter, parse_sales
from app.services.matcher import is_flagship_store
from app.services.urls import goods_id, normalize_url

JD_SEARCH_JS = """
() => {
  const items = Array.from(document.querySelectorAll("#J_goodsList li.gl-item, li.gl-item"));
  return items.map((li) => {
    const anchor = li.querySelector(".p-name a");
    const name = li.querySelector(".p-name em");
    const shop = li.querySelector(".p-shop a");
    const commit = li.querySelector(".p-commit strong a") || li.querySelector(".p-commit");
    return {
      url: anchor ? anchor.href : "",
      title: name ? name.textContent.trim() : (anchor ? anchor.textContent.trim() : ""),
      store: shop ? (shop.getAttribute("title") || shop.textContent.trim()) : "",
      sales: commit ? commit.textContent.trim() : "",
      sku: li.getAttribute("data-sku") || "",
    };
  }).filter((item) => item.url);
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


class JDAdapter(PlatformAdapter):
    platform = Platform.JD
    label = "京东"
    home_url = "https://www.jd.com"
    login_url = "https://passport.jd.com/new/login.aspx"
    search_url_template = "https://search.jd.com/Search?keyword={query}&enc=utf-8"
    cdn_hosts = ("360buyimg.com",)
    login_cookie_names = ("pt_key", "pt_pin", "thor", "pin")
    network_default_kind = ImageKind.DETAIL
    scroll_steps = 16

    def dom_groups(self) -> Sequence[Tuple[ImageKind, Sequence[str]]]:
        return (
            (
                ImageKind.MAIN,
                (
                    "#spec-list img",
                    ".spec-list img",
                    "#spec-img",
                    "[class*='specList'] img",
                ),
            ),
            (
                ImageKind.SKU,
                (
                    "#choose-attr img",
                    ".choose-attr img",
                    "#J-choose-sku img",
                    ".sku-img img",
                    "[class*='skuImg'] img",
                ),
            ),
            (
                ImageKind.DETAIL,
                (
                    "#J-detail-content img",
                    "#detail img",
                    ".detail-content img",
                    "[class*='detailContent'] img",
                    "[class*='detail-content'] img",
                ),
            ),
        )

    async def parse_search_results(self, page) -> List[MatchCandidate]:
        rows = await page.evaluate(JD_SEARCH_JS)
        candidates: List[MatchCandidate] = []
        seen = set()
        for row in rows or []:
            url = normalize_url(str(row.get("url") or ""))
            if not url or url in seen:
                continue
            seen.add(url)
            store = str(row.get("store") or "").strip()
            candidates.append(
                MatchCandidate(
                    platform=Platform.JD,
                    title=str(row.get("title") or "").strip(),
                    url=url,
                    store=store,
                    is_flagship=is_flagship_store(store),
                    sales=parse_sales(str(row.get("sales") or "")),
                    goods_id=str(row.get("sku") or "") or goods_id(url, Platform.JD),
                )
            )
        return candidates

    async def extract_meta(self, page, url: str) -> Tuple[str, str, str]:
        title = await _first_text(page, (".sku-name", "#name h1", "h1"))
        if not title:
            title = await super().extract_meta(page, url)
            title = title[0]
        store = await _first_text(
            page,
            (
                ".J-hove-wrap .name a",
                "[class*='shopName'] a",
                "[class*='shopName']",
                "#popbox .mt a",
                ".J-hove-wrap .name",
            ),
        )
        return title.strip(), store.strip(), goods_id(url, Platform.JD)
