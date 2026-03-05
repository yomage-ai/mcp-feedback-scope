#!/usr/bin/env python3
"""
主要路由處理
============

設置 Web UI 的主要路由和處理邏輯。
"""

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse

from ... import __version__
from ...debug import web_debug_log as debug_log
from ..constants import get_message_code as get_msg_code

# 模組載入時間戳，用於前端驗證代碼版本是否更新
_MODULE_LOAD_TIME = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


if TYPE_CHECKING:
    from ..main import WebUIManager


def load_user_layout_settings() -> str:
    """載入用戶的佈局模式設定"""
    try:
        # 使用統一的設定檔案路徑
        config_dir = Path.home() / ".config" / "mcp-feedback-scope"
        settings_file = config_dir / "ui_settings.json"

        if settings_file.exists():
            with open(settings_file, encoding="utf-8") as f:
                settings = json.load(f)
                layout_mode = settings.get("layoutMode", "combined-vertical")
                debug_log(f"從設定檔案載入佈局模式: {layout_mode}")
                # 修復 no-any-return 錯誤 - 確保返回 str 類型
                return str(layout_mode)
        else:
            debug_log("設定檔案不存在，使用預設佈局模式: combined-vertical")
            return "combined-vertical"
    except Exception as e:
        debug_log(f"載入佈局設定失敗: {e}，使用預設佈局模式: combined-vertical")
        return "combined-vertical"


# 使用統一的訊息代碼系統
# 從 ..constants 導入的 get_msg_code 函數會處理所有訊息代碼
# 舊的 key 會自動映射到新的常量


