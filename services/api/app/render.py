from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from .models import CourseDraft, CourseSession


def safe_name(value: str) -> str:
    value = re.sub(r"[\\/:*?\"<>|]", "-", value).strip(" .")
    return value[:100] or "未命名"


def recording_date(session: CourseSession) -> str:
    if session.publish_date:
        return session.publish_date
    created = datetime.fromisoformat(session.created_at.replace("Z", "+00:00"))
    try:
        return created.astimezone(ZoneInfo(session.timezone)).date().isoformat()
    except (KeyError, ValueError):
        return created.date().isoformat()


def note_relative_path(session: CourseSession, root: Path | None = None) -> Path:
    root = root or Path("Note/NTU课堂记录")
    course = safe_name(session.course)
    default_filename = f"{recording_date(session)}—{course}—{safe_name(session.title)}.md"
    filename = safe_name(session.publish_filename or default_filename)
    if not filename.lower().endswith(".md"):
        filename += ".md"
    return root / "课程" / course / filename


def mermaid(draft: CourseDraft) -> str:
    rows = ["mindmap"]
    by_parent: dict[str | None, list] = {}
    for node in draft.mindmap:
        by_parent.setdefault(node.parent_id, []).append(node)

    def walk(parent: str | None, depth: int) -> None:
        for node in by_parent.get(parent, []):
            label = node.label.replace("(", "（").replace(")", "）").replace("\n", " ")
            rows.append(f"{'  ' * (depth + 1)}{label}")
            walk(node.id, depth + 1)

    walk(None, 0)
    return "\n".join(rows) + "\n"


def note_markdown(session: CourseSession) -> str:
    draft = session.draft
    assert draft is not None
    duration_ms = max((segment.end_ms for segment in session.transcript), default=0)
    duration = f"{duration_ms // 60000}分{duration_ms % 60000 // 1000:02d}秒（据录音时间戳）"
    heading = f"{session.course}：{session.title}"
    properties = session.publish_properties
    note_type = str(properties.get("type", "note")); category = str(properties.get("category", "ntu-class-record"))
    note_format = str(properties.get("format", "课堂录音与AI整理")); tags = properties.get("tags", ["NTU", "课堂记录"])
    if not isinstance(tags, list): tags = ["NTU", "课堂记录"]
    lines = ["---", f"type: {note_type}", f"category: {category}", f"course: {session.course}",
             f"date: {recording_date(session)}", f"format: {note_format}", f"duration: {duration}",
             "source: 课堂录音经本地转写与千问AI整理", f"source_title: {heading}", "tags:",
             *[f"  - {tag}" for tag in tags], "---", "", f"# {heading}", "",
             f"> 本笔记依据课堂录音的机器转写整理，日期、专有名词及作业要求仍应以学校通知和教师原文为准。", "",
             "## 课程摘要", "", draft.summary, "", "## 本节重点", ""]
    lines += [f"- {item}" for item in draft.key_points]
    lines += ["", "## 时间线", ""]
    timeline = []
    for item in draft.schedule:
        for evidence in item.evidence:
            start = evidence.start_ms // 1000
            end = evidence.end_ms // 1000
            timeline.append((evidence.start_ms, f"| {start // 60:02d}:{start % 60:02d}–{end // 60:02d}:{end % 60:02d} | {item.title} |"))
    if timeline:
        lines += ["| 音频位置 | 内容 |", "| --- | --- |"] + [row for _, row in sorted(timeline)]
    else:
        lines += ["- 暂无可核验的分段时间线。"]
    lines += ["", "## 日程与待办", ""]
    for item in draft.schedule:
        when = item.datetime or "待确认"
        refs = ", ".join(f"{e.segment_id} @{e.start_ms/1000:.1f}s" for e in item.evidence)
        lines.append(f"- [ ] **{item.title}** — {when}（{item.status}；依据：{refs}）")
    if draft.pending_confirmation:
        lines += ["", "## 待确认", ""] + [f"- {x}" for x in draft.pending_confirmation]
    lines += ["", "## 脑图", "", "```mermaid", mermaid(draft).rstrip(), "```", ""]
    return "\n".join(lines)


def transcript_markdown(session: CourseSession) -> str:
    lines = [f"# {session.title}｜完整原文", "", "> 机器转写，请结合录音核对。", ""]
    for segment in session.transcript:
        lines += [f"## {segment.start_ms/1000:.1f}–{segment.end_ms/1000:.1f}s · {segment.id}", "",
                  segment.source, "", segment.translation, ""]
    return "\n".join(lines)


def controlled_block(session: CourseSession, kind: str) -> str:
    assert session.draft
    items = [x for x in session.draft.schedule if x.kind == kind]
    begin = f"<!-- NTU:{session.id}:{kind}:BEGIN -->"
    end = f"<!-- NTU:{session.id}:{kind}:END -->"
    note = note_relative_path(session).with_suffix("").as_posix()
    rows = [begin, f"### {recording_date(session)} · [[{note}|{session.course}：{session.title}]]"]
    rows += [f"- [ ] {x.title} — {x.datetime or '待确认'}" for x in items]
    rows.append(end)
    return "\n".join(rows)


def upsert_block(path: Path, session: CourseSession, kind: str) -> None:
    old = path.read_text(encoding="utf-8") if path.exists() else f"# {'NTU作业与DDL' if kind == 'ddl' else 'NTU课程日程'}\n\n"
    block = controlled_block(session, kind)
    pattern = re.compile(rf"<!-- NTU:{re.escape(session.id)}:{kind}:BEGIN -->.*?<!-- NTU:{re.escape(session.id)}:{kind}:END -->", re.S)
    content = pattern.sub(block, old) if pattern.search(old) else old.rstrip() + "\n\n" + block + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
