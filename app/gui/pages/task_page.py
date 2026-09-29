from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.core.config import Settings
from app.core.db import Database
from app.core.models import TargetStatus


class TaskPage(QWidget):
    log = Signal(str)

    def __init__(self, db: Database, settings: Settings, worker, parent=None) -> None:
        super().__init__(parent)
        self.db = db
        self.settings = settings
        self.worker = worker
        self._total = 0
        self._finished: set = set()
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        self.start_btn = QPushButton("开始下载")
        self.start_btn.clicked.connect(self._start)
        self.stop_btn = QPushButton("停止")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._stop)
        self.redone_check = QCheckBox("重新下载已完成任务")
        self.open_btn = QPushButton("打开输出目录")
        self.open_btn.clicked.connect(self._open_output)
        self.refresh_btn = QPushButton("刷新")
        self.refresh_btn.clicked.connect(self.refresh)
        row.addWidget(self.start_btn)
        row.addWidget(self.stop_btn)
        row.addWidget(self.redone_check)
        row.addWidget(self.open_btn)
        row.addWidget(self.refresh_btn)
        row.addStretch(1)
        layout.addLayout(row)

        progress_row = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.setFormat("%v / %m")
        self.stats_label = QLabel("就绪")
        progress_row.addWidget(self.progress, 1)
        progress_row.addWidget(self.stats_label)
        layout.addLayout(progress_row)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["商品", "平台", "店铺", "状态", "错误"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(self.table, 1)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(2000)
        self.log_view.setMinimumHeight(160)
        layout.addWidget(self.log_view, 1)

    # --------------------------------------------------------------- actions
    def _start(self) -> None:
        self._total = 0
        self._finished.clear()
        self.progress.setValue(0)
        self.progress.setMaximum(1)
        self.stats_label.setText("启动中...")
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.worker.start_download(include_done=self.redone_check.isChecked())

    def _stop(self) -> None:
        self.worker.stop_tasks()
        self.stats_label.setText("正在停止，等待当前图片下载结束...")

    def _open_output(self) -> None:
        import os
        import subprocess
        import sys

        path = self.settings.output_dir
        os.makedirs(path, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])

    def refresh(self) -> None:
        targets = self.db.list_targets()
        self.table.setRowCount(len(targets))
        for row, target in enumerate(targets):
            values = [
                target.product_name,
                target.platform.label,
                target.store,
                target.status.label,
                target.error,
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setToolTip(str(value))
                self.table.setItem(row, column, item)
        stats = self.db.stats()
        self.stats_label.setText(
            f"任务 {stats['done']}/{stats['targets']} · 图片 {stats['assets']}"
        )

    # ---------------------------------------------------------------- events
    def on_event(self, event) -> None:
        payload = event.payload or {}
        if event.type == "task_queued":
            self._total = int(payload.get("total") or 0)
            self.progress.setMaximum(max(1, self._total))
            self.progress.setValue(0)
            self._finished.clear()
        if event.type in ("task_finished", "task_started", "risk_detected", "risk_resolved",
                          "login_required", "login_done", "run_done", "image_saved", "log",
                          "supervision"):
            if event.message:
                self.log.emit(event.message)
        if event.type == "task_finished":
            target_id = payload.get("target_id")
            if target_id not in self._finished:
                self._finished.add(target_id)
                self.progress.setValue(min(self._total, len(self._finished)))
        if event.type == "run_done":
            self.start_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)
            self.stats_label.setText(event.message)
            self.refresh()
            QMessageBox.information(self, "下载结束", event.message)

    def on_task_done(self, action: str, payload) -> None:
        if action == "download":
            self.start_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)
            self.refresh()
