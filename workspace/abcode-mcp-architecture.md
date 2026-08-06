# ABcode 工具系统架构改进草案

目标：从"固定工具集"升级为"可插拔、可扩展、可记忆"的 Agent 工具架构，对齐成熟产品（Claude Code / OpenAI Operator / Manus）+ 成熟 Agent 开发框架（LangGraph / CrewAI / AutoGen）。

## 0. 成熟 Agent 框架对标（本轮新增）

| 能力设计 | 成熟框架对应组件 | ABcode 现状 |
|---------|----------------|------------|
| 有向图工作流 / 状态机 | LangGraph `StateGraph`（节点+边+分支/回退） | 无，纯顺序调工具 |
| 多 Agent 协作分工 | CrewAI（角色分工）、AutoGen（多 Agent 协商群聊） | 单 Agent 单线程 |
| 反射 / 自我修正 | ReAct 循环、reflector / validator 反馈节点 | 无结构化反思层 |
| 记忆层 | LangChain Memory、AutoGen 会话持久化 + 向量库 | 会话间清零 |
| 工具生态扩展 | LangChain 工具 + MCP 服务器接入 | 固定内置工具 |
| 可观测性 | trace/日志/回放调试 | 无 |

## 1. 三大核心扩展

### 1.1 浏览器自动化（P0）
新增工具控件，突破"只读静态文本"限制：
- `open_url` / `click(selector)` / `fill(selector, value)`
- `screenshot()`（配合视觉）/ `get_dom()`

### 1.2 视觉理解（P0）
引入多模态 `analyze_image(path)`：识别截图、设计稿、图表、验证码。

### 1.3 写权限 shell（P0）
`run_shell` 增加 `write` 模式（沙箱隔离）：改代码、装依赖、跑测试、起服务，用 Docker/cgroup 隔离。

## 2. MCP（Model Context Protocol）支持
工具描述采用 MCP schema，可动态挂载任意能力：
```json
{
  "name": "git_status",
  "description": "查看 git 工作区状态",
  "inputSchema": { "type": "object", "properties": { "path": { "type": "string" } } }
}
```
- `list_tools()` / `register_tool(mcp_schema, handler)`，工具集从"固定"变"可插拔"。

## 3. 长时记忆层（P1）
```json
{ "preferences": { "language": "zh", "tone": "简洁" },
  "memory": [ { "event": "任务失败原因", "lesson": "先搜索再动手，别空转" } ] }
```
每次任务结束写入经验反思，新会话加载，避免重复踩坑。

## 4. 状态/图驱动执行（对齐 LangGraph，P1）
把任务解析成 DAG：节点 = 单步工具调用；边 = 状态转移，支持条件分支、失败重试、回退。
避免"线性顺序调工具"无法处理复杂多步依赖的问题。

## 5. 多 Agent 分工（对齐 CrewAI/AutoGen，P2）
引入"规划者 / 执行者 / 审查者"角色；审查者对执行结果做 validator 反馈，形成 ReAct 闭环，杜绝"反复空转"。

## 6. 任务执行闭环
`规划 → 执行 → 验证 → 反思 → 记忆持久化`，每阶段都调用工具。

## 7. 优先级清单
| 优先级 | 事项 | 收益 |
|-------|------|------|
| P0 | 状态/图驱动工作流 | 复杂任务可控/可回退 |
| P0 | 浏览器自动化 | 可交互网络任务 |
| P0 | 视觉理解 | 读截图/UI |
| P0 | shell 写模式(沙箱) | 真正"做事" |
| P0 | ReAct 行动闭环 | 消除空转 |
| P1 | MCP 协议 | 工具可扩展 |
| P1 | 长时记忆 | 跨会话学习 |
| P2 | 多 Agent 协作 | 复杂任务分工 |