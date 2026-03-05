#!/usr/bin/env python3
"""
MCP Feedback Enhanced 伺服器主要模組

此模組提供 MCP (Model Context Protocol) 的增強回饋收集功能，
支援智能環境檢測，自動使用 Web UI 介面。

主要功能：
- MCP 工具實現
- 介面選擇（Web UI）
- 環境檢測 (SSH Remote, WSL, Local)
- 國際化支援
- 圖片處理與上傳
- 命令執行與結果展示
- 專案目錄管理

主要 MCP 工具：
- interactive_feedback: 收集用戶互動回饋
- get_system_info: 獲取系統環境資訊

作者: Fábio Ferreira (原作者)
增強: Minidoracat (Web UI, 圖片支援, 環境檢測)
重構: 模塊化設計
"""

import base64
import io
import json
import os
import sys
from typing import Annotated, Any

from fastmcp import FastMCP
from fastmcp.utilities.types import Image as MCPImage
from mcp.types import TextContent
from pydantic import Field

# 導入統一的調試功能
from .debug import server_debug_log as debug_log

# 導入多語系支援
# 導入錯誤處理框架
from .utils.error_handler import ErrorHandler, ErrorType

# 導入資源管理器
from .utils.resource_manager import create_temp_file


# ===== 編碼初始化 =====
def init_encoding():
    """初始化編碼設置，確保正確處理中文字符"""
    try:
        # Windows 特殊處理
        if sys.platform == "win32":
            import msvcrt

            # 設置為二進制模式
            msvcrt.setmode(sys.stdin.fileno(), os.O_BINARY)
            msvcrt.setmode(sys.stdout.fileno(), os.O_BINARY)

            # 重新包裝為 UTF-8 文本流，並禁用緩衝
            # 修復 union-attr 錯誤 - 安全獲取 buffer 或 detach
            stdin_buffer = getattr(sys.stdin, "buffer", None)
            if stdin_buffer is None and hasattr(sys.stdin, "detach"):
                stdin_buffer = sys.stdin.detach()

            stdout_buffer = getattr(sys.stdout, "buffer", None)
            if stdout_buffer is None and hasattr(sys.stdout, "detach"):
                stdout_buffer = sys.stdout.detach()

            sys.stdin = io.TextIOWrapper(
                stdin_buffer, encoding="utf-8", errors="replace", newline=None
            )
            sys.stdout = io.TextIOWrapper(
                stdout_buffer,
                encoding="utf-8",
                errors="replace",
                newline="",
                write_through=True,  # 關鍵：禁用寫入緩衝
            )
        else:
            # 非 Windows 系統的標準設置
            if hasattr(sys.stdout, "reconfigure"):
                sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            if hasattr(sys.stdin, "reconfigure"):
                sys.stdin.reconfigure(encoding="utf-8", errors="replace")

        # 設置 stderr 編碼（用於調試訊息）
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")

        return True
    except Exception:
        # 如果編碼設置失敗，嘗試基本設置
        try:
            if hasattr(sys.stdout, "reconfigure"):
                sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            if hasattr(sys.stdin, "reconfigure"):
                sys.stdin.reconfigure(encoding="utf-8", errors="replace")
            if hasattr(sys.stderr, "reconfigure"):
                sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except:
            pass
        return False


# 初始化編碼（在導入時就執行）
_encoding_initialized = init_encoding()

# ===== 常數定義 =====
SERVER_NAME = "互動式回饋收集 MCP"
SSH_ENV_VARS = ["SSH_CONNECTION", "SSH_CLIENT", "SSH_TTY"]
REMOTE_ENV_VARS = ["REMOTE_CONTAINERS", "CODESPACES"]


# 初始化 MCP 服務器
from . import __version__


# 確保 log_level 設定為正確的大寫格式
fastmcp_settings = {}

# 檢查環境變數並設定正確的 log_level
env_log_level = os.getenv("FASTMCP_LOG_LEVEL", "").upper()
if env_log_level in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
    fastmcp_settings["log_level"] = env_log_level
else:
    # 預設使用 INFO 等級
    fastmcp_settings["log_level"] = "INFO"

mcp: Any = FastMCP(SERVER_NAME)


# ===== 工具函數 =====
def is_wsl_environment() -> bool:
    """
    檢測是否在 WSL (Windows Subsystem for Linux) 環境中運行

    Returns:
        bool: True 表示 WSL 環境，False 表示其他環境
    """
    try:
        # 檢查 /proc/version 文件是否包含 WSL 標識
        if os.path.exists("/proc/version"):
            with open("/proc/version") as f:
                version_info = f.read().lower()
                if "microsoft" in version_info or "wsl" in version_info:
                    debug_log("偵測到 WSL 環境（通過 /proc/version）")
                    return True

        # 檢查 WSL 相關環境變數
        wsl_env_vars = ["WSL_DISTRO_NAME", "WSL_INTEROP", "WSLENV"]
        for env_var in wsl_env_vars:
            if os.getenv(env_var):
                debug_log(f"偵測到 WSL 環境變數: {env_var}")
                return True

        # 檢查是否存在 WSL 特有的路徑
        wsl_paths = ["/mnt/c", "/mnt/d", "/proc/sys/fs/binfmt_misc/WSLInterop"]
        for path in wsl_paths:
            if os.path.exists(path):
                debug_log(f"偵測到 WSL 特有路徑: {path}")
                return True

    except Exception as e:
        debug_log(f"WSL 檢測過程中發生錯誤: {e}")

    return False


