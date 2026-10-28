---
title: 连上 MCP，还不等于这把工具能调
date: 2026-10-21 08:30:00
updated: 2026-10-21 08:30:00
categories:
  - AI Agent
tags:
  - MCP
  - AI Agent
  - 安全
  - 权限
description: Safeguard 在 2026-10-17 宣布，MCP 工具执行前要过租户、组织、角色和 Agent。列表和调用读同一份启用集；新租户读开写关。工具开关和 Guard 策略是两套机制。
---

安全助手已经能回答「这个项目有哪些严重漏洞」。下一句若是「把这条 finding 关掉，再开一个修复 PR」，难的就不在句子，而在这把工具此刻准不准跑。Safeguard 在 2026-10-17 发了一篇短文，10 月 18 日更新：接到安全平台很容易，接上之后允许做什么才难。厂商写明，每次 MCP 工具调用在执行前检查租户、组织、角色和 Agent 四层；新租户读工具开着，写工具关着。连上服务器，只说明这条连接通了。

<!-- more -->

## 会话落在谁的租户里

[MCP 集成文档](https://docs.safeguard.sh/docs/mcp)写，远程服务器在 `https://mcp.safeguard.sh/mcp`，没有要安装的包，也不读本机的 `SAFEGUARD_API_KEY`。推荐走 OAuth：助手把人带到登录页，核对应用名和授权码将要送到的主机，再点 Authorize access。另一种是 MCP key，放在 `Authorization: Bearer sg_sk_...`。密钥只显示一次，并且以创建它的那个成员的身份作用于整个工作区。厂商写明，撤销、创建者账号关闭，或工作区关掉 API key 访问之后，一分钟内失效。

[Agents 文档](https://docs.safeguard.sh/docs/agents)写，已有账号时，Agent 以登录用户的身份行动，落在该用户的租户里。会话带着租户、组织和产品范围。未登录的注册端点是 `https://mcp.safeguard.sh/mcp/signup`，厂商写明只有 `safeguard_signup`、`safeguard_verify_email`、`safeguard_resend_verification`。这三把只属于这条端点。

Agents 文档写的是会话以登录用户的身份落在租户里。10 月 17 日的博客另外写了第四层：某一个 Agent 允许做什么，和把它接上的那个人分开记账。我在这五页里没有看到四层检查的配置字段，也没有看到四层拒绝的报文样例。行为声明在博客，启用名单在工具开关页。缺的不拿另一页补。

## 四层都通过，工具才执行

[分层访问那篇](https://safeguard.sh/resources/blog/layered-access-control-for-mcp-tools)把执行前的检查写成四层，一层不通过就停：

1. 租户：整个账号允许什么。
2. 组织：一个业务单元或团队允许什么。
3. 角色：这个人的角色允许什么。
4. Agent：这一个 Agent 允许什么。

拒绝要指出挡住的那一层，用来结束「到底是角色还是组织策略」的猜测。放宽访问要先确认，并且可以一步撤回。每次变更进入访问历史，可以筛选，可以查看某个人或某个 Agent 的有效权限，可以导出 CSV。博客没有列出 CSV 的列，也没有给出确认按钮的文案。已有租户保留它们已经打开的写工具。

```mermaid
flowchart TD
  src[同一份启用集合] --> list[tools/list 只广告已启用的工具]
  src --> call[tools/call 先看工具在不在集合里]
  call --> t{租户允许}
  t -->|否| bt[拒绝并点名 tenant]
  t -->|是| o{组织允许}
  o -->|否| bo[拒绝并点名 organization]
  o -->|是| r{角色允许}
  r -->|否| br[拒绝并点名 role]
  r -->|是| a{这个 Agent 允许}
  a -->|否| ba[拒绝并点名 agent]
  a -->|是| run[才执行工具]
```

图上的启用集合来自工具开关。`tools/list` 和 `tools/call` 都读它。组织、角色和 Agent 再决定这一次调用过不过。解析失败时退回那一小套默认只读，故障不能把名单变宽。

## 看得见和调得动，来自同一份名单

[工具开关文档](https://docs.safeguard.sh/docs/mcp/tool-gating)写，服务器注册了数百个工具。每个工具有一条 `mcp:tool:<tool_name>` 功能开关，按租户解析启用集合。这个集合用两次：发现（`tools/list`）只广告已启用的工具，执行（`tools/call`）拒绝未启用的工具。文档写的是两边同源：看不见不能调的，也调不了看不见的。未启用的工具不会以一条「已禁用」出现在列表里。

设计原则写，解析范围是租户、组织和产品上下文，一个工作区不影响另一个。FAQ 写，开关不按单个用户分；同一上下文里的人看到同一份启用集。会话可以用 `safeguard_switch_organization` 或 `safeguard_switch_product` 换上下文。10 月 17 日的博客又把组织写成调用前的一层拒绝。两页都没写明，这是不是同一个配置。演示分成两步：先取启用集合，再问组织、角色、Agent。

拒绝不拆连接。文档给的是普通工具结果，带错误标记：

```json
{
  "content": [
    {
      "type": "text",
      "text": "Tool \"safeguard_scan_manifest\" is not enabled for this tenant. An administrator can enable it via MCP tool feature flags."
    }
  ],
  "isError": true
}
```

这是工具开关这一层的句子。四层拒绝会点名层次，报文长什么样，这五页里没有。

新工作区默认六把只读工具。文档写明，整套都可以一次性批准，里面没有创建、修改、删除，也不碰凭证：

| 工具 | 文档中的用途 |
| --- | --- |
| `safeguard_list_products` | 列出租户里的产品 |
| `safeguard_list_projects` | 列出当前组织或产品下的项目 |
| `safeguard_get_project` | 读取一个项目，含组件和漏洞 |
| `safeguard_list_vulnerabilities` | 按严重级别、生态、CVSS 或利用状态过滤漏洞 |
| `safeguard_get_vulnerability` | 读取一条 CVE 的分数和修复说明 |
| `safeguard_list_findings` | 列出 SBOM 或项目里的 finding |

其余工具默认关，包括加集成和发起扫描。管理员在 Feature Flags 里按名字或 `mcp` 分类打开。覆盖掉平台默认之后，Reset to Defaults 会去掉覆盖，重新继承平台默认。厂商写，启用集大约按一分钟量级复查；不少客户端还会缓存 `tools/list`。开关刚打开却看不见，先重连。这一分钟不是我测的。

默认集合收窄之前的工作区，文档点名仍可能开着 `safeguard_add_integration`、`safeguard_scan_repository`、`safeguard_get_current_context`、`safeguard_switch_organization`。博客也写，老租户保留已经打开的写工具。实际名单以功能开关为准。

Agents 文档把新工作区说成「覆盖上手回路的一小套」，合并 PR、购买套餐是刻意的 opt-in，并写明列表和调用走同一套开关。它没有重复上面六行。同页回路里的 `safeguard_merge_pull_request`、`safeguard_add_integration` 是能力名单，不是新租户的默认启用集。

解析完不成时，例如短暂故障，服务器退回那一小套默认集。服务器自己不存这张表，向认证服务现查，会话内短缓存。故障不能把助手能做的事变多。

## 工具开关和 Guard 各记一笔账

10 月 18 日的[另一篇](https://safeguard.sh/resources/blog/how-mcp-guardrail-works)把两套机制分开。工具开关管 Safeguard 自己的 MCP 服务器：这个工作区能看见哪些工具，粒度是租户，不是用户。Guard 是另一个产品，对更一般的 MCP 流量做策略，包括你自己建的或代为运营的服务器和 Agent。策略放在 Safeguard 工作区里，不是仓库里的文件。Guard 拉取已保存的默认策略。

一条规则可以匹配方法（例如 `tools/call`）、带通配符的工具名、Agent ID，然后落到 allow、deny 或 monitor。deny 把理由返回调用方。monitor 放行并打标。优先级从高到低，先匹配先生效。没有规则命中时，厂商写明标成待监察，既不静默放行，也不静默拦截。规则还可以带输入过滤、输出过滤和速率限制。每次判定写入只追加的审计，带上命中的规则和 Guard 给出的分数。分数的算法，这篇没有写。

Guard Proxy 是自建的反向代理，Agent 指到代理，JSON-RPC 先判定再转发，适合改不了上游代码的服务器。Guard SDK 要嵌进自己的进程。MCP 文档写明 SDK 还没发布，PyPI、npm 和 Go 模块代理上都没有可安装的包。自称是它的包，按不可信处理。

三套名字容易拌在一起。在 Feature Flags 关掉一把工具，不会创建或修改一条 Guard 策略。Guard 策略也不改 Safeguard 的功能开关。Guard 策略也不是 Guardrails and Enforcement 那套给 CI、registry 和准入用的 YAML，那套的效果是 BLOCK、WARN、AUTO_FIX。应用里的 Guard 运行时拦截点，护栏文档标的是 early access。工具开关 FAQ 仍写：要按 Agent 细分，用 Guard。10 月 17 日的博客则写，调用本身还要过角色和 Agent，拒绝会点名。我的读法是三笔账：开关决定这把工具在这个工作区是否存在；四层决定这一次调用哪一个身份可以走；Guard 决定实时流量上的 allow、deny、monitor。五页没有写明四层检查是不是 Guard 规则的一种视图。写明之前，接线时按这三笔账分开查。

[MCP 文档的 FAQ](https://docs.safeguard.sh/docs/mcp)有一句范围：只把助手接到 Safeguard、只用功能开关，大多数团队这时还不需要 Guard。前面还有别人的服务器时，Guard 才是那一层。

## 四类问题，四张判定

接到高风险 MCP 时，先分清你在回答哪一个问题。下面只标分界。付款队列、SDK 护栏和操作系统沙箱各自有自己的实现，这里不复述。

| 问题 | 判定落在哪 | 和这篇的关系 |
| --- | --- | --- |
| 这把工具，这个租户、组织、角色、这个 Agent 能不能看见并调用 | 执行前的授权；列表和调用共用启用集 | 这篇要写的 |
| 对话里点过确认，钱出去了没有 | 付款请求和批准分成两段 | 聊过不等于已汇出 |
| 这一次调用的输入或输出要不要被拦住 | SDK 的工具护栏 | 护栏看着这一次调用，不负责工作区启用了哪些工具 |
| 进程起来之后还能碰什么文件、连什么地址 | 操作系统或虚拟机隔离 | 挡住的是系统调用，不是 `tools/call` 上的角色 |

沙箱仍然要有。它回答不了「审计员这个角色能不能调用 `safeguard_scan_repository`」。付款确认也回答不了。

## 接线时按这个顺序查

第一，对一下 `tools/list` 和真正能调用的名字。两边都应来自同一份启用集。列表里没有的，调用停在这一层。列表里有的，才进入组织、角色和 Agent。客户端若还显示旧列表，先重连。

第二，把人的角色和 Agent 的身份分开记。同一个人可以接一个只做分诊的 Agent，再接一个能合并 PR 的 Agent。角色通过，只说明这个人过了；两个 Agent 仍要各自过第四层。

第三，新租户保持读开、写关。打开写之前先确认，记进访问历史，并确认能一步撤回。博客点名的危险写包括关掉 finding、改策略、开 pull request。`safeguard_scan_repository` 和 `safeguard_merge_pull_request` 不在六把默认只读里。老租户以功能开关和访问历史为准。

第四，拒绝要带层名。层名告诉值班的人，挡住的是租户、组织、角色还是 Agent。Agents 文档写，`Tool "…" is not enabled for this tenant` 应当显示给用户，不要当成暂时错误去重试。那句对应工具开关。四层拒绝的字段，博客只说会点名，没有 schema。

## 离线模型：同一套决定跑两次

`demos/mcp-layered-access/run_demo.py` 不联网，不调用 Safeguard，也不做 OAuth。六把只读的名字来自工具开关文档。组织、角色、Agent 的允许集，确认用的布尔参数，以及 `layer=` 这行字，都是这份脚本自己的模型。四层拒绝的报文字段和访问历史 CSV 的列，这五页没有给到能照着填的程度。上面的 `isError` 样例只覆盖「本租户未启用」。

启用集只有一个出口。解析抛错时，出口换成默认只读，后面的判断不再看见那份更宽的载荷：

```python
def enabled_tools(tenant: Tenant) -> frozenset[str]:
    """Same set for discovery and execution. Failure falls back to reads."""
    try:
        resolved = tenant.resolve()
    except ResolutionError:
        return DEFAULT_READS
    return resolved
```

一次调用只保留最先挡住的那一层。租户里没有这把工具时，不再继续报告「角色也不许」：

```python
def authorize(who: Principal, tool: str) -> Decision:
    """First failing layer wins, so the refusal names that layer only."""
    if tool not in enabled_tools(who.tenant):
        return Decision(False, "tenant")
    if tool not in who.org_allows:
        return Decision(False, "organization")
    if tool not in who.role_allows:
        return Decision(False, "role")
    if tool not in who.agent_allows:
        return Decision(False, "agent")
    return Decision(True, "allow")
```

通过时层名记为 `allow`，只表示四层都过了，博客的四层名字里没有这个词。组织、角色或 Agent 没有配置时，允许集为空，拒绝仍点那一层。这是脚本自己的失败关闭。

Guard 在脚本里是另一张表。`triage-bot` 调 `safeguard_list_findings` 时，身份层是 `allow`，Guard 是 `deny`，工具仍在列表里。从启用集拿掉之后，列表里没有它，规则条数不变。厂商文档里的工具名可以带通配符；脚本只做精确比较，Agent 只认 `*` 或一个 id。

```bash
python3 demos/mcp-layered-access/run_demo.py
```

我连续执行了两次，标准输出一致。和四层直接相关的几行是：

```text
fresh call tool=safeguard_list_findings org=security role=maintainer agent=triage-bot layer=allow
fresh call tool=safeguard_scan_repository org=security role=maintainer agent=triage-bot layer=tenant
legacy call tool=safeguard_scan_repository org=interns role=maintainer agent=release-bot layer=organization
legacy call tool=safeguard_scan_repository org=platform role=auditor agent=release-bot layer=role
legacy call tool=safeguard_scan_repository org=platform role=maintainer agent=triage-bot layer=agent
legacy call tool=safeguard_scan_repository org=platform role=maintainer agent=release-bot layer=allow
resolve fallback=default_reads payload_has_scan=True visible=False call_layer=tenant
widen confirmed=false result=confirmation_required listed=False history=0
widen confirmed=true result=widened listed=True history=1
guard tool=safeguard_list_findings agent=triage-bot identity=allow action=deny
guard rules_before=2 rules_after_gating_off=2 listed_after_off=False action_still=deny
checks passed
```

在 `fresh` 上，脚本里的维护者角色允许扫描，调用仍停在 `tenant`，因为新租户的启用集里没有这把写工具。`legacy` 保留了已经打开的扫描，列表里看得到，分诊 Agent 仍然在 `agent` 层被拒，发布 Agent 可以通过。解析失败的那一户，载荷里带了扫描，退回默认集之后 `visible=False`。没有确认的放宽不改列表。最后一行是 `checks passed`。

脚本证明的是这些断言会互相卡住：列表和调用一旦分叉，或者解析失败时改成全开，检查就不会走到最后一行。它不证明厂商服务器的内部实现就是这些函数。

## 结语

模型会提出「关掉这条 finding」。接线的人要能回答四件事：这把工具在这个工作区存不存在，这个人的角色许不许，这个 Agent 自己许不许，拒绝时是哪一层说了不。答不上来的那个 Agent，按厂商博客的建议，先只读。

---

## 扩展阅读

- [Who Can Your AI Agent Call? Layered Access Control for MCP Tools](https://safeguard.sh/resources/blog/layered-access-control-for-mcp-tools)（2026-10-17 发布，2026-10-18 更新）
- [How MCP Guardrail works: tool gating and Guard policies](https://safeguard.sh/resources/blog/how-mcp-guardrail-works)（2026-10-18）
- [Tool availability and gating](https://docs.safeguard.sh/docs/mcp/tool-gating)
- [MCP Integrations](https://docs.safeguard.sh/docs/mcp)
- [Agents and LLMs](https://docs.safeguard.sh/docs/agents)

## 讨论

你现在接在安全 MCP 上的 Agent，哪一个写操作你说不出是被租户、组织、角色还是 Agent 这一层挡住的？
