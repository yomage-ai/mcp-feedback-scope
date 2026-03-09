"""Central Web Server — FastAPI application with REST API, WebSocket, and Web UI."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from starlette.requests import Request

from .store import store

logger = logging.getLogger("mcp-feedback-scope.web")

BASE_DIR = Path(__file__).parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"


# ── WebSocket connection manager ──

class ConnectionManager:
    def __init__(self) -> None:
        self._connections: list[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._connections.append(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self._connections.remove(ws)

    async def broadcast(self, message: dict) -> None:
        payload = json.dumps(message, ensure_ascii=False)
        stale: list[WebSocket] = []
        for ws in self._connections:
            try:
                await ws.send_text(payload)
            except Exception:
                stale.append(ws)
        for ws in stale:
            self._connections.remove(ws)


manager = ConnectionManager()


# ── Lifespan ──

@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    loop = asyncio.get_running_loop()

    def _on_store_change() -> None:
        asyncio.run_coroutine_threadsafe(
            manager.broadcast({"type": "update"}), loop
        )

    store.on_change(_on_store_change)
    logger.info("Web server started")
    yield
    logger.info("Web server stopped")


# ── FastAPI app ──

app = FastAPI(title="MCP Feedback Scope", lifespan=lifespan)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


# ── Pydantic request bodies ──

class CreateFeedbackBody(BaseModel):
    summary: str
    summary_images: list[str] = []


class RespondBody(BaseModel):
    response: str
    images: list[str] = []


# ── REST API ──

@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/api/sessions")
async def list_sessions() -> list[dict]:
    return [s.to_dict() for s in store.list_sessions()]


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str) -> dict:
    s = store.get_session(session_id)
    if s is None:
        return {"error": "not found"}
    return s.to_dict()


@app.post("/api/sessions/{session_id}/feedback")
async def create_feedback(session_id: str, body: CreateFeedbackBody) -> dict:
    req = store.create_request(
        session_id, body.summary, summary_images=body.summary_images
    )
    return req.to_dict()


@app.get("/api/sessions/{session_id}/feedback/pending")
async def get_pending_feedback(session_id: str) -> dict:
    req = store.get_pending_request(session_id)
    if req is None:
        return {"pending": None}
    return {"pending": req.to_dict()}


@app.get("/api/sessions/{session_id}/feedback")
async def list_feedback(session_id: str) -> list[dict]:
    return [r.to_dict() for r in store.list_requests(session_id)]


@app.post("/api/feedback/{request_id}/respond")
async def respond_feedback(request_id: str, body: RespondBody) -> dict:
    req = store.respond(request_id, body.response, images=body.images or [])
    if req is None:
        return {"error": "not found or already responded"}
    return req.to_dict()


@app.post("/api/sessions/allocate")
async def allocate_session() -> dict:
    """Allocate a new auto-increment session ID."""
    sid = store.allocate_session_id()
    return {"id": sid}


@app.post("/api/sessions/register")
async def register_session(body: dict) -> dict:
    """Register a session with a server-assigned ID."""
    session_id = body.get("id", "")
    title = body.get("title", "")
    if not session_id:
        return {"error": "id is required"}
    session = store.register_session(session_id, title)
    return session.to_dict()


@app.post("/api/sessions/{session_id}/disconnect")
async def disconnect_session(session_id: str) -> dict:
    """Mark a session as disconnected. Called by the MCP server when Cursor closes the connection."""
    ok = store.disconnect_session(session_id)
    if not ok:
        return {"error": "session not found"}
    s = store.get_session(session_id)
    return s.to_dict() if s else {"ok": True}


@app.post("/api/sessions/find-or-create")
async def find_or_create_session(body: dict) -> dict:
    title = body.get("title", "Untitled")
    session = store.get_or_create_session(title)
    return session.to_dict()


@app.post("/api/sessions/{session_id}/feedback/wait")
async def create_and_wait_feedback(
    session_id: str, body: CreateFeedbackBody, timeout: float = 3600
) -> dict:
    """Create a feedback request and block until a response arrives or timeout."""
    req = store.create_request(
        session_id, body.summary, summary_images=body.summary_images
    )
    result = await store.wait_for_response(req.id, timeout=timeout)
    store.cleanup_waiter(req.id)
    if result is None:
        return {"timeout": True, "request": req.to_dict()}
    return {"timeout": False, "request": result.to_dict()}


# ── WebSocket ──

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    await manager.connect(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(ws)


# ── Web UI ──

@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("index.html", {"request": request})


# ── Entry point ──

def main() -> None:
    host = os.environ.get("MCP_WEB_HOST", "127.0.0.1")
    port = int(os.environ.get("MCP_WEB_PORT", "5000"))
    logging.basicConfig(level=logging.INFO)
    logger.info("Starting web server on %s:%d", host, port)
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