def is_remote_environment() -> bool:
    """
    檢測是否在遠端環境中運行

    Returns:
        bool: True 表示遠端環境，False 表示本地環境
    """
    # WSL 不應被視為遠端環境，因為它可以訪問 Windows 瀏覽器
    if is_wsl_environment():
        debug_log("WSL 環境不被視為遠端環境")
        return False

    # 檢查 SSH 連線指標
    for env_var in SSH_ENV_VARS:
        if os.getenv(env_var):
            debug_log(f"偵測到 SSH 環境變數: {env_var}")
            return True

    # 檢查遠端開發環境
    for env_var in REMOTE_ENV_VARS:
        if os.getenv(env_var):
            debug_log(f"偵測到遠端開發環境: {env_var}")
            return True

    # 檢查 Docker 容器
    if os.path.exists("/.dockerenv"):
        debug_log("偵測到 Docker 容器環境")
        return True

    # Windows 遠端桌面檢查
    if sys.platform == "win32":
        session_name = os.getenv("SESSIONNAME", "")
        if session_name and "RDP" in session_name:
            debug_log(f"偵測到 Windows 遠端桌面: {session_name}")
            return True

    # Linux 無顯示環境檢查（但排除 WSL）
    if (
        sys.platform.startswith("linux")
        and not os.getenv("DISPLAY")
        and not is_wsl_environment()
    ):
        debug_log("偵測到 Linux 無顯示環境")
        return True

    return False


def save_feedback_to_file(feedback_data: dict, file_path: str | None = None) -> str:
    """
    將回饋資料儲存到 JSON 文件

    Args:
        feedback_data: 回饋資料字典
        file_path: 儲存路徑，若為 None 則自動產生臨時文件

    Returns:
        str: 儲存的文件路徑
    """
    if file_path is None:
        # 使用資源管理器創建臨時文件
        file_path = create_temp_file(suffix=".json", prefix="feedback_")

    # 確保目錄存在
    directory = os.path.dirname(file_path)
    if directory and not os.path.exists(directory):
        os.makedirs(directory, exist_ok=True)

    # 複製數據以避免修改原始數據
    json_data = feedback_data.copy()

    # 處理圖片數據：將 bytes 轉換為 base64 字符串以便 JSON 序列化
    if "images" in json_data and isinstance(json_data["images"], list):
        processed_images = []
        for img in json_data["images"]:
            if isinstance(img, dict) and "data" in img:
                processed_img = img.copy()
                # 如果 data 是 bytes，轉換為 base64 字符串
                if isinstance(img["data"], bytes):
                    processed_img["data"] = base64.b64encode(img["data"]).decode(
                        "utf-8"
                    )
                    processed_img["data_type"] = "base64"
                processed_images.append(processed_img)
            else:
                processed_images.append(img)
        json_data["images"] = processed_images

    # 儲存資料
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(json_data, f, ensure_ascii=False, indent=2)

    debug_log(f"回饋資料已儲存至: {file_path}")
    return file_path


