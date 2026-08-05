# 配置说明

## 供应商（模型）配置

所有模型服务都通过 **OpenAI 兼容** 接口接入，只需三个字段：

| 字段 | 示例 | 说明 |
|------|------|------|
| 名称 | `DeepSeek` | 显示名 |
| Base URL | `https://api.deepseek.com` | 兼容 `chat/completions` 的地址 |
| API Key | `sk-...` | 鉴权密钥 |

内置 **12+ 预设模板**（一键填入）：DeepSeek / OpenAI / 通义千问(Qwen3.7系列) / Kimi / 智谱 / 硅基流动 / OpenRouter / Ollama / ModelScope / 阿里云 TokenPlan / 阿里云 CodingPlan / 阿里云 MiMo 等。

### 免费模型 / 分级
每个预设标注了**免费模型列表**与**上下文长度**，便于选择。我们持续跟进各大平台免费额度。

### 一键获取模型列表
配置供应商后点「获取模型列表」，自动请求 `/models` 拉取可用模型填入。

### Ollama（本地）
开发测试用 Mock 已内置；本地 Ollama 端点 `http://localhost:11434/v1`。

### 自定义参数
每个供应商可配置 `max_tokens`、`temperature`、`top_p` 等推理参数，以及长上下文覆盖值。

## 联网搜索

内置 **Bing / 百度 / DuckDuckGo** 轻量搜索，直接解析结果页，**无需第三方搜索 API Key**。

如需对接自建搜索服务：

```json
POST /api/settings
{
  "search": {
    "enabled": true,
    "engine": "diy_search",
    "base_url": "http://your-search-service",
    "api_key": ""
  }
}
```

通过「测试搜索」验证连通性。

## 数据目录

| 路径 | 内容 |
|------|------|
| `data/abcode.db` | 全部业务数据（SQLite） |
| `data/kb/` | 知识库索引 |
| `data/uploads/` | 附件 |

删除后重启会自动重建空库。

## 环境变量

| 变量 | 默认 | 说明 |
|------|------|------|
| `PORT` | `8900` | 后端端口 |
| `HOST` | `0.0.0.0` | 监听地址 |
| `FRONTEND_DIR` | `frontend/` | 前端静态目录 |
| `DATA_DIR` | `data/` | 数据目录 |
| `ABCODE_VERSION` | 内置 | 版本号（更新流程使用） |

## 启动脚本

- **`./start.sh`**（macOS/Linux）：建 venv 用系统 python、安装依赖、启动并打开浏览器
- **`start.bat`**（Windows）：优先用 `.venv\Scripts\python.exe`，回退系统 `python`，`start.bat [port]` 可换端口