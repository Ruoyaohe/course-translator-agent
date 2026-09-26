import os
import time
from services.worker.cleanup import remove_expired_audio


def test_cleanup_removes_only_expired(tmp_path):
    old = tmp_path / "old"; new = tmp_path / "new"; old.mkdir(); new.mkdir()
    stamp = time.time() - 9 * 86400; os.utime(old, (stamp, stamp))
    assert remove_expired_audio(tmp_path, 7) == ["old"]
    assert new.exists() and not old.exists()