def create_feedback_text(feedback_data: dict) -> str:
    """
    建立格式化的回饋文字

    Args:
        feedback_data: 回饋資料字典

    Returns:
        str: 格式化後的回饋文字
    """
    text_parts = []

    # 會話信息
    session_title = feedback_data.get("session_title", "")
    session_id = feedback_data.get("session_id", "")
    if session_title or session_id:
        session_header = "=== 會話信息 ==="
        if session_title:
            session_header += f"\n標題: {session_title}"
        if session_id:
            session_header += f"\nID: {session_id[:8]}"
        text_parts.append(session_header)

    # 基本回饋內容
    if feedback_data.get("interactive_feedback"):
        text_parts.append(f"=== 用戶回饋 ===\n{feedback_data['interactive_feedback']}")

    # 命令執行日誌
    if feedback_data.get("command_logs"):
        text_parts.append(f"=== 命令執行日誌 ===\n{feedback_data['command_logs']}")

    # 圖片附件概要
    if feedback_data.get("images"):
        images = feedback_data["images"]
        text_parts.append(f"=== 圖片附件概要 ===\n用戶提供了 {len(images)} 張圖片：")

        for i, img in enumerate(images, 1):
            size = img.get("size", 0)
            name = img.get("name", "unknown")

            # 智能單位顯示
            if size < 1024:
                size_str = f"{size} B"
            elif size < 1024 * 1024:
                size_kb = size / 1024
                size_str = f"{size_kb:.1f} KB"
            else:
                size_mb = size / (1024 * 1024)
                size_str = f"{size_mb:.1f} MB"

            img_info = f"  {i}. {name} ({size_str})"

            # 為提高兼容性，添加 base64 預覽信息
            if img.get("data"):
                try:
                    if isinstance(img["data"], bytes):
                        img_base64 = base64.b64encode(img["data"]).decode("utf-8")
                    elif isinstance(img["data"], str):
                        img_base64 = img["data"]
                    else:
                        img_base64 = None

                    if img_base64:
                        # 只顯示前50個字符的預覽
                        preview = (
                            img_base64[:50] + "..."
                            if len(img_base64) > 50
                            else img_base64
                        )
                        img_info += f"\n     Base64 預覽: {preview}"
                        img_info += f"\n     完整 Base64 長度: {len(img_base64)} 字符"

                        # 如果 AI 助手不支援 MCP 圖片，可以提供完整 base64
                        debug_log(f"圖片 {i} Base64 已準備，長度: {len(img_base64)}")

                        # 檢查是否啟用 Base64 詳細模式（從 UI 設定中獲取）
                        include_full_base64 = feedback_data.get("settings", {}).get(
                            "enable_base64_detail", False
                        )

                        if include_full_base64:
                            # 根據檔案名推斷 MIME 類型
                            file_name = img.get("name", "image.png")
                            if file_name.lower().endswith((".jpg", ".jpeg")):
                                mime_type = "image/jpeg"
                            elif file_name.lower().endswith(".gif"):
                                mime_type = "image/gif"
                            elif file_name.lower().endswith(".webp"):
                                mime_type = "image/webp"
                            else:
                                mime_type = "image/png"

                            img_info += f"\n     完整 Base64: data:{mime_type};base64,{img_base64}"

                except Exception as e:
                    debug_log(f"圖片 {i} Base64 處理失敗: {e}")

            text_parts.append(img_info)

        # 添加兼容性說明
        text_parts.append(
            "\n💡 注意：如果 AI 助手無法顯示圖片，圖片數據已包含在上述 Base64 信息中。"
        )

    return "\n\n".join(text_parts) if text_parts else "用戶未提供任何回饋內容。"


def resolve_image_paths(images: list[dict]) -> list[dict]:
    """
    將 images 列表中的 path 引用解析為 base64 data。
    支持兩種格式的輸入：
      - path 模式: {"path": "/absolute/path/to/image.png"}
      - data 模式: {"data": "base64...", "media_type": "image/png"}
    path 模式會被轉換為 data 模式後返回。
    """
    resolved = []
    for i, img in enumerate(images, 1):
        if img.get("path"):
            file_path = img["path"]
            try:
                file_path = os.path.abspath(file_path)
                if not os.path.isfile(file_path):
                    debug_log(f"圖片 {i} 路徑不存在: {file_path}")
                    continue

                with open(file_path, "rb") as f:
                    raw = f.read()

                if len(raw) == 0:
                    debug_log(f"圖片 {i} 檔案為空: {file_path}")
                    continue

                ext = os.path.splitext(file_path)[1].lower()
                media_map = {
                    ".png": "image/png",
                    ".jpg": "image/jpeg",
                    ".jpeg": "image/jpeg",
                    ".gif": "image/gif",
                    ".webp": "image/webp",
                    ".svg": "image/svg+xml",
                }
                media_type = media_map.get(ext, "image/png")

                b64 = base64.b64encode(raw).decode("utf-8")
                debug_log(
                    f"圖片 {i} 從路徑載入成功: {file_path} "
                    f"({len(raw)} bytes, {media_type})"
                )
                resolved.append({"data": b64, "media_type": media_type})
            except Exception as e:
                debug_log(f"圖片 {i} 路徑解析失敗 ({file_path}): {e}")
        elif img.get("data"):
            resolved.append(img)
        else:
            debug_log(f"圖片 {i} 既無 path 也無 data，跳過")
    return resolved


def process_images(images_data: list[dict]) -> list[MCPImage]:
    """
    處理圖片資料，轉換為 MCP 圖片對象

    Args:
        images_data: 圖片資料列表

    Returns:
        List[MCPImage]: MCP 圖片對象列表
    """
    mcp_images = []

    for i, img in enumerate(images_data, 1):
        try:
            if not img.get("data"):
                debug_log(f"圖片 {i} 沒有資料，跳過")
                continue

            # 檢查數據類型並相應處理
            if isinstance(img["data"], bytes):
                # 如果是原始 bytes 數據，直接使用
                image_bytes = img["data"]
                debug_log(
                    f"圖片 {i} 使用原始 bytes 數據，大小: {len(image_bytes)} bytes"
                )
            elif isinstance(img["data"], str):
                # 如果是 base64 字符串，進行解碼
                image_bytes = base64.b64decode(img["data"])
                debug_log(f"圖片 {i} 從 base64 解碼，大小: {len(image_bytes)} bytes")
            else:
                debug_log(f"圖片 {i} 數據類型不支援: {type(img['data'])}")
                continue

            if len(image_bytes) == 0:
                debug_log(f"圖片 {i} 數據為空，跳過")
                continue

            # 根據文件名推斷格式
            file_name = img.get("name", "image.png")
            if file_name.lower().endswith((".jpg", ".jpeg")):
                image_format = "jpeg"
            elif file_name.lower().endswith(".gif"):
                image_format = "gif"
            else:
                image_format = "png"  # 默認使用 PNG

            # 創建 MCPImage 對象
            mcp_image = MCPImage(data=image_bytes, format=image_format)
            mcp_images.append(mcp_image)

            debug_log(f"圖片 {i} ({file_name}) 處理成功，格式: {image_format}")

        except Exception as e:
            # 使用統一錯誤處理（不影響 JSON RPC）
            error_id = ErrorHandler.log_error_with_context(
                e,
                context={"operation": "圖片處理", "image_index": i},
                error_type=ErrorType.FILE_IO,
            )
            debug_log(f"圖片 {i} 處理失敗 [錯誤ID: {error_id}]: {e}")

    debug_log(f"共處理 {len(mcp_images)} 張圖片")
    return mcp_images


