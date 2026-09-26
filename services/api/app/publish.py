from __future__ import annotations

import os
import subprocess
from pathlib import Path
from .models import CourseSession
from .render import mermaid, note_markdown, safe_name, transcript_markdown, upsert_block


def _git(path: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(path), *args], text=True, capture_output=True, check=check, timeout=60)


def publish_to_obsidian(session: CourseSession) -> tuple[str, str | None]:
    if not session.draft:
        raise ValueError("Draft is not ready")
    vault = Path(os.environ.get("OBSIDIAN_REPO_PATH", "./data/obsidian-vault")).resolve()
    root = Path(os.environ.get("OBSIDIAN_NOTES_ROOT", "Note/NTU课堂记录"))
    vault.mkdir(parents=True, exist_ok=True)
    is_git = (vault / ".git").exists()
    if is_git:
        if _git(vault, "status", "--porcelain").stdout.strip():
            raise RuntimeError("Obsidian repository has uncommitted changes; refusing to overwrite")
        remote = _git(vault, "remote", check=False).stdout.strip()
        if remote:
            _git(vault, "pull", "--ff-only")

    folder = root / safe_name(session.course) / f"{session.created_at[:10]} {safe_name(session.title)}"
    target = vault / folder
    target.mkdir(parents=True, exist_ok=True)
    (target / "课程纪要.md").write_text(note_markdown(session), encoding="utf-8")
    (target / "完整原文.md").write_text(transcript_markdown(session), encoding="utf-8")
    (target / "脑图.mmd").write_text(mermaid(session.draft), encoding="utf-8")
    upsert_block(vault / root / "NTU课程日程.md", session, "class")
    upsert_block(vault / root / "NTU作业与DDL.md", session, "ddl")

    commit = None
    if is_git:
        _git(vault, "add", str(root))
        staged = _git(vault, "diff", "--cached", "--quiet", check=False).returncode
        if staged:
            _git(vault, "commit", "-m", f"Add NTU course notes: {session.title}")
            remote = _git(vault, "remote", check=False).stdout.strip()
            if remote:
                _git(vault, "push")
            commit = _git(vault, "rev-parse", "HEAD").stdout.strip()
    return str(folder / "课程纪要.md"), commit

