from __future__ import annotations

import asyncio
from typing import Any, Callable, Optional

from PySide6.QtCore import QThread, Signal

from app.core.config import Settings
from app.core.db import Database
from app.core.events import EventBus


class EngineWorker(QThread):
    """在独立线程内运行 asyncio 引擎，通过信号与 GUI 通信。"""

    event = Signal(object)
    task_done = Signal(str, object)
    command_failed = Signal(str, str)
    ready = Signal()

    def __init__(self, db: Database, settings: Settings, parent=None) -> None:
        super().__init__(parent)
        self.db = db
        self.settings = settings
        self.bus = EventBus()
        self._engine: Optional[Any] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    # ----------------------------------------------------------- thread entry
    def run(self) -> None:
        from app.engine import Engine

        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._engine = Engine(self.db, self.settings, self.bus)
        self._loop.create_task(self._pump())
        self.ready.emit()
        try:
            self._loop.run_forever()
        finally:
            try:
                self._loop.run_until_complete(self._engine.close())
            except Exception:  # noqa: BLE001
                pass
            self._loop.close()
            self._loop = None

    async def _pump(self) -> None:
        while True:
            for event in self.bus.drain():
                self.event.emit(event)
            await asyncio.sleep(0.1)

    # ------------------------------------------------------------ submit API
    def _submit(self, action: str, factory: Callable[[], Any]) -> None:
        if self._loop is None or self._engine is None:
            self.command_failed.emit(action, "引擎尚未就绪，请稍后重试")
            return
        try:
            coro = factory()
        except Exception as exc:  # noqa: BLE001
            self.command_failed.emit(action, str(exc))
            return
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)

        def _done(done) -> None:
            try:
                result = done.result()
            except Exception as exc:  # noqa: BLE001
                self.command_failed.emit(action, str(exc))
                return
            self.task_done.emit(action, result)

        future.add_done_callback(_done)

    def start_match(self, min_score: float = 55.0, product_ids=None) -> None:
        self._submit(
            "match",
            lambda: self._engine.match_all(min_score=min_score, product_ids=product_ids),
        )

    def start_download(self, include_done: bool = False, product_ids=None) -> None:
        self._submit(
            "download",
            lambda: self._engine.run_targets(
                include_done=include_done, product_ids=product_ids
            ),
        )

    def start_search(self, product_id: int, platform, limit: int = 10) -> None:
        self._submit("search", lambda: self._search_wrapper(product_id, platform, limit))

    async def _search_wrapper(self, product_id: int, platform, limit: int):
        candidates = await self._engine.search_candidates(product_id, platform, limit)
        return {
            "product_id": product_id,
            "platform": platform.value,
            "candidates": candidates,
        }

    def start_manual_pick(self, product_id: int, platform) -> None:
        self._submit(
            "manual_pick", lambda: self._manual_pick_wrapper(product_id, platform)
        )

    async def _manual_pick_wrapper(self, product_id: int, platform):
        url = await self._engine.manual_pick(product_id, platform)
        return {"product_id": product_id, "platform": platform.value, "url": url or ""}

    def start_login(self, platform) -> None:
        self._submit("login", lambda: self._engine.login(platform))

    def query_login_status(self) -> None:
        self._submit("login_status", lambda: self._engine.login_status())

    def stop_tasks(self) -> None:
        if self._engine is not None:
            self._engine.request_stop()

    def shutdown(self) -> None:
        if self._engine is not None:
            self._engine.request_stop()
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._loop.stop)
        self.wait(10000)