# ===== MCP 工具定義 =====
@mcp.tool()
async def interactive_feedback(
    project_directory: Annotated[str, Field(description="專案目錄路徑")] = ".",
    summary: Annotated[
        str, Field(description="AI 工作完成的摘要說明")
    ] = "我已完成了您請求的任務。",
    timeout: Annotated[int, Field(description="等待用戶回饋的超時時間（秒）")] = 600,
    session_title: Annotated[
        str, Field(description="會話標題（必填），用於標識和復用會話。同一對話的多次調用必須使用相同標題，不同對話應使用不同標題。建議使用對話主題作為標題。")
    ] = "",
    images: Annotated[
        list[dict], Field(description="AI 提供的圖片列表。每個元素為 dict，支持兩種模式：1) path 模式：包含 path（本地檔案路徑）欄位，伺服器自動讀取並編碼；2) data 模式：包含 data（base64 編碼字串）和 media_type（如 image/png）欄位。推薦使用 path 模式以避免傳輸大量 base64 資料。")
    ] = [],
):
    """Interactive feedback collection tool for LLM agents.

    USAGE RULES:
    1. During any process, task, or conversation, whether asking, replying, or completing phased tasks, you must call this tool to ask for feedback.
    2. Unless receiving termination instructions, all steps must repeatedly call this tool.
    3. Whenever user feedback is received, if the feedback content is not empty, you must call this tool again and adjust behavior based on the feedback content.
    4. Only when the user explicitly indicates "end" or "no more interaction needed" can you stop calling this tool, and the process is considered complete.
    5. You should summarize what have done, and provide project directory through args to let user know what you have done to provide feedback for next step.

    Args:
        project_directory: Project directory path for context
        summary: Summary of AI work completed for user review
        timeout: Timeout in seconds for waiting user feedback (default: 600 seconds)

    Returns:
        list: List containing TextContent and MCPImage objects representing user feedback
    """
    # 環境偵測
    is_remote = is_remote_environment()
    is_wsl = is_wsl_environment()

    debug_log(f"環境偵測結果 - 遠端: {is_remote}, WSL: {is_wsl}")
    debug_log("使用介面: Web UI")

    try:
        # 確保專案目錄存在
        if not os.path.exists(project_directory):
            project_directory = os.getcwd()
        project_directory = os.path.abspath(project_directory)

        # 使用 Web 模式
        debug_log("回饋模式: web")

        resolved_images = resolve_image_paths(images) if images else images
        result = await launch_web_feedback_ui(project_directory, summary, timeout, session_title, images=resolved_images)

        # 處理取消情況
        if not result:
            return [TextContent(type="text", text="用戶取消了回饋。")]

        # 儲存詳細結果
        save_feedback_to_file(result)

        # 建立回饋項目列表
        feedback_items = []

        # 添加文字回饋
        if (
            result.get("interactive_feedback")
            or result.get("command_logs")
            or result.get("images")
        ):
            feedback_text = create_feedback_text(result)
            feedback_items.append(TextContent(type="text", text=feedback_text))
            debug_log("文字回饋已添加")

        # 添加圖片回饋
        if result.get("images"):
            mcp_images = process_images(result["images"])
            # 修復 arg-type 錯誤 - 直接擴展列表
            feedback_items.extend(mcp_images)
            debug_log(f"已添加 {len(mcp_images)} 張圖片")

        # 確保至少有一個回饋項目
        if not feedback_items:
            feedback_items.append(
                TextContent(type="text", text="用戶未提供任何回饋內容。")
            )

        debug_log(f"回饋收集完成，共 {len(feedback_items)} 個項目")
        return feedback_items

    except Exception as e:
        # 使用統一錯誤處理，但不影響 JSON RPC 響應
        error_id = ErrorHandler.log_error_with_context(
            e,
            context={"operation": "回饋收集", "project_dir": project_directory},
            error_type=ErrorType.SYSTEM,
        )

        # 生成用戶友好的錯誤信息
        user_error_msg = ErrorHandler.format_user_error(e, include_technical=False)
        debug_log(f"回饋收集錯誤 [錯誤ID: {error_id}]: {e!s}")

        return [TextContent(type="text", text=user_error_msg)]


