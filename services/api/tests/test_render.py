from services.api.app.models import CourseDraft, CourseSession, MindMapNode, SessionStatus
from services.api.app.render import mermaid, safe_name


def test_mermaid_is_generated_from_nodes():
    draft = CourseDraft(summary="x", mindmap=[MindMapNode(id="r", label="Film (Art)"), MindMapNode(id="c", label="Design", parent_id="r")])
    output = mermaid(draft)
    assert output == "mindmap\n  Film （Art）\n    Design\n"


def test_safe_name_removes_path_characters():
    assert safe_name("Film/Art: Week 1") == "Film-Art- Week 1"

