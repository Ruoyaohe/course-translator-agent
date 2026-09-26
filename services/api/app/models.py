from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Literal
from pydantic import BaseModel, Field


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SessionStatus(str, Enum):
    recording = "recording"
    uploading = "uploading"
    transcribing = "transcribing"
    organizing = "organizing"
    draft_ready = "draft_ready"
    approved = "approved"
    publishing = "publishing"
    published = "published"
    failed = "failed"


class Evidence(BaseModel):
    segment_id: str
    start_ms: int
    end_ms: int
    quote: str


class TranscriptSegment(BaseModel):
    id: str
    start_ms: int
    end_ms: int
    source: str
    translation: str = ""


class ScheduleItem(BaseModel):
    id: str
    kind: Literal["class", "ddl", "task", "correction"]
    title: str
    datetime: str | None = None
    status: Literal["confirmed", "pending_confirmation"] = "pending_confirmation"
    owner: str | None = None
    evidence: list[Evidence] = Field(default_factory=list)
    supersedes: str | None = None


class MindMapNode(BaseModel):
    id: str
    label: str
    parent_id: str | None = None


class CourseDraft(BaseModel):
    summary: str
    key_points: list[str] = Field(default_factory=list)
    schedule: list[ScheduleItem] = Field(default_factory=list)
    mindmap: list[MindMapNode] = Field(default_factory=list)
    pending_confirmation: list[str] = Field(default_factory=list)


class SessionCreate(BaseModel):
    course: str = Field(min_length=1, max_length=120)
    title: str = Field(min_length=1, max_length=200)
    source_language: str = "en"
    target_language: str = "zh-CN"
    timezone: str = "Asia/Hong_Kong"
    hotwords: list[str] = Field(default_factory=list, max_length=100)
    recording_consent: bool


class CourseSession(BaseModel):
    id: str
    course: str
    title: str
    source_language: str
    target_language: str
    timezone: str
    hotwords: list[str]
    status: SessionStatus
    created_at: str
    updated_at: str
    transcript: list[TranscriptSegment] = Field(default_factory=list)
    draft: CourseDraft | None = None
    parts: list[int] = Field(default_factory=list)
    idempotency: dict[str, str] = Field(default_factory=dict)
    error: str | None = None
    published_path: str | None = None
    git_commit: str | None = None

