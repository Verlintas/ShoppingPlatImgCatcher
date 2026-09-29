from __future__ import annotations

import unittest

from app.core.models import Platform
from app.services.urls import (
    detect_platform,
    goods_id,
    jd_original_url,
    normalize_url,
    original_candidates,
    original_url,
    pdd_original_url,
    taobao_original_url,
)


class TestPlatformDetection(unittest.TestCase):
    def test_jd(self):
        self.assertIs(detect_platform("https://item.jd.com/100012043978.html"), Platform.JD)
        self.assertIs(detect_platform("https://item.m.jd.com/product/100012043978.html"), Platform.JD)

    def test_taobao(self):
        self.assertIs(
            detect_platform("https://item.taobao.com/item.htm?id=123456"), Platform.TAOBAO
        )
        self.assertIs(
            detect_platform("https://detail.tmall.com/item.htm?id=123456"), Platform.TAOBAO
        )

    def test_pdd(self):
        self.assertIs(
            detect_platform("https://mobile.yangkeduo.com/goods.html?goods_id=123"),
            Platform.PDD,
        )

    def test_unknown(self):
        self.assertIsNone(detect_platform("https://example.com/a.jpg"))
        self.assertIsNone(detect_platform("not-a-url"))


class TestGoodsId(unittest.TestCase):
    def test_jd_id(self):
        self.assertEqual(goods_id("https://item.jd.com/100012043978.html"), "100012043978")

    def test_taobao_id(self):
        self.assertEqual(
            goods_id("https://item.taobao.com/item.htm?id=654321&spm=a.b.c"), "654321"
        )

    def test_pdd_id(self):
        self.assertEqual(
            goods_id("https://mobile.yangkeduo.com/goods.html?goods_id=998877"), "998877"
        )

    def test_missing(self):
        self.assertEqual(goods_id("https://item.jd.com/abc.html"), "")


class TestOriginalUrl(unittest.TestCase):
    def test_jd_search_thumb(self):
        url = "https://img14.360buyimg.com/s450x450_jfs/t1/123/45/678/12345/abc.jpg"
        self.assertEqual(
            jd_original_url(url),
            "https://img14.360buyimg.com/jfs/t1/123/45/678/12345/abc.jpg",
        )

    def test_jd_n_spec(self):
        url = "https://img14.360buyimg.com/n1/jfs/t1/123/45/678/12345/abc.jpg"
        self.assertEqual(
            jd_original_url(url),
            "https://img14.360buyimg.com/n0/jfs/t1/123/45/678/12345/abc.jpg",
        )

    def test_jd_image_view_query(self):
        url = "https://img14.360buyimg.com/n1/jfs/t1/abc.jpg?imageView2/2/w/800"
        self.assertNotIn("imageView2", jd_original_url(url))

    def test_taobao_thumb_suffix(self):
        url = "https://img.alicdn.com/imgextra/i3/123/O1CN01abc.jpg_430x430q90.jpg"
        self.assertEqual(
            taobao_original_url(url),
            "https://img.alicdn.com/imgextra/i3/123/O1CN01abc.jpg",
        )

    def test_taobao_webp_suffix(self):
        url = "https://img.alicdn.com/imgextra/i3/123/O1CN01abc.jpg_.webp"
        self.assertEqual(
            taobao_original_url(url),
            "https://img.alicdn.com/imgextra/i3/123/O1CN01abc.jpg",
        )

    def test_taobao_plain(self):
        url = "https://img.alicdn.com/bao/uploaded/i3/123/O1CN01abc.jpg"
        self.assertEqual(taobao_original_url(url), url)

    def test_pdd_query_and_webp(self):
        url = "https://img.pddpic.com/mms-material-img/2021/abc.jpg?imageMogr2/thumbnail"
        self.assertEqual(
            pdd_original_url(url),
            "https://img.pddpic.com/mms-material-img/2021/abc.jpg",
        )
        self.assertEqual(
            pdd_original_url("https://t16img.yangkeduo.com/goods/images/abc.jpg_.webp"),
            "https://t16img.yangkeduo.com/goods/images/abc.jpg",
        )

    def test_candidates_order(self):
        url = "https://img14.360buyimg.com/n1/jfs/t1/abc.jpg"
        candidates = original_candidates(url)
        self.assertEqual(len(candidates), 2)
        self.assertEqual(candidates[0], "https://img14.360buyimg.com/n0/jfs/t1/abc.jpg")
        self.assertEqual(candidates[1], url)

    def test_original_url_dispatch(self):
        url = "https://img.alicdn.com/i3/123/O1CN01abc.jpg_50x50.jpg"
        self.assertEqual(original_url(url), taobao_original_url(url))

    def test_normalize(self):
        self.assertEqual(normalize_url("//img.jd.com/a.jpg"), "https://img.jd.com/a.jpg")
        self.assertEqual(
            normalize_url("http://img.jd.com/a.jpg"), "https://img.jd.com/a.jpg"
        )


if __name__ == "__main__":
    unittest.main()
