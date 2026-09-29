from __future__ import annotations

import struct
import unittest

from app.services.image_meta import ext_from_content_type, sniff_image


def make_png(width: int, height: int) -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n"
        + struct.pack(">I", 13)
        + b"IHDR"
        + struct.pack(">II", width, height)
        + b"\x08\x02\x00\x00\x00"
    )


def make_gif(width: int, height: int) -> bytes:
    return b"GIF89a" + struct.pack("<HH", width, height) + b"\x00" * 8


def make_jpeg(width: int, height: int) -> bytes:
    app0 = (
        b"\xff\xe0"
        + struct.pack(">H", 16)
        + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    )
    sof0 = (
        b"\xff\xc0"
        + struct.pack(">H", 17)
        + bytes([8])
        + struct.pack(">HH", height, width)
        + b"\x03"
        + b"\x01\x11\x00" * 3
    )
    return b"\xff\xd8" + app0 + sof0 + b"\xff\xd9"


def make_webp_vp8x(width: int, height: int) -> bytes:
    header = b"RIFF" + struct.pack("<I", 22) + b"WEBP" + b"VP8X"
    payload = struct.pack("<I", 0)[:3] + b"\x00" * 1
    dims = (width - 1).to_bytes(3, "little") + (height - 1).to_bytes(3, "little")
    return header + b"\x0a\x00\x00\x00" + payload + dims


class TestSniff(unittest.TestCase):
    def test_png(self):
        self.assertEqual(sniff_image(make_png(800, 600)), ("png", 800, 600))

    def test_jpeg(self):
        self.assertEqual(sniff_image(make_jpeg(750, 1000)), ("jpg", 750, 1000))

    def test_gif(self):
        self.assertEqual(sniff_image(make_gif(200, 100)), ("gif", 200, 100))

    def test_webp(self):
        self.assertEqual(sniff_image(make_webp_vp8x(640, 480)), ("webp", 640, 480))

    def test_not_image(self):
        self.assertIsNone(sniff_image(b"<html>not an image</html>"))
        self.assertIsNone(sniff_image(b""))

    def test_content_type(self):
        self.assertEqual(ext_from_content_type("image/jpeg; charset=binary"), "jpg")
        self.assertEqual(ext_from_content_type("image/webp"), "webp")
        self.assertEqual(ext_from_content_type("text/html"), "")


if __name__ == "__main__":
    unittest.main()
