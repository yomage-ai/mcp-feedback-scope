"""
Hub 模組 - 跨進程會話共享

提供 Hub 發現、客戶端註冊和回饋輪詢功能，
讓多個 MCP 進程共享同一個 Web Hub 實例。
"""

from .hub_client import HubClient
from .hub_discovery import HubInfo, discover_hub, write_hub_lock, remove_hub_lock

__all__ = [
    "HubClient",
    "HubInfo",
    "discover_hub",
    "write_hub_lock",
    "remove_hub_lock",
]
