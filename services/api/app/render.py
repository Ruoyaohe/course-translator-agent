from __future__ import annotations

import re
from pathlib import Path
from .models import CourseDraft, CourseSession


def safe_name(value: str) -> str:
    value = re.sub(r"[\\/:*?\"<>|]", "-", value).strip(" .")
    return value[:100] or "未命名"


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
    lines = ["---", f"course: {session.course}", f"title: {session.title}",
             f"date: {session.created_at[:10]}", f"timezone: {session.timezone}",
             f"source_language: {session.source_language}", f"target_language: {session.target_language}",
             "status: reviewed", "tags: [NTU, 课堂记录]", "---", "", f"# {session.title}", "",
             "## 课程摘要", "", draft.summary, "", "## 重点", ""]
    lines += [f"- {item}" for item in draft.key_points]
    lines += ["", "## 日程与任务", ""]
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
    rows = [begin, f"### {session.created_at[:10]} · [[{session.title}/课程纪要|{session.title}]]"]
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

