"""
Hub 發現模組

透過 lock 文件發現已運行的 Hub 實例。
lock 文件存儲在 ~/.config/mcp-feedback-scope/hub.lock，
包含 Hub 的 PID、端口和認證 token。
"""

import json
import os
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path

import psutil

from ..debug import web_debug_log as debug_log


def _get_lock_dir() -> Path:
    """獲取 lock 文件所在目錄，跨平台"""
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "mcp-feedback-scope"


LOCK_FILE_PATH = _get_lock_dir() / "hub.lock"


@dataclass
class HubInfo:
    """Hub 實例資訊"""
    pid: int
    port: int
    host: str = "127.0.0.1"
    token: str = ""
    started_at: float = field(default_factory=time.time)

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"


def write_hub_lock(port: int, host: str = "127.0.0.1") -> str:
    """
    寫入 Hub lock 文件，返回生成的認證 token。

    Args:
        port: Hub 監聽的端口
        host: Hub 監聽的地址

    Returns:
        生成的認證 token
    """
    token = secrets.token_urlsafe(32)
    lock_data = {
        "pid": os.getpid(),
        "port": port,
        "host": host,
        "token": token,
        "started_at": time.time(),
    }

    lock_dir = LOCK_FILE_PATH.parent
    lock_dir.mkdir(parents=True, exist_ok=True)

    # 原子寫入：先寫臨時文件再重命名
    tmp_path = LOCK_FILE_PATH.with_suffix(".tmp")
    try:
        tmp_path.write_text(json.dumps(lock_data, indent=2), encoding="utf-8")
        # Windows 不支持原子 rename 如果目標已存在，需要先刪除
        if LOCK_FILE_PATH.exists():
            LOCK_FILE_PATH.unlink()
        tmp_path.rename(LOCK_FILE_PATH)
        debug_log(f"Hub lock 已寫入: port={port}, pid={os.getpid()}")
    except Exception as e:
        debug_log(f"寫入 Hub lock 失敗: {e}")
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        raise

    return token


def remove_hub_lock():
    """移除 Hub lock 文件"""
    try:
        if LOCK_FILE_PATH.exists():
            # 只有自己的進程才能移除
            data = _read_lock_file()
            if data and data.get("pid") == os.getpid():
                LOCK_FILE_PATH.unlink(missing_ok=True)
                debug_log("Hub lock 已移除")
            else:
                debug_log("Hub lock 不屬於當前進程，不移除")
    except Exception as e:
        debug_log(f"移除 Hub lock 失敗: {e}")


def _read_lock_file() -> dict | None:
    """讀取 lock 文件內容"""
    try:
        if not LOCK_FILE_PATH.exists():
            return None
        content = LOCK_FILE_PATH.read_text(encoding="utf-8")
        return json.loads(content)
    except (json.JSONDecodeError, OSError) as e:
        debug_log(f"讀取 lock 文件失敗: {e}")
        return None


def _is_process_alive(pid: int) -> bool:
    """檢查指定 PID 的進程是否存活"""
    try:
        return psutil.pid_exists(pid)
    except Exception:
        return False


def _health_check(url: str, token: str, timeout: float = 3.0) -> bool:
    """透過 HTTP 健康檢查驗證 Hub 是否可達"""
    import urllib.request
    import urllib.error

    try:
        req = urllib.request.Request(
            f"{url}/api/health",
            headers={"X-Hub-Token": token},
        )
        resp = urllib.request.urlopen(req, timeout=timeout)
        if resp.status == 200:
            data = json.loads(resp.read().decode())
            return data.get("status") == "ok"
    except (urllib.error.URLError, OSError, json.JSONDecodeError, TimeoutError):
        pass
    return False


def discover_hub() -> HubInfo | None:
    """
    發現已運行的 Hub 實例。

    檢查順序：
    1. 讀取 lock 文件
    2. 驗證進程是否存活
    3. HTTP 健康檢查

    Returns:
        HubInfo 如果找到可用的 Hub，否則 None
    """
    data = _read_lock_file()
    if not data:
        debug_log("沒有找到 Hub lock 文件")
        return None

    pid = data.get("pid", 0)
    port = data.get("port", 0)
    host = data.get("host", "127.0.0.1")
    token = data.get("token", "")
    started_at = data.get("started_at", 0)

    # 不發現自己
    if pid == os.getpid():
        debug_log("Lock 文件屬於當前進程，跳過")
        return None

    # 檢查進程是否存活
    if not _is_process_alive(pid):
        debug_log(f"Hub 進程 {pid} 已不存在，清理過期 lock")
        _cleanup_stale_lock()
        return None

    # HTTP 健康檢查
    hub_url = f"http://{host}:{port}"
    if not _health_check(hub_url, token):
        debug_log(f"Hub {hub_url} 健康檢查失敗")
        return None

    debug_log(f"發現可用的 Hub: pid={pid}, url={hub_url}")
    return HubInfo(
        pid=pid,
        port=port,
        host=host,
        token=token,
        started_at=started_at,
    )


def _cleanup_stale_lock():
    """清理過期的 lock 文件"""
    try:
        LOCK_FILE_PATH.unlink(missing_ok=True)
        debug_log("已清理過期的 Hub lock 文件")
    except Exception as e:
        debug_log(f"清理過期 lock 文件失敗: {e}")
