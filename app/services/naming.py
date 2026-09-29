from __future__ import annotations

import re
import unicodedata

from app.core.models import ImageKind, Platform

ILLEGAL_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
WHITESPACE = re.compile(r"\s+")
RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def sanitize(name: str, max_len: int = 80, fallback: str = "未命名") -> str:
    if not name:
        return fallback
    text = unicodedata.normalize("NFKC", str(name))
    text = ILLEGAL_CHARS.sub("_", text)
    text = WHITESPACE.sub(" ", text).strip(" .")
    text = text.replace("\u3000", " ").strip()
    if len(text) > max_len:
        text = text[:max_len].rstrip(" .")
    if not text or text.upper() in RESERVED_NAMES:
        return fallback
    return text


def product_folder(seq: int, name: str, goods_id: str = "") -> str:
    base = f"{seq:03d}_{sanitize(name, max_len=60)}"
    if goods_id:
        base = f"{base}_{goods_id}"
    return sanitize(base, max_len=100, fallback=f"{seq:03d}_product")


def image_filename(
    platform: Platform,
    kind: ImageKind,
    index: int,
    ext: str,
    width: int = 0,
    height: int = 0,
) -> str:
    ext = (ext or "jpg").lower().lstrip(".")
    dimensions = f"_{width}x{height}" if width and height else ""
    return f"{platform.value}_{kind.value}_{index:03d}{dimensions}.{ext}"


def manifest_filename() -> str:
    return "manifest.json"
