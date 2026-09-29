from __future__ import annotations

import json
import os
import urllib.request
import asyncio
import sys
import re
from pathlib import Path
from .models import CourseDraft, Evidence, MindMapNode, ScheduleItem, TranscriptSegment
from .pricing import SYSTEM_PROMPT


class MockCourseProvider:
    captions_from_upload = True
    draft_source = "mock"

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

    async def caption_audio(self, path: Path, sequence: int, source_language: str = "auto") -> TranscriptSegment:
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
        self.draft_source = "qwen_mcp"
        self.api_key = os.environ.get("DASHSCOPE_API_KEY", "")
        self.model = os.environ.get("QWEN_TEXT_MODEL", "qwen3.7-flash")
        if not self.api_key:
            raise RuntimeError("DASHSCOPE_API_KEY is required when COURSE_PROVIDER=qwen")

    def _finalize(self, transcript: list[TranscriptSegment], course: str) -> CourseDraft:
        schema = CourseDraft.model_json_schema()
        payload = json.dumps({"model": self.model, "messages": [{"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps([s.model_dump() for s in transcript], ensure_ascii=False)}],
            "response_format": {"type": "json_schema", "json_schema": {"name": "course_draft", "strict": True, "schema": schema}}}).encode()
        request = urllib.request.Request("https://dashscope-intl.aliyuncs.com/compatible-mode/v1/chat/completions",
            data=payload, headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=120) as response:
            data = json.load(response)
        draft = CourseDraft.model_validate_json(data["choices"][0]["message"]["content"])
        segments = {s.id: s for s in transcript}
        for item in draft.schedule:
            item.evidence = [Evidence(segment_id=e.segment_id, start_ms=segments[e.segment_id].start_ms,
                end_ms=segments[e.segment_id].end_ms, quote=segments[e.segment_id].source)
                for e in item.evidence if e.segment_id in segments]
            if not item.evidence:
                item.status = "pending_confirmation"
        return draft

    async def finalize(self, transcript: list[TranscriptSegment], course: str) -> CourseDraft:
        return await asyncio.to_thread(self._finalize, transcript, course)

    def translate_to_chinese(self, text: str, source_language: str = "auto") -> str:
        if not text.strip():
            return ""
        payload = json.dumps({"model": self.model, "messages": [
            {"role": "system", "content": "将课堂语音转写准确翻译成简洁中文。只输出译文，不解释。保留人名、术语、日期和数字。"},
            {"role": "user", "content": text}], "temperature": 0}).encode()
        request = urllib.request.Request("https://dashscope-intl.aliyuncs.com/compatible-mode/v1/chat/completions",
            data=payload, headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.load(response)["choices"][0]["message"]["content"].strip()


class LocalCourseProvider(MockCourseProvider):
    captions_from_upload = True

    def __init__(self):
        model_root = Path(os.environ.get("LOCAL_MODEL_ROOT", "../ntu-live-test")).resolve()
        sys.path.insert(0, str(model_root))
        from engine import Models
        self.models = Models()
        self.multilingual_asr = None
        self.multilingual_model = os.environ.get("MULTILINGUAL_WHISPER_MODEL", "base")
        self.ai = QwenCourseProvider() if os.environ.get("DASHSCOPE_API_KEY") else None
        self.draft_source = "qwen_mcp" if self.ai else "ai_unconfigured"

    def _caption(self, path: Path, sequence: int, source_language: str) -> TranscriptSegment:
        from faster_whisper.audio import decode_audio
        audio = decode_audio(str(path), sampling_rate=16000)
        if source_language == "en":
            source, translation, _, _ = self.models.process(audio)
        else:
            if self.multilingual_asr is None:
                from faster_whisper import WhisperModel
                self.multilingual_asr = WhisperModel(self.multilingual_model, device="cpu", compute_type="int8", cpu_threads=4, num_workers=1)
            language = None if source_language == "auto" else source_language
            segments, info = self.multilingual_asr.transcribe(audio, language=language, beam_size=1,
                temperature=0, condition_on_previous_text=False, vad_filter=False, without_timestamps=True)
            source = " ".join(segment.text.strip() for segment in segments).strip()
            detected = getattr(info, "language", source_language)
            if detected == "zh":
                translation = source
            elif self.ai:
                translation = self.ai.translate_to_chinese(source, detected)
            else:
                translation = source
        start = sequence * 3000
        return TranscriptSegment(id=f"seg-{sequence:04d}", start_ms=start, end_ms=start + 3000,
                                 source=source or "[未识别到清晰语音]", translation=translation)

    async def caption_audio(self, path: Path, sequence: int, source_language: str = "auto") -> TranscriptSegment:
        return await asyncio.to_thread(self._caption, path, sequence, source_language)

    async def finalize(self, transcript: list[TranscriptSegment], course: str) -> CourseDraft:
        if self.ai:
            return await self.ai.finalize(transcript, course)
        return CourseDraft(summary="尚未配置千问 API Key，AI 纪要未生成。",
            key_points=[], schedule=[], mindmap=[MindMapNode(id="root", label=course)],
            pending_confirmation=["请配置 DASHSCOPE_API_KEY 后点击“AI 重新整理”。原始转写已安全保留。"])

    async def finalize_extractively(self, transcript: list[TranscriptSegment], course: str) -> CourseDraft:
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
