import os
import httpx
from mcp.server.fastmcp import FastMCP

API = os.environ.get("API_BASE_URL", "http://localhost:8000")
mcp = FastMCP("NTU Course Agent", stateless_http=True)


async def request(method: str, path: str, **kwargs):
    async with httpx.AsyncClient(base_url=API, timeout=120) as client:
        response = await client.request(method, path, **kwargs)
        response.raise_for_status()
        return response.json()


@mcp.tool()
async def course_session_create(course: str, title: str, hotwords: list[str] | None = None):
    """Create an authorized classroom recording session."""
    return await request("POST", "/api/sessions", json={"course": course, "title": title,
        "source_language": "en", "target_language": "zh-CN", "timezone": "Asia/Hong_Kong",
        "hotwords": hotwords or [], "recording_consent": True})


@mcp.tool()
async def course_session_status(session_id: str):
    """Read processing state, transcript, draft, and publication status."""
    return await request("GET", f"/api/sessions/{session_id}")


@mcp.tool()
async def course_session_finalize(session_id: str, idempotency_key: str):
    """End intake and start final transcription and organization."""
    return await request("POST", f"/api/sessions/{session_id}/finish", headers={"Idempotency-Key": idempotency_key})


@mcp.tool()
async def course_draft_get(session_id: str):
    """Get a reviewable draft with evidence and unresolved date warnings."""
    return await course_session_status(session_id)


@mcp.tool()
async def course_draft_generate(session_id: str, idempotency_key: str):
    """Run the configured Qwen course-note agent over the final transcript and populate REVIEW_DRAFT."""
    return await request("POST", f"/api/sessions/{session_id}/organize", headers={"Idempotency-Key": idempotency_key})


@mcp.tool()
async def course_draft_update(session_id: str, draft: dict):
    """Replace a draft after user edits; preserve evidence fields."""
    return await request("PATCH", f"/api/sessions/{session_id}/draft", json=draft)


@mcp.tool()
async def course_mindmap_render(session_id: str):
    """Return generated Mermaid for the reviewed course graph."""
    async with httpx.AsyncClient(base_url=API) as client:
        response = await client.get(f"/api/sessions/{session_id}/artifacts/mindmap.mmd")
        response.raise_for_status()
        return {"mermaid": response.text}


@mcp.tool()
async def course_obsidian_publish(session_id: str, idempotency_key: str):
    """Publish only after the user has reviewed and explicitly approved the draft."""
    return await request("POST", f"/api/sessions/{session_id}/publish", headers={"Idempotency-Key": idempotency_key})


@mcp.tool()
async def course_session_search(query: str = ""):
    """Search previous sessions by course or title."""
    return await request("GET", "/api/sessions", params={"q": query})


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
