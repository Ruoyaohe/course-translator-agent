import os
import shutil
import time
from pathlib import Path


def remove_expired_audio(root: Path, retention_days: int) -> list[str]:
    cutoff = time.time() - retention_days * 86400
    removed = []
    if not root.exists():
        return removed
    for session_dir in root.iterdir():
        if session_dir.is_dir() and session_dir.stat().st_mtime < cutoff:
            shutil.rmtree(session_dir)
            removed.append(session_dir.name)
    return removed


if __name__ == "__main__":
    base = Path(os.environ.get("NTU_DATA_DIR", "./data")) / "uploads"
    print({"removed": remove_expired_audio(base, int(os.environ.get("RAW_AUDIO_RETENTION_DAYS", "7")))})

