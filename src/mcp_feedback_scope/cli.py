"""CLI tool for interacting with the MCP Feedback Scope web server."""

from __future__ import annotations

import os
import sys
import time

import httpx

WEB_HOST = os.environ.get("MCP_WEB_HOST", "127.0.0.1")
WEB_PORT = int(os.environ.get("MCP_WEB_PORT", "5000"))
BASE_URL = f"http://{WEB_HOST}:{WEB_PORT}"


def _client() -> httpx.Client:
    return httpx.Client(base_url=BASE_URL, timeout=10)


def cmd_list() -> None:
    """List all sessions."""
    with _client() as c:
        sessions = c.get("/api/sessions").json()

    if not sessions:
        print("没有活跃的会话。")
        return

    status_map = {"active": "活跃", "waiting": "等待反馈", "closed": "已关闭"}
    for s in sessions:
        status = status_map.get(s["status"], s["status"])
        print(f"  [{status}] {s['title']}  (id: {s['id']})")


def cmd_pending(session_id: str) -> None:
    """Show pending feedback request for a session."""
    with _client() as c:
        data = c.get(f"/api/sessions/{session_id}/feedback/pending").json()

    pending = data.get("pending")
    if not pending:
        print("该会话没有待处理的反馈请求。")
        return

    print(f"请求 ID: {pending['id']}")
    print(f"状态: {pending['status']}")
    print(f"创建时间: {pending['created_at']}")
    print("─" * 40)
    print("AI 工作汇报:")
    print(pending["summary"])
    print("─" * 40)


def cmd_respond(request_id: str, text: str) -> None:
    """Submit a response to a feedback request."""
    with _client() as c:
        result = c.post(
            f"/api/feedback/{request_id}/respond",
            json={"response": text},
        ).json()

    if "error" in result:
        print(f"错误: {result['error']}")
    else:
        print(f"反馈已提交 (请求 {result['id']})")


def cmd_watch() -> None:
    """Watch for new feedback requests and respond interactively."""
    print(f"正在监听 {BASE_URL} 上的反馈请求... (Ctrl+C 退出)")
    seen: set[str] = set()

    try:
        while True:
            with _client() as c:
                sessions = c.get("/api/sessions").json()

            for s in sessions:
                if s["status"] != "waiting":
                    continue
                with _client() as c:
                    data = c.get(
                        f"/api/sessions/{s['id']}/feedback/pending"
                    ).json()

                pending = data.get("pending")
                if not pending or pending["id"] in seen:
                    continue

                seen.add(pending["id"])
                print(f"\n{'═' * 50}")
                print(f"  会话: {s['title']}")
                print(f"  请求 ID: {pending['id']}")
                print(f"{'─' * 50}")
                print(pending["summary"])
                print(f"{'─' * 50}")

                try:
                    text = input("输入反馈 (回车跳过): ").strip()
                except EOFError:
                    continue

                if text:
                    cmd_respond(pending["id"], text)

            time.sleep(2)
    except KeyboardInterrupt:
        print("\n已停止监听。")


def main() -> None:
    args = sys.argv[1:]
    if not args:
        print("用法:")
        print("  mcp-feedback-cli list                     列出所有会话")
        print("  mcp-feedback-cli pending <session_id>     查看待处理请求")
        print("  mcp-feedback-cli respond <request_id> <text>  提交反馈")
        print("  mcp-feedback-cli watch                    交互式监听")
        sys.exit(1)

    cmd = args[0]
    if cmd == "list":
        cmd_list()
    elif cmd == "pending" and len(args) >= 2:
        cmd_pending(args[1])
    elif cmd == "respond" and len(args) >= 3:
        cmd_respond(args[1], " ".join(args[2:]))
    elif cmd == "watch":
        cmd_watch()
    else:
        print(f"未知命令: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
