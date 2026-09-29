from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QLabel, QMainWindow, QTabWidget

from app import APP_TITLE, __version__
from app.core.config import Settings
from app.core.db import Database
from app.gui.pages.import_page import ImportPage
from app.gui.pages.match_page import MatchPage
from app.gui.pages.settings_page import SettingsPage
from app.gui.pages.task_page import TaskPage
from app.gui.worker import EngineWorker


class MainWindow(QMainWindow):
    def __init__(self, db: Database, settings: Settings, worker: EngineWorker) -> None:
        super().__init__()
        self.db = db
        self.settings = settings
        self.worker = worker
        self.setWindowTitle(f"{APP_TITLE} v{__version__}")
        self.resize(1280, 860)
        self._build_ui()
        self._connect()

    def _build_ui(self) -> None:
        self.tabs = QTabWidget()
        self.import_page = ImportPage(self.db)
        self.match_page = MatchPage(self.db, self.worker)
        self.task_page = TaskPage(self.db, self.settings, self.worker)
        self.settings_page = SettingsPage(self.settings, self.worker)
        self.tabs.addTab(self.import_page, "1. 导入商品")
        self.tabs.addTab(self.match_page, "2. 匹配确认")
        self.tabs.addTab(self.task_page, "3. 下载任务")
        self.tabs.addTab(self.settings_page, "4. 设置与登录")
        self.setCentralWidget(self.tabs)

        self.status_label = QLabel("就绪")
        self.statusBar().addPermanentWidget(self.status_label)
        self.statusBar().showMessage(
            "提示：首次使用请到“设置与登录”完成各平台登录，再执行自动匹配。"
        )

    def _connect(self) -> None:
        self.worker.event.connect(self._on_event)
        self.worker.task_done.connect(self._on_task_done)
        self.worker.command_failed.connect(self._on_command_failed)
        self.import_page.imported.connect(lambda _count: self.match_page.refresh())
        self.match_page.log.connect(self._append_log)
        self.task_page.log.connect(self._append_log)

    def _on_event(self, event) -> None:
        if event.message:
            self.status_label.setText(event.message[:160])
        for page in (
            self.match_page,
            self.task_page,
            self.settings_page,
            self.import_page,
        ):
            handler = getattr(page, "on_event", None)
            if handler is not None:
                try:
                    handler(event)
                except Exception:  # noqa: BLE001
                    pass

    def _on_task_done(self, action: str, payload) -> None:
        for page in (self.match_page, self.task_page, self.settings_page):
            handler = getattr(page, "on_task_done", None)
            if handler is not None:
                try:
                    handler(action, payload)
                except Exception:  # noqa: BLE001
                    pass

    def _on_command_failed(self, action: str, message: str) -> None:
        self.status_label.setText(f"{action} 失败：{message}")
        self._append_log(f"[{action}] {message}")

    def _append_log(self, message: str) -> None:
        self.task_page.log_view.appendPlainText(message)

    def closeEvent(self, event: QCloseEvent) -> None:
        self.worker.shutdown()
        self.db.close()
        event.accept()
