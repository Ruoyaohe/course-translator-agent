from __future__ import annotations

import asyncio
import hashlib
import json
import os
import uuid
from pathlib import Path
from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, File, Header, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from .auth import current_user, router as auth_router, verify as verify_auth
from .models import CourseDraft, CourseSession, PublishOptions, SessionCreate, SessionStatus, now_iso
from .provider import get_provider
from .pricing import estimate_organize
from .publish import publish_to_obsidian
from .render import mermaid, note_markdown, transcript_markdown
from .store import JsonStore

load_dotenv()
ROOT = Path(os.environ.get("NTU_DATA_DIR", "./data")).resolve()
STORE = JsonStore(ROOT / "sessions")
UPLOADS = ROOT / "uploads"
UPLOADS.mkdir(parents=True, exist_ok=True)
provider = get_provider()
app = FastAPI(title="Course Translator Agent API", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=[os.environ.get("PUBLIC_BASE_URL", "http://localhost:3000")],
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.include_router(auth_router)


@app.middleware("http")
async def require_authentication(request, call_next):
    if request.url.path.startswith("/api/") and not current_user(request):
        from fastapi.responses import JSONResponse
        return JSONResponse({"detail": "Not authenticated"}, status_code=401)
    return await call_next(request)


def load(session_id: str) -> CourseSession:
    try:
        return STORE.get(session_id)
    except KeyError:
        raise HTTPException(404, "Session not found")


def ensure_key(session: CourseSession, operation: str, key: str | None) -> bool:
    if not key:
        raise HTTPException(400, "Idempotency-Key header is required")
    if session.idempotency.get(operation) == key:
        return False
    session.idempotency[operation] = key
    return True


@app.get("/health")
def health():
    return {"ok": True, "provider": os.environ.get("COURSE_PROVIDER", "mock")}


@app.post("/api/sessions", response_model=CourseSession)
def create_session(body: SessionCreate):
    if not body.recording_consent:
        raise HTTPException(422, "Recording consent must be confirmed")
    stamp = now_iso()
    session = CourseSession(id=uuid.uuid4().hex[:16], status=SessionStatus.recording,
        created_at=stamp, updated_at=stamp, **body.model_dump(exclude={"recording_consent"}))
    return STORE.save(session)


@app.get("/api/sessions", response_model=list[CourseSession])
def search_sessions(q: str = ""):
    return STORE.list(q)


@app.get("/api/sessions/{session_id}", response_model=CourseSession)
def get_session(session_id: str):
    return load(session_id)


@app.post("/api/sessions/{session_id}/audio-parts")
async def upload_part(session_id: str, sequence: int, sha256: str, audio: UploadFile = File(...)):
    session = load(session_id)
    payload = await audio.read()
    if len(payload) > 8 * 1024 * 1024:
        raise HTTPException(413, "Audio part is too large")
    if hashlib.sha256(payload).hexdigest() != sha256:
        raise HTTPException(422, "SHA-256 mismatch")
    folder = UPLOADS / session.id
    folder.mkdir(parents=True, exist_ok=True)
    suffix = ".wav" if audio.content_type == "audio/wav" else ".webm"
    target = folder / f"{sequence:08d}{suffix}"
    if not target.exists():
        target.write_bytes(payload)
    if sequence not in session.parts:
        session.parts = sorted([*session.parts, sequence])
    caption = next((item for item in session.transcript if item.id == f"seg-{sequence:04d}"), None)
    if caption is None and getattr(provider, "captions_from_upload", False):
        try:
            caption = await provider.caption_audio(target, sequence, session.source_language)
        except RuntimeError as exc:
            raise HTTPException(503, str(exc)) from exc
        session.transcript.append(caption)
        session.transcript.sort(key=lambda item: item.start_ms)
    session.updated_at = now_iso()
    STORE.save(session)
    return {"ok": True, "sequence": sequence, "received": session.parts,
            "caption": caption.model_dump() if caption else None}


@app.websocket("/api/sessions/{session_id}/live")
async def live(session_id: str, websocket: WebSocket):
    if os.environ.get("APP_ENV", "development") == "production" and not verify_auth(websocket.cookies.get("ntu_session")):
        await websocket.close(code=4401)
        return
    await websocket.accept()
    session = load(session_id)
    sequence = len(session.transcript)
    try:
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                break
            if message.get("bytes") is not None:
                segment = await provider.live_caption(sequence)
                sequence += 1
                session.transcript.append(segment)
                session.updated_at = now_iso()
                STORE.save(session)
                await websocket.send_json({"type": "caption", "segment": segment.model_dump()})
            elif message.get("text") == "ping":
                await websocket.send_text("pong")
    except (WebSocketDisconnect, RuntimeError):
        return


async def process_session(session_id: str):
    session = load(session_id)
    try:
        session.status = SessionStatus.transcribing
        session.updated_at = now_iso(); STORE.save(session)
        await asyncio.sleep(0.05)
        session.status = SessionStatus.organizing
        session.updated_at = now_iso(); STORE.save(session)
        session.draft = await provider.finalize(session.transcript, session.course)
        session.draft_source = getattr(provider, "draft_source", "mock")
        session.status = SessionStatus.draft_ready
        session.updated_at = now_iso(); STORE.save(session)
    except Exception as exc:
        session.status = SessionStatus.failed
        session.error = str(exc)
        session.updated_at = now_iso(); STORE.save(session)


@app.post("/api/sessions/{session_id}/finish", response_model=CourseSession)
async def finish(session_id: str, background_tasks: BackgroundTasks, idempotency_key: str | None = Header(None)):
    session = load(session_id)
    if not ensure_key(session, "finish", idempotency_key):
        return session
    session.status = SessionStatus.uploading
    session.updated_at = now_iso(); STORE.save(session)
    background_tasks.add_task(process_session, session.id)
    return session


@app.get("/api/sessions/{session_id}/events")
def events(session_id: str):
    session = load(session_id)
    return {"status": session.status, "updated_at": session.updated_at, "error": session.error}


@app.post("/api/sessions/{session_id}/organize", response_model=CourseSession)
async def organize(session_id: str, background_tasks: BackgroundTasks, idempotency_key: str | None = Header(None)):
    session = load(session_id)
    if not session.transcript:
        raise HTTPException(409, "Transcript is empty")
    if not ensure_key(session, "organize", idempotency_key):
        return session
    session.status = SessionStatus.organizing
    session.error = None
    session.updated_at = now_iso(); STORE.save(session)
    background_tasks.add_task(process_session, session.id)
    return session


@app.get("/api/sessions/{session_id}/organize-estimate")
def organize_estimate(session_id: str):
    session = load(session_id)
    if not session.transcript:
        raise HTTPException(409, "Transcript is empty")
    return estimate_organize(session.transcript)


@app.patch("/api/sessions/{session_id}/draft", response_model=CourseSession)
def update_draft(session_id: str, draft: CourseDraft):
    session = load(session_id)
    if session.status not in (SessionStatus.draft_ready, SessionStatus.approved):
        raise HTTPException(409, "Draft is not editable in the current state")
    session.draft = draft
    session.status = SessionStatus.draft_ready
    session.updated_at = now_iso()
    return STORE.save(session)


@app.post("/api/sessions/{session_id}/publish", response_model=CourseSession)
def publish(session_id: str, options: PublishOptions | None = None, idempotency_key: str | None = Header(None)):
    session = load(session_id)
    if session.status == SessionStatus.published:
        return session
    if session.status != SessionStatus.draft_ready or not session.draft:
        raise HTTPException(409, "A reviewed draft is required")
    if not ensure_key(session, "publish", idempotency_key):
        return session
    if options:
        session.publish_date = options.date
        session.publish_filename = options.filename
        session.publish_properties = {"type": options.note_type, "category": options.category, "format": options.format, "tags": options.tags}
    session.status = SessionStatus.approved
    STORE.save(session)
    try:
        session.status = SessionStatus.publishing; STORE.save(session)
        session.published_path, session.git_commit = publish_to_obsidian(session)
        session.status = SessionStatus.published
        session.updated_at = now_iso()
        return STORE.save(session)
    except Exception as exc:
        session.status = SessionStatus.draft_ready
        session.error = str(exc)
        STORE.save(session)
        raise HTTPException(409, str(exc))


@app.get("/api/sessions/{session_id}/artifacts/{name}", response_class=PlainTextResponse)
def artifact(session_id: str, name: str):
    session = load(session_id)
    if not session.draft:
        raise HTTPException(409, "Draft not ready")
    renderers = {"note.md": note_markdown, "transcript.md": transcript_markdown,
                 "mindmap.mmd": lambda s: mermaid(s.draft)}
    if name not in renderers:
        raise HTTPException(404, "Artifact not found")
    return renderers[name](session)
