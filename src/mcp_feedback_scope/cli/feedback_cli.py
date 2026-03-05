"""
CLI 反馈工具
============

通过命令行直接向指定 session 发送反馈，无需打开浏览器。
依赖 hub.lock 文件发现运行中的 Web 服务器，并通过 HTTP API 操作。
"""

import json
import sys
import urllib.error
import urllib.request
from typing import Any

from ..hub.hub_discovery import HubInfo, discover_hub, _read_lock_file, _is_process_alive


def _discover_hub_for_cli() -> HubInfo | None:
    """
    为 CLI 场景发现 Hub，与 discover_hub 的区别是不排除当前进程。
    CLI 进程与 Hub 进程是不同的 PID，所以直接使用 discover_hub 即可。
    如果 discover_hub 返回 None，尝试直接读取 lock 文件做降级处理。
    """
    hub = discover_hub()
    if hub:
        return hub

    # 降级：直接读取 lock 文件，跳过"不发现自己"的逻辑
    data = _read_lock_file()
    if not data:
        return None

    pid = data.get("pid", 0)
    port = data.get("port", 0)
    host = data.get("host", "127.0.0.1")
    token = data.get("token", "")
    started_at = data.get("started_at", 0)

    if not _is_process_alive(pid):
        return None

    return HubInfo(
        pid=pid,
        port=port,
        host=host,
        token=token,
        started_at=started_at,
    )


def _make_request(
    hub: HubInfo,
    method: str,
    path: str,
    data: dict | None = None,
    timeout: float = 10.0,
) -> dict[str, Any]:
    """向 Hub 发送 HTTP 请求"""
    url = f"{hub.url}{path}"
    headers = {
        "Content-Type": "application/json",
        "X-Hub-Token": hub.token,
    }

    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)

    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        error_body = e.read().decode() if e.fp else ""
        try:
            return json.loads(error_body)
        except (json.JSONDecodeError, ValueError):
            raise RuntimeError(f"HTTP {e.code}: {error_body}") from e
    except (urllib.error.URLError, OSError) as e:
        raise ConnectionError(f"无法连接到服务器 {hub.url}: {e}") from e


def list_sessions(hub: HubInfo) -> list[dict[str, Any]]:
    """获取所有活跃会话列表"""
    result = _make_request(hub, "GET", "/api/all-sessions")
    return result.get("sessions", [])


def submit_feedback(
    hub: HubInfo,
    session_id: str,
    feedback: str,
    images: list[dict] | None = None,
) -> dict[str, Any]:
    """向指定 session 提交反馈"""
    payload: dict[str, Any] = {
        "feedback": feedback,
        "images": images or [],
        "settings": {},
    }
    return _make_request(
        hub, "POST", f"/api/session/{session_id}/submit-feedback", data=payload
    )


def _print_sessions_table(sessions: list[dict]) -> None:
    """格式化输出会话列表"""
    if not sessions:
        print("当前没有活跃的会话。")
        return

    # 表头
    id_w, title_w, status_w, dir_w = 10, 24, 12, 40
    header = (
        f"{'ID':<{id_w}}  "
        f"{'标题':<{title_w}}  "
        f"{'状态':<{status_w}}  "
        f"{'项目目录':<{dir_w}}"
    )
    print(header)
    print("-" * len(header))

    for s in sessions:
        sid = s.get("session_id", "")[:8]
        title = s.get("title", "") or "(无标题)"
        if len(title) > title_w:
            title = title[: title_w - 2] + ".."
        status = s.get("status", "unknown")
        proj = s.get("project_directory", "")
        if len(proj) > dir_w:
            proj = ".." + proj[-(dir_w - 2) :]

        print(f"{sid:<{id_w}}  {title:<{title_w}}  {status:<{status_w}}  {proj:<{dir_w}}")


def _find_session_by_identifier(
    sessions: list[dict], identifier: str
) -> dict | None:
    """
    通过 session_id 前缀或标题匹配查找 session。
    优先精确匹配 ID，其次前缀匹配，最后标题包含匹配。
    """
    # 精确 ID 匹配
    for s in sessions:
        if s.get("session_id") == identifier:
            return s

    # ID 前缀匹配
    matches = [s for s in sessions if s.get("session_id", "").startswith(identifier)]
    if len(matches) == 1:
        return matches[0]

    # 标题精确匹配
    for s in sessions:
        if s.get("title", "") == identifier:
            return s

    # 标题包含匹配
    matches = [s for s in sessions if identifier in s.get("title", "")]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        print(f"找到 {len(matches)} 个匹配的会话，请使用更精确的标识符：")
        _print_sessions_table(matches)
        return None

    return None


def _find_latest_waiting_session(sessions: list[dict]) -> dict | None:
    """找到最新的等待中的 session"""
    waiting = [s for s in sessions if s.get("status") in ("waiting", "active")]
    if not waiting:
        return None
    # sessions 已按创建时间倒序排列，取第一个
    return waiting[0]


def cmd_list(args: Any) -> int:
    """执行 feedback list 命令"""
    hub = _discover_hub_for_cli()
    if not hub:
        print("错误：未找到运行中的 MCP Feedback 服务器。")
        print("请确保 Cursor 已启动并调用了 interactive_feedback 工具。")
        return 1

    try:
        sessions = list_sessions(hub)
    except (RuntimeError, ConnectionError) as e:
        print(f"错误：无法获取会话列表 - {e}")
        return 1

    print(f"服务器: {hub.url}  (PID: {hub.pid})")
    print()
    _print_sessions_table(sessions)
    return 0