async def launch_web_feedback_ui(project_dir: str, summary: str, timeout: int, session_title: str = "", *, images: list[dict] | None = None) -> dict:
    """
    啟動 Web UI 收集回饋，支援自訂超時時間

    Args:
        project_dir: 專案目錄路徑
        summary: AI 工作摘要
        timeout: 超時時間（秒）
        session_title: 會話標題，用於復用

    Returns:
        dict: 收集到的回饋資料
    """
    debug_log(f"啟動 Web UI 介面，超時時間: {timeout} 秒, 標題: {session_title or '(空)'}")

    try:
        # 使用新的 web 模組
        from .web import launch_web_feedback_ui as web_launch

        return await web_launch(project_dir, summary, timeout, session_title=session_title, images=images)
    except ImportError as e:
        # 使用統一錯誤處理
        error_id = ErrorHandler.log_error_with_context(
            e,
            context={"operation": "Web UI 模組導入", "module": "web"},
            error_type=ErrorType.DEPENDENCY,
        )
        user_error_msg = ErrorHandler.format_user_error(
            e, ErrorType.DEPENDENCY, include_technical=False
        )
        debug_log(f"Web UI 模組導入失敗 [錯誤ID: {error_id}]: {e}")

        return {
            "command_logs": "",
            "interactive_feedback": user_error_msg,
            "images": [],
        }


@mcp.tool()
def list_sessions() -> str:
    """List all active feedback sessions in the current MCP server process.

    Use this tool before calling interactive_feedback to check existing sessions
    and generate a unique session_title that won't conflict with others.

    Returns:
        str: JSON with session list including id, title, status, and project directory
    """
    try:
        from .web import get_web_ui_manager
        manager = get_web_ui_manager()
        sessions = manager.get_all_active_sessions()
        result = {
            "total": len(sessions),
            "sessions": [
                {
                    "session_id": s.session_id[:8],
                    "title": s.title,
                    "status": s.status.value,
                    "project_directory": s.project_directory,
                }
                for s in sessions
            ],
        }
        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e), "total": 0, "sessions": []}, ensure_ascii=False)


@mcp.tool()
def send_feedback_to_session(
    session_identifier: Annotated[str, Field(description="目标会话的标题或 ID 前缀，用于匹配目标 session")] = "",
    message: Annotated[str, Field(description="要发送给目标 session 的反馈/指令内容")] = "",
) -> str:
    """Send feedback or instructions to another session, enabling AI-to-AI communication.

    This tool allows a master AI agent to send instructions to a worker session,
    implementing the orchestration pattern for multi-agent workflows.

    The target session must be in 'waiting' or 'active' state to receive feedback.
    Use list_sessions first to find available sessions and their identifiers.

    Args:
        session_identifier: Title or ID prefix of the target session
        message: Feedback/instruction content to send

    Returns:
        str: JSON result with status and details
    """
    import urllib.error
    import urllib.request as _urllib_request

    if not message:
        return json.dumps({"error": "message is required"}, ensure_ascii=False)

    if not session_identifier:
        return json.dumps({"error": "session_identifier is required"}, ensure_ascii=False)

    try:
        from .hub import discover_hub
        from .hub.hub_discovery import _read_lock_file, _is_process_alive, HubInfo

        hub = discover_hub()
        if not hub:
            data = _read_lock_file()
            if not data:
                return json.dumps({"error": "未找到运行中的 Hub 服务器"}, ensure_ascii=False)
            pid = data.get("pid", 0)
            if not _is_process_alive(pid):
                return json.dumps({"error": "Hub 服务器进程已停止"}, ensure_ascii=False)
            hub = HubInfo(
                pid=pid,
                port=data.get("port", 0),
                host=data.get("host", "127.0.0.1"),
                token=data.get("token", ""),
                started_at=data.get("started_at", 0),
            )

        headers = {
            "Content-Type": "application/json",
            "X-Hub-Token": hub.token,
        }

        # 获取所有活跃会话
        req = _urllib_request.Request(
            f"{hub.url}/api/all-sessions",
            headers=headers,
            method="GET",
        )
        resp = _urllib_request.urlopen(req, timeout=10)
        sessions_data = json.loads(resp.read().decode())
        sessions = sessions_data.get("sessions", [])

        if not sessions:
            return json.dumps({"error": "当前没有活跃的会话"}, ensure_ascii=False)

        # 按标识符匹配目标 session
        target = None

        # 精确 ID 匹配
        for s in sessions:
            if s.get("session_id") == session_identifier:
                target = s
                break

        # ID 前缀匹配
        if not target:
            matches = [s for s in sessions if s.get("session_id", "").startswith(session_identifier)]
            if len(matches) == 1:
                target = matches[0]

        # 标题精确匹配
        if not target:
            for s in sessions:
                if s.get("title", "") == session_identifier:
                    target = s
                    break

        # 标题包含匹配
        if not target:
            matches = [s for s in sessions if session_identifier in s.get("title", "")]
            if len(matches) == 1:
                target = matches[0]
            elif len(matches) > 1:
                titles = [f"{s.get('session_id', '')[:8]}: {s.get('title', '')}" for s in matches]
                return json.dumps({
                    "error": f"找到 {len(matches)} 个匹配的会话，请使用更精确的标识符",
                    "matches": titles,
                }, ensure_ascii=False)

        if not target:
            available = [
                {"id": s.get("session_id", "")[:8], "title": s.get("title", ""), "status": s.get("status", "")}
                for s in sessions
            ]
            return json.dumps({
                "error": f"未找到匹配 '{session_identifier}' 的会话",
                "available_sessions": available,
            }, ensure_ascii=False)

        target_id = target["session_id"]
        target_status = target.get("status", "")

        if target_status not in ("waiting", "active"):
            return json.dumps({
                "error": f"目标会话状态为 '{target_status}'，只有 waiting/active 状态的会话才能接收反馈",
                "session_id": target_id[:8],
                "title": target.get("title", ""),
            }, ensure_ascii=False)

        # 提交反馈到目标 session
        payload = json.dumps({
            "feedback": message,
            "images": [],
            "settings": {},
        }).encode()

        submit_req = _urllib_request.Request(
            f"{hub.url}/api/session/{target_id}/submit-feedback",
            data=payload,
            headers=headers,
            method="POST",
        )
        submit_resp = _urllib_request.urlopen(submit_req, timeout=10)
        result = json.loads(submit_resp.read().decode())

        if result.get("status") == "ok":
            debug_log(f"send_feedback_to_session: 成功向 {target_id[:8]} 发送指令")
            return json.dumps({
                "status": "ok",
                "message": f"指令已发送到会话 [{target_id[:8]}] {target.get('title', '')}",
                "session_id": target_id[:8],
                "title": target.get("title", ""),
            }, ensure_ascii=False)
        else:
            return json.dumps({
                "error": f"提交失败: {result.get('error', '未知错误')}",
            }, ensure_ascii=False)

    except urllib.error.HTTPError as e:
        error_body = e.read().decode() if e.fp else ""
        return json.dumps({"error": f"HTTP {e.code}: {error_body}"}, ensure_ascii=False)
    except (urllib.error.URLError, OSError) as e:
        return json.dumps({"error": f"无法连接到 Hub 服务器: {e}"}, ensure_ascii=False)
    except Exception as e:
        debug_log(f"send_feedback_to_session 异常: {e}")
        return json.dumps({"error": f"发送失败: {e!s}"}, ensure_ascii=False)


