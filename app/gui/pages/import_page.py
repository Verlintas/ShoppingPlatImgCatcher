from __future__ import annotations

from pathlib import Path
from typing import List

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.core.db import Database
from app.core.models import Platform, TargetSource
from app.services import excel_io
from app.services.excel_io import ImportedProduct


class ImportPage(QWidget):
    imported = Signal(int)

    def __init__(self, db: Database, parent=None) -> None:
        super().__init__(parent)
        self.db = db
        self._rows: List[ImportedProduct] = []
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_file_tab(), "Excel / CSV 导入")
        self.tabs.addTab(self._build_text_tab(), "粘贴链接 / 关键词")
        layout.addWidget(self.tabs)

        preview_box = QVBoxLayout()
        preview_box.addWidget(QLabel("导入预览（本页仅在点击“导入”后写入项目）"))
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["序号", "商品名称", "规格", "京东", "淘宝", "拼多多", "备注"]
        )
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        preview_box.addWidget(self.table)

        bottom = QHBoxLayout()
        self.status = QLabel("尚未选择数据")
        self.import_btn = QPushButton("导入到项目")
        self.import_btn.setEnabled(False)
        self.import_btn.clicked.connect(self._on_import)
        bottom.addWidget(self.status, 1)
        bottom.addWidget(self.import_btn)
        preview_box.addLayout(bottom)
        layout.addLayout(preview_box, 1)

    def _build_file_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        row = QHBoxLayout()
        pick = QPushButton("选择 Excel / CSV 文件")
        pick.clicked.connect(self._pick_file)
        template = QPushButton("导出导入模板")
        template.clicked.connect(self._export_template)
        row.addWidget(pick)
        row.addWidget(template)
        row.addStretch(1)
        layout.addLayout(row)
        self.replace_check = QCheckBox("导入前清空已有商品数据（覆盖模式）")
        layout.addWidget(self.replace_check)
        hint = QLabel(
            "表头支持：商品名称、规格/型号、京东链接、淘宝链接、拼多多链接、店铺名、备注。<br>"
            "链接留空的行会在“自动匹配”阶段按商品名称搜索对应平台。"
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch(1)
        return widget

    def _build_text_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        hint = QLabel(
            "每行一条：可写“商品名称 链接”或只写商品名称（走关键词搜索）。<br>"
            "示例：<br>Apple iPhone 16 256G https://item.jd.com/100000000001.html<br>"
            "戴森吹风机 HD08"
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.text_edit = QPlainTextEdit()
        self.text_edit.setPlaceholderText("在此粘贴内容，每行一条...")
        layout.addWidget(self.text_edit)
        row = QHBoxLayout()
        parse = QPushButton("解析并预览")
        parse.clicked.connect(self._parse_text)
        row.addStretch(1)
        row.addWidget(parse)
        layout.addLayout(row)
        return widget

    # ------------------------------------------------------------------ file
    def _pick_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "选择商品表", "", "表格文件 (*.xlsx *.xlsm *.csv *.txt)"
        )
        if not path:
            return
        try:
            rows = excel_io.load_rows(path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "读取失败", str(exc))
            return
        if not rows:
            QMessageBox.warning(self, "没有数据", "未在文件中发现有效商品行")
            return
        self._set_rows(rows, f"文件导入：{Path(path).name}")

    def _export_template(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "保存模板", "商品导入模板.xlsx", "Excel (*.xlsx)"
        )
        if not path:
            return
        try:
            excel_io.write_template(path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "保存失败", str(exc))
            return
        QMessageBox.information(self, "完成", f"模板已保存：{path}")

    # ------------------------------------------------------------------ text
    def _parse_text(self) -> None:
        text = self.text_edit.toPlainText()
        if not text.strip():
            QMessageBox.warning(self, "内容为空", "请先粘贴商品名称或链接")
            return
        has_url = "http" in text
        rows = (
            excel_io.parse_paste_text(text)
            if has_url
            else excel_io.parse_keyword_text(text)
        )
        if not rows:
            QMessageBox.warning(self, "没有数据", "未解析到有效内容")
            return
        self._set_rows(rows, f"粘贴导入（{'链接模式' if has_url else '关键词模式'}）")

    # --------------------------------------------------------------- preview
    def _set_rows(self, rows: List[ImportedProduct], source: str) -> None:
        self._rows = rows
        self.table.setRowCount(len(rows))
        for index, row in enumerate(rows):
            links = row.links
            values = [
                f"{row.product.seq:03d}",
                row.product.name,
                row.product.spec,
                links.get(Platform.JD, ""),
                links.get(Platform.TAOBAO, ""),
                links.get(Platform.PDD, ""),
                row.product.remark,
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setToolTip(str(value))
                self.table.setItem(index, column, item)
        self.status.setText(f"{source}，共 {len(rows)} 条")
        self.import_btn.setEnabled(bool(rows))

    def _on_import(self) -> None:
        if not self._rows:
            return
        replace = self.replace_check.isChecked()
        products = [row.product for row in self._rows]
        self.db.add_products(products, replace=replace)
        saved_products = self.db.list_products()
        by_seq = {p.seq: p for p in saved_products}
        for row in self._rows:
            product = by_seq.get(row.product.seq)
            if product is None or product.id is None:
                continue
            for platform, url in row.links.items():
                if url:
                    self.db.upsert_target(
                        product.id,
                        platform,
                        url,
                        source=TargetSource.EXCEL,
                    )
        QMessageBox.information(
            self,
            "导入完成",
            f"已导入 {len(self._rows)} 个商品，链接会自动进入匹配/下载队列",
        )
        self.imported.emit(len(self._rows))
