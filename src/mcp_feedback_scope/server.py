"""MCP Server — stdio transport, defines interactive_feedback and list_sessions tools."""

from __future__ import annotations

import atexit
import logging
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.types import ImageContent, TextContent

logger = logging.getLogger("mcp-feedback-scope")

WEB_HOST = os.environ.get("MCP_WEB_HOST", "127.0.0.1")
WEB_PORT = int(os.environ.get("MCP_WEB_PORT", "5000"))
BASE_URL = f"http://{WEB_HOST}:{WEB_PORT}"
LOCK_FILE = Path(tempfile.gettempdir()) / "mcp_feedback_scope.lock"

SESSION_ID: str | None = None

mcp = FastMCP("mcp-feedback-scope")


# ── Web Server lifecycle helpers ──

def _is_web_server_running() -> bool:
    try:
        with httpx.Client(timeout=2) as client:
            r = client.get(f"{BASE_URL}/health")
            return r.status_code == 200
    except Exception:
        return False


def _start_web_server() -> None:
    """Start the web server in a detached subprocess if not already running."""
    if _is_web_server_running():
        logger.info("Web server already running at %s", BASE_URL)
        return

    try:
        lock = LOCK_FILE
        if lock.exists():
            age = time.time() - lock.stat().st_mtime
            if age < 10:
                time.sleep(3)
                if _is_web_server_running():
                    return
            lock.unlink(missing_ok=True)

        lock.write_text(str(os.getpid()))

        logger.info("Starting web server subprocess...")
        cmd = [
            sys.executable, "-m", "mcp_feedback_scope.web_server",
        ]
        env = os.environ.copy()
        env["MCP_WEB_HOST"] = WEB_HOST
        env["MCP_WEB_PORT"] = str(WEB_PORT)

        kwargs: dict = dict(
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if sys.platform == "win32":
            kwargs["creationflags"] = (
                subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS
            )
        else:
            kwargs["start_new_session"] = True

        subprocess.Popen(cmd, **kwargs)

        for _ in range(30):
            time.sleep(0.5)
            if _is_web_server_running():
                logger.info("Web server is now running at %s", BASE_URL)
                return

        logger.warning("Web server did not start within 15 seconds")
    except Exception as exc:
        logger.error("Failed to start web server: %s", exc)


# ── HTTP client helpers ──

async def _api_post(
    path: str,
    json: dict | None = None,
    params: dict | None = None,
    timeout: float = 10,
) -> dict:
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=timeout) as client:
        r = await client.post(path, json=json, params=params)
        return r.json()


async def _api_get(path: str) -> dict | list:
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
        r = await client.get(path)
        return r.json()


# ── Session registration ──

async def _ensure_session(title: str = "") -> str:
    """Allocate a session ID from the web server on first call, then reuse it."""
    global SESSION_ID
    _start_web_server()

    if SESSION_ID is None:
        data = await _api_post("/api/sessions/allocate")
        SESSION_ID = data["id"]
        logger.info("Allocated session ID: %s", SESSION_ID)

    await _api_post("/api/sessions/register", json={
        "id": SESSION_ID,
        "title": title or f"Session {SESSION_ID}",
    })
    return SESSION_ID


# ── MCP Tools ──

@mcp.tool()
async def interactive_feedback(
    summary: str,
    session_title: str = "",
    images: list[str] | None = None,
    timeout: int = 3600,
) -> list[TextContent | ImageContent]:
    """Request interactive feedback from the user.

    This tool pauses execution and waits for the user to provide feedback
    through the Web UI or CLI. Use it whenever you need user confirmation,
    clarification, or further instructions.

    Args:
        summary: A markdown summary of the work you've completed.
                 This is displayed to the user in the feedback UI.
                 Supports markdown image syntax: ![alt](url)
        session_title: Optional display name for this session.
        images: Optional list of base64 data-URL images to show the user.
                Format: ["data:image/png;base64,iVBOR...", ...]
        timeout: Maximum seconds to wait for a response (default 3600).

    Returns:
        The user's feedback text and optional images.
    """
    session_id = await _ensure_session(session_title)

    result = await _api_post(
        f"/api/sessions/{session_id}/feedback/wait",
        json={
            "summary": summary,
            "summary_images": images or [],
        },
        params={"timeout": timeout},
        timeout=timeout + 30,
    )

    if result.get("timeout"):
        return [TextContent(type="text", text="[Timeout] 用户未在规定时间内响应。")]

    req_data = result.get("request", {})
    response_text = req_data.get("response", "")
    response_images = req_data.get("response_images", [])

    content: list[TextContent | ImageContent] = []
    content.append(TextContent(
        type="text",
        text=response_text or "[Empty] 用户提交了空反馈。",
    ))

    for data_url in response_images:
        if not isinstance(data_url, str) or not data_url.startswith("data:"):
            continue
        parts = data_url.split(",", 1)
        if len(parts) == 2:
            mime = parts[0].split(":")[1].split(";")[0] if ":" in parts[0] else "image/png"
            content.append(ImageContent(
                type="image",
                data=parts[1],
                mimeType=mime,
            ))

    return content


@mcp.tool()
async def list_sessions() -> str:
    """List all active feedback sessions.

    Returns a formatted list of current sessions with their status.
    """
    _start_web_server()

    sessions = await _api_get("/api/sessions")
    if not sessions:
        return "当前没有活跃的会话。"

    lines = []
    for s in sessions:
        status_map = {"active": "活跃", "waiting": "等待反馈", "closed": "已关闭", "disconnected": "已断开"}
        status = status_map.get(s["status"], s["status"])
        lines.append(f"- [{status}] {s['title']} (id: {s['id']})")
    return "\n".join(lines)


# ── Disconnect cleanup ──

_cleanup_done = False


def _notify_disconnect() -> None:
    """Notify the web server that this session has disconnected.

    Called after mcp.run() returns (Cursor closed stdin) and
    also registered via atexit as a safety net.
    """
    global _cleanup_done
    if _cleanup_done or SESSION_ID is None:
        return
    _cleanup_done = True

    try:
        with httpx.Client(base_url=BASE_URL, timeout=5) as client:
            client.post(f"/api/sessions/{SESSION_ID}/disconnect")
        logger.info("Notified web server: session %s disconnected", SESSION_ID)
    except Exception as exc:
        logger.warning("Failed to notify disconnect for session %s: %s", SESSION_ID, exc)


atexit.register(_notify_disconnect)


# ── Entry point ──

def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    _start_web_server()
    mcp.run(transport="stdio")
    _notify_disconnect()


if __name__ == "__main__":
    main()