@mcp.tool()
def get_session_status(
    session_identifier: Annotated[str, Field(description="目标会话的标题或 ID 前缀，留空则返回所有会话的状态")] = "",
) -> str:
    """Get the status and message history of a feedback session.

    Use this tool to monitor worker sessions and check their progress.
    Returns session status, latest messages, and conversation history.

    If session_identifier is empty, returns a summary of all active sessions.
    If specified, returns detailed info for the matching session.

    Args:
        session_identifier: Title or ID prefix of the target session (empty for all)

    Returns:
        str: JSON with session status, message history, and details
    """
    import urllib.error
    import urllib.request as _urllib_request

    try:
        from .hub import discover_hub
        from .hub.hub_discovery import _read_lock_file, _is_process_alive, HubInfo

        hub = discover_hub()
        if not hub:
            data = _read_lock_file()
            if not data:
                return json.dumps({"error": "未找到运行中的 Hub 服务器"}, ensure_ascii=False)
            pid = data.get("pid", 0)
            if not _is_process_alive(pid):
                return json.dumps({"error": "Hub 服务器进程已停止"}, ensure_ascii=False)
            hub = HubInfo(
                pid=pid,
                port=data.get("port", 0),
                host=data.get("host", "127.0.0.1"),
                token=data.get("token", ""),
                started_at=data.get("started_at", 0),
            )

        headers = {
            "Content-Type": "application/json",
            "X-Hub-Token": hub.token,
        }

        # 获取所有活跃会话
        req = _urllib_request.Request(
            f"{hub.url}/api/all-sessions",
            headers=headers,
            method="GET",
        )
        resp = _urllib_request.urlopen(req, timeout=10)
        sessions_data = json.loads(resp.read().decode())
        sessions = sessions_data.get("sessions", [])

        if not session_identifier:
            summary = []
            for s in sessions:
                summary.append({
                    "session_id": s.get("session_id", "")[:8],
                    "title": s.get("title", ""),
                    "status": s.get("status", ""),
                    "project_directory": s.get("project_directory", ""),
                })
            return json.dumps({
                "total": len(summary),
                "sessions": summary,
            }, ensure_ascii=False, indent=2)

        # 匹配目标 session
        target = None
        for s in sessions:
            if s.get("session_id") == session_identifier:
                target = s
                break
        if not target:
            matches = [s for s in sessions if s.get("session_id", "").startswith(session_identifier)]
            if len(matches) == 1:
                target = matches[0]
        if not target:
            for s in sessions:
                if s.get("title", "") == session_identifier:
                    target = s
                    break
        if not target:
            matches = [s for s in sessions if session_identifier in s.get("title", "")]
            if len(matches) == 1:
                target = matches[0]

        if not target:
            available = [f"{s.get('session_id', '')[:8]}: {s.get('title', '')}" for s in sessions]
            return json.dumps({
                "error": f"未找到匹配 '{session_identifier}' 的会话",
                "available": available,
            }, ensure_ascii=False)

        target_id = target["session_id"]

        # 获取会话详情
        detail_req = _urllib_request.Request(
            f"{hub.url}/api/session/{target_id}",
            headers=headers,
            method="GET",
        )
        detail_resp = _urllib_request.urlopen(detail_req, timeout=10)
        detail = json.loads(detail_resp.read().decode())

        history = detail.get("message_history", [])
        result = {
            "session_id": target_id[:8],
            "title": detail.get("title", ""),
            "status": detail.get("status", ""),
            "project_directory": detail.get("project_directory", ""),
            "summary": detail.get("summary", ""),
            "message_count": len(history),
            "message_history": history[-10:] if len(history) > 10 else history,
            "feedback_result": detail.get("feedback_result", ""),
        }
        return json.dumps(result, ensure_ascii=False, indent=2)

    except urllib.error.HTTPError as e:
        error_body = e.read().decode() if e.fp else ""
        return json.dumps({"error": f"HTTP {e.code}: {error_body}"}, ensure_ascii=False)
    except (urllib.error.URLError, OSError) as e:
        return json.dumps({"error": f"无法连接到 Hub 服务器: {e}"}, ensure_ascii=False)
    except Exception as e:
        debug_log(f"get_session_status 异常: {e}")
        return json.dumps({"error": f"获取状态失败: {e!s}"}, ensure_ascii=False)


