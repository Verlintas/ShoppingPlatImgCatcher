from __future__ import annotations


def set_windows_app_id() -> None:
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(  # type: ignore[attr-defined]
            "ShoppingPlatImgCatcher.App"
        )
    except Exception:  # noqa: BLE001
        pass
