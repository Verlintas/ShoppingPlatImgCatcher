from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Dict, Iterable, List, Sequence

from app.core.models import ImageAsset, ProductTarget

try:  # pragma: no cover - depends on optional dependency
    from openpyxl import Workbook

    HAVE_OPENPYXL = True
except ImportError:  # pragma: no cover
    HAVE_OPENPYXL = False

SUMMARY_HEADERS: Sequence[str] = (
    "序号",
    "商品名称",
    "平台",
    "店铺",
    "商品链接",
    "状态",
    "图片数",
    "产物目录",
    "错误",
)

ASSET_HEADERS: Sequence[str] = (
    "商品名称",
    "平台",
    "图片类型",
    "文件名",
    "分辨率",
    "字节数",
    "原图地址",
    "状态",
    "错误",
)


def write_manifest(path: Path, payload: Dict) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def write_summary_report(
    path: Path,
    summary_rows: Sequence[Dict[str, object]],
    asset_rows: Sequence[Dict[str, object]] = (),
) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if HAVE_OPENPYXL:
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "任务汇总"
        sheet.append(list(SUMMARY_HEADERS))
        for row in summary_rows:
            sheet.append([row.get(header, "") for header in SUMMARY_HEADERS])
        widths = [8, 34, 12, 26, 46, 10, 8, 46, 40]
        for index, width in enumerate(widths, start=1):
            sheet.column_dimensions[sheet.cell(row=1, column=index).column_letter].width = width

        asset_sheet = workbook.create_sheet("图片明细")
        asset_sheet.append(list(ASSET_HEADERS))
        for row in asset_rows:
            asset_sheet.append([row.get(header, "") for header in ASSET_HEADERS])
        for index, width in enumerate([34, 12, 10, 34, 14, 12, 52, 10, 30], start=1):
            asset_sheet.column_dimensions[
                asset_sheet.cell(row=1, column=index).column_letter
            ].width = width
        workbook.save(str(path))
        return path

    with path.with_suffix(".csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(SUMMARY_HEADERS))
        writer.writeheader()
        for row in summary_rows:
            writer.writerow(row)
    return path.with_suffix(".csv")


def summary_row(
    target: ProductTarget,
    saved: int,
    output_dir: str,
    status_label: str,
    error: str = "",
) -> Dict[str, object]:
    return {
        "序号": target.product_seq,
        "商品名称": target.product_name,
        "平台": target.platform.label,
        "店铺": target.store,
        "商品链接": target.url,
        "状态": status_label,
        "图片数": saved,
        "产物目录": output_dir,
        "错误": error,
    }


def asset_row(product_name: str, asset: ImageAsset) -> Dict[str, object]:
    resolution = (
        f"{asset.width}x{asset.height}" if asset.width and asset.height else ""
    )
    return {
        "商品名称": product_name,
        "平台": "",
        "图片类型": asset.kind.label,
        "文件名": Path(asset.path).name if asset.path else "",
        "分辨率": resolution,
        "字节数": asset.size,
        "原图地址": asset.original_url or asset.source_url,
        "状态": asset.status,
        "错误": asset.error,
    }
