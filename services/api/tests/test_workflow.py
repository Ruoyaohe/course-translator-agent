import hashlib
import time
from pathlib import Path
from fastapi.testclient import TestClient


def make_client(tmp_path, monkeypatch):
    monkeypatch.setenv("NTU_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("OBSIDIAN_REPO_PATH", str(tmp_path / "vault"))
    monkeypatch.setenv("COURSE_PROVIDER", "mock")
    import importlib
    from services.api.app import main
    importlib.reload(main)
    return TestClient(main.app), tmp_path / "vault"


def test_review_and_publish_workflow(tmp_path, monkeypatch):
    client, vault = make_client(tmp_path, monkeypatch)
    created = client.post("/api/sessions", json={"course":"Film Art", "title":"Production Design",
        "source_language":"en", "target_language":"zh-CN", "timezone":"Asia/Hong_Kong",
        "hotwords":["mise-en-scène"], "recording_consent":True})
    assert created.status_code == 200
    sid = created.json()["id"]

    audio = b"deterministic-audio-part"
    digest = hashlib.sha256(audio).hexdigest()
    uploaded = client.post(f"/api/sessions/{sid}/audio-parts?sequence=0&sha256={digest}", files={"audio":("part.webm", audio, "audio/webm")})
    assert uploaded.status_code == 200
    assert uploaded.json()["received"] == [0]

    estimate = client.get(f"/api/sessions/{sid}/organize-estimate")
    assert estimate.status_code == 200
    assert estimate.json()["model"] == "qwen3.7-flash"
    assert estimate.json()["estimated_total_tokens"] > 0
    assert estimate.json()["estimated_total_cost"] > 0
    assert 20 <= estimate.json()["estimated_duration_seconds"] <= 180
    assert estimate.json()["cache_assumed"] is False

    finished = client.post(f"/api/sessions/{sid}/finish", headers={"Idempotency-Key":"finish-1"})
    assert finished.status_code == 200
    for _ in range(50):
        state = client.get(f"/api/sessions/{sid}").json()
        if state["status"] == "draft_ready": break
        time.sleep(.02)
    assert state["draft"]["schedule"][0]["status"] == "pending_confirmation"
    assert state["draft"]["schedule"][0]["evidence"]

    published = client.post(f"/api/sessions/{sid}/publish", headers={"Idempotency-Key":"publish-1"})
    assert published.status_code == 200
    assert published.json()["status"] == "published"
    note = next(vault.rglob("2026-*Film Art*Production Design.md"))
    assert "待确认" in note.read_text(encoding="utf-8")
    assert "category: ntu-class-record" in note.read_text(encoding="utf-8")
    assert not list(vault.rglob("完整原文.md"))
    assert not list(vault.rglob("脑图.mmd"))

    again = client.post(f"/api/sessions/{sid}/publish", headers={"Idempotency-Key":"publish-1"})
    assert again.status_code == 200
    ddl = (vault / "Note/NTU课堂记录/NTU作业与DDL.md").read_text(encoding="utf-8")
    assert ddl.count(f"NTU:{sid}:ddl:BEGIN") == 1


def test_rejects_bad_hash_and_missing_consent(tmp_path, monkeypatch):
    client, _ = make_client(tmp_path, monkeypatch)
    response = client.post("/api/sessions", json={"course":"X", "title":"Y", "recording_consent":False})
    assert response.status_code == 422
    created = client.post("/api/sessions", json={"course":"X", "title":"Y", "recording_consent":True}).json()
    response = client.post(f"/api/sessions/{created['id']}/audio-parts?sequence=0&sha256=bad", files={"audio":("p.webm", b"x")})
    assert response.status_code == 422


def test_local_finalize_requires_ai_instead_of_copying_transcript(monkeypatch):
    from services.api.app.models import TranscriptSegment
    from services.api.app.provider import LocalCourseProvider
    provider = LocalCourseProvider.__new__(LocalCourseProvider)
    provider.ai = None
    provider.draft_source = "ai_unconfigured"
    transcript = [
        TranscriptSegment(id="seg-1", start_ms=0, end_ms=2000, source="We discussed documentary ethics.", translation="我们讨论了纪录片伦理。"),
        TranscriptSegment(id="seg-2", start_ms=2000, end_ms=4000, source="Submit the essay next Friday.", translation="请在下周五提交论文。"),
    ]
    draft = __import__("asyncio").run(provider.finalize(transcript, "Film Studies"))
    assert "未配置千问" in draft.summary
    assert draft.key_points == []
    assert draft.schedule == []
    assert "我们讨论了纪录片伦理" not in draft.summary


def test_qwen_flash_estimate_uses_higher_tier_for_long_transcript():
    from services.api.app.models import TranscriptSegment
    from services.api.app.pricing import estimate_organize
    transcript = [TranscriptSegment(id="seg-long", start_ms=0, end_ms=3_600_000,
        source="lecture content " * 9_000, translation="课程内容" * 12_000)]
    estimate = estimate_organize(transcript)
    assert estimate["estimated_input_tokens"] > 32_000
    assert estimate["pricing_tier"] == "32K < INPUT <= 256K"
    assert estimate["input_rate_per_million"] == .749
