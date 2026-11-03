# 放行是批准，围栏是碰得到哪里

本地脚本。伪权限决定是 `ask`、`allow`、`deny`。伪围栏是一份工具名单加写入前缀。`allow` 之后，路径不在前缀里，结局是 `blocked_by_isolation`。工具不在名单里，结局是 `host_path`：Bash 沙箱的名单只有 shell，`Write` 仍落在宿主上。

不调用 API，不读密钥，不访问网络，不打开本机的 `~/.ssh`。路径是字符串。夹具不是分类器，也不是 Seatbelt 或 bubblewrap。

Bash 那一档的读不做前缀检查，对应 [Configure the sandboxed Bash tool](https://code.claude.com/docs/en/sandboxing) 的默认：沙箱内命令能读机器上的大部分路径，包括 `~/.ssh`。整进程那一档只挡写到前缀外。运行时默认是否禁止读宿主密钥，[Choose a sandbox environment](https://code.claude.com/docs/en/sandbox-environments) 那一页没有写，夹具不编。

```bash
python3 demos/permission-vs-isolation/run_demo.py
```

通过时最后一行是 `result=pass`。

| 夹具 | 在看什么 |
| --- | --- |
| `allow_outside` | 整进程围栏放行了 Bash 写 `~/.ssh/config`，路径在写入前缀外 |
| `write_on_host` | 来源标成分类器的 allow，工具是 `Write`，围栏只有 Bash |
| `bypass_write` | 来源标成跳过提示的 allow，工具仍是 `Write` |
| `bash_read_ssh` | Bash 读 `~/.ssh/id_rsa`，读取策略是默认的宽 |
| `mcp_host` | MCP 读凭证路径，围栏只有 Bash |
| `write_fenced` | 整进程围栏，`Write` 的目标在前缀外 |
| `deny_first` | 权限 deny，路径其实在项目里 |
| `in_repo` | Bash 写项目内文件 |

`ask_stops` 和 `hook_host` 只在断言里。分类器来源的 allow 不会印成审计通过。