def cmd_send(args: Any) -> int:
    """执行 feedback send 命令"""
    hub = _discover_hub_for_cli()
    if not hub:
        print("错误：未找到运行中的 MCP Feedback 服务器。")
        print("请确保 Cursor 已启动并调用了 interactive_feedback 工具。")
        return 1

    try:
        sessions = list_sessions(hub)
    except (RuntimeError, ConnectionError) as e:
        print(f"错误：无法获取会话列表 - {e}")
        return 1

    if not sessions:
        print("当前没有活跃的会话。")
        return 1

    # 确定目标 session
    target = None

    if getattr(args, "latest", False):
        target = _find_latest_waiting_session(sessions)
        if not target:
            print("没有找到等待中的会话。")
            return 1
    elif getattr(args, "title", None):
        target = _find_session_by_identifier(sessions, args.title)
        if not target:
            print(f"未找到标题匹配 '{args.title}' 的会话。")
            return 1
    elif getattr(args, "session", None):
        target = _find_session_by_identifier(sessions, args.session)
        if not target:
            print(f"未找到匹配 '{args.session}' 的会话。")
            print()
            print("可用的会话：")
            _print_sessions_table(sessions)
            return 1
    else:
        # 没有指定目标，自动选择最新的等待中 session
        target = _find_latest_waiting_session(sessions)
        if not target:
            print("没有找到等待中的会话。当前会话列表：")
            _print_sessions_table(sessions)
            return 1

    session_id = target["session_id"]
    session_title = target.get("title", "") or "(无标题)"
    feedback_text = args.message

    # 如果没有提供 message，从 stdin 读取
    if not feedback_text:
        if sys.stdin.isatty():
            print(f"目标会话: [{session_id[:8]}] {session_title}")
            print("请输入反馈内容 (Ctrl+Z 回车结束)：")
        try:
            feedback_text = sys.stdin.read().strip()
        except (EOFError, KeyboardInterrupt):
            print("\n已取消。")
            return 1

    if not feedback_text:
        print("错误：反馈内容不能为空。")
        return 1

    # 提交反馈
    try:
        result = submit_feedback(hub, session_id, feedback_text)
    except (RuntimeError, ConnectionError) as e:
        print(f"错误：提交反馈失败 - {e}")
        return 1

    if result.get("status") == "ok":
        print(f"反馈已发送到会话 [{session_id[:8]}] {session_title}")
        return 0
    else:
        error = result.get("error", "未知错误")
        print(f"提交失败: {error}")
        return 1


def cmd_interactive(args: Any) -> int:
    """交互模式：列出会话并等待用户选择"""
    hub = _discover_hub_for_cli()
    if not hub:
        print("错误：未找到运行中的 MCP Feedback 服务器。")
        print("请确保 Cursor 已启动并调用了 interactive_feedback 工具。")
        return 1

    try:
        sessions = list_sessions(hub)
    except (RuntimeError, ConnectionError) as e:
        print(f"错误：无法获取会话列表 - {e}")
        return 1

    if not sessions:
        print("当前没有活跃的会话。")
        return 1

    waiting = [s for s in sessions if s.get("status") in ("waiting", "active")]
    if not waiting:
        print("没有等待反馈的会话。当前会话列表：")
        _print_sessions_table(sessions)
        return 1

    print(f"服务器: {hub.url}  (PID: {hub.pid})")
    print()
    print("等待反馈的会话：")
    print()

    for i, s in enumerate(waiting, 1):
        sid = s.get("session_id", "")[:8]
        title = s.get("title", "") or "(无标题)"
        proj = s.get("project_directory", "")
        print(f"  [{i}] {sid}  {title}  ({proj})")

    print()

    # 自动选择唯一的会话
    if len(waiting) == 1:
        target = waiting[0]
        print(f"自动选择唯一的等待会话: [{target['session_id'][:8]}]")
    else:
        try:
            choice = input("选择会话编号 (直接回车选择第一个): ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n已取消。")
            return 1

        if not choice:
            target = waiting[0]
        else:
            try:
                idx = int(choice) - 1
                if 0 <= idx < len(waiting):
                    target = waiting[idx]
                else:
                    print("无效的编号。")
                    return 1
            except ValueError:
                print("无效的输入。")
                return 1

    session_id = target["session_id"]
    session_title = target.get("title", "") or "(无标题)"
    print()
    print(f"目标: [{session_id[:8]}] {session_title}")
    print("请输入反馈内容 (Ctrl+Z 回车结束)：")

    try:
        feedback_text = sys.stdin.read().strip()
    except (EOFError, KeyboardInterrupt):
        print("\n已取消。")
        return 1

    if not feedback_text:
        print("错误：反馈内容不能为空。")
        return 1

    try:
        result = submit_feedback(hub, session_id, feedback_text)
    except (RuntimeError, ConnectionError) as e:
        print(f"错误：提交反馈失败 - {e}")
        return 1

    if result.get("status") == "ok":
        print(f"反馈已发送到会话 [{session_id[:8]}] {session_title}")
        return 0
    else:
        error = result.get("error", "未知错误")
        print(f"提交失败: {error}")
        return 1
