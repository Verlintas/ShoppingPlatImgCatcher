from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.core.db import Database
from app.core.models import (
    ImageAsset,
    ImageKind,
    Platform,
    Product,
    TargetSource,
    TargetStatus,
)


class TestDatabase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "test.sqlite3")

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_add_and_list_products(self):
        ids = self.db.add_products(
            [Product(seq=1, name="A"), Product(seq=2, name="B", spec="256G")]
        )
        self.assertEqual(len(ids), 2)
        products = self.db.list_products()
        self.assertEqual([p.name for p in products], ["A", "B"])
        self.assertEqual(products[1].spec, "256G")

    def test_replace_products_clears(self):
        self.db.add_products([Product(seq=1, name="A")], replace=True)
        self.db.add_products([Product(seq=1, name="B")], replace=True)
        products = self.db.list_products()
        self.assertEqual(len(products), 1)
        self.assertEqual(products[0].name, "B")

    def test_targets_created_for_all_platforms(self):
        self.db.add_products([Product(seq=1, name="A")])
        targets = self.db.list_targets()
        self.assertEqual(len(targets), 3)
        self.assertTrue(all(t.status is TargetStatus.PENDING for t in targets))

    def test_upsert_target_and_urls(self):
        self.db.add_products([Product(seq=1, name="A")])
        product = self.db.list_products()[0]
        self.db.upsert_target(
            product.id,
            Platform.JD,
            "https://item.jd.com/1.html",
            store="测试旗舰店",
            source=TargetSource.AUTO,
        )
        target = [t for t in self.db.list_targets() if t.platform is Platform.JD][0]
        self.assertEqual(target.store, "测试旗舰店")
        self.assertIs(target.status, TargetStatus.MATCHED)
        self.db.set_target_status(target.id, TargetStatus.DONE)
        target = [t for t in self.db.list_targets() if t.platform is Platform.JD][0]
        self.assertIs(target.status, TargetStatus.DONE)

    def test_runnable_filter(self):
        self.db.add_products([Product(seq=1, name="A")])
        product = self.db.list_products()[0]
        self.db.upsert_target(product.id, Platform.JD, "https://item.jd.com/1.html")
        self.db.upsert_target(product.id, Platform.PDD, "https://x/goods.html?goods_id=2")
        runnable = self.db.list_runnable_targets()
        self.assertEqual({t.platform for t in runnable}, {Platform.JD, Platform.PDD})
        self.assertEqual(len(self.db.list_runnable_targets(include_done=True)), 2)

    def test_assets_and_dedupe_helpers(self):
        self.db.add_products([Product(seq=1, name="A")])
        product = self.db.list_products()[0]
        self.db.upsert_target(product.id, Platform.JD, "https://item.jd.com/1.html")
        target = [t for t in self.db.list_targets() if t.platform is Platform.JD][0]
        asset = ImageAsset(
            target_id=target.id,
            kind=ImageKind.MAIN,
            source_url="https://img.jd.com/a.jpg",
            original_url="https://img.jd.com/a.jpg",
            sha256="abc",
            status="ok",
        )
        self.db.add_asset(asset)
        self.assertTrue(self.db.has_asset_url(target.id, "https://img.jd.com/a.jpg"))
        self.assertTrue(
            self.db.has_original_url(target.id, "https://img.jd.com/a.jpg")
        )
        self.assertFalse(self.db.has_asset_url(target.id, "https://img.jd.com/b.jpg"))
        self.assertEqual(self.db.target_asset_hashes(target.id), {"abc"})
        self.assertEqual(len(self.db.list_assets(target.id)), 1)

    def test_stats(self):
        self.db.add_products([Product(seq=1, name="A")])
        product = self.db.list_products()[0]
        self.db.upsert_target(product.id, Platform.JD, "https://item.jd.com/1.html")
        stats = self.db.stats()
        self.assertEqual(stats["products"], 1)
        self.assertEqual(stats["targets"], 1)


if __name__ == "__main__":
    unittest.main()
