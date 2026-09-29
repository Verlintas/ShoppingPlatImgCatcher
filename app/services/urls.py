from __future__ import annotations

import re
from typing import List, Optional
from urllib.parse import urlsplit, urlunsplit

from app.core.models import Platform

JD_HOST_RE = re.compile(r"(^|\.)(jd\.com|jd\.hk|3\.cn)$", re.I)
TB_HOST_RE = re.compile(r"(^|\.)(taobao\.com|tmall\.com|tb\.cn)$", re.I)
PDD_HOST_RE = re.compile(r"(^|\.)(yangkeduo\.com|pinduoduo\.com|pddpic\.com)$", re.I)

JD_CDN_RE = re.compile(r"(^|\.)(360buyimg\.com|jdimg\.com|jd\.com)$", re.I)
TB_CDN_RE = re.compile(r"(^|\.)(alicdn\.com|tbcdn\.cn|taobaocdn\.com)$", re.I)
PDD_CDN_RE = re.compile(r"(^|\.)(pddpic\.com|yangkeduo\.com|pinduoduo\.com)$", re.I)

JD_ID_RE = re.compile(r"(?:item\.jd\.com/|item\.m\.jd\.com/product/)(\d+)", re.I)
JD_ID_QUERY_RE = re.compile(r"[?&](?:sku|skuId|wareId)=(\d+)", re.I)
TB_ID_RE = re.compile(r"[?&](?:id|itemId|item_id)=(\d+)", re.I)
PDD_ID_RE = re.compile(r"[?&]goods_id=(\d+)", re.I)


def host_of(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


def detect_platform(url: str) -> Optional[Platform]:
    host = host_of(url)
    if not host:
        return None
    if JD_HOST_RE.search(host):
        return Platform.JD
    if TB_HOST_RE.search(host):
        return Platform.TAOBAO
    if PDD_HOST_RE.search(host):
        return Platform.PDD
    if JD_CDN_RE.search(host):
        return Platform.JD
    if TB_CDN_RE.search(host):
        return Platform.TAOBAO
    if PDD_CDN_RE.search(host):
        return Platform.PDD
    return None


def goods_id(url: str, platform: Optional[Platform] = None) -> str:
    platform = platform or detect_platform(url)
    if platform is Platform.JD:
        match = JD_ID_RE.search(url) or JD_ID_QUERY_RE.search(url)
    elif platform is Platform.TAOBAO:
        match = TB_ID_RE.search(url)
    elif platform is Platform.PDD:
        match = PDD_ID_RE.search(url)
    else:
        match = None
    return match.group(1) if match else ""


def extract_urls(text: str) -> List[str]:
    return re.findall(r"https?://[^\s,;，；'\"<>]+", text)


def _strip_image_view_query(query: str) -> str:
    if not query:
        return ""
    cleaned = re.sub(
        r"(?:^|&)(?:imageView2|imageMogr2|watermark|x-oss-process)[^&]*",
        "",
        query,
    )
    return cleaned.strip("&")


def jd_original_url(url: str) -> str:
    """京东: /s450x450_jfs/ 或 /n1/ 等缩略规格 -> 原图规格。"""
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    path = parts.path
    path = re.sub(r"/s\d+x\d+_jfs/", "/jfs/", path, flags=re.I)
    path = re.sub(r"/(?:n\d+|imgzone|sku)/jfs/", "/n0/jfs/", path, flags=re.I)
    path = re.sub(r"/n\d+/", "/n0/", path, flags=re.I)
    query = _strip_image_view_query(parts.query)
    return urlunsplit((parts.scheme, parts.netloc, path, query, ""))


def taobao_original_url(url: str) -> str:
    """淘宝/天猫: xxx.jpg_430x430q90.jpg 或 xxx.jpg_.webp -> xxx.jpg。"""
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    path = parts.path
    path = re.sub(
        r"(?i)(\.(?:jpg|jpeg|png|gif|webp))_(?:[^/]*)$",
        r"\1",
        path,
    )
    path = re.sub(r"(?i)(\.(?:jpg|jpeg|png))\.webp$", r"\1", path)
    query = _strip_image_view_query(parts.query)
    return urlunsplit((parts.scheme, parts.netloc, path, query, ""))


def pdd_original_url(url: str) -> str:
    """拼多多: 去掉 imageMogr2 处理参数与 webp 包装。"""
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    path = parts.path
    path = re.sub(r"(?i)(\.(?:jpg|jpeg|png))_?\.webp$", r"\1", path)
    query = _strip_image_view_query(parts.query)
    return urlunsplit((parts.scheme, parts.netloc, path, query, ""))


def original_url(url: str, platform: Optional[Platform] = None) -> str:
    platform = platform or detect_platform(url)
    if platform is Platform.JD:
        return jd_original_url(url)
    if platform is Platform.TAOBAO:
        return taobao_original_url(url)
    if platform is Platform.PDD:
        return pdd_original_url(url)
    return url


def original_candidates(url: str, platform: Optional[Platform] = None) -> List[str]:
    """优先原图，失败时回退到页面提供的地址。"""
    resolved = original_url(url, platform)
    candidates: List[str] = []
    for candidate in (resolved, url):
        candidate = candidate.strip()
        if candidate and candidate not in candidates:
            candidates.append(candidate)
    return candidates


def normalize_url(url: str) -> str:
    if not url:
        return ""
    url = url.strip()
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("http://"):
        return "https://" + url[len("http://") :]
    return url
