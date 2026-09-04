# github-mcp-server-lite

A **zero-dependency** GitHub MCP server. Pure Python standard library (`urllib`) — it talks to the GitHub REST API with a Personal Access Token and exposes 24 tools.

[中文说明](./README.md)

## Why this exists

On Windows behind a proxy, the built-in GitHub connector in WorkBuddy / Claude Code often fails, and the two "official" routes are not always available either:

| Approach | Measured result |
| --- | --- |
| GitHub remote MCP `api.githubcopilot.com/mcp/` | `unauthorized: AuthenticateToken authentication failed` — the token is issued by the client backend and was never really authorized; a direct connection to that host times out |
| `npm install @github/github-mcp-server` | npm registry times out; the China mirror fails the SSL handshake |
| Built-in OAuth connector | Handshake fails, and no matching entry ever appears in GitHub's authorized applications list |

So this project skips both: no downloads, no OAuth. Just the standard library implementing MCP, authenticated with a PAT.

## Features

- **Zero dependencies** — Python 3.8+ is enough, no `pip install`
- **Direct first, proxy fallback** — some proxies need 15+ seconds for the TLS handshake to `api.github.com` and drop connections constantly, while a direct connection takes 1–3 seconds. This server tries direct first and only falls back to the proxy from the environment variables. Measured on the same batch of calls: **2 min 25 s → 6 s**
- **24 tools** — repos, files, branches, commits, issues, pull requests, search, notifications
- **Escape hatch** — `run_api` calls any GitHub REST endpoint, so anything not covered is still reachable

## Install

### 1. Create a token

GitHub → Settings → Developer settings → Personal access tokens → Tokens (classic) → Generate new token (classic).

Recommended scopes: `repo` (all sub-scopes), `workflow`, `gist`, `read:org`.

### 2. Register the MCP server

**WorkBuddy**: user-level config lives at `~/.workbuddy/.mcp.json` (note the leading dot). You can also drop a `.mcp.json` in the project root to scope it to that project.

**Claude Code**: `~/.claude.json`, or a project-level `.mcp.json`.

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

On Windows, `command` must be the absolute path to the interpreter, and backslashes must be escaped:

```json
"command": "C:\\Users\\you\\.workbuddy\\binaries\\python\\versions\\3.13.12\\python.exe",
"args": ["C:\\Users\\you\\.workbuddy\\mcp-servers\\github_mcp.py"]
```

### 3. Restart the host app

MCP configs are loaded at startup, so you must **fully quit and relaunch** (closing the window is not enough). Then trust the server in the connectors panel.

## Tools

| Category | Tools |
| --- | --- |
| Identity | `whoami` |
| Repositories | `list_repos`, `get_repo`, `create_repo`, `delete_repo` |
| Files | `list_dir`, `get_file`, `create_file`, `delete_file`, `push_files` |
| Branches & commits | `list_branches`, `create_branch`, `list_commits` |
| Issues | `list_issues`, `create_issue`, `comment_issue`, `close_issue` |
| Pull requests | `list_prs`, `create_pr`, `merge_pr` |
| Search & notifications | `search_repos`, `search_code`, `list_notifications` |
| Escape hatch | `run_api` (any REST endpoint) |

## Manual test

You can verify it without any MCP client by piping JSON-RPC into stdin:

```bash
export GITHUB_TOKEN=ghp_xxx
printf '%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"t","version":"1"}}}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"whoami","arguments":{}}}' \
  | python github_mcp.py
```

## Security

- A token is equivalent to your password. **Never commit it.** The bundled `.gitignore` excludes common sensitive files
- Prefer setting an expiration date and granting the minimum scopes you need
- Revoke it at GitHub → Settings → Developer settings → Personal access tokens when you are done

## Protocol

MCP over stdio, JSON-RPC 2.0, newline-delimited. Supports `initialize`, `tools/list`, `tools/call`, and `ping`.

## License

MIT — see [LICENSE](./LICENSE).
