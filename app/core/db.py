from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

from app.core.models import (
    ImageAsset,
    ImageKind,
    Platform,
    Product,
    ProductTarget,
    TargetSource,
    TargetStatus,
)

SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS products(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  seq INTEGER NOT NULL DEFAULT 0,
  name TEXT NOT NULL,
  spec TEXT NOT NULL DEFAULT '',
  remark TEXT NOT NULL DEFAULT '',
  store_hint TEXT NOT NULL DEFAULT '',
  created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS targets(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
  platform TEXT NOT NULL,
  url TEXT NOT NULL DEFAULT '',
  store TEXT NOT NULL DEFAULT '',
  title TEXT NOT NULL DEFAULT '',
  source TEXT NOT NULL DEFAULT 'auto',
  status TEXT NOT NULL DEFAULT 'pending',
  error TEXT NOT NULL DEFAULT '',
  updated_at REAL NOT NULL,
  UNIQUE(product_id, platform)
);

CREATE TABLE IF NOT EXISTS assets(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  target_id INTEGER NOT NULL REFERENCES targets(id) ON DELETE CASCADE,
  kind TEXT NOT NULL DEFAULT 'main',
  source_url TEXT NOT NULL,
  original_url TEXT NOT NULL DEFAULT '',
  path TEXT NOT NULL DEFAULT '',
  sha256 TEXT NOT NULL DEFAULT '',
  size INTEGER NOT NULL DEFAULT 0,
  width INTEGER NOT NULL DEFAULT 0,
  height INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'pending',
  error TEXT NOT NULL DEFAULT '',
  created_at REAL NOT NULL,
  UNIQUE(target_id, source_url)
);

CREATE INDEX IF NOT EXISTS idx_targets_product ON targets(product_id);
CREATE INDEX IF NOT EXISTS idx_assets_target ON assets(target_id);
CREATE INDEX IF NOT EXISTS idx_assets_sha ON assets(sha256);
"""


def _now() -> float:
    return time.time()


class Database:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ---------------------------------------------------------------- products
    def clear_products(self) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM products")
            self._conn.commit()

    def add_products(self, products: Sequence[Product], replace: bool = False) -> List[int]:
        ids: List[int] = []
        with self._lock:
            if replace:
                self._conn.execute("DELETE FROM products")
            for index, product in enumerate(products, start=1):
                seq = product.seq or index
                cur = self._conn.execute(
                    "INSERT INTO products(seq, name, spec, remark, store_hint, created_at) "
                    "VALUES(?,?,?,?,?,?)",
                    (seq, product.name, product.spec, product.remark, product.store_hint, _now()),
                )
                pid = int(cur.lastrowid)
                ids.append(pid)
                for platform in Platform:
                    self._conn.execute(
                        "INSERT OR IGNORE INTO targets(product_id, platform, updated_at) "
                        "VALUES(?,?,?)",
                        (pid, platform.value, _now()),
                    )
            self._conn.commit()
        return ids

    def update_product(self, product: Product) -> None:
        if product.id is None:
            return
        with self._lock:
            self._conn.execute(
                "UPDATE products SET name=?, spec=?, remark=?, store_hint=? WHERE id=?",
                (product.name, product.spec, product.remark, product.store_hint, product.id),
            )
            self._conn.commit()

    def list_products(self) -> List[Product]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM products ORDER BY seq, id"
            ).fetchall()
        return [
            Product(
                id=int(r["id"]),
                seq=int(r["seq"]),
                name=r["name"],
                spec=r["spec"],
                remark=r["remark"],
                store_hint=r["store_hint"],
            )
            for r in rows
        ]

    def get_product(self, product_id: int) -> Optional[Product]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM products WHERE id=?", (product_id,)
            ).fetchone()
        if row is None:
            return None
        return Product(
            id=int(row["id"]),
            seq=int(row["seq"]),
            name=row["name"],
            spec=row["spec"],
            remark=row["remark"],
            store_hint=row["store_hint"],
        )

    # ----------------------------------------------------------------- targets
    def upsert_target(
        self,
        product_id: int,
        platform: Platform,
        url: str,
        store: str = "",
        title: str = "",
        source: TargetSource = TargetSource.AUTO,
        status: Optional[TargetStatus] = None,
    ) -> None:
        if status is None:
            status = TargetStatus.MATCHED if url else TargetStatus.PENDING
        with self._lock:
            self._conn.execute(
                "INSERT INTO targets(product_id, platform, url, store, title, source, status, updated_at) "
                "VALUES(?,?,?,?,?,?,?,?) "
                "ON CONFLICT(product_id, platform) DO UPDATE SET "
                "url=excluded.url, store=excluded.store, title=excluded.title, "
                "source=excluded.source, status=excluded.status, error='', updated_at=excluded.updated_at",
                (product_id, platform.value, url, store, title, source.value, status.value, _now()),
            )
            self._conn.commit()

    def set_target_status(
        self, target_id: int, status: TargetStatus, error: str = "", url: Optional[str] = None
    ) -> None:
        with self._lock:
            if url is None:
                self._conn.execute(
                    "UPDATE targets SET status=?, error=?, updated_at=? WHERE id=?",
                    (status.value, error, _now(), target_id),
                )
            else:
                self._conn.execute(
                    "UPDATE targets SET status=?, error=?, url=?, updated_at=? WHERE id=?",
                    (status.value, error, url, _now(), target_id),
                )
            self._conn.commit()

    def reset_running_targets(self) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE targets SET status='failed', error='上次运行中断', updated_at=? "
                "WHERE status='running'",
                (_now(),),
            )
            self._conn.commit()

    def list_targets(self) -> List[ProductTarget]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT t.*, p.name AS product_name, p.seq AS product_seq "
                "FROM targets t JOIN products p ON p.id = t.product_id "
                "ORDER BY p.seq, p.id, t.platform"
            ).fetchall()
        return [self._row_to_target(r) for r in rows]

    def list_targets_for_product(self, product_id: int) -> List[ProductTarget]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT t.*, p.name AS product_name, p.seq AS product_seq "
                "FROM targets t JOIN products p ON p.id = t.product_id "
                "WHERE t.product_id=? ORDER BY t.platform",
                (product_id,),
            ).fetchall()
        return [self._row_to_target(r) for r in rows]

    def list_runnable_targets(self, include_done: bool = False) -> List[ProductTarget]:
        statuses = ["matched", "failed", "running"]
        if include_done:
            statuses.append("done")
        placeholders = ",".join("?" for _ in statuses)
        with self._lock:
            rows = self._conn.execute(
                "SELECT t.*, p.name AS product_name, p.seq AS product_seq "
                "FROM targets t JOIN products p ON p.id = t.product_id "
                f"WHERE t.url <> '' AND t.status IN ({placeholders}) "
                "ORDER BY p.seq, p.id, t.platform",
                statuses,
            ).fetchall()
        return [self._row_to_target(r) for r in rows]

    def update_target_meta(self, target_id: int, title: str = "", store: str = "") -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE targets SET title=?, store=?, updated_at=? WHERE id=?",
                (title, store, _now(), target_id),
            )
            self._conn.commit()

    @staticmethod
    def _row_to_target(row: sqlite3.Row) -> ProductTarget:
        return ProductTarget(
            id=int(row["id"]),
            product_id=int(row["product_id"]),
            platform=Platform(row["platform"]),
            url=row["url"],
            store=row["store"],
            title=row["title"],
            source=TargetSource(row["source"]),
            status=TargetStatus(row["status"]),
            error=row["error"],
            product_name=row["product_name"],
            product_seq=int(row["product_seq"]),
        )

    # ------------------------------------------------------------------ assets
    def add_asset(self, asset: ImageAsset) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO assets(target_id, kind, source_url, original_url, path, sha256, "
                "size, width, height, status, error, created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(target_id, source_url) DO UPDATE SET "
                "original_url=excluded.original_url, path=excluded.path, sha256=excluded.sha256, "
                "size=excluded.size, width=excluded.width, height=excluded.height, "
                "status=excluded.status, error=excluded.error",
                (
                    asset.target_id,
                    asset.kind.value,
                    asset.source_url,
                    asset.original_url,
                    asset.path,
                    asset.sha256,
                    asset.size,
                    asset.width,
                    asset.height,
                    asset.status,
                    asset.error,
                    _now(),
                ),
            )
            self._conn.commit()
            return int(cur.lastrowid or 0)

    def list_assets(self, target_id: Optional[int] = None) -> List[ImageAsset]:
        with self._lock:
            if target_id is None:
                rows = self._conn.execute("SELECT * FROM assets ORDER BY id").fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM assets WHERE target_id=? ORDER BY id", (target_id,)
                ).fetchall()
        return [
            ImageAsset(
                id=int(r["id"]),
                target_id=int(r["target_id"]),
                kind=ImageKind(r["kind"]),
                source_url=r["source_url"],
                original_url=r["original_url"],
                path=r["path"],
                sha256=r["sha256"],
                size=int(r["size"]),
                width=int(r["width"]),
                height=int(r["height"]),
                status=r["status"],
                error=r["error"],
            )
            for r in rows
        ]

    def has_original_url(self, target_id: int, original_url: str) -> bool:
        if not original_url:
            return False
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM assets WHERE target_id=? AND original_url=? AND status='ok' LIMIT 1",
                (target_id, original_url),
            ).fetchone()
        return row is not None

    def has_asset_url(self, target_id: int, source_url: str) -> bool:
        if not source_url:
            return False
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM assets WHERE target_id=? AND source_url=? AND status='ok' LIMIT 1",
                (target_id, source_url),
            ).fetchone()
        return row is not None

    def target_asset_hashes(self, target_id: int) -> set:
        with self._lock:
            rows = self._conn.execute(
                "SELECT sha256 FROM assets WHERE target_id=? AND status='ok' AND sha256 <> ''",
                (target_id,),
            ).fetchall()
        return {r["sha256"] for r in rows}

    def stats(self) -> Dict[str, int]:
        with self._lock:
            products = self._conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
            targets = self._conn.execute(
                "SELECT COUNT(*) FROM targets WHERE url <> ''"
            ).fetchone()[0]
            done = self._conn.execute(
                "SELECT COUNT(*) FROM targets WHERE status='done' AND url <> ''"
            ).fetchone()[0]
            assets = self._conn.execute(
                "SELECT COUNT(*) FROM assets WHERE status='ok'"
            ).fetchone()[0]
        return {
            "products": int(products),
            "targets": int(targets),
            "done": int(done),
            "assets": int(assets),
        }
