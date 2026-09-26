from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
import urllib.parse
import urllib.request
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

router = APIRouter(prefix="/auth", tags=["auth"])


def _secret() -> bytes:
    return os.environ.get("APP_SECRET", "development-only-secret").encode()


def sign(data: dict) -> str:
    body = base64.urlsafe_b64encode(json.dumps(data, separators=(",", ":")).encode()).decode().rstrip("=")
    signature = hmac.new(_secret(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{signature}"


def verify(token: str | None) -> dict | None:
    if not token or "." not in token:
        return None
    body, signature = token.rsplit(".", 1)
    expected = hmac.new(_secret(), body.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return None
    try:
        data = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        return data if data.get("exp", 0) > time.time() else None
    except (ValueError, json.JSONDecodeError):
        return None


def current_user(request: Request) -> dict | None:
    if os.environ.get("APP_ENV", "development") != "production":
        return {"id": "dev", "login": "local-developer"}
    return verify(request.cookies.get("ntu_session"))


@router.get("/me")
def me(request: Request):
    user = current_user(request)
    if not user:
        raise HTTPException(401, "Not authenticated")
    return {"user": user}


@router.get("/github/login")
def github_login(return_to: str = "/"):
    client_id = os.environ.get("GITHUB_CLIENT_ID")
    if not client_id:
        raise HTTPException(503, "GitHub OAuth is not configured")
    state = sign({"nonce": secrets.token_urlsafe(16), "return_to": return_to, "exp": time.time() + 600})
    callback = os.environ.get("API_BASE_URL", "http://localhost:8000") + "/auth/github/callback"
    url = "https://github.com/login/oauth/authorize?" + urllib.parse.urlencode({"client_id": client_id, "redirect_uri": callback, "state": state, "scope": "read:user"})
    response = RedirectResponse(url)
    response.set_cookie("ntu_oauth_state", state, httponly=True, secure=os.environ.get("APP_ENV") == "production", samesite="lax", max_age=600)
    return response


@router.get("/github/callback")
def github_callback(code: str, state: str, request: Request):
    expected = request.cookies.get("ntu_oauth_state")
    if not expected or not hmac.compare_digest(expected, state) or not verify(state):
        raise HTTPException(400, "Invalid OAuth state")
    payload = urllib.parse.urlencode({"client_id": os.environ["GITHUB_CLIENT_ID"], "client_secret": os.environ["GITHUB_CLIENT_SECRET"], "code": code}).encode()
    exchange = urllib.request.Request("https://github.com/login/oauth/access_token", data=payload, headers={"Accept": "application/json"})
    with urllib.request.urlopen(exchange, timeout=20) as response:
        token = json.load(response).get("access_token")
    profile = urllib.request.Request("https://api.github.com/user", headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(profile, timeout=20) as response:
        user = json.load(response)
    allowed = os.environ.get("ALLOWED_GITHUB_USER_ID")
    if not allowed or str(user["id"]) != allowed:
        raise HTTPException(403, "GitHub user is not allowed")
    session = sign({"id": str(user["id"]), "login": user["login"], "exp": time.time() + 86400 * 30})
    target = verify(state).get("return_to") or os.environ.get("PUBLIC_BASE_URL", "/")
    response = RedirectResponse(target)
    response.set_cookie("ntu_session", session, httponly=True, secure=os.environ.get("APP_ENV") == "production", samesite="lax", max_age=86400 * 30)
    response.delete_cookie("ntu_oauth_state")
    return response
