from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path

from app.core.config import Settings
from app.core.logging_setup import logger


def check_browser_installed() -> bool:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return False
    try:
        with sync_playwright() as playwright:
            path = Path(playwright.chromium.executable_path)
            return path.exists()
    except Exception:  # noqa: BLE001 - playwright raises multiple error types
        return False


def install_browser(settings: Settings, on_log=None) -> bool:
    """下载 Playwright Chromium 内核，支持国内镜像。"""
    env = None
    try:
        from playwright._impl._driver import compute_driver_executable, get_driver_env

        driver = compute_driver_executable()
        env = get_driver_env()
        if isinstance(driver, (tuple, list)):
            command = [str(part) for part in driver]
        else:
            command = [str(driver)]
        command.append("install")
        command.append("chromium")
    except Exception:  # noqa: BLE001
        command = [sys.executable, "-m", "playwright", "install", "chromium"]

    if settings.playwright_mirror:
        env = dict(env or {})
        env.setdefault("PLAYWRIGHT_DOWNLOAD_HOST", settings.playwright_mirror)
        env.setdefault("PLAYWRIGHT_DOWNLOAD_CONNECTION_TIMEOUT", "120000")

    if on_log:
        on_log("开始下载浏览器内核（约 150MB，仅首次需要）...")
    logger.info("运行: {}", " ".join(command))
    try:
        process = subprocess.run(
            command,
            env=env,
            capture_output=True,
            text=True,
            timeout=1800,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.error("浏览器内核安装失败: {}", exc)
        if on_log:
            on_log(f"浏览器内核安装失败: {exc}")
        return False
    if process.returncode != 0:
        detail = (process.stderr or process.stdout or "").strip()[-800:]
        logger.error("浏览器内核安装失败: {}", detail)
        if on_log:
            on_log(f"浏览器内核安装失败: {detail}")
        return False
    if on_log:
        on_log("浏览器内核安装完成")
    return True


async def ensure_browser(settings: Settings, on_log=None) -> None:
    path = _chromium_path()
    if path and Path(path).exists():
        return
    loop = asyncio.get_running_loop()
    ok = await loop.run_in_executor(None, install_browser, settings, on_log)
    if not ok:
        raise RuntimeError("Playwright 浏览器内核不可用，请检查网络后重试")


def _chromium_path() -> str:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            return playwright.chromium.executable_path
    except Exception:  # noqa: BLE001
        return ""
