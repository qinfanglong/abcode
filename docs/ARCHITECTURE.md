# 架构设计

```
┌─────────────────────────────────────────────┐
│              浏览器  / Mac App              │
│   frontend/ 原生 HTML+CSS+JS（零框架）      │
└───────────────────┬─────────────────────────┘
                    │ HTTP / SSE
┌───────────────────▼─────────────────────────┐
│             backend/ FastAPI                │
│                                             │
│  main.py ── 路由 / Agent 循环 / 调度入口      │
│   │                                         │
│   ├─ llm.py       多模型调用(OpenAI兼容)     │
│   ├─ agent.py     工具注册与执行(AutoLoop)   │
│   ├─ rag.py       知识库分块与检索           │
│   ├─ cron.py      定时任务线程               │
│   ├─ workflow.py  工作流执行引擎             │
│   ├─ connector.py 数据连接器查询            │
│   ├─ mcp_client.py MCP 客户端(6协议)       │
│   ├─ skills.py    技能                       │
│   ├─ updater.py   自动更新/回滚             │
│   ├─ search_engine/ 自建搜索(Bing/百度/DDG) │
│   └─ db.py        SQLite 数据层             │
└──────────────┬──────────────────────────────┘
               │
        ┌──────▼──────┐   ┌─────────┐   ┌────────┐
        │ SQLite data │   │ LLM API │   │  MCP   │
        └─────────────┘   └─────────┘   └────────┘
```

## 分层职责

### 前端层
- 原生 JS，无框架、无构建、零外网 CDN 依赖（`marked.min.js` / `highlight.min.js` 本地内置）
- 单页：聊天、设置、扩展能力（团队/专家/MCP/连接器/工作流/更新）、频道
- 通过 `/api/*` 与后端交互；聊天使用 **SSE 流式** 输出

### 后端层（FastAPI）
- 无状态 HTTP 服务，`uvicorn` 启动，跨平台 Python 3.9+
- 会话、供应商、偏好等持久化到 SQLite（`db.py`）
- **Agent 工具调用**：`llm.py` 流式/工具协商 → `agent.py` 执行工具 → 循环直到无工具调用
- **知识库 RAG**：`rag.py` 关键词 TF-IDF 近似检索（纯本地，无需外部向量库）
- **工作流**：`workflow.py` 有向图遍历，16 种节点，分支/聚合/提前终止
- **MCP**：`mcp_client.py` 统一连接管理（stdio/HTTP/SSE/WebSocket/Unix Socket/TCP），异步收发、自动重连
- **数据连接器**：`connector.py` 统一查询 SQLite/MySQL/PostgreSQL/CSV/JSON/HTTP，结果拼装为文本喂给模型
- **自建搜索**：`search_engine/` 直接请求 Bing/百度/DuckDuckGo，解析结果，无需第三方搜索 API Key

### 数据层
- 单文件 SQLite：`data/abcode.db`
- 表（节选）：`conversations`、`messages`、`providers`、`cron_jobs`、`kb_docs`、`workflows`、`connectors`、`mcp_servers`、`team`、`experts`、`settings`、`update_history` 等，启动时自动迁移

## 关键设计决策

| 决策 | 理由 |
|------|------|
| 前端零框架零外网 | 离线可用、部署简单、无供应链风险 |
| 后端 OpenAI 兼容 | 一处适配接入几乎所有模型服务 |
| 关键词检索 RAG | 免向量库/免联网，100% 本地，隐私优先 |
| 数据连接器统一查询 | 把任意数据源转成文本工具，供 Agent/工作流使用 |
| SSE 流式 | 低延迟、实现简单、代理友好 |

## 数据流（一次 Agent 对话）

```
用户输入 ──► /api/chat
          └─► llm.chat(流式, tools) ──► SSE 返回增量
                                │ 模型请求调用工具
                                ▼
                          agent.execute_tool
                   （web_search / fetch_url / 文件 / shell / 连接器 / MCP）
                                │
                                ▼
                       再次调用模型（带工具结果）──► 直到结束 ──► 返回最终回答
```