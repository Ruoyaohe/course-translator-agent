from services.api.app.models import CourseDraft, CourseSession, MindMapNode, SessionStatus
from services.api.app.render import mermaid, note_relative_path, recording_date, safe_name


def test_mermaid_is_generated_from_nodes():
    draft = CourseDraft(summary="x", mindmap=[MindMapNode(id="r", label="Film (Art)"), MindMapNode(id="c", label="Design", parent_id="r")])
    output = mermaid(draft)
    assert output == "mindmap\n  Film （Art）\n    Design\n"


def test_safe_name_removes_path_characters():
    assert safe_name("Film/Art: Week 1") == "Film-Art- Week 1"


def test_note_path_matches_ntu_archive_convention():
    session = CourseSession(id="x", course="Film Art", title="Production Design", source_language="en",
        target_language="zh-CN", timezone="Asia/Hong_Kong", hotwords=[], status=SessionStatus.draft_ready,
        created_at="2026-09-27T00:00:00+00:00", updated_at="2026-09-27T00:00:00+00:00")
    assert note_relative_path(session).as_posix() == "Note/课程记录/课程/Film Art/2026-09-27—Film Art—Production Design.md"


def test_recording_date_uses_session_timezone_across_utc_midnight():
    session = CourseSession(id="x", course="Film Art", title="Production Design", source_language="en",
        target_language="zh-CN", timezone="Asia/Hong_Kong", hotwords=[], status=SessionStatus.draft_ready,
        created_at="2026-09-27T22:30:00+00:00", updated_at="2026-09-27T22:30:00+00:00")
    assert recording_date(session) == "2026-09-28"
    assert note_relative_path(session).name.startswith("2026-09-28—")
