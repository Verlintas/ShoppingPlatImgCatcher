from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict

from app import APP_NAME


def app_data_dir() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = str(Path.home() / "Library" / "Application Support")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    path = Path(base) / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def default_output_dir() -> str:
    if sys.platform == "win32":
        base = Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Pictures"
    else:
        base = Path.home() / "Pictures"
    return str(base / APP_NAME)


@dataclass
class Settings:
    output_dir: str = field(default_factory=default_output_dir)
    headless: bool = True
    pdd_visible: bool = False
    platform_enabled: Dict[str, bool] = field(
        default_factory=lambda: {"jd": True, "tb": True, "pdd": True}
    )
    concurrency: Dict[str, int] = field(
        default_factory=lambda: {"jd": 4, "tb": 3, "pdd": 2}
    )
    delay_min: float = 0.3
    delay_max: float = 1.2
    proxy: str = ""
    timeout: float = 30.0
    retries: int = 3
    min_image_bytes: int = 4096
    prefer_original: bool = True
    playwright_mirror: str = "https://cdn.npmmirror.com/binaries/playwright"
    save_review_images: bool = False

    @property
    def profiles_dir(self) -> Path:
        return app_data_dir() / "profiles"

    @property
    def db_path(self) -> Path:
        return app_data_dir() / "data.sqlite3"

    @property
    def logs_dir(self) -> Path:
        return app_data_dir() / "logs"

    @property
    def settings_path(self) -> Path:
        return app_data_dir() / "settings.json"

    @classmethod
    def load(cls) -> "Settings":
        path = app_data_dir() / "settings.json"
        if not path.exists():
            return cls()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        if not isinstance(raw, dict):
            return cls()
        defaults = cls()
        known = {f for f in defaults.__dataclass_fields__}
        data: Dict[str, Any] = {}
        for key, value in raw.items():
            if key in known:
                data[key] = value
        merged = asdict(defaults)
        merged.update(data)
        settings = cls(**merged)
        settings.profiles_dir.mkdir(parents=True, exist_ok=True)
        settings.logs_dir.mkdir(parents=True, exist_ok=True)
        return settings

    def save(self) -> None:
        path = self.settings_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8"
        )
