from __future__ import annotations

import json
import os
import urllib.request
import asyncio
import sys
import re
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

    async def finalize(self, transcript: list[TranscriptSegment], course: str) -> CourseDraft:
        meaningful = [s for s in transcript if s.source != "[未识别到清晰语音]" and len(s.source.strip()) > 1]
        if not meaningful:
            return CourseDraft(summary="本次录音没有识别到足够清晰的课堂内容。",
                pending_confirmation=["请检查录音收声后重新整理。"],
                mindmap=[MindMapNode(id="root", label=course)])

        def clean(text: str) -> str:
            return re.sub(r"\s+", " ", text).strip(" ,.;，。；")

        translated = [clean(s.translation) for s in meaningful if clean(s.translation)]
        unique = []
        for text in translated:
            if len(text) >= 3 and text not in unique:
                unique.append(text)
        key_points = unique[:8]
        summary_text = "；".join(key_points[:4])
        summary = f"本次 {course} 课程主要记录：{summary_text}。" if summary_text else f"本次 {course} 录音已完成转写。"

        schedule = []
        pending = []
        task_pattern = re.compile(r"\b(submit|deadline|due|assignment|homework|class|meet|presentation)\b", re.I)
        date_pattern = re.compile(r"\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|today|tomorrow|next\s+\w+|\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?)\b", re.I)
        previous_task = None
        for segment in meaningful:
            if not task_pattern.search(segment.source):
                continue
            kind = "ddl" if re.search(r"submit|deadline|due|assignment|homework", segment.source, re.I) else "class"
            item_id = f"{kind}-{segment.id}"
            correction = bool(re.search(r"\b(correction|actually|instead|not\s+.+but)\b", segment.source, re.I))
            evidence = [Evidence(segment_id=segment.id, start_ms=segment.start_ms, end_ms=segment.end_ms, quote=segment.source)]
            schedule.append(ScheduleItem(id=item_id, kind="correction" if correction else kind,
                title=clean(segment.translation) or clean(segment.source), datetime=None,
                status="pending_confirmation", evidence=evidence,
                supersedes=previous_task if correction else None))
            if not correction:
                previous_task = item_id
            dates = date_pattern.findall(segment.source)
            if dates:
                pending.append(f"“{dates[-1]}”缺少可验证的完整日期，请确认。")

        nodes = [MindMapNode(id="root", label=course)]
        nodes += [MindMapNode(id=f"point-{i+1}", label=text[:80], parent_id="root") for i, text in enumerate(key_points[:8])]
        return CourseDraft(summary=summary, key_points=key_points, schedule=schedule,
            mindmap=nodes, pending_confirmation=list(dict.fromkeys(pending)))


def get_provider():
    name = os.environ.get("COURSE_PROVIDER", "mock")
    if name == "qwen":
        return QwenCourseProvider()
    if name == "local":
        return LocalCourseProvider()
    return MockCourseProvider()
