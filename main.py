from __future__ import annotations

import sys


def main() -> int:
    from PySide6.QtWidgets import QApplication

    from app import APP_TITLE
    from app.core.config import Settings
    from app.core.db import Database
    from app.core.logging_setup import setup_logging
    from app.gui import set_windows_app_id
    from app.gui.main_window import MainWindow
    from app.gui.worker import EngineWorker

    set_windows_app_id()
    settings = Settings.load()
    setup_logging(settings.logs_dir)
    db = Database(settings.db_path)
    db.reset_running_targets()

    app = QApplication(sys.argv)
    app.setApplicationName(APP_TITLE)
    worker = EngineWorker(db, settings)
    window = MainWindow(db, settings, worker)
    worker.start()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
