from __future__ import annotations

import unittest

from app.core.models import MatchCandidate, Platform, Product
from app.services.matcher import (
    best_candidate,
    build_query,
    is_flagship_store,
    rank_candidates,
    similarity,
)


class TestMatcher(unittest.TestCase):
    def setUp(self):
        self.product = Product(seq=1, name="Apple iPhone 16", spec="256G 黑色")

    def test_flagship_detection(self):
        self.assertTrue(is_flagship_store("Apple产品京东自营旗舰店"))
        self.assertTrue(is_flagship_store("华为官方旗舰店"))
        self.assertFalse(is_flagship_store("数码精品小店"))
        self.assertFalse(is_flagship_store(""))

    def test_similarity(self):
        self.assertGreater(similarity("iPhone 16 256G", "Apple iPhone 16 256G"), 0.5)
        self.assertLess(similarity("iPhone 16", "洗衣机"), 0.5)

    def test_query(self):
        self.assertEqual(build_query(self.product), "Apple iPhone 16 256G 黑色")

    def test_flagship_ranks_first(self):
        candidates = [
            MatchCandidate(
                platform=Platform.JD,
                title="Apple iPhone 16 256G 黑色 手机",
                url="https://item.jd.com/1.html",
                store="数码小店",
                sales=100,
            ),
            MatchCandidate(
                platform=Platform.JD,
                title="Apple iPhone 16 256G 黑色 手机",
                url="https://item.jd.com/2.html",
                store="Apple产品京东自营旗舰店",
                is_flagship=True,
                sales=10000,
            ),
        ]
        ranked = rank_candidates(candidates, self.product)
        self.assertEqual(ranked[0].url, "https://item.jd.com/2.html")

    def test_best_candidate_threshold(self):
        weak = [
            MatchCandidate(
                platform=Platform.JD,
                title="洗衣机全自动",
                url="https://item.jd.com/9.html",
                store="家电小店",
            )
        ]
        self.assertIsNone(best_candidate(weak, self.product))
        strong = [
            MatchCandidate(
                platform=Platform.JD,
                title="Apple iPhone 16 256G 黑色",
                url="https://item.jd.com/1.html",
                store="Apple产品京东自营旗舰店",
                sales=50000,
            )
        ]
        chosen = best_candidate(strong, self.product)
        self.assertIsNotNone(chosen)
        self.assertEqual(chosen.url, "https://item.jd.com/1.html")

    def test_store_hint_bonus(self):
        candidate = MatchCandidate(
            platform=Platform.TAOBAO,
            title="Apple iPhone 16 256G",
            url="https://item.taobao.com/item.htm?id=1",
            store="Apple 官方旗舰店",
        )
        hinted = Product(seq=1, name="Apple iPhone 16", spec="256G", store_hint="Apple")
        ranked = rank_candidates([candidate], hinted)
        self.assertGreater(ranked[0].score, 50)


if __name__ == "__main__":
    unittest.main()
