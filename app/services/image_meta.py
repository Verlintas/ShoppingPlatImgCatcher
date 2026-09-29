from __future__ import annotations

import struct
from typing import Optional, Tuple

ImageInfo = Tuple[str, int, int]


def _png(data: bytes) -> Optional[ImageInfo]:
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    width, height = struct.unpack(">II", data[16:24])
    return "png", int(width), int(height)


def _gif(data: bytes) -> Optional[ImageInfo]:
    if len(data) < 10 or data[:6] not in (b"GIF87a", b"GIF89a"):
        return None
    width, height = struct.unpack("<HH", data[6:10])
    return "gif", int(width), int(height)


def _bmp(data: bytes) -> Optional[ImageInfo]:
    if len(data) < 26 or data[:2] != b"BM":
        return None
    width, height = struct.unpack("<ii", data[18:26])
    return "bmp", abs(int(width)), abs(int(height))


def _jpeg(data: bytes) -> Optional[ImageInfo]:
    if len(data) < 4 or data[0:2] != b"\xff\xd8":
        return None
    offset = 2
    total = len(data)
    while offset + 4 <= total:
        if data[offset] != 0xFF:
            offset += 1
            continue
        marker = data[offset + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            offset += 2
            continue
        if marker == 0xD9:
            return None
        if offset + 4 > total:
            return None
        seg_len = struct.unpack(">H", data[offset + 2 : offset + 4])[0]
        if seg_len < 2:
            return None
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            if offset + 9 > total:
                return None
            height, width = struct.unpack(">HH", data[offset + 5 : offset + 9])
            return "jpg", int(width), int(height)
        offset += 2 + seg_len
    return None


def _webp(data: bytes) -> Optional[ImageInfo]:
    if len(data) < 30 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        return None
    chunk = data[12:16]
    if chunk == b"VP8 ":
        width, height = struct.unpack("<HH", data[26:30])
        return "webp", int(width & 0x3FFF), int(height & 0x3FFF)
    if chunk == b"VP8L":
        bits = struct.unpack("<I", data[21:25])[0]
        width = (bits & 0x3FFF) + 1
        height = ((bits >> 14) & 0x3FFF) + 1
        return "webp", int(width), int(height)
    if chunk == b"VP8X":
        width = int.from_bytes(data[24:27], "little") + 1
        height = int.from_bytes(data[27:30], "little") + 1
        return "webp", int(width), int(height)
    return None


def sniff_image(data: bytes) -> Optional[ImageInfo]:
    """返回 (扩展名, 宽, 高)，非图片返回 None。"""
    if not data or len(data) < 12:
        return None
    for parser in (_png, _jpeg, _gif, _webp, _bmp):
        info = parser(data)
        if info:
            if info[1] <= 0 or info[2] <= 0 or info[1] > 100000 or info[2] > 100000:
                return None
            return info
    return None


def ext_from_content_type(content_type: str) -> str:
    content_type = (content_type or "").split(";")[0].strip().lower()
    return {
        "image/jpeg": "jpg",
        "image/jpg": "jpg",
        "image/png": "png",
        "image/gif": "gif",
        "image/webp": "webp",
        "image/bmp": "bmp",
        "image/avif": "avif",
    }.get(content_type, "")
