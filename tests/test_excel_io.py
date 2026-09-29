from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.core.models import Platform
from app.services.excel_io import (
    build_header_map,
    load_rows,
    parse_keyword_text,
    parse_paste_text,
)


class TestHeaderMap(unittest.TestCase):
    def test_aliases(self):
        header = ["商品名称", "规格/型号", "京东链接", "淘宝链接", "拼多多链接", "店铺名", "备注"]
        mapping = build_header_map(header)
        self.assertEqual(mapping["name"], 0)
        self.assertEqual(mapping["spec"], 1)
        self.assertEqual(mapping["jd"], 2)
        self.assertEqual(mapping["tb"], 3)
        self.assertEqual(mapping["pdd"], 4)
        self.assertEqual(mapping["store_hint"], 5)
        self.assertEqual(mapping["remark"], 6)

    def test_english_aliases(self):
        mapping = build_header_map(["name", "spec", "jd", "taobao", "pdd"])
        self.assertEqual(mapping["name"], 0)
        self.assertEqual(mapping["tb"], 3)


class TestPasteParsing(unittest.TestCase):
    def test_paste_with_urls(self):
        text = (
            "Apple iPhone 16 256G, https://item.jd.com/100012043978.html\n"
            "戴森 HD08 https://item.taobao.com/item.htm?id=123 https://mobile.yangkeduo.com/goods.html?goods_id=9\n"
        )
        rows = parse_paste_text(text)
        self.assertEqual(len(rows), 2)
        self.assertIn(Platform.JD, rows[0].links)
        self.assertEqual(rows[0].product.name, "Apple iPhone 16 256G")
        self.assertIn(Platform.TAOBAO, rows[1].links)
        self.assertIn(Platform.PDD, rows[1].links)
        self.assertEqual(rows[1].product.name, "戴森 HD08")

    def test_paste_plain_url(self):
        rows = parse_paste_text("https://item.jd.com/100012043978.html\n")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].product.name, "商品001")

    def test_keywords(self):
        rows = parse_keyword_text("Apple iPhone 16, 256G\n戴森吹风机\n# 注释\n")
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].product.spec, "256G")
        self.assertEqual(rows[1].product.spec, "")


class TestLoadRows(unittest.TestCase):
    def test_load_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "input.csv"
            path.write_text(
                "商品名称,规格,京东链接\niPhone 16,256G,https://item.jd.com/1.html\n",
                encoding="utf-8-sig",
            )
            rows = load_rows(path)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].product.name, "iPhone 16")
            self.assertEqual(rows[0].links[Platform.JD], "https://item.jd.com/1.html")

    def test_load_csv_without_header(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "input.csv"
            path.write_text("iPhone 16\nMate 70\n", encoding="utf-8-sig")
            rows = load_rows(path)
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0].product.name, "iPhone 16")

    def test_missing_file_type(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "input.xyz"
            path.write_text("x", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_rows(path)


if __name__ == "__main__":
    unittest.main()
