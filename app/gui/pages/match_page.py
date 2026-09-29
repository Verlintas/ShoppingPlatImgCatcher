from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.core.db import Database
from app.core.models import MatchCandidate, Platform, ProductTarget, TargetSource, TargetStatus


class CandidateDialog(QDialog):
    def __init__(self, candidates: List[MatchCandidate], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("选择匹配商品")
        self.resize(980, 520)
        self._candidates = candidates
        layout = QVBoxLayout(self)
        self.table = QTableWidget(len(candidates), 5)
        self.table.setHorizontalHeaderLabels(["店铺", "标题", "是否旗舰", "得分", "链接"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        for row, candidate in enumerate(candidates):
            values = [
                candidate.store_label,
                candidate.title,
                "是" if candidate.is_flagship else "",
                f"{candidate.score:.1f}",
                candidate.url,
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setToolTip(str(value))
                self.table.setItem(row, column, item)
        if candidates:
            self.table.selectRow(0)
        layout.addWidget(self.table)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("使用选中项")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.table.doubleClicked.connect(self.accept)

    def selected(self) -> Optional[MatchCandidate]:
        row = self.table.currentRow()
        if 0 <= row < len(self._candidates):
            return self._candidates[row]
        return None


class MatchPage(QWidget):
    log = Signal(str)

    def __init__(self, db: Database, worker, parent=None) -> None:
        super().__init__(parent)
        self.db = db
        self.worker = worker
        self._pending_search: Optional[ProductTarget] = None
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        self.refresh_btn = QPushButton("刷新")
        self.refresh_btn.clicked.connect(self.refresh)
        self.match_selected_btn = QPushButton("自动匹配选中")
        self.match_selected_btn.clicked.connect(lambda: self._auto_match(True))
        self.match_all_btn = QPushButton("自动匹配全部（含未选中）")
        self.match_all_btn.clicked.connect(lambda: self._auto_match(False))
        self.search_btn = QPushButton("手动搜索…")
        self.search_btn.clicked.connect(self._manual_search)
        self.pick_btn = QPushButton("拼多多人工选品")
        self.pick_btn.clicked.connect(self._manual_pick)
        row.addWidget(self.refresh_btn)
        row.addWidget(self.match_selected_btn)
        row.addWidget(self.match_all_btn)
        row.addWidget(self.search_btn)
        row.addWidget(self.pick_btn)
        row.addStretch(1)
        layout.addLayout(row)

        row2 = QHBoxLayout()
        self.link_btn = QPushButton("填写/修改链接")
        self.link_btn.clicked.connect(self._edit_link)
        self.skip_btn = QPushButton("忽略所选平台")
        self.skip_btn.clicked.connect(lambda: self._set_status(TargetStatus.SKIPPED))
        self.restore_btn = QPushButton("恢复为待匹配")
        self.restore_btn.clicked.connect(self._restore)
        hint = QLabel("提示：双击行可编辑链接")
        row2.addWidget(self.link_btn)
        row2.addWidget(self.skip_btn)
        row2.addWidget(self.restore_btn)
        row2.addStretch(1)
        row2.addWidget(hint)
        layout.addLayout(row2)

        self.table = QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels(
            ["选择", "序号", "商品名称", "平台", "来源", "店铺", "链接", "状态", "错误"]
        )
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.doubleClicked.connect(self._edit_link)
        layout.addWidget(self.table, 1)

        self.status_label = QLabel("")
        layout.addWidget(self.status_label)

    # ---------------------------------------------------------------- render
    def refresh(self) -> None:
        targets = self.db.list_targets()
        self.table.setRowCount(len(targets))
        for row, target in enumerate(targets):
            check = QTableWidgetItem()
            check.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            check.setCheckState(Qt.Checked)
            check.setData(Qt.UserRole, target.id)
            self.table.setItem(row, 0, check)
            values = [
                f"{target.product_seq:03d}",
                target.product_name,
                target.platform.label,
                {
                    TargetSource.EXCEL: "表内链接",
                    TargetSource.AUTO: "自动匹配",
                    TargetSource.MANUAL: "手动",
                }.get(target.source, target.source.value),
                target.store,
                target.url,
                target.status.label,
                target.error,
            ]
            for offset, value in enumerate(values, start=1):
                item = QTableWidgetItem(str(value))
                item.setToolTip(str(value))
                self.table.setItem(row, offset, item)
        stats = self.db.stats()
        self.status_label.setText(
            f"商品 {stats['products']} · 已匹配 {stats['targets']} · 已完成 {stats['done']} · 已保存图片 {stats['assets']}"
        )

    def _checked_targets(self) -> List[ProductTarget]:
        targets = {t.id: t for t in self.db.list_targets()}
        result: List[ProductTarget] = []
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is not None and item.checkState() == Qt.Checked:
                target = targets.get(item.data(Qt.UserRole))
                if target is not None:
                    result.append(target)
        return result

    def _current_target(self) -> Optional[ProductTarget]:
        rows = self._checked_targets()
        if not rows:
            QMessageBox.information(self, "未选择", "请先勾选要操作的行")
            return None
        return rows[0]

    # --------------------------------------------------------------- actions
    def _auto_match(self, selected_only: bool) -> None:
        product_ids = None
        if selected_only:
            targets = self._checked_targets()
            if not targets:
                QMessageBox.information(self, "未选择", "请先勾选要匹配的行")
                return
            product_ids = {t.product_id for t in targets}
        self.log.emit("开始自动匹配，请关注日志输出...")
        self.worker.start_match(product_ids=product_ids)

    def _manual_search(self) -> None:
        target = self._current_target()
        if target is None:
            return
        self._pending_search = target
        self.worker.start_search(target.product_id, target.platform)

    def _manual_pick(self) -> None:
        target = self._current_target()
        if target is None:
            return
        if target.platform is not Platform.PDD:
            QMessageBox.information(self, "提示", "人工选品目前仅用于拼多多")
            return
        self.worker.start_manual_pick(target.product_id, target.platform)

    def _edit_link(self) -> None:
        target = self._current_target()
        if target is None:
            return
        text, ok = QInputDialog.getText(
            self, "填写链接", f"{target.product_name} · {target.platform.label} 链接：",
            text=target.url,
        )
        if not ok:
            return
        text = text.strip()
        self.db.upsert_target(
            target.product_id,
            target.platform,
            text,
            source=TargetSource.MANUAL if text else target.source,
        )
        self.refresh()

    def _set_status(self, status: TargetStatus) -> None:
        targets = self._checked_targets()
        if not targets:
            QMessageBox.information(self, "未选择", "请先勾选要操作的行")
            return
        for target in targets:
            self.db.set_target_status(target.id, status)
        self.refresh()

    def _restore(self) -> None:
        targets = self._checked_targets()
        if not targets:
            return
        for target in targets:
            status = TargetStatus.MATCHED if target.url else TargetStatus.PENDING
            self.db.set_target_status(target.id, status)
        self.refresh()

    # ---------------------------------------------------------------- events
    def on_event(self, event) -> None:
        if event.type in ("match_progress", "match_done"):
            self.refresh()
            self.log.emit(event.message)

    def on_task_done(self, action: str, payload) -> None:
        if action == "search":
            self._show_candidates(payload)
        elif action == "manual_pick":
            url = payload.get("url") if isinstance(payload, dict) else ""
            self.refresh()
            if url:
                self.log.emit(f"人工选品成功：{url}")
            else:
                self.log.emit("人工选品未完成或超时")
        elif action == "match":
            self.refresh()

    def _show_candidates(self, payload) -> None:
        candidates = payload.get("candidates") or []
        product_id = payload.get("product_id")
        platform = Platform(payload.get("platform"))
        if not candidates:
            QMessageBox.warning(self, "没有结果", "未搜索到候选商品，请检查登录态或稍后重试")
            return
        dialog = CandidateDialog(candidates, self)
        if dialog.exec() != QDialog.Accepted:
            return
        candidate = dialog.selected()
        if candidate is None:
            return
        self.db.upsert_target(
            product_id,
            platform,
            candidate.url,
            candidate.store,
            candidate.title,
            TargetSource.MANUAL,
            TargetStatus.MATCHED,
        )
        self.refresh()
        self.log.emit(f"已采用手动选择的商品：{candidate.store_label}")
