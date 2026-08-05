# API 参考

后端为 FastAPI，完整交互式文档见 `/docs`。以下为常用接口速查。

- Base URL：`http://127.0.0.1:8900`
- 聊天为 SSE 流式：`data: {"delta":"..."}`

## 会话与聊天

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/conversations` | 会话列表 |
| POST | `/api/conversations` | 新建会话 |
| DELETE | `/api/conversations/{cid}` | 删除会话 |
| GET | `/api/conversations/{cid}/messages` | 获取消息 |
| GET/POST | `/api/conversations/{cid}/tools` | 读取/设置会话工具（知识库/Skills/MCP） |
| POST | `/api/chat` | **对话**（SSE 流式），body 含 `conversation_id, content, agent_enabled, thinking, use_kb, use_skills, use_mcp` |

## 供应商与模型

| 方法 | 路径 | 说明 |
|------|------|------|
| GET/POST | `/api/providers` | 供应商列表/新增 |
| DELETE | `/api/providers/{pid}` | 删除 |
| POST | `/api/providers/test` | 测试连接 |
| POST | `/api/providers/models` | 一键拉取模型列表 |

## Agent & 搜索

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/tools` | 可用工具列表 |
| POST | `/api/search` | 自建搜索（Bing/百度/DDG） |

## 知识库

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/kb/docs` | 文档列表 |
| POST | `/api/kb/upload` | 上传文档（multipart，任意文本格式） |
| DELETE | `/api/kb/docs/{doc_id}` | 删除文档 |
| POST | `/api/kb/search` | 检索（返回 doc_id/doc_name/content/score/chunks 等元信息） |

## 定时任务

| 方法 | 路径 | 说明 |
|------|------|------|
| GET/POST | `/api/cron/jobs` | 任务列表/新增 |
| PUT/DELETE | `/api/cron/jobs/{jid}` | 更新/删除 |
| POST | `/api/cron/jobs/{jid}/run` | 立即执行 |

## 团队 & 专家

| 方法 | 路径 | 说明 |
|------|------|------|
| GET/POST | `/api/team/members` | 成员列表/新增 |
| PUT/DELETE | `/api/team/members/{mid}` | 更新/删除成员 |
| GET | `/api/team/activity` | 活动日志 |
| POST | `/api/team/share` | 共享对话 |
| GET | `/api/experts` | 专家列表（支持分类筛选） |
| POST | `/api/experts/{eid}/apply` | 应用专家到当前会话 |

## 扩展能力

| 方法 | 路径 | 说明 |
|------|------|------|
| GET/POST | `/api/skills` | 技能列表/新增 |
| POST | `/api/skills/{sid}/toggle` | 启用/停用 |
| GET/POST | `/api/mcp/servers` | MCP 服务器 |
| POST | `/api/mcp/test` | MCP 连接测试 |
| GET/POST | `/api/connectors` | 连接器列表/新增 |
| POST | `/api/connectors/test` | 连接器测试 |
| GET | `/api/connectors/{cid}/tables` | 列出数据源表 |

## 工作流

| 方法 | 路径 | 说明 |
|------|------|------|
| GET/POST | `/api/workflows` | 工作流列表/保存 |
| GET/DELETE | `/api/workflows/{wid}` | 详情/删除 |
| POST | `/api/workflows/{wid}/run` | **执行**，body `{"input": {...}}` |
| GET | `/api/workflows/{wid}/executions` | 执行历史 |
| GET | `/api/workflow/templates` | 模板列表 |
| POST | `/api/workflow/templates/{tid}/use` | 从模板创建工作流 |

## 更新

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/update/check` | 检查更新 |
| POST | `/api/update/download` | 下载更新包 |
| GET | `/api/update/status` | 更新状态 |
| GET | `/api/update/history` | 更新历史 |
| POST | `/api/update/apply` | 应用更新 |
| POST | `/api/update/rollback` | 回滚 |

## 设置

| 方法 | 路径 | 说明 |
|------|------|------|
| GET/POST | `/api/settings` | 读取/保存设置 |
| POST | `/api/settings/test-search` | 测试搜索服务 |
| GET | `/api/version` | 版本号 |

## 频道 / 附件

| 方法 | 路径 | 说明 |
|------|------|------|
| GET/POST | `/api/channels` | 频道列表/新增 |
| POST | `/api/channels/{cid}/toggle` | 启停频道 |
| POST | `/api/upload` | 上传附件 |
| POST | `/api/tts` | 语音朗读 |