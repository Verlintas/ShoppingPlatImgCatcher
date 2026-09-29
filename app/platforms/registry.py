from __future__ import annotations

from typing import Callable, Dict, Optional

from app.core.config import Settings
from app.core.models import Platform
from app.platforms.base import PlatformAdapter
from app.platforms.browser import BrowserManager
from app.platforms.jd import JDAdapter
from app.platforms.pdd import PDDAdapter
from app.platforms.taobao import TaobaoAdapter

ADAPTER_CLASSES = {
    Platform.JD: JDAdapter,
    Platform.TAOBAO: TaobaoAdapter,
    Platform.PDD: PDDAdapter,
}


def create_adapters(
    browser: BrowserManager,
    settings: Settings,
    on_event: Optional[Callable[..., None]] = None,
) -> Dict[Platform, PlatformAdapter]:
    return {
        platform: adapter_class(browser, settings, on_event)
        for platform, adapter_class in ADAPTER_CLASSES.items()
    }
