# MCP Feedback Scope

MCP 交互式反馈服务器，让 AI 在执行过程中暂停并等待用户反馈。支持 Cursor 多会话并发、Web UI 图文交互、连接断开检测。

## 架构

```
Cursor Session 1 ──stdio──> MCP Server 1 ──HTTP──┐
Cursor Session 2 ──stdio──> MCP Server 2 ──HTTP──┤
                                                  ▼
                                       Central Web Server (:5000)
                                            │         │
                                       Web UI     CLI Tool
```

- 每个 Cursor 会话启动独立的 MCP Server 进程（stdio 传输）
- 所有实例共享同一个中央 Web Server（首个 MCP 实例自动启动）
- Session ID 由 Web Server 统一分配（自增），保证跨实例唯一
- Cursor 断开时 MCP Server 自动通知 Web Server 清理会话

## 安装

```bash
cd F:\project\mcp-feedback-scope
uv sync
```

## Cursor 配置

在 Cursor 的 MCP 配置中（`Settings > MCP` 或项目 `.cursor/mcp.json`）添加：

**方式 A — 使用 uv（推荐，无需全局安装）**

```json
{
  "mcpServers": {
    "mcp-feedback-scope": {
      "command": "uv",
      "args": [
        "run",
        "--directory",
        "F:\\project\\mcp-feedback-scope",
        "python",
        "-m",
        "mcp_feedback_scope"
      ],
      "timeout": 3602,
      "autoApprove": ["interactive_feedback", "list_sessions"]
    }
  }
}
```

**方式 B — 使用全局 python**

先安装包：`pip install -e F:\project\mcp-feedback-scope`

```json
{
  "mcpServers": {
    "mcp-feedback-scope": {
      "command": "python",
      "args": ["-m", "mcp_feedback_scope"],
      "timeout": 3602,
      "autoApprove": ["interactive_feedback", "list_sessions"]
    }
  }
}
```

> `timeout` 设为 3602 是因为 `interactive_feedback` 默认等待 3600 秒，留 2 秒余量避免 Cursor 先超时。

## MCP 工具

### interactive_feedback

请求用户反馈，阻塞直到用户响应或超时。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| summary | str | 是 | AI 工作汇报，支持完整 Markdown 语法 |
| session_title | str | 否 | 会话显示名称 |
| images | list[str] | 否 | base64 data URL 图片列表 |
| timeout | int | 否 | 等待超时秒数，默认 3600 |

**返回值**: `list[TextContent | ImageContent]` — 用户的文本反馈和可选图片。

### list_sessions

列出所有会话及状态，无需参数。

## Web UI

MCP Server 启动时自动在 `http://127.0.0.1:5000` 启动 Web Server。

功能：
- 多会话管理，左侧边栏实时切换
- Markdown 渲染（标题、列表、粗体、斜体、链接）
- 代码块语法展示 + 一键复制 + 折叠/展开
- 图片双向传递（AI → 用户，用户 → AI）
- 图片上传：文件选择、Ctrl+V 全局粘贴、拖拽上传
- 图片预览与全屏查看
- 连接断开检测与会话状态显示
- WebSocket 实时推送更新
- 对话式历史记录浏览

## CLI 工具

```bash
# 列出所有会话
uv run mcp-feedback-cli list

# 查看待处理请求
uv run mcp-feedback-cli pending <session_id>

# 提交反馈
uv run mcp-feedback-cli respond <request_id> "你的反馈"

# 交互式监听
uv run mcp-feedback-cli watch
```

## 单独启动 Web Server

```bash
uv run mcp-feedback-web
```

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| MCP_WEB_HOST | 127.0.0.1 | Web Server 监听地址 |
| MCP_WEB_PORT | 5000 | Web Server 端口 |

## 会话生命周期

```
active ──[调用 interactive_feedback]──> waiting ──[用户提交]──> active
                                           │
                                    [Cursor 断开]
                                           │
                                           ▼
                                      disconnected
                                    (pending 请求自动取消)
```

## 技术栈

- Python 3.10+
- MCP SDK (FastMCP) — stdio 传输协议
- FastAPI + Uvicorn — 中央 Web Server
- WebSocket — 实时推送
- httpx — MCP Server 与 Web Server 间通信
- Jinja2 — 模板引擎