def setup_routes(manager: "WebUIManager"):
    """設置路由"""

    @manager.app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        """統一回饋頁面 - 多會話並發模式"""
        active_sessions = manager.get_all_active_sessions()
        current_session = manager.get_current_session()
        layout_mode = load_user_layout_settings()

        if not active_sessions:
            return manager.templates.TemplateResponse(
                "index.html",
                {
                    "request": request,
                    "title": "MCP Feedback Enhanced",
                    "has_session": False,
                    "version": __version__,
                },
            )

        # 總是渲染帶會話切換器的回饋頁面，前端負責會話選擇
        display_session = current_session or active_sessions[-1]

        return manager.templates.TemplateResponse(
            "feedback.html",
            {
                "request": request,
                "project_directory": display_session.project_directory,
                "summary": display_session.summary,
                "title": "Interactive Feedback - 回饋收集",
                "version": __version__,
                "build_time": _MODULE_LOAD_TIME,
                "has_session": True,
                "layout_mode": layout_mode,
                "session_count": len(active_sessions),
            },
        )

    @manager.app.get("/api/translations")
    async def get_translations():
        """獲取翻譯數據 - 從 Web 專用翻譯檔案載入"""
        translations = {}

        # 獲取 Web 翻譯檔案目錄
        web_locales_dir = Path(__file__).parent.parent / "locales"
        supported_languages = ["zh-TW", "zh-CN", "en"]

        for lang_code in supported_languages:
            lang_dir = web_locales_dir / lang_code
            translation_file = lang_dir / "translation.json"

            try:
                if translation_file.exists():
                    with open(translation_file, encoding="utf-8") as f:
                        lang_data = json.load(f)
                        translations[lang_code] = lang_data
                        debug_log(f"成功載入 Web 翻譯: {lang_code}")
                else:
                    debug_log(f"Web 翻譯檔案不存在: {translation_file}")
                    translations[lang_code] = {}
            except Exception as e:
                debug_log(f"載入 Web 翻譯檔案失敗 {lang_code}: {e}")
                translations[lang_code] = {}

        debug_log(f"Web 翻譯 API 返回 {len(translations)} 種語言的數據")
        return JSONResponse(content=translations)

    @manager.app.get("/api/session-status")
    async def get_session_status(request: Request):
        """獲取當前會話狀態"""
        current_session = manager.get_current_session()

        # 從請求頭獲取客戶端語言
        lang = (
            request.headers.get("Accept-Language", "zh-TW").split(",")[0].split("-")[0]
        )
        if lang == "zh":
            lang = "zh-TW"

        if not current_session:
            return JSONResponse(
                content={
                    "has_session": False,
                    "status": "no_session",
                    "messageCode": get_msg_code("no_active_session"),
                }
            )

        return JSONResponse(
            content={
                "has_session": True,
                "status": "active",
                "session_info": {
                    "project_directory": current_session.project_directory,
                    "summary": current_session.summary,
                    "feedback_completed": current_session.feedback_completed.is_set(),
                },
            }
        )

    @manager.app.get("/api/current-session")
    async def get_current_session(request: Request):
        """獲取最近創建的會話詳細信息（向後兼容）"""
        current_session = manager.get_current_session()

        if not current_session:
            return JSONResponse(
                status_code=404,
                content={
                    "error": "No active session",
                    "messageCode": get_msg_code("no_active_session"),
                },
            )

        return JSONResponse(
            content={
                "session_id": current_session.session_id,
                "project_directory": current_session.project_directory,
                "summary": current_session.summary,
                "feedback_completed": current_session.feedback_completed.is_set(),
                "command_logs": current_session.command_logs,
                "images_count": len(current_session.images),
            }
        )

    @manager.app.get("/api/session/{session_id}")
    async def get_session_by_id(session_id: str):
        """獲取特定會話詳細信息"""
        session = manager.get_session(session_id)
        if not session:
            return JSONResponse(
                status_code=404,
                content={"error": f"Session {session_id} not found"},
            )

        return JSONResponse(
            content={
                "session_id": session.session_id,
                "project_directory": session.project_directory,
                "summary": session.summary,
                "status": session.status.value,
                "status_message": session.status_message,
                "feedback_completed": session.feedback_completed.is_set(),
                "command_logs": session.command_logs,
                "images_count": len(session.images),
                "created_at": int(session.created_at * 1000),
                "last_activity": int(session.last_activity * 1000),
                "has_websocket": session.websocket is not None,
                "is_current": session == manager.current_session,
            }
        )

    @manager.app.get("/api/all-sessions")
    async def get_all_sessions(request: Request):
        """獲取所有會話的實時狀態"""

        try:
            sessions_data = []

            # 獲取所有會話的實時狀態
            for session_id, session in manager.sessions.items():
                session_info = {
                    "session_id": session.session_id,
                    "project_directory": session.project_directory,
                    "summary": session.summary,
                    "status": session.status.value,
                    "status_message": session.status_message,
                    "created_at": int(session.created_at * 1000),  # 轉換為毫秒
                    "last_activity": int(session.last_activity * 1000),
                    "feedback_completed": session.feedback_completed.is_set(),
                    "has_websocket": session.websocket is not None,
                    "is_current": session == manager.current_session,
                    "user_messages": session.user_messages,  # 包含用戶消息記錄
                }
                sessions_data.append(session_info)

            # 按創建時間排序（最新的在前）
            sessions_data.sort(key=lambda x: x["created_at"], reverse=True)

            debug_log(f"返回 {len(sessions_data)} 個會話的實時狀態")
            return JSONResponse(content={"sessions": sessions_data})

        except Exception as e:
            debug_log(f"獲取所有會話狀態失敗: {e}")
            return JSONResponse(
                status_code=500,
                content={
                    "error": f"Failed to get sessions: {e!s}",
                    "messageCode": get_msg_code("get_sessions_failed"),
                },
            )

    @manager.app.post("/api/add-user-message")
    async def add_user_message(request: Request):
        """添加用戶消息到當前會話"""

        try:
            data = await request.json()
            current_session = manager.get_current_session()

            if not current_session:
                return JSONResponse(
                    status_code=404,
                    content={
                        "error": "No active session",
                        "messageCode": get_msg_code("no_active_session"),
                    },
                )

            # 添加用戶消息到會話
            current_session.add_user_message(data)

            debug_log(f"用戶消息已添加到會話 {current_session.session_id}")
            return JSONResponse(
                content={
                    "status": "success",
                    "messageCode": get_msg_code("user_message_recorded"),
                }
            )

        except Exception as e:
            debug_log(f"添加用戶消息失敗: {e}")
            return JSONResponse(
                status_code=500,
                content={
                    "error": f"Failed to add user message: {e!s}",
                    "messageCode": get_msg_code("add_user_message_failed"),
                },
            )

    @manager.app.websocket("/ws")
    async def websocket_endpoint(
        websocket: WebSocket,
        session_id: str | None = None,
        lang: str = "zh-TW",
    ):
        """WebSocket 端點 - 支援 session_id 路由到特定會話"""
        # 根據 session_id 查找會話，或回退到最新會話
        if session_id:
            session = manager.get_session(session_id)
        else:
            session = manager.get_current_session()

        if not session:
            await websocket.close(code=4004, reason="No active session")
            return

        await websocket.accept()
        debug_log(f"WebSocket 連接建立，綁定會話 {session.session_id[:8]}")

        if session.websocket and session.websocket != websocket:
            debug_log(f"會話 {session.session_id[:8]} 已有 WebSocket，替換為新連接")

        session.websocket = websocket

        try:
            await websocket.send_json(
                {
                    "type": "connection_established",
                    "session_id": session.session_id,
                    "messageCode": get_msg_code("websocket_connected"),
                }
            )

            await websocket.send_json(
                {"type": "status_update", "status_info": session.get_status_info()}
            )
        except Exception as e:
            debug_log(f"發送連接確認失敗: {e}")

        try:
            while True:
                data = await websocket.receive_text()
                message = json.loads(data)

                # 確保消息路由到正確的會話（連接綁定的會話）
                target = manager.get_session(session.session_id)
                if target and target.websocket == websocket:
                    await handle_websocket_message(manager, target, message)
                else:
                    debug_log(f"會話 {session.session_id[:8]} 的 WebSocket 已失效")
                    break

        except WebSocketDisconnect:
            debug_log(f"WebSocket 正常斷開，會話 {session.session_id[:8]}")
        except ConnectionResetError:
            debug_log(f"WebSocket 連接被重置，會話 {session.session_id[:8]}")
        except Exception as e:
            debug_log(f"WebSocket 錯誤: {e}")
        finally:
            target = manager.get_session(session.session_id)
            if target and target.websocket == websocket:
                target.websocket = None
                debug_log(f"已清理會話 {session.session_id[:8]} 的 WebSocket 連接")

    @manager.app.websocket("/ws/lobby")
    async def lobby_websocket(websocket: WebSocket):
        """Lobby WebSocket - 全局通知頻道，接收新會話創建和狀態變更"""
        await websocket.accept()
        manager.add_lobby_connection(websocket)
        debug_log("Lobby WebSocket 連接建立")

        # 發送當前所有活躍會話列表
        try:
            active_sessions = manager.get_all_active_sessions()
            sessions_info = [
                {
                    "session_id": s.session_id,
                    "project_directory": s.project_directory,
                    "summary": s.summary,
                    "status": s.status.value,
                    "created_at": int(s.created_at * 1000),
                    "title": s.title,
                }
                for s in active_sessions
            ]
            await websocket.send_json(
                {"type": "sessions_list", "sessions": sessions_info}
            )
        except Exception as e:
            debug_log(f"發送 lobby 初始數據失敗: {e}")

        try:
            while True:
                data = await websocket.receive_text()
                message = json.loads(data)
                msg_type = message.get("type")

                if msg_type == "heartbeat":
                    await websocket.send_json(
                        {"type": "heartbeat_response", "timestamp": message.get("timestamp", 0)}
                    )
                elif msg_type == "get_sessions":
                    active = manager.get_all_active_sessions()
                    await websocket.send_json(
                        {
                            "type": "sessions_list",
                            "sessions": [
                                {
                                    "session_id": s.session_id,
                                    "project_directory": s.project_directory,
                                    "summary": s.summary,
                                    "status": s.status.value,
                                    "created_at": int(s.created_at * 1000),
                                    "title": s.title,
                                }
                                for s in active
                            ],
                        }
                    )

        except WebSocketDisconnect:
            debug_log("Lobby WebSocket 正常斷開")
        except Exception as e:
            debug_log(f"Lobby WebSocket 錯誤: {e}")
        finally:
            manager.remove_lobby_connection(websocket)

    @manager.app.post("/api/save-settings")
    async def save_settings(request: Request):
        """保存設定到檔案"""

        try:
            data = await request.json()

            # 使用統一的設定檔案路徑
            config_dir = Path.home() / ".config" / "mcp-feedback-scope"
            config_dir.mkdir(parents=True, exist_ok=True)
            settings_file = config_dir / "ui_settings.json"

            # 保存設定到檔案
            with open(settings_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            debug_log(f"設定已保存到: {settings_file}")

            return JSONResponse(
                content={
                    "status": "success",
                    "messageCode": get_msg_code("settings_saved"),
                }
            )

        except Exception as e:
            debug_log(f"保存設定失敗: {e}")
            return JSONResponse(
                status_code=500,
                content={
                    "status": "error",
                    "message": f"Save failed: {e!s}",
                    "messageCode": get_msg_code("save_failed"),
                },
            )

    @manager.app.get("/api/load-settings")
    async def load_settings(request: Request):
        """從檔案載入設定"""

        try:
            # 使用統一的設定檔案路徑
            config_dir = Path.home() / ".config" / "mcp-feedback-scope"
            settings_file = config_dir / "ui_settings.json"

            if settings_file.exists():
                with open(settings_file, encoding="utf-8") as f:
                    settings = json.load(f)

                debug_log(f"設定已從檔案載入: {settings_file}")
                return JSONResponse(content=settings)
            debug_log("設定檔案不存在，返回空設定")
            return JSONResponse(content={})

        except Exception as e:
            debug_log(f"載入設定失敗: {e}")
            return JSONResponse(
                status_code=500,
                content={
                    "status": "error",
                    "message": f"Load failed: {e!s}",
                    "messageCode": get_msg_code("load_failed"),
                },
            )

    @manager.app.post("/api/clear-settings")
    async def clear_settings(request: Request):
        """清除設定檔案"""

        try:
            # 使用統一的設定檔案路徑
            config_dir = Path.home() / ".config" / "mcp-feedback-scope"
            settings_file = config_dir / "ui_settings.json"

            if settings_file.exists():
                settings_file.unlink()
                debug_log(f"設定檔案已刪除: {settings_file}")
            else:
                debug_log("設定檔案不存在，無需刪除")

            return JSONResponse(
                content={
                    "status": "success",
                    "messageCode": get_msg_code("settings_cleared"),
                }
            )

        except Exception as e:
            debug_log(f"清除設定失敗: {e}")
            return JSONResponse(
                status_code=500,
                content={
                    "status": "error",
                    "message": f"Clear failed: {e!s}",
                    "messageCode": get_msg_code("clear_failed"),
                },
            )

    @manager.app.get("/api/load-session-history")
    async def load_session_history(request: Request):
        """從檔案載入會話歷史"""

        try:
            # 使用統一的設定檔案路徑
            config_dir = Path.home() / ".config" / "mcp-feedback-scope"
            history_file = config_dir / "session_history.json"

            if history_file.exists():
                with open(history_file, encoding="utf-8") as f:
                    history_data = json.load(f)

                debug_log(f"會話歷史已從檔案載入: {history_file}")

                # 確保資料格式相容性
                if isinstance(history_data, dict):
                    # 新格式：包含版本資訊和其他元資料
                    sessions = history_data.get("sessions", [])
                    last_cleanup = history_data.get("lastCleanup", 0)
                else:
                    # 舊格式：直接是會話陣列（向後相容）
                    sessions = history_data if isinstance(history_data, list) else []
                    last_cleanup = 0

                # 回傳會話歷史資料
                return JSONResponse(
                    content={"sessions": sessions, "lastCleanup": last_cleanup}
                )

            debug_log("會話歷史檔案不存在，返回空歷史")
            return JSONResponse(content={"sessions": [], "lastCleanup": 0})

        except Exception as e:
            debug_log(f"載入會話歷史失敗: {e}")
            return JSONResponse(
                status_code=500,
                content={
                    "status": "error",
                    "message": f"Load failed: {e!s}",
                    "messageCode": get_msg_code("load_failed"),
                },
            )

    @manager.app.post("/api/save-session-history")
    async def save_session_history(request: Request):
        """保存會話歷史到檔案"""

        try:
            data = await request.json()

            # 使用統一的設定檔案路徑
            config_dir = Path.home() / ".config" / "mcp-feedback-scope"
            config_dir.mkdir(parents=True, exist_ok=True)
            history_file = config_dir / "session_history.json"

            # 建立新格式的資料結構
            history_data = {
                "version": "1.0",
                "sessions": data.get("sessions", []),
                "lastCleanup": data.get("lastCleanup", 0),
                "savedAt": int(time.time() * 1000),  # 當前時間戳
            }

            # 保存會話歷史到檔案
            with open(history_file, "w", encoding="utf-8") as f:
                json.dump(history_data, f, ensure_ascii=False, indent=2)

            debug_log(f"會話歷史已保存到: {history_file}")
            session_count = len(history_data["sessions"])
            debug_log(f"保存了 {session_count} 個會話記錄")

            return JSONResponse(
                content={
                    "status": "success",
                    "messageCode": get_msg_code("session_history_saved"),
                    "params": {"count": session_count},
                }
            )

        except Exception as e:
            debug_log(f"保存會話歷史失敗: {e}")
            return JSONResponse(
                status_code=500,
                content={
                    "status": "error",
                    "message": f"Save failed: {e!s}",
                    "messageCode": get_msg_code("save_failed"),
                },
            )

    @manager.app.get("/api/log-level")
    async def get_log_level(request: Request):
        """獲取日誌等級設定"""

        try:
            # 使用統一的設定檔案路徑
            config_dir = Path.home() / ".config" / "mcp-feedback-scope"
            settings_file = config_dir / "ui_settings.json"

            if settings_file.exists():
                with open(settings_file, encoding="utf-8") as f:
                    settings_data = json.load(f)
                    log_level = settings_data.get("logLevel", "INFO")
                    debug_log(f"從設定檔案載入日誌等級: {log_level}")
                    return JSONResponse(content={"logLevel": log_level})
            else:
                # 預設日誌等級
                default_log_level = "INFO"
                debug_log(f"使用預設日誌等級: {default_log_level}")
                return JSONResponse(content={"logLevel": default_log_level})

        except Exception as e:
            debug_log(f"獲取日誌等級失敗: {e}")
            return JSONResponse(
                status_code=500,
                content={
                    "error": f"Failed to get log level: {e!s}",
                    "messageCode": get_msg_code("get_log_level_failed"),
                },
            )

    @manager.app.post("/api/log-level")
    async def set_log_level(request: Request):
        """設定日誌等級"""

        try:
            data = await request.json()
            log_level = data.get("logLevel")

            if not log_level or log_level not in ["DEBUG", "INFO", "WARN", "ERROR"]:
                return JSONResponse(
                    status_code=400,
                    content={
                        "error": "Invalid log level",
                        "messageCode": get_msg_code("invalid_log_level"),
                    },
                )

            # 使用統一的設定檔案路徑
            config_dir = Path.home() / ".config" / "mcp-feedback-scope"
            config_dir.mkdir(parents=True, exist_ok=True)
            settings_file = config_dir / "ui_settings.json"

            # 載入現有設定或創建新設定
            settings_data = {}
            if settings_file.exists():
                with open(settings_file, encoding="utf-8") as f:
                    settings_data = json.load(f)

            # 更新日誌等級
            settings_data["logLevel"] = log_level

            # 保存設定到檔案
            with open(settings_file, "w", encoding="utf-8") as f:
                json.dump(settings_data, f, ensure_ascii=False, indent=2)

            debug_log(f"日誌等級已設定為: {log_level}")

            return JSONResponse(
                content={
                    "status": "success",
                    "logLevel": log_level,
                    "messageCode": get_msg_code("log_level_updated"),
                }
            )

        except Exception as e:
            debug_log(f"設定日誌等級失敗: {e}")
            return JSONResponse(
                status_code=500,
                content={
                    "status": "error",
                    "message": f"Set failed: {e!s}",
                    "messageCode": get_msg_code("set_failed"),
                },
            )


    @manager.app.get("/api/health")
    async def health_check():
        """健康檢查端點"""
        active = manager.get_all_active_sessions()
        return JSONResponse(
            content={
                "status": "ok",
                "active_sessions": len(active),
                "total_sessions": len(manager.sessions),
                "version": __version__,
            }
        )

    @manager.app.get("/api/active-sessions")
    async def get_active_sessions():
        """獲取所有活躍（未完成）會話列表"""
        active = manager.get_all_active_sessions()
        return JSONResponse(
            content={
                "sessions": [
                    {
                        "session_id": s.session_id,
                        "project_directory": s.project_directory,
                        "summary": s.summary,
                        "status": s.status.value,
                        "created_at": int(s.created_at * 1000),
                        "has_websocket": s.websocket is not None,
                        "is_current": s == manager.current_session,
                    }
                    for s in active
                ]
            }
        )


    # ===== 內部 API（跨進程 Hub 通信） =====

    def _verify_hub_token(request: Request) -> bool:
        """驗證 Hub 內部 API 的 token"""
        token = request.headers.get("X-Hub-Token", "")
        expected = getattr(manager, "_hub_token", "")
        if not expected:
            return True
        return token == expected

    @manager.app.post("/api/internal/register-session")
    async def internal_register_session(request: Request):
        """遠端 MCP 進程註冊新會話"""
        if not _verify_hub_token(request):
            return JSONResponse(status_code=403, content={"error": "Invalid token"})

        try:
            data = await request.json()
            project_directory = data.get("project_directory", "")
            summary = data.get("summary", "")

            if not project_directory or not summary:
                return JSONResponse(
                    status_code=400,
                    content={"error": "project_directory and summary are required"},
                )

            session_id = manager.create_session(project_directory, summary)
            debug_log(f"內部 API: 遠端會話已註冊 {session_id[:8]}")

            return JSONResponse(
                content={
                    "session_id": session_id,
                    "status": "registered",
                }
            )
        except Exception as e:
            debug_log(f"內部 API: 註冊會話失敗: {e}")
            return JSONResponse(
                status_code=500,
                content={"error": f"Registration failed: {e!s}"},
            )

    @manager.app.get("/api/internal/session/{session_id}/wait-feedback")
    async def internal_wait_feedback(session_id: str, request: Request, timeout: int = 30):
        """長輪詢等待回饋 - 遠端 MCP 進程使用"""
        if not _verify_hub_token(request):
            return JSONResponse(status_code=403, content={"error": "Invalid token"})

        session = manager.get_session(session_id)
        if not session:
            return JSONResponse(
                status_code=404,
                content={"status": "error", "message": f"Session {session_id} not found"},
            )

        # 限制單次輪詢的最大超時
        poll_timeout = min(timeout, 30)

        try:
            import asyncio as _asyncio

            # 透過輪詢檢查回饋是否已提交
            start = time.time()
            while time.time() - start < poll_timeout:
                if session.feedback_completed.is_set():
                    return JSONResponse(
                        content={
                            "status": "feedback_received",
                            "feedback": session.feedback_result or {
                                "command_logs": session.command_logs,
                                "interactive_feedback": "",
                                "images": [],
                            },
                        }
                    )
                await _asyncio.sleep(0.5)

            return JSONResponse(
                content={"status": "timeout", "message": "No feedback yet"}
            )

        except Exception as e:
            debug_log(f"內部 API: 等待回饋失敗: {e}")
            return JSONResponse(
                status_code=500,
                content={"status": "error", "message": str(e)},
            )

    @manager.app.delete("/api/internal/session/{session_id}")
    async def internal_unregister_session(session_id: str, request: Request):
        """遠端 MCP 進程註銷會話"""
        if not _verify_hub_token(request):
            return JSONResponse(status_code=403, content={"error": "Invalid token"})

        session = manager.get_session(session_id)
        if not session:
            return JSONResponse(
                status_code=404,
                content={"error": f"Session {session_id} not found"},
            )

        manager.remove_session(session_id)
        debug_log(f"內部 API: 會話 {session_id[:8]} 已註銷")

        return JSONResponse(content={"status": "removed"})


async def handle_websocket_message(manager: "WebUIManager", session, data: dict):
    """處理 WebSocket 消息"""
    message_type = data.get("type")

    if message_type == "submit_feedback":
        feedback = data.get("feedback", "")
        images = data.get("images", [])
        settings = data.get("settings", {})
        await session.submit_feedback(feedback, images, settings)
        # 通知 lobby 會話狀態變更
        await manager.notify_lobby_session_changed(session, "feedback_submitted")

    elif message_type == "run_command":
        # 執行命令
        command = data.get("command", "")
        if command.strip():
            await session.run_command(command)

    elif message_type == "get_status":
        # 獲取會話狀態
        if session.websocket:
            try:
                await session.websocket.send_json(
                    {"type": "status_update", "status_info": session.get_status_info()}
                )
            except Exception as e:
                debug_log(f"發送狀態更新失敗: {e}")

    elif message_type == "heartbeat":
        # WebSocket 心跳處理（簡化版）
        # 更新心跳時間
        session.last_heartbeat = time.time()
        session.last_activity = time.time()

        # 發送心跳回應
        if session.websocket:
            try:
                await session.websocket.send_json(
                    {
                        "type": "heartbeat_response",
                        "timestamp": data.get("timestamp", 0),
                    }
                )
            except Exception as e:
                debug_log(f"發送心跳回應失敗: {e}")

    elif message_type == "user_timeout":
        # 用戶設置的超時已到
        debug_log(f"收到用戶超時通知: {session.session_id}")
        # 清理會話資源
        await session._cleanup_resources_on_timeout()
        # 重構：不再自動停止服務器，保持服務器運行以支援持久性

    elif message_type == "pong":
        # 處理來自前端的 pong 回應（用於連接檢測）
        debug_log(f"收到 pong 回應，時間戳: {data.get('timestamp', 'N/A')}")
        # 可以在這裡記錄延遲或更新連接狀態

    elif message_type == "update_timeout_settings":
        # 處理超時設定更新
        settings = data.get("settings", {})
        debug_log(f"收到超時設定更新: {settings}")
        if settings.get("enabled"):
            session.update_timeout_settings(
                enabled=True, timeout_seconds=settings.get("seconds", 3600)
            )
        else:
            session.update_timeout_settings(enabled=False)

    else:
        debug_log(f"未知的消息類型: {message_type}")


async def _delayed_server_stop(manager: "WebUIManager"):
    """延遲停止服務器"""
    import asyncio

    await asyncio.sleep(5)  # 等待 5 秒讓前端有時間關閉
    from ..main import stop_web_ui

    stop_web_ui()
    debug_log("Web UI 服務器已因用戶超時而停止")
