from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


class EventType:
    LOG = "log"
    IMPORT_DONE = "import_done"
    MATCH_PROGRESS = "match_progress"
    MATCH_DONE = "match_done"
    TASK_QUEUED = "task_queued"
    TASK_STARTED = "task_started"
    TASK_PROGRESS = "task_progress"
    IMAGE_SAVED = "image_saved"
    TASK_FINISHED = "task_finished"
    RISK_DETECTED = "risk_detected"
    RISK_RESOLVED = "risk_resolved"
    LOGIN_REQUIRED = "login_required"
    LOGIN_DONE = "login_done"
    RUN_DONE = "run_done"
    ENGINE_STOPPED = "engine_stopped"
    ENGINE_ERROR = "engine_error"


@dataclass
class Event:
    type: str
    message: str = ""
    level: str = "info"
    payload: Dict[str, Any] = field(default_factory=dict)
    ts: float = field(default_factory=time.time)


class EventBus:
    """Thread-safe bus bridging the engine thread and the Qt GUI thread."""

    def __init__(self) -> None:
        self._queue: "queue.Queue[Event]" = queue.Queue()
        self._lock = threading.Lock()
        self._last: Optional[Event] = None

    def emit(self, event_type: str, message: str = "", level: str = "info", **payload: Any) -> None:
        event = Event(type=event_type, message=message, level=level, payload=payload)
        with self._lock:
            self._last = event
        self._queue.put(event)

    def drain(self, max_items: int = 200) -> List[Event]:
        events: List[Event] = []
        for _ in range(max_items):
            try:
                events.append(self._queue.get_nowait())
            except queue.Empty:
                break
        return events

    @property
    def last(self) -> Optional[Event]:
        with self._lock:
            return self._last

    def clear(self) -> None:
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                return
