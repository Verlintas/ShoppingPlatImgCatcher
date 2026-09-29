from __future__ import annotations

import subprocess
import sys

from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.core.config import Settings, app_data_dir
from app.core.models import Platform


class SettingsPage(QWidget):
    def __init__(self, settings: Settings, worker, parent=None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.worker = worker
        self._build_ui()
        self._load()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        output_box = QGroupBox("输出")
        output_form = QFormLayout(output_box)
        row = QHBoxLayout()
        self.output_edit = QLineEdit()
        browse = QPushButton("浏览…")
        browse.clicked.connect(self._browse)
        row.addWidget(self.output_edit, 1)
        row.addWidget(browse)
        wrapper = QWidget()
        wrapper.setLayout(row)
        output_form.addRow("图片保存目录", wrapper)
        layout.addWidget(output_box)

        browser_box = QGroupBox("浏览器与登录")
        browser_form = QFormLayout(browser_box)
        self.headless_check = QCheckBox("后台运行浏览器（关闭后窗口常驻，便于观察）")
        self.pdd_visible_check = QCheckBox("拼多多始终显示浏览器窗口（监督模式推荐）")
        browser_form.addRow(self.headless_check)
        browser_form.addRow(self.pdd_visible_check)
        login_row = QHBoxLayout()
        for platform in Platform:
            button = QPushButton(f"{platform.label} 登录")
            button.clicked.connect(lambda _, p=platform: self._login(p))
            login_row.addWidget(button)
        self.login_status_label = QLabel("登录状态未知")
        self.login_status_label.setWordWrap(True)
        login_row.addWidget(self.login_status_label, 1)
        wrapper = QWidget()
        wrapper.setLayout(login_row)
        browser_form.addRow("账号", wrapper)
        layout.addWidget(browser_box)

        perf_box = QGroupBox("抓取与下载")
        perf_form = QFormLayout(perf_box)
        concurrency_row = QHBoxLayout()
        self.concurrency_spins = {}
        for platform in Platform:
            spin = QSpinBox()
            spin.setRange(1, 10)
            self.concurrency_spins[platform.value] = spin
            concurrency_row.addWidget(QLabel(platform.label))
            concurrency_row.addWidget(spin)
        wrapper = QWidget()
        wrapper.setLayout(concurrency_row)
        perf_form.addRow("平台并发数", wrapper)

        delay_row = QHBoxLayout()
        self.delay_min_spin = QDoubleSpinBox()
        self.delay_min_spin.setRange(0, 30)
        self.delay_min_spin.setSingleStep(0.1)
        self.delay_max_spin = QDoubleSpinBox()
        self.delay_max_spin.setRange(0, 30)
        self.delay_max_spin.setSingleStep(0.1)
        delay_row.addWidget(self.delay_min_spin)
        delay_row.addWidget(QLabel("~"))
        delay_row.addWidget(self.delay_max_spin)
        delay_row.addWidget(QLabel("秒 / 每次请求"))
        delay_row.addStretch(1)
        wrapper = QWidget()
        wrapper.setLayout(delay_row)
        perf_form.addRow("随机延迟", wrapper)

        self.retries_spin = QSpinBox()
        self.retries_spin.setRange(1, 10)
        perf_form.addRow("单图重试次数", self.retries_spin)
        self.min_bytes_spin = QSpinBox()
        self.min_bytes_spin.setRange(0, 100000)
        self.min_bytes_spin.setSingleStep(1024)
        perf_form.addRow("最小图片字节数", self.min_bytes_spin)
        self.proxy_edit = QLineEdit()
        self.proxy_edit.setPlaceholderText("如 http://127.0.0.1:7890，留空不使用")
        perf_form.addRow("代理", self.proxy_edit)
        self.mirror_edit = QLineEdit()
        self.mirror_edit.setPlaceholderText("Playwright 内核下载镜像")
        perf_form.addRow("浏览器下载镜像", self.mirror_edit)
        layout.addWidget(perf_box)

        platform_box = QGroupBox("启用的平台")
        platform_row = QHBoxLayout(platform_box)
        self.platform_checks = {}
        for platform in Platform:
            check = QCheckBox(platform.label)
            self.platform_checks[platform.value] = check
            platform_row.addWidget(check)
        platform_row.addStretch(1)
        layout.addWidget(platform_box)

        buttons = QHBoxLayout()
        save = QPushButton("保存设置")
        save.clicked.connect(self._save)
        refresh = QPushButton("刷新登录状态")
        refresh.clicked.connect(lambda: self.worker.query_login_status())
        open_data = QPushButton("打开数据目录")
        open_data.clicked.connect(self._open_data_dir)
        buttons.addWidget(save)
        buttons.addWidget(refresh)
        buttons.addWidget(open_data)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        layout.addStretch(1)

    # ------------------------------------------------------------------ load
    def _load(self) -> None:
        settings = self.settings
        self.output_edit.setText(settings.output_dir)
        self.headless_check.setChecked(settings.headless)
        self.pdd_visible_check.setChecked(settings.pdd_visible)
        for key, spin in self.concurrency_spins.items():
            spin.setValue(int(settings.concurrency.get(key, 2)))
        self.delay_min_spin.setValue(settings.delay_min)
        self.delay_max_spin.setValue(settings.delay_max)
        self.retries_spin.setValue(settings.retries)
        self.min_bytes_spin.setValue(settings.min_image_bytes)
        self.proxy_edit.setText(settings.proxy)
        self.mirror_edit.setText(settings.playwright_mirror)
        for key, check in self.platform_checks.items():
            check.setChecked(bool(settings.platform_enabled.get(key, True)))

    def _save(self) -> None:
        self.settings.output_dir = self.output_edit.text().strip() or self.settings.output_dir
        self.settings.headless = self.headless_check.isChecked()
        self.settings.pdd_visible = self.pdd_visible_check.isChecked()
        self.settings.concurrency = {
            key: spin.value() for key, spin in self.concurrency_spins.items()
        }
        delay_min = self.delay_min_spin.value()
        delay_max = max(delay_min, self.delay_max_spin.value())
        self.settings.delay_min = delay_min
        self.settings.delay_max = delay_max
        self.settings.retries = self.retries_spin.value()
        self.settings.min_image_bytes = self.min_bytes_spin.value()
        self.settings.proxy = self.proxy_edit.text().strip()
        self.settings.playwright_mirror = self.mirror_edit.text().strip()
        self.settings.platform_enabled = {
            key: check.isChecked() for key, check in self.platform_checks.items()
        }
        self.settings.save()
        QMessageBox.information(
            self, "已保存", "设置已保存。登录状态与并发调整会在下次任务生效。"
        )

    def _browse(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择保存目录", self.output_edit.text())
        if path:
            self.output_edit.setText(path)

    def _login(self, platform: Platform) -> None:
        QMessageBox.information(
            self,
            "登录说明",
            f"将打开浏览器窗口，请在其中完成 {platform.label} 登录。\n"
            "登录状态会被保存，之后无需重复登录（除非登录态失效）。",
        )
        self.worker.start_login(platform)

    def _open_data_dir(self) -> None:
        path = str(app_data_dir())
        if sys.platform == "win32":
            import os

            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])

    # ---------------------------------------------------------------- events
    def on_task_done(self, action: str, payload) -> None:
        if action == "login":
            ok = bool(payload)
            self.login_status_label.setText("登录成功" if ok else "登录未完成或超时")
            self.worker.query_login_status()
        elif action == "login_status" and isinstance(payload, dict):
            labels = []
            for key, value in payload.items():
                name = {"jd": "京东", "tb": "淘宝", "pdd": "拼多多"}.get(key, key)
                labels.append(f"{name}: {'已登录' if value else '未登录'}")
            self.login_status_label.setText(" · ".join(labels))

    def on_event(self, event) -> None:
        if event.type == "login_required":
            self.login_status_label.setText(event.message)
