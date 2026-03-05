"""
Hub 客戶端模組

遠端 MCP 進程用來與 Hub 交互的客戶端。
支援會話註冊、回饋等待（長輪詢）和會話註銷。
"""

import asyncio
import json
import urllib.error
import urllib.request
from typing import Any

from ..debug import web_debug_log as debug_log
from .hub_discovery import HubInfo


class HubClient:
    """Hub 客戶端 - 遠端 MCP 進程用來與共享 Hub 交互"""

    def __init__(self, hub_info: HubInfo):
        self.hub_info = hub_info
        self.base_url = hub_info.url
        self.token = hub_info.token

    def _make_request(
        self,
        method: str,
        path: str,
        data: dict | None = None,
        timeout: float = 10.0,
    ) -> dict:
        """發送 HTTP 請求到 Hub"""
        url = f"{self.base_url}{path}"
        headers = {
            "Content-Type": "application/json",
            "X-Hub-Token": self.token,
        }

        body = json.dumps(data).encode() if data else None
        req = urllib.request.Request(url, data=body, headers=headers, method=method)

        try:
            resp = urllib.request.urlopen(req, timeout=timeout)
            return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            error_body = e.read().decode() if e.fp else ""
            debug_log(f"Hub API 錯誤: {e.code} {error_body}")
            raise RuntimeError(f"Hub API error {e.code}: {error_body}") from e
        except (urllib.error.URLError, OSError) as e:
            debug_log(f"Hub 連接失敗: {e}")
            raise ConnectionError(f"Cannot reach Hub at {self.base_url}: {e}") from e

    def register_session(
        self,
        project_directory: str,
        summary: str,
        timeout: int = 600,
        *,
        title: str = "",
    ) -> str:
        """
        向 Hub 註冊新會話。

        Args:
            project_directory: 專案目錄路徑
            summary: AI 工作摘要
            timeout: 回饋等待超時時間
            title: 會話標題

        Returns:
            會話 ID
        """
        result = self._make_request(
            "POST",
            "/api/internal/register-session",
            data={
                "project_directory": project_directory,
                "summary": summary,
                "timeout": timeout,
                "title": title,
            },
        )
        session_id = result.get("session_id", "")
        debug_log(f"遠端會話已註冊: {session_id[:8]}")
        return session_id

    async def wait_for_feedback(
        self,
        session_id: str,
        timeout: int = 600,
    ) -> dict[str, Any]:
        """
        等待用戶回饋 - 使用 HTTP 長輪詢。

        透過重複發送帶有較長超時的 HTTP GET 請求實現。
        每次請求最多等待 30 秒，超時後重試直到總超時。

        Args:
            session_id: 會話 ID
            timeout: 總超時時間（秒）

        Returns:
            回饋結果字典
        """
        poll_timeout = 30
        elapsed = 0
        poll_interval = 1.0

        while elapsed < timeout:
            try:
                result = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: self._make_request(
                        "GET",
                        f"/api/internal/session/{session_id}/wait-feedback?timeout={poll_timeout}",
                        timeout=poll_timeout + 5,
                    ),
                )

                status = result.get("status")

                if status == "feedback_received":
                    debug_log(f"遠端會話 {session_id[:8]} 收到回饋")
                    return result.get("feedback", {})

                if status == "timeout":
                    elapsed += poll_timeout
                    debug_log(f"長輪詢超時，已等待 {elapsed}s / {timeout}s")
                    continue

                if status == "expired" or status == "error":
                    raise RuntimeError(f"Session {session_id} error: {result.get('message', status)}")

            except ConnectionError:
                debug_log(f"Hub 連接中斷，{poll_interval}s 後重試...")
                await asyncio.sleep(poll_interval)
                elapsed += poll_interval
                poll_interval = min(poll_interval * 1.5, 10)
                continue

        # 總超時
        self.unregister_session(session_id)
        raise TimeoutError(f"Feedback timeout after {timeout}s for session {session_id}")

    def submit_feedback(
        self,
        session_id: str,
        feedback: str,
        images: list[dict] | None = None,
    ) -> dict[str, Any]:
        """
        向指定会话提交反馈。

        Args:
            session_id: 会话 ID
            feedback: 反馈文本
            images: 图片列表

        Returns:
            API 响应字典
        """
        result = self._make_request(
            "POST",
            f"/api/session/{session_id}/submit-feedback",
            data={
                "feedback": feedback,
                "images": images or [],
                "settings": {},
            },
        )
        debug_log(f"远端会话 {session_id[:8]} 已提交反馈")
        return result

    def list_sessions(self) -> list[dict[str, Any]]:
        """获取所有活跃会话列表"""
        result = self._make_request("GET", "/api/all-sessions")
        return result.get("sessions", [])

    def unregister_session(self, session_id: str):
        """從 Hub 註銷會話"""
        try:
            self._make_request("DELETE", f"/api/internal/session/{session_id}")
            debug_log(f"遠端會話 {session_id[:8]} 已註銷")
        except Exception as e:
            debug_log(f"註銷會話失敗: {e}")
