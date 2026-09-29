from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from app.core.models import Platform, Product
from app.services.urls import detect_platform, extract_urls

try:  # pragma: no cover - exercised only when openpyxl is installed
    from openpyxl import Workbook, load_workbook

    HAVE_OPENPYXL = True
except ImportError:  # pragma: no cover
    HAVE_OPENPYXL = False

CANONICAL_FIELDS = ("name", "spec", "remark", "store_hint", "jd", "tb", "pdd")

HEADER_ALIASES: Dict[str, Tuple[str, ...]] = {
    "name": ("商品名称", "商品名", "名称", "标题", "商品标题", "产品名称", "product", "name", "title"),
    "spec": ("规格", "型号", "规格型号", "规格/型号", "属性", "sku", "spec"),
    "remark": ("备注", "说明", "note", "remark", "comments"),
    "store_hint": ("店铺名", "店铺", "店铺名称", "期望店铺", "店铺关键字", "shop", "store"),
    "jd": ("京东链接", "京东url", "京东地址", "京东", "jd", "jd链接", "jd url"),
    "tb": ("淘宝链接", "淘宝url", "淘宝地址", "淘宝", "天猫链接", "天猫", "tb", "taobao", "tmall"),
    "pdd": ("拼多多链接", "拼多多url", "拼多多地址", "拼多多", "pdd", "pinduoduo"),
}

PREFIX = {"jd": Platform.JD, "tb": Platform.TAOBAO, "pdd": Platform.PDD}


@dataclass
class ImportedProduct:
    product: Product
    links: Dict[Platform, str] = field(default_factory=dict)


def normalize_header(value: object) -> str:
    text = "" if value is None else str(value)
    text = re.sub(r"[\s_\-（）()\[\]【】:：]+", "", text).lower()
    return text


def build_header_map(header_cells: Sequence[object]) -> Dict[str, int]:
    mapping: Dict[str, int] = {}
    normalized = [normalize_header(c) for c in header_cells]
    for field_name, aliases in HEADER_ALIASES.items():
        alias_set = {normalize_header(a) for a in aliases}
        for index, cell in enumerate(normalized):
            if cell and cell in alias_set:
                mapping[field_name] = index
                break
    return mapping


def _clean(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _row_to_imported(cells: Sequence[object], header: Dict[str, int], seq: int) -> Optional[ImportedProduct]:
    def cell(field_name: str) -> str:
        index = header.get(field_name)
        if index is None or index >= len(cells):
            return ""
        return _clean(cells[index])

    name = cell("name")
    links = {
        Platform.JD: cell("jd"),
        Platform.TAOBAO: cell("tb"),
        Platform.PDD: cell("pdd"),
    }
    links = {p: u for p, u in links.items() if u}
    if not name and not links:
        return None
    if not name:
        name = f"商品{seq:03d}"
    product = Product(
        seq=seq,
        name=name,
        spec=cell("spec"),
        remark=cell("remark"),
        store_hint=cell("store_hint"),
    )
    return ImportedProduct(product=product, links=links)


def load_rows(path: str | Path) -> List[ImportedProduct]:
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix in (".xlsx", ".xlsm", ".xltx"):
        return _load_rows_excel(path)
    if suffix in (".csv", ".txt"):
        return _load_rows_csv(path)
    raise ValueError(f"不支持的文件类型: {suffix}，请使用 xlsx/csv")


def _load_rows_excel(path: Path) -> List[ImportedProduct]:
    if not HAVE_OPENPYXL:
        raise RuntimeError("缺少 openpyxl，请先安装依赖: pip install openpyxl")
    workbook = load_workbook(filename=str(path), read_only=True, data_only=True)
    try:
        sheet = workbook.active
        rows = list(sheet.iter_rows(values_only=True))
    finally:
        workbook.close()
    if not rows:
        return []
    header = build_header_map(rows[0])
    if "name" not in header and not any(k in header for k in ("jd", "tb", "pdd")):
        header = {"name": 0}
        body = rows
    else:
        body = rows[1:]
    result: List[ImportedProduct] = []
    for index, row in enumerate(body, start=1):
        imported = _row_to_imported(row, header, len(result) + 1)
        if imported:
            result.append(imported)
    return result


def _load_rows_csv(path: Path) -> List[ImportedProduct]:
    rows: Optional[List[List[str]]] = None
    for encoding in ("utf-8-sig", "gbk", "utf-8"):
        try:
            with path.open("r", encoding=encoding, newline="") as handle:
                sample = handle.read(4096)
                handle.seek(0)
                try:
                    dialect = csv.Sniffer().sniff(sample, delimiters=",\t;")
                except csv.Error:
                    dialect = csv.excel
                reader = csv.reader(handle, dialect)
                rows = [row for row in reader]
            break
        except UnicodeDecodeError:
            continue
    if rows is None:
        raise ValueError(f"无法解析 CSV 文件: {path}")
    if not rows:
        return []
    header = build_header_map(rows[0])
    body = rows[1:] if header else rows
    if not header:
        header = {"name": 0}
    result: List[ImportedProduct] = []
    for row in body:
        imported = _row_to_imported(row, header, len(result) + 1)
        if imported:
            result.append(imported)
    return result


def parse_paste_text(text: str) -> List[ImportedProduct]:
    """支持每行: 名称 + 逗号/空白分隔的链接，或纯链接。"""
    result: List[ImportedProduct] = []
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        urls = extract_urls(line)
        links: Dict[Platform, str] = {}
        for url in urls:
            platform = detect_platform(url)
            if platform and platform not in links:
                links[platform] = url
        remainder = line
        for url in urls:
            remainder = remainder.replace(url, " ")
        remainder = re.sub(r"[,;，；\t]+", " ", remainder).strip()
        seq = len(result) + 1
        name = remainder or f"商品{seq:03d}"
        result.append(
            ImportedProduct(
                product=Product(seq=seq, name=name),
                links=links,
            )
        )
    return result


def parse_keyword_text(text: str) -> List[ImportedProduct]:
    result: List[ImportedProduct] = []
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = re.split(r"[,;\t，；]+", line, maxsplit=1)
        name = parts[0].strip()
        spec = parts[1].strip() if len(parts) > 1 else ""
        if not name:
            continue
        seq = len(result) + 1
        result.append(ImportedProduct(product=Product(seq=seq, name=name, spec=spec)))
    return result


def write_template(path: str | Path) -> None:
    if not HAVE_OPENPYXL:
        raise RuntimeError("缺少 openpyxl，请先安装依赖: pip install openpyxl")
    path = Path(path)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "商品清单"
    sheet.append(["商品名称", "规格/型号", "京东链接", "淘宝链接", "拼多多链接", "店铺名", "备注"])
    sheet.append(
        [
            "示例：Apple iPhone 16 256G",
            "256G 黑色",
            "https://item.jd.com/100000000001.html",
            "",
            "",
            "Apple产品京东自营旗舰店",
            "留空的链接会自动搜索匹配",
        ]
    )
    widths = [36, 18, 42, 42, 42, 28, 24]
    for index, width in enumerate(widths, start=1):
        sheet.column_dimensions[sheet.cell(row=1, column=index).column_letter].width = width
    workbook.save(str(path))
