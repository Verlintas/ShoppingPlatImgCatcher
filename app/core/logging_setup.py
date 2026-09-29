from __future__ import annotations

import logging
import sys
from pathlib import Path

try:  # pragma: no cover - loguru 为可选依赖
    from loguru import logger as _loguru_logger

    HAVE_LOGURU = True
except ImportError:  # pragma: no cover
    HAVE_LOGURU = False
    _loguru_logger = None

_configured = False


class _StdlibLogger:
    """loguru 缺失时的最小兼容实现（本地开发/测试用）。"""

    def __init__(self, name: str = "app") -> None:
        self._logger = logging.getLogger(name)

    @staticmethod
    def _format(message: str, args: tuple) -> str:
        try:
            return message.format(*args)
        except (IndexError, KeyError, ValueError):
            return message

    def debug(self, message: str, *args) -> None:
        self._logger.debug(self._format(message, args))

    def info(self, message: str, *args) -> None:
        self._logger.info(self._format(message, args))

    def warning(self, message: str, *args) -> None:
        self._logger.warning(self._format(message, args))

    def error(self, message: str, *args) -> None:
        self._logger.error(self._format(message, args))

    def exception(self, message: str, *args) -> None:
        self._logger.exception(self._format(message, args))


logger = _loguru_logger if HAVE_LOGURU else _StdlibLogger()


def setup_logging(logs_dir: Path, verbose: bool = False) -> None:
    global _configured
    if _configured:
        return
    level = "DEBUG" if verbose else "INFO"
    logs_dir.mkdir(parents=True, exist_ok=True)
    if HAVE_LOGURU and _loguru_logger is not None:
        _loguru_logger.remove()
        _loguru_logger.add(sys.stderr, level=level, enqueue=True)
        _loguru_logger.add(
            str(logs_dir / "app_{time:YYYY-MM-DD}.log"),
            level="DEBUG",
            rotation="10 MB",
            retention="14 days",
            encoding="utf-8",
            enqueue=True,
        )
    else:
        logging.basicConfig(
            level=getattr(logging, level),
            format="%(asctime)s | %(levelname)s | %(message)s",
            handlers=[
                logging.StreamHandler(sys.stderr),
                logging.FileHandler(logs_dir / "app.log", encoding="utf-8"),
            ],
        )
    _configured = True
