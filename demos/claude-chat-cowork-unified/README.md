# Chat 还是 Cowork：按文档触发做路由

本地脚本。给定任务特征和组织开关，输出留在 chat、升格到云会话，或需要本机链接。

不调用 Claude，不登录 Enterprise，不读密钥，也不访问网络。判决按 2026-10-31 读到的四页写成，官方路由器若用了别的信号，这里会错。

```bash
python3 demos/claude-chat-cowork-unified/run_demo.py
```

通过时最后一行是 `result=pass`。

`cases.json` 的 `base` 是一项已经打开统一体验的 Enterprise 组织：Chat 和 Cloud code execution and file creation 都开着，出站为关。每条样例只写自己改动的字段。

| 样例 | 在看什么 |
| --- | --- |
| `qa` | 纯问答，留在 chat |
| `deck` | 要交回文件，升格云 |
| `code-no-net` | 要跑代码，不访问网络。出站关着也升格 |
| `code-egress-off` | 要跑代码且要联网。仍升格，备注 `egress_off` |
| `local-mcp` | 要本地 MCP，桌面开着，走本机链接 |
| `local-mcp-offline` | 同上，桌面关着 |
| `local-mcp-mdm` | `isLocalDevMcpEnabled` 关掉，任务又只要本地 MCP |
| `code-and-local-mcp` | 代码和本地 MCP 都要。本地进程不在云会话里，升格覆盖不了 |
| `zdr` / `hipaa` / `cmek` | 这三项配置下统一开关不可用 |
| `unified-off` | 现有组织还没开 |
| `no-cloud-exec` / `no-chat` | 两项能力缺一 |
| `pro-waiting` | Pro 还没分到新界面。任务即使要文件，选择器还在 |
| `pro-deck` | Pro 已经是统一界面，要文件就升格 |
| `ultra-qa` | 架构文和用户文把 Ultra 和 Pro、Max 写在一起 |
| `computer-use-pro` | 用户文把 computer use 写成 Pro、Max、Ultra 的 beta |
| `computer-use-enterprise` | Enterprise 这页没有写 computer use |
| `web-folder-no-remote` | 从 web 要本机文件夹，Remote control 关 |
| `desktop-folder` | 从桌面要文件夹。Remote control 关着也不挡桌面入口 |
| `team-off` / `team-files` | Team 是 beta，看开关开了没有 |

Max 不单列样例。脚本里用同一份「要文件」任务对过 Pro 和 Max，路由相同。Team 的能力项前提写在 Enterprise 管理文里，脚本没有套到 Team 上。

来源：

- https://claude.com/resources/articles/unified-claude-enterprise
- https://support.claude.com/en/articles/17444462-set-up-and-manage-the-new-unified-claude-experience-for-your-enterprise-organization
- https://support.claude.com/en/articles/14479288-claude-cowork-architecture-overview
- https://support.claude.com/en/articles/16761823-claude-cowork-and-chat-are-one-claude
