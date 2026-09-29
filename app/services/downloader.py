from __future__ import annotations

import asyncio
import hashlib
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, Optional

import httpx

from app.core.config import Settings
from app.core.models import Platform
from app.services.image_meta import sniff_image
from app.services.urls import normalize_url, original_candidates

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

PLATFORM_REFERER: Dict[Platform, str] = {
    Platform.JD: "https://item.jd.com/",
    Platform.TAOBAO: "https://item.taobao.com/",
    Platform.PDD: "https://mobile.yangkeduo.com/",
}


class DownloadError(Exception):
    def __init__(self, url: str, reason: str) -> None:
        super().__init__(f"{reason}: {url}")
        self.url = url
        self.reason = reason


@dataclass
class FetchedImage:
    data: bytes
    ext: str
    width: int
    height: int
    sha256: str
    source_url: str
    content_type: str = ""
    extra: dict = field(default_factory=dict)


class ImageFetcher:
    """图片下载：原图还原优先、失败回退、重试与限速。"""

    def __init__(
        self,
        settings: Settings,
        cookies: Optional[Dict[Platform, Dict[str, str]]] = None,
    ) -> None:
        self.settings = settings
        self.cookies = cookies or {}
        self._clients: Dict[Platform, httpx.AsyncClient] = {}

    def _client(self, platform: Platform) -> httpx.AsyncClient:
        client = self._clients.get(platform)
        if client is not None:
            return client
        cookie_map = self.cookies.get(platform) or {}
        client = httpx.AsyncClient(
            follow_redirects=True,
            timeout=self.settings.timeout,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9",
                "Referer": PLATFORM_REFERER.get(platform, ""),
            },
            cookies=cookie_map,
            proxy=self.settings.proxy or None,
        )
        self._clients[platform] = client
        return client

    async def fetch(
        self, platform: Platform, url: str, referer: str = ""
    ) -> FetchedImage:
        url = normalize_url(url)
        if not url:
            raise DownloadError(str(url), "空链接")
        candidates = original_candidates(url, platform)
        client = self._client(platform)
        last_error = "未知错误"
        for candidate in candidates:
            headers = {"Referer": referer} if referer else {}
            for attempt in range(max(1, self.settings.retries)):
                if attempt or self.settings.delay_max > 0:
                    await asyncio.sleep(
                        random.uniform(self.settings.delay_min, self.settings.delay_max)
                    )
                try:
                    response = await client.get(candidate, headers=headers)
                except httpx.HTTPError as exc:
                    last_error = f"网络错误 {exc.__class__.__name__}"
                    await asyncio.sleep(0.5 * (2**attempt))
                    continue
                if response.status_code in (403, 404, 410):
                    last_error = f"HTTP {response.status_code}"
                    break
                if response.status_code != 200:
                    last_error = f"HTTP {response.status_code}"
                    await asyncio.sleep(0.5 * (2**attempt))
                    continue
                data = response.content
                if len(data) < self.settings.min_image_bytes:
                    last_error = f"文件过小({len(data)}B)"
                    break
                info = sniff_image(data)
                if info is None:
                    last_error = "不是有效图片"
                    break
                ext, width, height = info
                return FetchedImage(
                    data=data,
                    ext=ext,
                    width=width,
                    height=height,
                    sha256=hashlib.sha256(data).hexdigest(),
                    source_url=candidate,
                    content_type=response.headers.get("content-type", ""),
                )
        raise DownloadError(url, last_error)

    async def aclose(self) -> None:
        for client in self._clients.values():
            await client.aclose()
        self._clients.clear()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def save_image(data: bytes, path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".part")
    temp.write_bytes(data)
    temp.replace(path)


def unique_path(path: Path, seen_paths: Optional[Iterable[Path]] = None) -> Path:
    known = {str(p) for p in (seen_paths or [])}
    if not path.exists() and str(path) not in known:
        return path
    stem, suffix = path.stem, path.suffix
    index = 2
    while True:
        candidate = path.with_name(f"{stem}_{index}{suffix}")
        if not candidate.exists() and str(candidate) not in known:
            return candidate
        index += 1
