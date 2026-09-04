# github-mcp-server-lite

[English](./README_EN.md) | 中文

一个**零第三方依赖**的 GitHub MCP server。只用 Python 标准库（`urllib`），通过 Personal Access Token 直连 GitHub REST API，提供 24 个工具。

## 为什么会有这个项目

在 Windows + 代理环境下，WorkBuddy / Claude Code 内置的 GitHub 连接器走不通，两条"官方"路也未必可用：

| 方案 | 实测结果 |
| --- | --- |
| GitHub 官方远端 MCP `api.githubcopilot.com/mcp/` | 走连接器时返回 `unauthorized: AuthenticateToken authentication failed`（token 由客户端后端下发，未真正授权）；直连该域名则超时 |
| npm 安装 `@github/github-mcp-server` | npm 官方源超时、国内镜像 SSL 握手失败 |
| 内置连接器 OAuth | 握手失败，GitHub 应用授权页里查不到记录 |

于是就有了这个：不下载任何依赖，直接用标准库实现 MCP 协议，用 PAT 认证，绕开 OAuth 与 npm。

## 特点

- **零依赖**：Python 3.8+ 即可，不需要 `pip install`
- **直连优先、代理回退**：某些代理对 `api.github.com` 的 TLS 握手要 15 秒以上还频繁掉线，而直连只要 1-3 秒。脚本默认直连，失败才回退到环境变量里的代理（实测同一组调用：2 分 25 秒 → 6 秒）
- **24 个工具**：覆盖仓库、文件、分支、提交、Issue、PR、搜索、通知
- **逃生口**：`run_api` 可以调用任意 GitHub REST 端点，没覆盖到的能力也能用

## 安装

### 1. 准备 Token

GitHub → Settings → Developer settings → Personal access tokens → Tokens (classic) → Generate new token (classic)。

建议勾选：`repo`（全部子项）、`workflow`、`gist`、`read:org`。

### 2. 配置 MCP

**WorkBuddy**：用户级配置在 `~/.workbuddy/.mcp.json`（注意文件名前面有点），也可以放在项目根目录的 `.mcp.json` 里只对当前项目生效。

**Claude Code**：`~/.claude.json` 或项目的 `.mcp.json`。

```json
{
  "mcpServers": {
    "github": {
      "command": "python",
      "args": ["/absolute/path/to/github_mcp.py"],
      "env": {
        "GITHUB_TOKEN": "ghp_xxxxxxxxxxxxxxxxxxxx"
      }
    }
  }
}
```

Windows 上 `command` 要写 Python 解释器的绝对路径，路径里的反斜杠需要转义：

```json
"command": "C:\\Users\\you\\.workbuddy\\binaries\\python\\versions\\3.13.12\\python.exe",
"args": ["C:\\Users\\you\\.workbuddy\\mcp-servers\\github_mcp.py"]
```

### 3. 重启宿主程序

MCP 配置只在启动时加载，**必须完全退出再打开**（关窗口不算）。重启后在连接器中信任这个 server。

## 工具列表

| 分类 | 工具 |
| --- | --- |
| 身份 | `whoami` |
| 仓库 | `list_repos`、`get_repo`、`create_repo`、`delete_repo` |
| 文件 | `list_dir`、`get_file`、`create_file`、`delete_file`、`push_files` |
| 分支与提交 | `list_branches`、`create_branch`、`list_commits` |
| Issue | `list_issues`、`create_issue`、`comment_issue`、`close_issue` |
| Pull Request | `list_prs`、`create_pr`、`merge_pr` |
| 搜索与通知 | `search_repos`、`search_code`、`list_notifications` |
| 逃生口 | `run_api`（调用任意 REST 端点） |

## 手动测试

不装 MCP 客户端也能直接验证，往 stdin 灌 JSON-RPC 就行：

```bash
export GITHUB_TOKEN=ghp_xxx
printf '%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"t","version":"1"}}}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"whoami","arguments":{}}}' \
  | python github_mcp.py
```

## 安全提示

- Token 等价于账号密码，**不要提交到仓库**。上面示例里的 `.gitignore` 已经排除了常见敏感文件
- 建议给 token 设过期时间，并按最小权限勾选
- 不用时去 GitHub → Settings → Developer settings → Personal access tokens 点 **Delete** 吊销

## 协议

MCP over stdio，JSON-RPC 2.0，换行分隔。支持 `initialize`、`tools/list`、`tools/call`、`ping`。

## License

MIT — 详见 [LICENSE](./LICENSE)
