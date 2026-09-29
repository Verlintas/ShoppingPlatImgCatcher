from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class Platform(str, Enum):
    JD = "jd"
    TAOBAO = "tb"
    PDD = "pdd"

    @property
    def label(self) -> str:
        return PLATFORM_LABELS[self]


PLATFORM_LABELS: Dict[Platform, str] = {
    Platform.JD: "京东",
    Platform.TAOBAO: "淘宝/天猫",
    Platform.PDD: "拼多多",
}

PLATFORM_FOLDER: Dict[Platform, str] = {
    Platform.JD: "JD",
    Platform.TAOBAO: "TB",
    Platform.PDD: "PDD",
}

ALL_PLATFORMS: tuple = (Platform.JD, Platform.TAOBAO, Platform.PDD)


class ImageKind(str, Enum):
    MAIN = "main"
    DETAIL = "detail"
    SKU = "sku"

    @property
    def label(self) -> str:
        return IMAGE_KIND_LABELS[self]

    @property
    def folder(self) -> str:
        return IMAGE_KIND_FOLDERS[self]


IMAGE_KIND_LABELS: Dict[ImageKind, str] = {
    ImageKind.MAIN: "主图",
    ImageKind.DETAIL: "详情图",
    ImageKind.SKU: "SKU图",
}

IMAGE_KIND_FOLDERS: Dict[ImageKind, str] = {
    ImageKind.MAIN: "主图",
    ImageKind.DETAIL: "详情图",
    ImageKind.SKU: "SKU图",
}


class TargetSource(str, Enum):
    EXCEL = "excel"
    AUTO = "auto"
    MANUAL = "manual"


class TargetStatus(str, Enum):
    PENDING = "pending"
    MATCHED = "matched"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"

    @property
    def label(self) -> str:
        return {
            TargetStatus.PENDING: "待匹配",
            TargetStatus.MATCHED: "已匹配",
            TargetStatus.RUNNING: "下载中",
            TargetStatus.DONE: "已完成",
            TargetStatus.FAILED: "失败",
            TargetStatus.SKIPPED: "已跳过",
        }[self]


class MatchStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class Product:
    id: Optional[int] = None
    seq: int = 0
    name: str = ""
    spec: str = ""
    remark: str = ""
    store_hint: str = ""

    @property
    def query(self) -> str:
        return " ".join(x for x in (self.name.strip(), self.spec.strip()) if x)


@dataclass
class MatchCandidate:
    platform: Platform
    title: str
    url: str
    store: str = ""
    is_flagship: bool = False
    sales: int = 0
    score: float = 0.0
    goods_id: str = ""

    @property
    def store_label(self) -> str:
        return self.store or "(未知店铺)"


@dataclass
class ProductTarget:
    id: Optional[int] = None
    product_id: int = 0
    platform: Platform = Platform.JD
    url: str = ""
    store: str = ""
    title: str = ""
    source: TargetSource = TargetSource.AUTO
    status: TargetStatus = TargetStatus.PENDING
    error: str = ""
    product_name: str = ""
    product_seq: int = 0


@dataclass
class ProductPage:
    platform: Platform
    url: str
    title: str = ""
    store: str = ""
    goods_id: str = ""
    images: List["ImageRef"] = field(default_factory=list)


@dataclass
class ImageRef:
    url: str
    kind: ImageKind = ImageKind.MAIN
    width: int = 0
    height: int = 0


@dataclass
class ImageAsset:
    id: Optional[int] = None
    target_id: int = 0
    kind: ImageKind = ImageKind.MAIN
    source_url: str = ""
    original_url: str = ""
    path: str = ""
    sha256: str = ""
    size: int = 0
    width: int = 0
    height: int = 0
    status: str = "pending"
    error: str = ""


@dataclass
class TargetRunResult:
    target_id: int
    platform: Platform
    product_id: int
    status: TargetStatus
    saved: int = 0
    skipped: int = 0
    failed: int = 0
    error: str = ""
    output_dir: str = ""
