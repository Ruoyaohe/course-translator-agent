from __future__ import annotations

import json
import threading
from pathlib import Path
from .models import CourseSession


class JsonStore:
    """Small local store. Production swaps this module for PostgreSQL without changing routes."""

    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()

    def _path(self, session_id: str) -> Path:
        return self.root / f"{session_id}.json"

    def save(self, session: CourseSession) -> CourseSession:
        with self.lock:
            path = self._path(session.id)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(session.model_dump_json(indent=2), encoding="utf-8")
            tmp.replace(path)
        return session

    def get(self, session_id: str) -> CourseSession:
        path = self._path(session_id)
        if not path.exists():
            raise KeyError(session_id)
        return CourseSession.model_validate_json(path.read_text(encoding="utf-8"))

    def list(self, query: str = "") -> list[CourseSession]:
        result = []
        for path in sorted(self.root.glob("*.json"), reverse=True):
            try:
                session = CourseSession.model_validate_json(path.read_text(encoding="utf-8"))
                haystack = f"{session.course} {session.title}".lower()
                if query.lower() in haystack:
                    result.append(session)
            except (ValueError, json.JSONDecodeError):
                continue
        return result

