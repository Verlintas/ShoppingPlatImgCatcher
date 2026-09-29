from __future__ import annotations

import unittest

from app.core.models import ImageKind, Platform
from app.services.naming import image_filename, product_folder, sanitize


class TestSanitize(unittest.TestCase):
    def test_illegal_chars(self):
        self.assertEqual(sanitize('a/b\\c:d*e?f"g<h>i|j'), "a_b_c_d_e_f_g_h_i_j")

    def test_reserved(self):
        self.assertEqual(sanitize("CON"), "未命名")
        self.assertEqual(sanitize("com1"), "未命名")

    def test_empty(self):
        self.assertEqual(sanitize("   "), "未命名")
        self.assertEqual(sanitize("..."), "未命名")

    def test_truncate(self):
        result = sanitize("x" * 200, max_len=20)
        self.assertEqual(len(result), 20)
        self.assertTrue(result.endswith("x"))

    def test_strip_windows_trailing(self):
        self.assertEqual(sanitize("name. "), "name")


class TestNames(unittest.TestCase):
    def test_product_folder(self):
        self.assertEqual(product_folder(3, "iPhone 16"), "003_iPhone 16")
        self.assertEqual(
            product_folder(12, "戴森/吹风机", "100012043978"),
            "012_戴森_吹风机_100012043978",
        )

    def test_image_filename(self):
        name = image_filename(Platform.JD, ImageKind.MAIN, 2, "jpg", 800, 800)
        self.assertEqual(name, "jd_main_002_800x800.jpg")

    def test_image_filename_no_size(self):
        name = image_filename(Platform.PDD, ImageKind.DETAIL, 10, ".png")
        self.assertEqual(name, "pdd_detail_010.png")


if __name__ == "__main__":
    unittest.main()
