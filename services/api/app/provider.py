from __future__ import annotations

import json
import os
import urllib.request
import asyncio
import sys
from pathlib import Path
from .models import CourseDraft, Evidence, MindMapNode, ScheduleItem, TranscriptSegment


class MockCourseProvider:
    captions_from_upload = True

    async def live_caption(self, sequence: int) -> TranscriptSegment:
        samples = [
            ("Today we will review visual storytelling and production design.", "今天我们将复习视觉叙事和制作设计。"),
            ("Please submit the Photoshop restoration exercise next Friday.", "请在下周五前提交 Photoshop 修复练习。"),
            ("Correction: the deadline is Monday, not Friday.", "更正：截止日期是周一，不是周五。"),
        ]
        source, translation = samples[sequence % len(samples)]
        start = sequence * 5000
        return TranscriptSegment(id=f"seg-{sequence:04d}", start_ms=start, end_ms=start + 4500,
                                 source=source, translation=translation)

    async def caption_audio(self, path: Path, sequence: int) -> TranscriptSegment:
        return await self.live_caption(sequence)

    async def finalize(self, transcript: list[TranscriptSegment], course: str) -> CourseDraft:
        if not transcript:
            transcript = [await self.live_caption(i) for i in range(3)]
        ev = lambda s: [Evidence(segment_id=s.id, start_ms=s.start_ms, end_ms=s.end_ms, quote=s.source)]
        return CourseDraft(
            summary=f"{course} 课堂讨论了视觉叙事、制作设计与 Photoshop 修复作业。",
            key_points=["视觉叙事应服务于人物动机。", "制作设计需要通过空间和道具提供叙事线索。"],
            schedule=[ScheduleItem(id="ddl-restoration", kind="ddl", title="提交 Photoshop 修复练习",
                datetime=None, status="pending_confirmation", evidence=ev(transcript[-1]))],
            mindmap=[MindMapNode(id="root", label=course), MindMapNode(id="story", label="视觉叙事", parent_id="root"),
                MindMapNode(id="design", label="制作设计", parent_id="root"), MindMapNode(id="task", label="Photoshop 修复", parent_id="design")],
            pending_confirmation=["作业截止日期提到周一，但缺少具体年月日。"],
        )


class QwenCourseProvider(MockCourseProvider):
    """DashScope adapter. Live audio transport is proxied by the websocket route."""

    def __init__(self):
        self.captions_from_upload = False
        self.api_key = os.environ.get("DASHSCOPE_API_KEY", "")
        self.model = os.environ.get("QWEN_TEXT_MODEL", "qwen3.8-max")
        if not self.api_key:
            raise RuntimeError("DASHSCOPE_API_KEY is required when COURSE_PROVIDER=qwen")

    async def finalize(self, transcript: list[TranscriptSegment], course: str) -> CourseDraft:
        schema = CourseDraft.model_json_schema()
        prompt = "根据带时间戳的课堂原文生成中文纪要。日期不完整必须标记待确认；所有日程包含证据。"
        payload = json.dumps({"model": self.model, "messages": [{"role": "system", "content": prompt},
            {"role": "user", "content": json.dumps([s.model_dump() for s in transcript], ensure_ascii=False)}],
            "response_format": {"type": "json_schema", "json_schema": {"name": "course_draft", "strict": True, "schema": schema}}}).encode()
        request = urllib.request.Request("https://dashscope-intl.aliyuncs.com/compatible-mode/v1/chat/completions",
            data=payload, headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=120) as response:
            data = json.load(response)
        return CourseDraft.model_validate_json(data["choices"][0]["message"]["content"])


class LocalCourseProvider(MockCourseProvider):
    captions_from_upload = True

    def __init__(self):
        model_root = Path(os.environ.get("LOCAL_MODEL_ROOT", "../ntu-live-test")).resolve()
        sys.path.insert(0, str(model_root))
        from engine import Models
        self.models = Models()

    def _caption(self, path: Path, sequence: int) -> TranscriptSegment:
        from faster_whisper.audio import decode_audio
        audio = decode_audio(str(path), sampling_rate=16000)
        source, translation, _, _ = self.models.process(audio)
        start = sequence * 3000
        return TranscriptSegment(id=f"seg-{sequence:04d}", start_ms=start, end_ms=start + 3000,
                                 source=source or "[未识别到清晰语音]", translation=translation)

    async def caption_audio(self, path: Path, sequence: int) -> TranscriptSegment:
        return await asyncio.to_thread(self._caption, path, sequence)


def get_provider():
    name = os.environ.get("COURSE_PROVIDER", "mock")
    if name == "qwen":
        return QwenCourseProvider()
    if name == "local":
        return LocalCourseProvider()
    return MockCourseProvider()