@mcp.tool()
async def wait_for_session_completion(
    session_identifier: Annotated[str, Field(description="目标会话的标题或 ID 前缀")] = "",
    poll_interval: Annotated[int, Field(description="轮询间隔秒数，检查会话状态的频率")] = 5,
    max_wait: Annotated[int, Field(description="最大等待时间秒数，超过后返回当前状态")] = 300,
) -> str:
    """Wait for a worker session to complete its task and return the result.

    This tool polls the target session until it transitions from 'waiting' to
    'feedback_submitted' or 'completed', meaning the worker agent has finished
    processing and submitted its results.

    Useful for orchestration: send an instruction, then wait for completion.

    Args:
        session_identifier: Title or ID prefix of the target session
        poll_interval: Seconds between status checks (default: 5)
        max_wait: Maximum seconds to wait before returning (default: 300)

    Returns:
        str: JSON with final session status, message history, and result
    """
    import time as _time
    import urllib.error
    import urllib.request as _urllib_request

    if not session_identifier:
        return json.dumps({"error": "session_identifier is required"}, ensure_ascii=False)

    poll_interval = max(2, min(poll_interval, 60))
    max_wait = max(5, min(max_wait, 3600))

    try:
        from .hub import discover_hub
        from .hub.hub_discovery import _read_lock_file, _is_process_alive, HubInfo

        def _get_hub() -> "HubInfo | None":
            hub = discover_hub()
            if hub:
                return hub
            data = _read_lock_file()
            if not data:
                return None
            pid = data.get("pid", 0)
            if not _is_process_alive(pid):
                return None
            return HubInfo(
                pid=pid,
                port=data.get("port", 0),
                host=data.get("host", "127.0.0.1"),
                token=data.get("token", ""),
                started_at=data.get("started_at", 0),
            )

        hub = _get_hub()
        if not hub:
            return json.dumps({"error": "未找到运行中的 Hub 服务器"}, ensure_ascii=False)

        headers = {
            "Content-Type": "application/json",
            "X-Hub-Token": hub.token,
        }

        # 首先找到目标 session ID
        req = _urllib_request.Request(f"{hub.url}/api/all-sessions", headers=headers, method="GET")
        resp = _urllib_request.urlopen(req, timeout=10)
        sessions = json.loads(resp.read().decode()).get("sessions", [])

        target = None
        for s in sessions:
            sid = s.get("session_id", "")
            title = s.get("title", "")
            if sid == session_identifier or sid.startswith(session_identifier) or title == session_identifier or session_identifier in title:
                target = s
                break

        if not target:
            available = [f"{s.get('session_id', '')[:8]}: {s.get('title', '')}" for s in sessions]
            return json.dumps({
                "error": f"未找到匹配 '{session_identifier}' 的会话",
                "available": available,
            }, ensure_ascii=False)

        target_id = target["session_id"]
        start_time = _time.time()

        # 轮询等待状态变化
        while (_time.time() - start_time) < max_wait:
            try:
                detail_req = _urllib_request.Request(
                    f"{hub.url}/api/session/{target_id}",
                    headers=headers,
                    method="GET",
                )
                detail_resp = _urllib_request.urlopen(detail_req, timeout=10)
                detail = json.loads(detail_resp.read().decode())

                status = detail.get("status", "")
                elapsed = int(_time.time() - start_time)

                # 完成条件：已提交反馈、已完成、错误、超时
                if status in ("feedback_submitted", "completed", "error", "timeout"):
                    history = detail.get("message_history", [])
                    return json.dumps({
                        "status": "completed",
                        "session_status": status,
                        "session_id": target_id[:8],
                        "title": detail.get("title", ""),
                        "elapsed_seconds": elapsed,
                        "summary": detail.get("summary", ""),
                        "feedback_result": detail.get("feedback_result", ""),
                        "message_count": len(history),
                        "latest_messages": history[-5:] if history else [],
                    }, ensure_ascii=False, indent=2)

                debug_log(f"wait_for_session_completion: {target_id[:8]} 状态={status}，已等待 {elapsed}s")

            except (urllib.error.URLError, OSError):
                debug_log("wait_for_session_completion: Hub 连接中断，重试...")

            import asyncio as _asyncio
            await _asyncio.sleep(poll_interval)

        # 超过最大等待时间
        return json.dumps({
            "status": "timeout",
            "message": f"等待超过 {max_wait} 秒，会话仍未完成",
            "session_id": target_id[:8],
            "title": target.get("title", ""),
            "elapsed_seconds": max_wait,
        }, ensure_ascii=False, indent=2)

    except Exception as e:
        debug_log(f"wait_for_session_completion 异常: {e}")
        return json.dumps({"error": f"等待失败: {e!s}"}, ensure_ascii=False)


