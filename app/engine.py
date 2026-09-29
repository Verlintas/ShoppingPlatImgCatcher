from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set

from app.core.config import Settings
from app.core.db import Database
from app.core.events import EventBus, EventType
from app.core.logging_setup import logger
from app.core.models import (
    ImageAsset,
    ImageKind,
    Platform,
    Product,
    ProductTarget,
    TargetRunResult,
    TargetSource,
    TargetStatus,
)
from app.platforms.base import LoginRequired, PlatformAdapter, RiskDetected
from app.platforms.browser import BrowserManager
from app.platforms.registry import create_adapters
from app.services.downloader import DownloadError, ImageFetcher, save_image, unique_path
from app.services.matcher import best_candidate, rank_candidates
from app.services.naming import image_filename, manifest_filename, product_folder
from app.services.playwright_setup import ensure_browser
from app.services.report import (
    asset_row,
    summary_row,
    write_manifest,
    write_summary_report,
)
from app.services.urls import original_url


@dataclass
class EngineConfig:
    min_match_score: float = 55.0
    search_limit: int = 8
    include_done: bool = False


class Engine:
    def __init__(self, db: Database, settings: Settings, bus: EventBus) -> None:
        self.db = db
        self.settings = settings
        self.bus = bus
        self.browser: Optional[BrowserManager] = None
        self.adapters: Dict[Platform, PlatformAdapter] = {}
        self.fetcher: Optional[ImageFetcher] = None
        self._stop = False
        self._running = False
        self._resume_events: Dict[Platform, asyncio.Event] = {}
        self._semaphores: Dict[Platform, asyncio.Semaphore] = {}

    # ----------------------------------------------------------------- basics
    def emit(self, event_type: str, message: str = "", level: str = "info", **payload) -> None:
        self.bus.emit(event_type, message, level, **payload)

    @property
    def running(self) -> bool:
        return self._running

    def request_stop(self) -> None:
        self._stop = True
        for event in self._resume_events.values():
            event.set()

    def _platform_enabled(self, platform: Platform) -> bool:
        return bool(self.settings.platform_enabled.get(platform.value, True))

    async def start(self) -> None:
        if self.browser is not None:
            return
        await ensure_browser(self.settings, on_log=lambda message: self.emit(EventType.LOG, message))
        self.browser = BrowserManager(self.settings, on_event=self.bus.emit)
        await self.browser.start()
        self.adapters = create_adapters(self.browser, self.settings, self.bus.emit)
        self._resume_events = {platform: asyncio.Event() for platform in Platform}
        for event in self._resume_events.values():
            event.set()
        self._semaphores = {
            platform: asyncio.Semaphore(
                max(1, int(self.settings.concurrency.get(platform.value, 2)))
            )
            for platform in Platform
        }
        self.fetcher = ImageFetcher(self.settings, await self._cookies())

    async def close(self) -> None:
        self.request_stop()
        if self.fetcher is not None:
            await self.fetcher.aclose()
            self.fetcher = None
        if self.browser is not None:
            await self.browser.close()
            self.browser = None
        self.adapters = {}

    async def _cookies(self) -> Dict[Platform, Dict[str, str]]:
        result: Dict[Platform, Dict[str, str]] = {}
        if self.browser is None:
            return result
        for platform in Platform:
            result[platform] = await self.browser.cookies(platform)
        return result

    async def refresh_cookies(self) -> None:
        if self.fetcher is not None:
            self.fetcher.cookies = await self._cookies()

    async def login(self, platform: Platform, timeout: float = 300.0) -> bool:
        await self.start()
        adapter = self.adapters[platform]
        ok = await adapter.ensure_login(timeout=timeout)
        await self.refresh_cookies()
        return ok

    async def login_status(self) -> Dict[str, bool]:
        await self.start()
        status: Dict[str, bool] = {}
        for platform, adapter in self.adapters.items():
            try:
                status[platform.value] = not await adapter.login_required()
            except Exception:  # noqa: BLE001
                status[platform.value] = False
        return status

    # ------------------------------------------------------------ 匹配阶段
    async def match_all(
        self,
        min_score: float = 55.0,
        limit: int = 8,
        product_ids: Optional[Set[int]] = None,
    ) -> int:
        if self._running:
            self.emit(EventType.ENGINE_ERROR, "已有任务在运行中", level="warning")
            return 0
        self._running = True
        self._stop = False
        matched = 0
        try:
            await self.start()
            products = self.db.list_products()
            if product_ids:
                products = [p for p in products if p.id in product_ids]
            existing = {
                (t.product_id, t.platform): t for t in self.db.list_targets()
            }
            pending: List[tuple] = []
            for product in products:
                for platform in Platform:
                    if not self._platform_enabled(platform):
                        continue
                    target = existing.get((product.id, platform))
                    if target and (target.url or target.status is TargetStatus.SKIPPED):
                        continue
                    pending.append((product, platform))
            total = len(pending)
            self.emit(
                EventType.MATCH_PROGRESS,
                f"开始自动匹配，共 {total} 个商品×平台",
                done=0,
                total=total,
            )
            for index, (product, platform) in enumerate(pending, start=1):
                if self._stop:
                    break
                adapter = self.adapters[platform]
                candidates: List = []
                try:
                    candidates = await self._search_with_retry(adapter, product, limit)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("搜索失败 {} {}: {}", product.name, platform.value, exc)
                best = best_candidate(candidates, product, min_score=min_score)
                if best is not None:
                    self.db.upsert_target(
                        product.id,
                        platform,
                        best.url,
                        best.store,
                        best.title,
                        TargetSource.AUTO,
                        TargetStatus.MATCHED,
                    )
                    matched += 1
                    self.emit(
                        EventType.MATCH_PROGRESS,
                        f"匹配成功 {product.name} · {platform.label} → {best.store_label}",
                        done=index,
                        total=total,
                        product_id=product.id,
                        platform=platform.value,
                        matched=True,
                    )
                else:
                    self.db.upsert_target(
                        product.id,
                        platform,
                        "",
                        "",
                        candidates[0].title if candidates else "",
                        TargetSource.AUTO,
                        TargetStatus.PENDING,
                    )
                    self.emit(
                        EventType.MATCH_PROGRESS,
                        f"未找到可信结果 {product.name} · {platform.label}，请人工确认",
                        level="warning",
                        done=index,
                        total=total,
                        product_id=product.id,
                        platform=platform.value,
                        matched=False,
                    )
            self.emit(
                EventType.MATCH_DONE,
                f"匹配完成：{matched}/{total}",
                matched=matched,
                total=total,
            )
            return matched
        finally:
            self._running = False

    async def _search_with_retry(
        self, adapter: PlatformAdapter, product: Product, limit: int, depth: int = 0
    ) -> List:
        page = None
        try:
            page = await self.browser.new_page(adapter.platform)
            if await adapter.login_required():
                ok = await adapter.ensure_login()
                await self.refresh_cookies()
                if not ok:
                    raise LoginRequired(adapter.platform)
            return await adapter.run_search(page, product.query, limit)
        except RiskDetected as exc:
            self.emit(
                EventType.RISK_DETECTED,
                f"{adapter.label} 触发风控：{exc.reason}",
                level="warning",
                platform=adapter.platform.value,
            )
            await self._pause_platform(adapter.platform)
            try:
                if depth < 1 and await adapter.resolve_risk(page.url if page else ""):
                    await self._resume_platform(adapter.platform)
                    return await self._search_with_retry(adapter, product, limit, depth + 1)
            finally:
                await self._resume_platform(adapter.platform)
            self.emit(EventType.RISK_RESOLVED, f"{adapter.label} 风控处理结束", level="warning")
            return []
        except LoginRequired:
            ok = await adapter.ensure_login()
            await self.refresh_cookies()
            if depth < 1 and ok:
                return await self._search_with_retry(adapter, product, limit, depth + 1)
            return []
        except Exception as exc:  # noqa: BLE001
            self.emit(
                EventType.MATCH_PROGRESS,
                f"{adapter.label} 搜索出错：{exc}",
                level="warning",
                product_id=product.id,
                platform=adapter.platform.value,
            )
            return []
        finally:
            if page is not None:
                try:
                    await page.close()
                except Exception:  # noqa: BLE001
                    pass

    async def search_candidates(
        self, product_id: int, platform: Platform, limit: int = 10
    ) -> List:
        await self.start()
        product = self.db.get_product(product_id)
        if product is None:
            return []
        adapter = self.adapters[platform]
        candidates = await self._search_with_retry(adapter, product, limit)
        return rank_candidates(candidates, product)

    async def manual_pick(
        self, product_id: int, platform: Platform, timeout: float = 600.0
    ) -> Optional[str]:
        await self.start()
        product = self.db.get_product(product_id)
        if product is None:
            return None
        adapter = self.adapters[platform]
        picker = getattr(adapter, "manual_pick", None)
        if picker is None:
            return None
        return await picker(product.query, timeout=timeout)

    async def _pause_platform(self, platform: Platform) -> None:
        self._resume_events[platform].clear()

    async def _resume_platform(self, platform: Platform) -> None:
        self._resume_events[platform].set()

    # ------------------------------------------------------------ 下载阶段
    async def run_targets(
        self,
        include_done: bool = False,
        product_ids: Optional[Set[int]] = None,
    ) -> List[TargetRunResult]:
        if self._running:
            self.emit(EventType.ENGINE_ERROR, "已有任务在运行中", level="warning")
            return []
        self._running = True
        self._stop = False
        results: List[TargetRunResult] = []
        try:
            await self.start()
            targets = self.db.list_runnable_targets(include_done=include_done)
            if product_ids:
                targets = [t for t in targets if t.product_id in product_ids]
            targets = [t for t in targets if self._platform_enabled(t.platform)]
            if not targets:
                self.emit(EventType.RUN_DONE, "没有可运行的下载任务", level="warning")
                return []
            self.emit(
                EventType.TASK_QUEUED,
                f"开始下载，共 {len(targets)} 个商品×平台任务",
                total=len(targets),
            )
            results = list(
                await asyncio.gather(*(self._run_target(target) for target in targets))
            )
            self._write_manifests(results)
            self._write_report(results)
            done = sum(1 for r in results if r.status is TargetStatus.DONE)
            saved = sum(r.saved for r in results)
            self.emit(
                EventType.RUN_DONE,
                f"下载结束：{done}/{len(results)} 个任务完成，共保存 {saved} 张图片",
                total=len(results),
                done=done,
                saved=saved,
            )
            return results
        finally:
            self._running = False

    async def _run_target(
        self, target: ProductTarget, depth: int = 0
    ) -> TargetRunResult:
        platform = target.platform
        adapter = self.adapters[platform]
        assert self.fetcher is not None
        await self._resume_events[platform].wait()
        async with self._semaphores[platform]:
            if self._stop:
                self.db.set_target_status(target.id, TargetStatus.PENDING, "已手动停止")
                return TargetRunResult(target.id, platform, target.product_id, TargetStatus.PENDING)
            self.db.set_target_status(target.id, TargetStatus.RUNNING)
            self.emit(
                EventType.TASK_STARTED,
                f"[{platform.label}] {target.product_name} 开始抓取",
                target_id=target.id,
                platform=platform.value,
            )
            try:
                page = await adapter.fetch(target.url)
                self.db.update_target_meta(target.id, page.title, page.store)
                if not page.images:
                    raise RuntimeError("未提取到任何图片（可能需要登录或页面结构变化）")
                output_dir = Path(self.settings.output_dir) / product_folder(
                    target.product_seq, target.product_name, page.goods_id
                )
                saved, skipped, failed = await self._download_images(
                    target, page.images, output_dir
                )
                status = TargetStatus.DONE if (saved or skipped) else TargetStatus.FAILED
                error = "" if status is TargetStatus.DONE else "所有图片下载失败"
                self.db.set_target_status(target.id, status, error)
                self.emit(
                    EventType.TASK_FINISHED,
                    f"[{platform.label}] {target.product_name} 完成："
                    f"新增 {saved}，跳过 {skipped}，失败 {failed}",
                    level="info" if status is TargetStatus.DONE else "warning",
                    target_id=target.id,
                    platform=platform.value,
                    saved=saved,
                    skipped=skipped,
                    failed=failed,
                )
                return TargetRunResult(
                    target.id,
                    platform,
                    target.product_id,
                    status,
                    saved=saved,
                    skipped=skipped,
                    failed=failed,
                    error=error,
                    output_dir=str(output_dir),
                )
            except RiskDetected as exc:
                self.emit(
                    EventType.RISK_DETECTED,
                    f"[{platform.label}] 触发风控：{exc.reason}",
                    level="warning",
                    target_id=target.id,
                    platform=platform.value,
                )
                await self._pause_platform(platform)
                resolved = False
                try:
                    resolved = await adapter.resolve_risk(target.url)
                finally:
                    await self._resume_platform(platform)
                if resolved and depth < 1:
                    return await self._run_target(target, depth + 1)
                return self._fail_target(target, "风控验证未通过")
            except LoginRequired:
                self.emit(
                    EventType.LOGIN_REQUIRED,
                    f"[{platform.label}] 登录态失效，等待重新登录",
                    level="warning",
                    platform=platform.value,
                )
                ok = await adapter.ensure_login()
                await self.refresh_cookies()
                if ok and depth < 1:
                    return await self._run_target(target, depth + 1)
                return self._fail_target(target, "登录未完成")
            except Exception as exc:  # noqa: BLE001
                logger.exception("任务失败 target={}", target.id)
                return self._fail_target(target, str(exc))

    def _fail_target(self, target: ProductTarget, error: str) -> TargetRunResult:
        self.db.set_target_status(target.id, TargetStatus.FAILED, error)
        self.emit(
            EventType.TASK_FINISHED,
            f"[{target.platform.label}] {target.product_name} 失败：{error}",
            level="error",
            target_id=target.id,
            platform=target.platform.value,
            error=error,
        )
        return TargetRunResult(
            target.id,
            target.platform,
            target.product_id,
            TargetStatus.FAILED,
            error=error,
        )

    async def _download_images(
        self, target: ProductTarget, images: Sequence, output_dir: Path
    ) -> tuple:
        assert self.fetcher is not None
        platform = target.platform
        saved = skipped = failed = 0
        hashes = self.db.target_asset_hashes(target.id)
        counters: Dict[ImageKind, int] = {kind: 0 for kind in ImageKind}
        total = len(images)
        for index, ref in enumerate(images, start=1):
            if self._stop:
                break
            self.emit(
                EventType.TASK_PROGRESS,
                f"[{platform.label}] {target.product_name} {index}/{total}",
                target_id=target.id,
                platform=platform.value,
                done=index,
                total=total,
            )
            if self.db.has_asset_url(target.id, ref.url):
                skipped += 1
                counters[ref.kind] += 1
                continue
            if self.db.has_original_url(target.id, original_url(ref.url, platform)):
                skipped += 1
                counters[ref.kind] += 1
                continue
            try:
                fetched = await self.fetcher.fetch(platform, ref.url, referer=target.url)
            except DownloadError as exc:
                failed += 1
                self.db.add_asset(
                    ImageAsset(
                        target_id=target.id,
                        kind=ref.kind,
                        source_url=ref.url,
                        status="failed",
                        error=exc.reason,
                    )
                )
                continue
            except Exception as exc:  # noqa: BLE001
                failed += 1
                self.db.add_asset(
                    ImageAsset(
                        target_id=target.id,
                        kind=ref.kind,
                        source_url=ref.url,
                        status="failed",
                        error=str(exc),
                    )
                )
                continue
            if fetched.sha256 in hashes:
                skipped += 1
                counters[ref.kind] += 1
                self.db.add_asset(
                    ImageAsset(
                        target_id=target.id,
                        kind=ref.kind,
                        source_url=ref.url,
                        original_url=fetched.source_url,
                        sha256=fetched.sha256,
                        size=len(fetched.data),
                        width=fetched.width,
                        height=fetched.height,
                        status="duplicate",
                    )
                )
                continue
            counters[ref.kind] += 1
            filename = image_filename(
                platform,
                ref.kind,
                counters[ref.kind],
                fetched.ext,
                fetched.width,
                fetched.height,
            )
            path = unique_path(output_dir / ref.kind.folder / filename)
            save_image(fetched.data, path)
            hashes.add(fetched.sha256)
            saved += 1
            self.db.add_asset(
                ImageAsset(
                    target_id=target.id,
                    kind=ref.kind,
                    source_url=ref.url,
                    original_url=fetched.source_url,
                    path=str(path),
                    sha256=fetched.sha256,
                    size=len(fetched.data),
                    width=fetched.width,
                    height=fetched.height,
                    status="ok",
                )
            )
            self.emit(
                EventType.IMAGE_SAVED,
                f"保存 {path.name} ({fetched.width}x{fetched.height})",
                target_id=target.id,
                platform=platform.value,
                path=str(path),
                saved=saved,
            )
        return saved, skipped, failed

    # ----------------------------------------------------------------- 产物
    def _write_manifests(self, results: Sequence[TargetRunResult]) -> None:
        product_ids = sorted({r.product_id for r in results})
        for product_id in product_ids:
            product = self.db.get_product(product_id)
            if product is None:
                continue
            targets = self.db.list_targets_for_product(product_id)
            images_payload: List[Dict] = []
            output_dir = ""
            for target in targets:
                assets = self.db.list_assets(target.id)
                for asset in assets:
                    payload = asset_row(product.name, asset)
                    payload["平台"] = target.platform.label
                    images_payload.append(payload)
                    if asset.path and not output_dir:
                        output_dir = str(Path(asset.path).parent.parent)
            if not output_dir:
                continue
            payload = {
                "商品": {
                    "序号": product.seq,
                    "名称": product.name,
                    "规格": product.spec,
                    "备注": product.remark,
                },
                "任务": [
                    {
                        "平台": t.platform.label,
                        "店铺": t.store,
                        "链接": t.url,
                        "状态": t.status.label,
                        "错误": t.error,
                    }
                    for t in targets
                ],
                "图片": images_payload,
            }
            write_manifest(Path(output_dir) / manifest_filename(), payload)

    def _write_report(self, results: Sequence[TargetRunResult]) -> None:
        if not results:
            return
        targets = {t.id: t for t in self.db.list_targets()}
        summary_rows = []
        asset_rows = []
        for result in results:
            target = targets.get(result.target_id)
            if target is None:
                continue
            summary_rows.append(
                summary_row(
                    target,
                    result.saved,
                    result.output_dir,
                    result.status.label,
                    result.error,
                )
            )
            for asset in self.db.list_assets(result.target_id):
                asset_rows.append(asset_row(target.product_name, asset))
        output_dir = Path(self.settings.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        import time as _time

        stamp = _time.strftime("%Y%m%d_%H%M%S")
        path = write_summary_report(
            output_dir / f"下载报告_{stamp}.xlsx", summary_rows, asset_rows
        )
        self.emit(EventType.LOG, f"报告已生成：{path}")
