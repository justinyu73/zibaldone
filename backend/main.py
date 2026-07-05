"""FastAPI backend for the VaultWiki YouTube transcript tool.

Bootstrap only: app construction, sidecar security middleware, CORS, and router
registration. Feature endpoints live under routers/ with shared logic in services/.
"""
from __future__ import annotations

import hmac
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from services.security import configured_session_token
from routers.capture import router as capture_router
from routers.library import router as library_router
from routers.meetings import router as meetings_router
from routers.providers import router as providers_router
from routers.readiness import router as readiness_router
from routers.settings import router as settings_router

if os.getenv("VIDEO_INTAKE_DISABLE_DOTENV") != "1":
    load_dotenv(Path(__file__).with_name(".env"), override=True)

import app_config  # noqa: E402
app_config.load_key_into_env()  # user-home config key overrides repo .env
app_config.apply_settings_to_env()  # configured models -> env for model_for_task

FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "http://localhost:5173")
SESSION_HEADER = "x-yt-note-token"

app = FastAPI(title="VaultWiki YT Transcript API", version="0.1.0")

# DNS-rebinding guard: a malicious page can point its own hostname at 127.0.0.1
# and bypass CORS (same-origin after rebind). The sidecar only ever serves
# loopback/tauri hosts, so anything else in the Host header is rejected.
_ALLOWED_HOSTS = {"127.0.0.1", "localhost", "tauri.localhost", "ipc.localhost"}
_PUBLIC_SESSION_PATHS = {"/api/health", "/api/app/health"}


def host_header_allowed(host_header: str) -> bool:
    host = (host_header or "").split(":")[0].strip().lower()
    return not host or host in _ALLOWED_HOSTS


def session_token_required(path: str, method: str) -> bool:
    if not configured_session_token():
        return False
    if method.upper() == "OPTIONS":
        return False
    if not path.startswith("/api/"):
        return False
    # Native <audio> cannot attach the session header. This GET is authorized by
    # a short-lived path-bound ticket minted through a protected POST endpoint.
    if method.upper() == "GET" and path == "/api/app/meeting-audio":
        return False
    return path not in _PUBLIC_SESSION_PATHS


def session_token_valid(header_value: str | None) -> bool:
    token = configured_session_token()
    if not token:
        return True
    return hmac.compare_digest(header_value or "", token)


@app.middleware("http")
async def _local_sidecar_security_guard(request, call_next):
    if not host_header_allowed(request.headers.get("host", "")):
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=400, content={"detail": "invalid host header"})
    if session_token_required(request.url.path, request.method) and not session_token_valid(request.headers.get(SESSION_HEADER)):
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=401, content={"detail": "invalid or missing local app session token"})
    return await call_next(request)
app.add_middleware(
    CORSMiddleware,
    # Dev = vite proxy origin; packaged desktop = Tauri webview origin (tauri://localhost
    # on Linux/macOS, http://tauri.localhost on Windows). The sidecar binds 127.0.0.1 only.
    allow_origins=[
        FRONTEND_ORIGIN,
        "http://127.0.0.1:5173",
        "tauri://localhost",
        "http://tauri.localhost",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(readiness_router)
app.include_router(settings_router)
app.include_router(library_router)
app.include_router(meetings_router)
app.include_router(providers_router)
app.include_router(capture_router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