@mcp.tool()
def get_system_info() -> str:
    """
    獲取系統環境資訊

    Returns:
        str: JSON 格式的系統資訊
    """
    is_remote = is_remote_environment()
    is_wsl = is_wsl_environment()

    system_info = {
        "平台": sys.platform,
        "Python 版本": sys.version.split()[0],
        "WSL 環境": is_wsl,
        "遠端環境": is_remote,
        "介面類型": "Web UI",
        "環境變數": {
            "SSH_CONNECTION": os.getenv("SSH_CONNECTION"),
            "SSH_CLIENT": os.getenv("SSH_CLIENT"),
            "DISPLAY": os.getenv("DISPLAY"),
            "VSCODE_INJECTION": os.getenv("VSCODE_INJECTION"),
            "SESSIONNAME": os.getenv("SESSIONNAME"),
            "WSL_DISTRO_NAME": os.getenv("WSL_DISTRO_NAME"),
            "WSL_INTEROP": os.getenv("WSL_INTEROP"),
            "WSLENV": os.getenv("WSLENV"),
        },
    }

    return json.dumps(system_info, ensure_ascii=False, indent=2)


# ===== 主程式入口 =====
def main():
    """主要入口點，用於套件執行
    收集用戶的互動回饋，支援文字和圖片
    此工具使用 Web UI 介面收集用戶回饋，支援智能環境檢測。

    用戶可以：
    1. 執行命令來驗證結果
    2. 提供文字回饋
    3. 上傳圖片作為回饋
    4. 查看 AI 的工作摘要

    調試模式：
    - 設置環境變數 MCP_DEBUG=true 可啟用詳細調試輸出
    - 生產環境建議關閉調試模式以避免輸出干擾


    """
    # 檢查是否啟用調試模式
    debug_enabled = os.getenv("MCP_DEBUG", "").lower() in ("true", "1", "yes", "on")

    # 檢查是否啟用桌面模式
    desktop_mode = os.getenv("MCP_DESKTOP_MODE", "").lower() in (
        "true",
        "1",
        "yes",
        "on",
    )

    if debug_enabled:
        debug_log("🚀 啟動互動式回饋收集 MCP 服務器")
        debug_log(f"   服務器名稱: {SERVER_NAME}")
        debug_log(f"   版本: {__version__}")
        debug_log(f"   平台: {sys.platform}")
        debug_log(f"   編碼初始化: {'成功' if _encoding_initialized else '失敗'}")
        debug_log(f"   遠端環境: {is_remote_environment()}")
        debug_log(f"   WSL 環境: {is_wsl_environment()}")
        debug_log(f"   桌面模式: {'啟用' if desktop_mode else '禁用'}")
        debug_log("   介面類型: Web UI")
        debug_log("   等待來自 AI 助手的調用...")
        debug_log("準備啟動 MCP 伺服器...")
        debug_log("調用 mcp.run()...")

    try:
        # 使用正確的 FastMCP API
        mcp.run()
    except KeyboardInterrupt:
        if debug_enabled:
            debug_log("收到中斷信號，正常退出")
        sys.exit(0)
    except Exception as e:
        if debug_enabled:
            debug_log(f"MCP 服務器啟動失敗: {e}")
            import traceback

            debug_log(f"詳細錯誤: {traceback.format_exc()}")
        sys.exit(1)


if __name__ == "__main__":
    main()
