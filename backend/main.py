"""ABcode - AI Agent 工具主入口 v0.3.0"""
import json
import os
import sys
import time
import uuid
import random
import string
import mimetypes
from pathlib import Path
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Body, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse, JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import db
import llm
import agent
import rag
import cron as cron_mod
import skills as skills_mod
import swarm as swarm_mod  # 提前初始化 agno（Python3.9 下 agno 模块级 asyncio.Lock 需要主线程事件循环）
import mcp_client
import connector as connector_mod
import updater
import workflow_mod as workflow_mod
import channels as channels_mod
import asr as asr_mod

app = FastAPI(title="ABcode", version=updater.VERSION)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# PyInstaller 支持：运行时文件在 sys._MEIPASS 中
if getattr(sys, 'frozen', False):
    BASE_DIR = Path(sys._MEIPASS)
    # frozen 模式下把 stdout/stderr 写入 exe 旁的日志文件（-w 无控制台时错误可查）
    try:
        _log_dir = Path(sys.executable).parent / "data"
        _log_dir.mkdir(parents=True, exist_ok=True)
        _log_file = open(_log_dir / "abcode.log", "a", encoding="utf-8", buffering=1)
        sys.stdout = _log_file
        sys.stderr = _log_file
    except Exception:
        pass
else:
    BASE_DIR = Path(__file__).parent.parent

FRONTEND_DIR = Path(os.environ.get("ABCODE_FRONTEND", BASE_DIR / "frontend"))
# 上传目录：frozen 模式放 exe 旁 data/uploads（可持久），源码模式在仓库根 data/uploads
if getattr(sys, 'frozen', False):
    UPLOAD_DIR = Path(os.environ.get("ABCODE_UPLOADS", Path(sys.executable).parent / "data" / "uploads"))
else:
    UPLOAD_DIR = Path(os.environ.get("ABCODE_UPLOADS", BASE_DIR / "data" / "uploads"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


@app.on_event("startup")
def startup():
    db.init_db()
    rag.init_kb()
    cron_mod.init_cron()
    skills_mod.init_builtins()
    connector_mod.init_builtins()
    db.init_channels_table()
    db.init_channel_qr_codes_table()
    db.channel_msg_table()
    db.init_workflows_table()
    # 初始化内置智能体
    from agent_runtime import init_builtin_agents
    init_builtin_agents()
    app.state.scheduler = cron_mod.start_scheduler(run_cron_job)
    
    # 启动自动更新检查（每24小时检查一次）
    settings = db.get_all_settings()
    if settings.get("auto_update_enabled", "true").lower() == "true":
        interval = int(settings.get("auto_update_interval", "24"))
        updater.start_auto_check(interval)

    # 启动频道运行时（钉钉 Stream、Telegram 长轮询等）
    try:
        channels_mod.start_dingtalk_runtime()
    except Exception as e:
        print(f"[channel] 钉钉频道运行时启动异常: {e}")
    try:
        channels_mod.start_telegram_runtime()
    except Exception as e:
        print(f"[channel] Telegram 频道运行时启动异常: {e}")
    try:
        channels_mod.start_feishu_runtime()
    except Exception as e:
        print(f"[channel] 飞书频道运行时启动异常: {e}")
    try:
        channels_mod.start_wecom_runtime()
    except Exception as e:
        print(f"[channel] 企业微信频道运行时启动异常: {e}")
    try:
        channels_mod.start_discord_runtime()
    except Exception as e:
        print(f"[channel] Discord 频道运行时启动异常: {e}")
    try:
        channels_mod.start_onebot_runtime()
    except Exception as e:
        print(f"[channel] OneBot 频道运行时启动异常: {e}")
    try:
        channels_mod.start_slack_runtime()
    except Exception as e:
        print(f"[channel] Slack 频道运行时启动异常: {e}")
    try:
        channels_mod.start_matrix_runtime()
    except Exception as e:
        print(f"[channel] Matrix 频道运行时启动异常: {e}")
    try:
        channels_mod.start_mqtt_runtime()
    except Exception as e:
        print(f"[channel] MQTT 频道运行时启动异常: {e}")
    try:
        channels_mod.start_qq_runtime()
    except Exception as e:
        print(f"[channel] QQ 频道运行时启动异常: {e}")
    try:
        channels_mod.start_mattermost_runtime()
    except Exception as e:
        print(f"[channel] Mattermost 频道运行时启动异常: {e}")


def run_cron_job(job):
    """定时任务执行：调用模型，结果写入会话"""
    from time_utils import get_current_time_str
    providers = db.list_providers()
    if not providers:
        return "无可用供应商"
    provider = next((p for p in providers if p["id"] == job["provider_id"]), None)
    if not provider:
        provider = next((p for p in providers if p["enabled"]), providers[0])
    model = job["model"] or provider.get("default_model", "") or (provider["models"][0] if provider.get("models") else "")
    if not model:
        return "未配置模型"
    messages = [{"role": "system", "content": f"你是 ABcode，执行定时任务。当前时间：{get_current_time_str()}"},
                {"role": "user", "content": job["prompt"]}]
    parts = []
    for evt in llm.stream_chat(provider, model, messages, tools=None):
        if evt.get("type") == "text":
            parts.append(evt["content"])
    text = "".join(parts)
    conv_id = job["conv_id"]
    if not conv_id:
        conv_id = db.create_conversation(f"[定时] {job['name']}", model)
        cron_mod.update_job(job["id"], conv_id=conv_id)
    db.add_message(conv_id, "user", f"⏰ 定时任务「{job['name']}」执行中\n\n任务内容: {job['prompt']}")
    db.add_message(conv_id, "assistant", text)
    return text[:100]


# ================= 会话 =================
class ConvCreate(BaseModel):
    title: str = "新对话"
    model: str = ""


@app.get("/api/conversations")
def api_list_convs():
    return db.list_conversations()


@app.post("/api/conversations")
def api_create_conv(body: ConvCreate):
    cid = db.create_conversation(body.title, body.model)
    return {"id": cid, "title": body.title}


@app.delete("/api/conversations/{cid}")
def api_delete_conv(cid: str):
    db.delete_conversation(cid)
    return {"ok": True}


@app.get("/api/conversations/{cid}/messages")
def api_list_messages(cid: str):
    return db.list_messages(cid)


# ================= 供应商 =================
class ProviderBody(BaseModel):
    id: str = ""
    name: str
    base_url: str
    api_key: str = ""
    models: list = []
    default_model: str = ""
    enabled: bool = True
    max_context: int = 0


@app.get("/api/providers")
def api_list_providers():
    return db.list_providers()


@app.post("/api/providers")
def api_save_provider(body: ProviderBody):
    pid = body.id or f"p{int(time.time()*1000)}"
    db.upsert_provider({
        "id": pid, "name": body.name, "base_url": body.base_url,
        "api_key": body.api_key, "models": body.models,
        "default_model": body.default_model, "enabled": body.enabled,
        "max_context": body.max_context,
    })
    return {"id": pid}


@app.delete("/api/providers/{pid}")
def api_delete_provider(pid: str):
    db.delete_provider(pid)
    return {"ok": True}


@app.post("/api/providers/test")
def api_test_provider(body: ProviderBody):
    model = body.default_model or (body.models[0] if body.models else "")
    p = {"id": body.id, "name": body.name, "base_url": body.base_url,
         "api_key": body.api_key, "models": body.models, "default_model": body.default_model}
    ok, msg = llm.test_provider(p, model)
    return {"ok": ok, "msg": msg}


@app.post("/api/providers/models")
def api_fetch_models(body: dict):
    """一键获取供应商模型列表"""
    import httpx
    base_url = body.get("base_url", "").rstrip("/")
    api_key = body.get("api_key", "")
    if not base_url:
        return {"ok": False, "msg": "缺少 Base URL", "models": []}

    # OpenCode Zen 特殊处理：使用硬编码列表，准确区分免费/付费
    if "opencode.ai" in base_url.lower():
        models = [
            "mimo-v2.5-free", "deepseek-v4-flash-free", "big-pickle",
            "laguna-s-2.1-free", "ling-3.0-flash-free", "longcat-2.0-free",
            "north-mini-code-free", "nemotron-3-ultra-free",
            "qwen3.7-max", "qwen3.7-plus", "qwen3.6-plus", "qwen3.5-plus",
            "claude-sonnet-4.5", "claude-opus-4.5", "claude-haiku-4.5",
            "gpt-5.4-mini", "gpt-5.4-nano", "gpt-5-nano",
            "deepseek-v4-flash", "deepseek-v4-pro",
            "minimax-m3", "minimax-m2.7",
            "glm-5.2", "glm-5.1", "glm-5",
            "kimi-k2.7-code", "kimi-k2.6", "kimi-k3",
        ]
        free_models = [m for m in models if m.endswith("-free") or m == "big-pickle"]
        return {"ok": True, "models": models, "free_models": free_models, "max_context": 200000}

    try:
        # 尝试标准 OpenAI 格式
        url = base_url + "/models"
        headers = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        resp = httpx.get(url, headers=headers, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            models = []
            for m in data.get("data", []):
                mid = m.get("id", "")
                if mid:
                    models.append(mid)
            models.sort()
            # 识别免费模型
            free_keywords = ["free", "flash", "mini", "lite", "tiny", "small"]
            free_models = [m for m in models if any(k in m.lower() for k in free_keywords)]
            # 自动推断上下文长度
            max_context = 0
            for m in data.get("data", []):
                ctx = m.get("context_length", m.get("max_context", 0))
                if ctx and ctx > max_context:
                    max_context = ctx
            return {"ok": True, "models": models, "free_models": free_models, "max_context": max_context}
        
        # 尝试 Ollama 格式
        ollama_url = base_url + "/api/tags"
        resp2 = httpx.get(ollama_url, timeout=15)
        if resp2.status_code == 200:
            data2 = resp2.json()
            models = [m.get("name", "") for m in data2.get("models", []) if m.get("name")]
            models.sort()
            return {"ok": True, "models": models, "free_models": models, "max_context": 32000}
        
        # 尝试 ModelScope 格式
        if "modelscope" in base_url.lower():
            models = [
                "Qwen/Qwen3.5-122B-A10B",
                "ZhipuAI/GLM-5",
                "Qwen/Qwen3-8B",
                "deepseek-ai/DeepSeek-V3",
            ]
            return {"ok": True, "models": models, "free_models": models, "max_context": 128000}
        
        # 尝试 OpenCode Zen 格式
        if "opencode.ai" in base_url.lower():
            models = [
                "mimo-v2.5-free", "deepseek-v4-flash-free", "big-pickle",
                "laguna-s-2.1-free", "ling-3.0-flash-free", "longcat-2.0-free",
                "north-mini-code-free", "nemotron-3-ultra-free",
                "qwen3.7-max", "qwen3.7-plus", "qwen3.6-plus", "qwen3.5-plus",
                "claude-sonnet-4.5", "claude-opus-4.5", "claude-haiku-4.5",
                "gpt-5.4-mini", "gpt-5.4-nano", "gpt-5-nano",
                "deepseek-v4-flash", "deepseek-v4-pro",
                "minimax-m3", "minimax-m2.7",
                "glm-5.2", "glm-5.1", "glm-5",
                "kimi-k2.7-code", "kimi-k2.6", "kimi-k3",
            ]
            free_models = [m for m in models if "free" in m.lower()]
            return {"ok": True, "models": models, "free_models": free_models, "max_context": 200000}
        
        return {"ok": False, "msg": f"HTTP {resp.status_code}", "models": []}
    except Exception as e:
        return {"ok": False, "msg": str(e), "models": []}


@app.get("/api/ollama/models")
def api_ollama_models(base_url: str = "http://localhost:11434"):
    """获取本地 Ollama 模型列表"""
    import httpx as _httpx
    try:
        resp = _httpx.get(f"{base_url.rstrip('/')}/api/tags", timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            models = []
            for m in data.get("models", []):
                name = m.get("name", "")
                size = m.get("size", 0)
                details = m.get("details", {})
                models.append({
                    "name": name,
                    "size": size,
                    "size_gb": round(size / (1024**3), 1) if size else 0,
                    "family": details.get("family", ""),
                    "parameter_size": details.get("parameter_size", ""),
                    "quantization": details.get("quantization_level", ""),
                })
            models.sort(key=lambda x: x["name"])
            return {"ok": True, "models": models, "count": len(models)}
        return {"ok": False, "msg": f"Ollama 返回 {resp.status_code}", "models": []}
    except Exception as e:
        return {"ok": False, "msg": f"无法连接 Ollama: {e}", "models": []}


# ================= 团队协作 =================
class TeamMemberBody(BaseModel):
    id: str = ""
    name: str
    email: str = ""
    role: str = "member"
    avatar: str = "👤"
    status: str = "active"
    permissions: dict = {}


@app.get("/api/team/members")
def api_list_team_members():
    return db.list_team_members()


@app.post("/api/team/members")
def api_create_team_member(body: TeamMemberBody):
    mid = body.id or f"tm_{uuid.uuid4().hex[:8]}"
    db.upsert_team_member({
        "id": mid, "name": body.name, "email": body.email, "role": body.role,
        "avatar": body.avatar, "status": body.status, "permissions": body.permissions,
    })
    db.log_team_activity("system", "create", "member", mid, {"name": body.name})
    return {"id": mid}


@app.put("/api/team/members/{mid}")
def api_update_team_member(mid: str, body: TeamMemberBody):
    db.upsert_team_member({
        "id": mid, "name": body.name, "email": body.email, "role": body.role,
        "avatar": body.avatar, "status": body.status, "permissions": body.permissions,
    })
    return {"ok": True}


@app.delete("/api/team/members/{mid}")
def api_delete_team_member(mid: str):
    db.delete_team_member(mid)
    return {"ok": True}


@app.get("/api/team/activity")
def api_list_team_activity(limit: int = 50):
    return db.list_team_activity(limit)


@app.post("/api/team/share")
def api_share_conversation(body: dict):
    conv_id = body.get("conv_id", "")
    shared_by = body.get("shared_by", "admin")
    shared_with = body.get("shared_with", [])
    permission = body.get("permission", "view")
    sid = db.share_conversation(conv_id, shared_by, shared_with, permission)
    return {"id": sid}


@app.get("/api/team/shared")
def api_list_shared(user_id: str = None):
    return db.list_shared_conversations(user_id)


# ================= 搜索引擎 =================
from search_engine.engine import search as engine_search, search_multi

class SearchBody(BaseModel):
    query: str
    engine: str = "bing"
    max_results: int = 10
    engines: str = ""  # 多引擎搜索，逗号分隔

@app.post("/api/search")
def api_search(body: SearchBody):
    # 支持多引擎搜索
    if body.engines:
        engine_list = [e.strip() for e in body.engines.split(",") if e.strip()]
        results = search_multi(body.query, engine_list, body.max_results)
        return {"ok": True, "results": results, "engine": ",".join(engine_list)}
    # 单引擎搜索
    results = engine_search(body.query, body.engine, body.max_results)
    return {"ok": True, "results": results, "engine": body.engine}


# ================= 工具统一分派 =================
def build_tools(conv_id=None):
    """收集当前会话可用的全部工具（内置 + 技能 + MCP + 连接器）"""
    tools = list(agent.TOOLS)
    ct = db.get_conv_tools(conv_id) if conv_id else None
    if ct:
        tools += skills_mod.skill_tools_for(ct.get("skill_ids"))
        tools += mcp_client.mcp_tools_for(ct.get("mcp_ids"))
        tools += connector_mod.connector_tools_for(ct.get("connector_ids"))
    else:
        tools += skills_mod.skill_tools_for(None)
        tools += mcp_client.mcp_tools_for(None)
        tools += connector_mod.connector_tools_for(None)
    return tools


def build_tools_filtered(conv_id=None, skills_enabled=True, mcp_enabled=True):
    """根据开关构建工具列表"""
    tools = list(agent.TOOLS)
    ct = db.get_conv_tools(conv_id) if conv_id else None
    if skills_enabled:
        tools += skills_mod.skill_tools_for(ct.get("skill_ids") if ct else None)
    if mcp_enabled:
        tools += mcp_client.mcp_tools_for(ct.get("mcp_ids") if ct else None)
    # 连接器始终可用（数据查询是基础能力）
    tools += connector_mod.connector_tools_for(ct.get("connector_ids") if ct else None)
    return tools


def dispatch_tool(tool_name, args):
    """统一工具分派：内置/技能/MCP/连接器"""
    # 内置
    if tool_name in agent.TOOL_NAMES:
        return agent.execute_tool(tool_name, args)
    # 技能
    smap = skills_mod.build_tool_map()
    if tool_name in smap:
        return skills_mod.execute_skill_tool(smap[tool_name][1], tool_name, args)
    # MCP
    mmap = mcp_client.build_tool_map()
    if tool_name in mmap:
        return mcp_client.execute_mcp_tool(mmap[tool_name][1], tool_name, args)
    # 连接器
    cmap = connector_mod.build_tool_map()
    if tool_name in cmap:
        return connector_mod.execute_connector_tool(cmap[tool_name][1], tool_name, args)
    return False, f"未知工具: {tool_name}"


# ================= 聊天（SSE 流式 + Agent 工具循环） =================
class ChatBody(BaseModel):
    conv_id: str
    provider_id: str = ""
    model: str = ""
    message: str
    history: list = []
    attachments: list = []
    kb_enabled: bool = True
    kb_id: str = ""
    skills_enabled: bool = True
    mcp_enabled: bool = True
    thinking_mode: bool = False


@app.post("/api/chat")
def api_chat(body: ChatBody):
    providers = db.list_providers()
    if not providers:
        raise HTTPException(400, "请先在设置中添加模型供应商")

    provider = next((p for p in providers if p["id"] == body.provider_id), None)
    if not provider:
        provider = next((p for p in providers if p["enabled"]), providers[0])

    model = body.model or provider.get("default_model", "")
    if not model and provider.get("models"):
        model = provider["models"][0]
    if not model:
        raise HTTPException(400, "该供应商未配置模型")

    # 根据开关决定是否启用知识库检索（kb_id 非空时只检索该库）
    rag_context = rag.build_context(body.message, kb_id=body.kb_id or None) if body.kb_enabled else None

    db.add_message(body.conv_id, "user", body.message, body.attachments)
    conv = db.get_conversation(body.conv_id)
    kw = {"model": model}
    if conv and conv.get("title", "") in ("", "新对话"):
        kw["title"] = body.message[:30]
    db.update_conversation(body.conv_id, **kw)

    def gen():
        try:
            yield from agent_loop(provider, model, body, rag_context)
        except llm.ModelError as e:
            yield f"data: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': f'未知错误: {e}'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


# ---------- 会话压缩 ----------
class CompressBody(BaseModel):
    messages: list = []
    provider_id: str = ""
    model: str = ""


class CompressConvBody(BaseModel):
    conv_id: str
    provider_id: str = ""
    model: str = ""


def _pick_provider_model(provider_id, model):
    """复用 api_chat 的 provider/model 选择逻辑"""
    providers = db.list_providers()
    if not providers:
        raise HTTPException(400, "请先在设置中添加模型供应商")
    provider = next((p for p in providers if p["id"] == provider_id), None)
    if not provider:
        provider = next((p for p in providers if p["enabled"]), providers[0])
    m = model or provider.get("default_model", "")
    if not m and provider.get("models"):
        m = provider["models"][0]
    if not m:
        raise HTTPException(400, "该供应商未配置模型")
    return provider, m


def _msg_to_text(content):
    """消息 content 可能是字符串或多模态数组，统一转字符串"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    parts.append(item.get("text", ""))
                elif item.get("type") == "image_url":
                    parts.append("[图片]")
                elif item.get("type") == "image":
                    parts.append("[图片]")
                else:
                    parts.append(item.get("text", "") or "")
            else:
                parts.append(str(item))
        return "\n".join(parts)
    return str(content)


def _make_summary(provider, model, messages):
    """调用 LLM 压缩消息列表，返回摘要文本"""
    sys_prompt = (
        "你是对话摘要助手。请把下面的对话历史压缩成一份精炼的中文摘要："
        "保留关键事实、用户需求、已得出的结论与待办事项，"
        "控制在 300-500 字以内，不要编造内容。只输出摘要本身，不要解释。"
    )
    cleaned = []
    for m in messages:
        role = m.get("role", "user")
        content = _msg_to_text(m.get("content", ""))
        if not content.strip():
            continue
        cleaned.append({"role": role, "content": content})
    if not cleaned:
        raise HTTPException(400, "没有可压缩的消息内容")
    msgs = [{"role": "system", "content": sys_prompt}] + cleaned
    try:
        summary = llm.chat_once(provider, model, msgs, timeout=180)
    except llm.ModelError as e:
        raise HTTPException(502, f"压缩失败: {e}")
    except Exception as e:
        raise HTTPException(502, f"压缩失败: {e}")
    if not summary:
        raise HTTPException(502, "模型未返回摘要")
    return summary


@app.post("/api/compress")
def api_compress(body: CompressBody):
    """压缩一段消息历史为摘要（无副作用，用于发送前自动压缩）"""
    if not body.messages:
        raise HTTPException(400, "没有可压缩的消息")
    provider, model = _pick_provider_model(body.provider_id, body.model)
    summary = _make_summary(provider, model, body.messages)
    return {"summary": summary}


@app.post("/api/compress_conv")
def api_compress_conv(body: CompressConvBody):
    """压缩整个会话：旧消息替换为一条摘要消息（重写消息记录）"""
    conv = db.get_conversation(body.conv_id)
    if not conv:
        raise HTTPException(404, "会话不存在")
    msgs = db.list_messages(body.conv_id)
    if not msgs:
        raise HTTPException(400, "会话暂无消息")
    provider, model = _pick_provider_model(body.provider_id, body.model)
    summary = _make_summary(provider, model, msgs)
    db.clear_messages(body.conv_id)
    db.add_message(body.conv_id, "assistant", "📌 历史已压缩为摘要：\n\n" + summary)
    return {"summary": summary}


def _message_content_with_attachments(text, attachments):
    """将附件转成多模态 content 数组"""
    if not attachments:
        return text
    content = [{"type": "text", "text": text or ""}]
    base = os.environ.get("ABCODE_PUBLIC_BASE", "http://127.0.0.1:8900")
    for att in attachments:
        mime = att.get("mime", "")
        url = f"{base}/uploads/{att.get('filename', '')}"
        if mime.startswith("image/"):
            content.append({"type": "image_url", "image_url": {"url": url}})
        elif mime.startswith("video/"):
            content.append({"type": "text", "text": f"[视频附件: {att.get('filename', '')} ({url})]"})
        elif mime.startswith("audio/"):
            content.append({"type": "text", "text": f"[音频附件: {att.get('filename', '')} ({url})]"})
        else:
            content.append({"type": "text", "text": f"[文件附件: {att.get('filename', '')} ({url})]"})
    return content


def agent_loop(provider, model, body, rag_context):
    """Agent 主循环：模型 <-> 工具，最多 5 轮"""
    # 会话绑定智能体：用其系统提示词与工具配置
    conv_cfg = db.get_conv_tools(body.conv_id) if body.conv_id else None
    bound_agent = None
    if conv_cfg and conv_cfg.get("expert_id"):
        try:
            from agent_runtime import AgentManager
            bound_agent = AgentManager.get(conv_cfg["expert_id"])
        except Exception:
            bound_agent = None

    if bound_agent and bound_agent.system_prompt:
        sys_prompt = bound_agent.system_prompt
        # 绑定智能体但未填写提示词时使用默认
    else:
        sys_prompt = (
            "你是 ABcode，一个 AI Agent 助手。你可以使用工具来完成任务："
            "联网搜索实时信息、抓取网页、读写工作区文件、执行安全命令。"
            "需要时主动调用工具，不要编造信息。回答用中文，简洁清晰。"
        )
    # 注入实时时间
    from time_utils import get_current_time_str, TIME_PROMPT_TPL
    sys_prompt += TIME_PROMPT_TPL.format(time=get_current_time_str())
    
    if body.thinking_mode:
        sys_prompt += (
            "\n\n请先在 <thinking> 标签内展示你的思考过程（推理、分析、权衡），"
            "然后再给出最终回答。思考过程要简洁，突出关键推理步骤。"
            "示例格式：\n<thinking>\n用户想了解 X，我需要先查 Y...\n</thinking>\n\n最终回答..."
        )
    if rag_context:
        sys_prompt += f"\n\n以下是从你的知识库中检索到的参考资料，优先依据这些内容回答：\n{rag_context}"
    
    # 构建消息：系统提示 + 历史 + 当前问题
    messages = [{"role": "system", "content": sys_prompt}]
    for h in body.history[-12:]:
        if h.get("role") in ("user", "assistant"):
            messages.append({"role": h["role"], "content": h["content"]})
    messages.append({"role": "user", "content": body.message})
    
    # 当前用户消息带附件 -> 转多模态
    if body.attachments:
        messages[-1] = {"role": "user", "content": _message_content_with_attachments(body.message, body.attachments)}
    
    # 根据开关构建可用工具列表
    tools = build_tools_filtered(body.conv_id, body.skills_enabled, body.mcp_enabled)
    
    max_rounds = 5

    for round_idx in range(max_rounds):
        assistant_parts = []
        tool_call_objs = []

        for evt in llm.stream_chat(provider, model, messages, tools=tools):
            if evt["type"] == "text":
                assistant_parts.append(evt["content"])
                yield f"data: {json.dumps({'delta': evt['content']}, ensure_ascii=False)}\n\n"
            elif evt["type"] == "tool_calls":
                tool_call_objs = evt["tool_calls"]

        text = "".join(assistant_parts)

        if text.strip():
            db.add_message(body.conv_id, "assistant", text)
            assistant_msg = {"role": "assistant", "content": text}
        else:
            assistant_msg = {"role": "assistant", "content": text or "(调用工具)"}

        if not tool_call_objs:
            yield f"data: {json.dumps({'done': True}, ensure_ascii=False)}\n\n"
            return

        messages.append(assistant_msg)
        tool_results_msgs = []
        for tc in tool_call_objs:
            name = tc.get("name", "")
            args_str = tc.get("args", "") or "{}"
            try:
                args = json.loads(args_str) if args_str else {}
            except Exception:
                args = {}
            yield f"data: {json.dumps({'tool_start': {'name': name, 'args': args}}, ensure_ascii=False)}\n\n"
            # 工具执行兜底：任何异常/非字符串返回值都不允许中断 SSE 流
            try:
                ok, result = dispatch_tool(name, args)
            except Exception as e:
                ok, result = False, f"工具执行异常: {type(e).__name__}: {e}"
            if result is None:
                result = ""
            if not isinstance(result, str):
                try:
                    result = json.dumps(result, ensure_ascii=False)
                except Exception:
                    result = str(result)
            yield f"data: {json.dumps({'tool_result': {'name': name, 'ok': ok, 'result': result[:2000]}}, ensure_ascii=False)}\n\n"
            tool_results_msgs.append({
                "role": "tool",
                "tool_call_id": tc.get("id", f"{name}_{round_idx}"),
                "content": json.dumps({"ok": ok, "result": result}, ensure_ascii=False),
            })

        messages.extend(tool_results_msgs)

    # ===== 轮数用尽：不报错中断，而是基于已收集的工具结果强制收尾 =====
    # 防止模型陷入无限工具调用循环导致前端"调用工具后无最终回复/中断"。
    messages.append({
        "role": "user",
        "content": "（请基于以上工具调用已经获得的信息，现在直接给出最终回答，不要再调用任何工具。）",
    })
    # 无 tools 再跑一轮，确保拿到最终文本
    final_parts = []
    try:
        for evt in llm.stream_chat(provider, model, messages, tools=None):
            if evt["type"] == "text":
                final_parts.append(evt["content"])
                yield f"data: {json.dumps({'delta': evt['content']}, ensure_ascii=False)}\n\n"
    except Exception as e:
        yield f"data: {json.dumps({'error': f'收尾失败: {e}'}, ensure_ascii=False)}\n\n"
    final_text = "".join(final_parts)
    if final_text.strip():
        db.add_message(body.conv_id, "assistant", final_text)
    yield f"data: {json.dumps({'done': True}, ensure_ascii=False)}\n\n"


# ================= 知识库 RAG =================
@app.get("/api/kb/list")
def api_kb_list():
    return rag.list_kbs()


@app.post("/api/kb/create")
def api_kb_create(body: dict):
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "名称不能为空")
    kb_id = rag.create_kb(name)
    return {"id": kb_id, "name": name}


@app.delete("/api/kb/{kb_id}")
def api_kb_delete_kb(kb_id: str):
    if kb_id == "default":
        raise HTTPException(400, "默认知识库不可删除")
    rag.delete_kb(kb_id)
    return {"ok": True}


@app.get("/api/kb/docs")
def api_kb_docs(kb_id: str = None):
    return rag.list_docs(kb_id)


@app.post("/api/kb/upload")
async def api_kb_upload(file: UploadFile = File(...), kb_id: str = Form("default")):
    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(400, "文件过大（>10MB）")
    if len(content) == 0:
        raise HTTPException(400, "文件为空")
    ext = rag._ext(file.filename)
    if ext in rag.UNSUPPORTED_EXTS:
        raise HTTPException(400, f"不支持的文件类型 .{ext}（知识库仅支持文本格式）")
    # PDF/Word 是二进制格式但有专用解析器，放行；其余二进制（伪装文本）拒绝
    if ext not in ("pdf", "docx") and rag._is_binary(content):
        raise HTTPException(400, f"文件内容是二进制格式（{rag._binary_name(content)}），不是文本文件")
    doc_id, n, is_dup = rag.add_document(file.filename, content, kb_id=kb_id)
    if not doc_id:
        raise HTTPException(400, "文档内容过少，无法建立知识库")
    return {"id": doc_id, "chunks": n, "name": file.filename, "duplicate": is_dup, "kb_id": kb_id}


@app.delete("/api/kb/docs/{doc_id}")
def api_kb_delete(doc_id: str):
    rag.delete_doc(doc_id)
    return {"ok": True}


@app.post("/api/kb/search")
def api_kb_search(body: dict):
    query = body.get("query", "")
    top_k = int(body.get("top_k", 5))
    highlight = bool(body.get("highlight", False))
    kb_id = body.get("kb_id") or None
    min_score = float(body.get("min_score", 0.0) or 0.0)
    diversify = bool(body.get("diversify", True))
    if highlight:
        return rag.search_with_highlight(query, top_k, kb_id=kb_id, min_score=min_score, diversify=diversify)
    return rag.search(query, top_k, kb_id=kb_id, min_score=min_score, diversify=diversify)


@app.get("/api/kb/docs/{doc_id}")
def api_kb_doc_detail(doc_id: str):
    doc = rag.get_doc(doc_id)
    if not doc:
        raise HTTPException(404, "文档不存在")
    return doc


@app.post("/api/kb/docs/{doc_id}/rename")
def api_kb_doc_rename(doc_id: str, body: dict):
    new_name = (body.get("name") or "").strip()
    if not new_name:
        raise HTTPException(400, "名称不能为空")
    rag.rename_doc(doc_id, new_name)
    return {"ok": True, "name": new_name}


@app.get("/api/kb/stats")
def api_kb_stats(kb_id: str = None):
    docs = rag.list_docs(kb_id)
    total_chunks = sum(d.get("chunks", 0) for d in docs)
    total_size = sum(d.get("size", 0) for d in docs)
    return {"doc_count": len(docs), "chunk_count": total_chunks, "total_size": total_size, "supported": list(rag.TEXT_EXTS.values())}


@app.get("/api/kb/export")
def api_kb_export(kb_id: str = None):
    """导出知识库文档（含分块），返回 JSON 下载；kb_id 非空时只导出该库"""
    docs = rag.list_docs(kb_id)
    data = []
    for d in docs:
        detail = rag.get_doc(d["id"])
        if not detail:
            continue
        data.append({
            "name": d["name"],
            "size": d["size"],
            "created_at": d["created_at"],
            "type": d.get("type", ""),
            "chunk_list": detail["chunk_list"],
        })
    import json as _json
    content = _json.dumps({"exported_at": time.time(), "docs": data}, ensure_ascii=False, indent=2)
    from fastapi.responses import Response
    return Response(
        content=content,
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="abcode_kb_export.json"'},
    )


@app.post("/api/kb/clear")
def api_kb_clear(body: dict = None):
    """清空知识库；body.kb_id 非空时只清空该库"""
    body = body or {}
    rag.clear_all(body.get("kb_id") or None)
    return {"ok": True}


# ================= 定时任务 =================
class JobBody(BaseModel):
    name: str = ""
    prompt: str
    interval_min: int = 0
    schedule_at: str = ""
    provider_id: str = ""
    model: str = ""
    conv_id: str = ""
    enabled: bool = True


@app.get("/api/cron/jobs")
def api_cron_list():
    return cron_mod.list_jobs()


@app.post("/api/cron/jobs")
def api_cron_create(body: JobBody):
    jid = cron_mod.create_job(body.model_dump())
    return {"id": jid}


@app.put("/api/cron/jobs/{jid}")
def api_cron_update(jid: str, body: JobBody):
    cron_mod.update_job(jid, **body.model_dump())
    return {"ok": True}


@app.delete("/api/cron/jobs/{jid}")
def api_cron_delete(jid: str):
    cron_mod.delete_job(jid)
    return {"ok": True}


@app.post("/api/cron/jobs/{jid}/run")
def api_cron_run_now(jid: str):
    conn = db.get_conn()
    row = conn.execute("SELECT * FROM cron_jobs WHERE id=?", (jid,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "任务不存在")
    job = dict(row)
    cron_mod.update_job(jid, last_run=time.time())
    try:
        result = run_cron_job(job)
        cron_mod.update_job(jid, last_result=str(result)[:2000])
        return {"ok": True, "result": str(result)[:500]}
    except Exception as e:
        return {"ok": False, "result": str(e)}


# ================= 技能插件 =================
class SkillBody(BaseModel):
    id: str = ""
    name: str
    description: str = ""
    code: str = ""
    enabled: bool = True


@app.get("/api/skills")
def api_skills_list():
    return db.list_skills()


@app.post("/api/skills")
def api_skills_save(body: SkillBody):
    sid = body.id or f"skill_{int(time.time()*1000)}"
    # 校验代码可编译
    if body.code.strip():
        try:
            compile(body.code, "<skill>", "exec")
        except Exception as e:
            raise HTTPException(400, f"代码语法错误: {e}")
    db.upsert_skill({"id": sid, "name": body.name, "description": body.description,
                     "code": body.code, "enabled": body.enabled})
    return {"id": sid}


@app.post("/api/skills/{sid}/toggle")
def api_skills_toggle(sid: str):
    s = db.get_skill(sid)
    if not s:
        raise HTTPException(404, "技能不存在")
    db.upsert_skill({**s, "enabled": 0 if s["enabled"] else 1})
    return {"ok": True, "enabled": 0 if s["enabled"] else 1}


@app.delete("/api/skills/{sid}")
def api_skills_delete(sid: str):
    s = db.get_skill(sid)
    if s and s["builtin"]:
        raise HTTPException(400, "内置技能不可删除")
    db.delete_skill(sid)
    return {"ok": True}


# ================= MCP 服务器 =================
class McpBody(BaseModel):
    id: str = ""
    name: str
    transport: str = "stdio"
    command: str = ""
    args: list = []
    url: str = ""
    headers: dict = {}
    enabled: bool = True


@app.get("/api/mcp/servers")
def api_mcp_list():
    return db.list_mcp()


@app.post("/api/mcp/servers")
def api_mcp_save(body: McpBody):
    mid = body.id or f"mcp_{int(time.time()*1000)}"
    db.upsert_mcp({"id": mid, "name": body.name, "transport": body.transport,
                   "command": body.command, "args": body.args, "url": body.url,
                   "headers": body.headers, "enabled": body.enabled})
    mcp_client.close_client(mid)
    return {"id": mid}


@app.post("/api/mcp/test")
def api_mcp_test(body: McpBody):
    server = {"id": body.id or "test", "name": body.name, "transport": body.transport,
              "command": body.command, "args": body.args, "url": body.url,
              "headers": body.headers, "enabled": True}
    ok, msg = mcp_client.test_mcp(server)
    return {"ok": ok, "msg": msg}


@app.delete("/api/mcp/servers/{mid}")
def api_mcp_delete(mid: str):
    mcp_client.close_client(mid)
    db.delete_mcp(mid)
    return {"ok": True}


# ================= 数据连接器 =================
class ConnectorBody(BaseModel):
    id: str = ""
    name: str
    type: str = "sqlite"
    config: dict = {}
    enabled: bool = True


@app.get("/api/connectors")
def api_connector_list():
    return db.list_connectors()


@app.post("/api/connectors")
def api_connector_save(body: ConnectorBody):
    cid = body.id or f"conn_{int(time.time()*1000)}"
    db.upsert_connector({"id": cid, "name": body.name, "type": body.type,
                         "config": body.config, "enabled": body.enabled})
    return {"id": cid}


@app.post("/api/connectors/test")
def api_connector_test(body: ConnectorBody):
    # 用提交的配置直接测试连接（无论是否已保存）
    ok, msg = connector_mod.test_connector({
        "id": body.id or "test", "name": body.name, "type": body.type,
        "config": body.config, "enabled": body.enabled,
    })
    return {"ok": ok, "msg": msg}


@app.get("/api/connectors/{cid}/tables")
def api_connector_tables(cid: str):
    return {"tables": connector_mod.list_tables(cid)}


@app.delete("/api/connectors/{cid}")
def api_connector_delete(cid: str):
    db.delete_connector(cid)
    return {"ok": True}


# ================= 频道管理 =================
class ChannelBody(BaseModel):
    id: str = ""
    name: str
    type: str
    icon: str = "📡"
    enabled: bool = True
    bot_prefix: str = ""
    config: dict = {}
    description: str = ""


@app.get("/api/channels")
def api_channels_list():
    return db.list_channels()


@app.post("/api/channels")
def api_channels_save(body: ChannelBody):
    cid = body.id or f"ch_{int(time.time()*1000)}"
    ch = db.get_channel(cid)
    is_builtin = ch["builtin"] if ch else False
    db.upsert_channel({
        "id": cid, "name": body.name, "type": body.type, "icon": body.icon,
        "builtin": is_builtin, "enabled": body.enabled,
        "bot_prefix": body.bot_prefix, "config": body.config,
        "description": body.description,
    })
    return {"id": cid}


@app.post("/api/channels/{cid}/toggle")
def api_channels_toggle(cid: str):
    ch = db.get_channel(cid)
    if not ch:
        raise HTTPException(404, "频道不存在")
    db.upsert_channel({**ch, "enabled": 0 if ch["enabled"] else 1})
    return {"ok": True, "enabled": 0 if ch["enabled"] else 1}


@app.delete("/api/channels/{cid}")
def api_channels_delete(cid: str):
    ch = db.get_channel(cid)
    if ch and ch.get("builtin"):
        raise HTTPException(400, "内置频道不可删除")
    db.delete_channel(cid)
    return {"ok": True}


@app.post("/api/channels/{cid}/config")
def api_channels_config(cid: str, body: dict):
    ch = db.get_channel(cid)
    if not ch:
        raise HTTPException(404, "频道不存在")
    ch["config"] = body.get("config", ch["config"])
    if "bot_prefix" in body:
        ch["bot_prefix"] = body["bot_prefix"]
    db.upsert_channel(ch)
    return {"ok": True}


# ===== 频道扫码接入 =====
QR_TTL = 600  # 二维码 10 分钟有效

def _detect_lan_ip():
    """自动检测本机局域网 IP，供手机扫码访问（127.0.0.1 手机扫不开）"""
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # 连接一个外部地址（不发包）以触发路由，获取本机出口 IP
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        try:
            import subprocess
            out = subprocess.check_output(["ipconfig", "getifaddr", "en0"]).decode().strip()
            if out:
                return out
        except Exception:
            pass
        return "127.0.0.1"


def _qr_url_for(code):
    base = os.environ.get("ABCODE_PUBLIC_BASE", "")
    if not base:
        base = f"http://{_detect_lan_ip()}:8900"
    return f"{base}/channel/{code}"


@app.post("/api/channels/{cid}/qr")
def api_channel_qr_create(cid: str):
    ch = db.get_channel(cid)
    if not ch:
        raise HTTPException(404, "频道不存在")
    # 每次生成全新二维码：旧的 pending 码立即作废（频繁刷新也能拿到新码）
    old = db.get_latest_channel_qr(cid)
    if old and old.get("status") == "pending":
        db.update_channel_qr_status(old["code"], "expired")
    code = f"qr_{uuid.uuid4().hex[:12]}"
    db.create_channel_qr(cid, code, time.time() + QR_TTL)
    return {"ok": True, "code": code, "url": _qr_url_for(code), "expires_in": QR_TTL}


@app.get("/api/channels/{cid}/qr/png")
def api_channel_qr_png(cid: str, code: str = ""):
    ch = db.get_channel(cid)
    if not ch:
        raise HTTPException(404, "频道不存在")
    if not code:
        latest = db.get_latest_channel_qr(cid)
        code = latest["code"] if latest else ""
    if not code:
        raise HTTPException(404, "请先生成接入二维码")
    import io
    import segno
    url = _qr_url_for(code)
    buf = io.BytesIO()
    segno.make(url, error="m").save(buf, kind="png", scale=6, border=2)
    buf.seek(0)
    from fastapi.responses import Response
    return Response(content=buf.getvalue(), media_type="image/png")


@app.get("/api/channels/{cid}/qr/status")
def api_channel_qr_status(cid: str):
    latest = db.get_latest_channel_qr(cid)
    if not latest:
        return {"status": "none"}
    if latest["expires_at"] < time.time() and latest["status"] == "pending":
        return {"status": "expired"}
    return {"status": latest["status"], "code": latest["code"]}


@app.post("/api/channels/qr/confirm")
def api_channel_qr_confirm(body: dict):
    code = (body or {}).get("code", "")
    qr = db.get_channel_qr(code) if code else None
    if not qr:
        raise HTTPException(404, "二维码无效或已失效")
    if qr["status"] == "expired":
        raise HTTPException(410, "二维码已作废，请扫描最新二维码")
    if qr["expires_at"] < time.time():
        db.update_channel_qr_status(code, "expired")
        raise HTTPException(410, "二维码已过期，请重新生成")
    if qr["status"] == "confirmed":
        return {"ok": True, "channel": qr["cid"]}
    ch = db.get_channel(qr["cid"])
    if not ch:
        raise HTTPException(404, "频道不存在")
    db.update_channel_qr_status(code, "confirmed")
    db.upsert_channel({**ch, "enabled": 1})
    return {"ok": True, "channel": qr["cid"], "channel_name": ch.get("name", "")}


@app.get("/channel/{code}")
def api_channel_qr_page(code: str, request: Request):
    """手机扫码打开的确认接入页"""
    qr = db.get_channel_qr(code)
    if not qr:
        return HTMLResponse("<h3>二维码无效或已失效</h3>")
    ch = db.get_channel(qr["cid"]) or {}
    expired = qr["expires_at"] < time.time() or qr["status"] == "expired"
    confirmed = qr["status"] == "confirmed"
    name = (ch.get("name") or "未知频道").replace("<", "&lt;").replace(">", "&gt;")
    if expired:
        msg = f"<h3>❌ 二维码已失效，请重新生成最新二维码</h3><p>频道：{name}</p>"
    elif confirmed:
        msg = f"<h3>✅ 已接入</h3><p>频道「{name}」已成功接入，请关闭本页面。</p>"
    else:
        msg = f"""
        <h3>📡 {name}</h3>
        <p>确认将该频道接入 ABcode 吗？</p>
        <button onclick="confirmQr()" style="...">✅ 确认接入</button>
        <p id="msg"></p>
        <script>
          async function confirmQr() {{
            const r = await fetch('/api/channels/qr/confirm', {{
              method: 'POST',
              headers: {{'Content-Type': 'application/json'}},
              body: JSON.stringify({{code: '{code}'}})
            }});
            const d = await r.json();
            if (r.ok) {{
              document.body.innerHTML = '<h3>✅ 接入成功</h3><p>频道「{name}」已启用，请关闭本页面。</p>';
            }} else {{
              document.getElementById('msg').textContent = d.detail || '接入失败';
            }}
          }}
        </script>
        """
    return HTMLResponse(f"<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>频道接入确认</title><style>body{{font-family:-apple-system,sans-serif;max-width:420px;margin:60px auto;padding:0 20px;text-align:center;color:#222}}button{{background:#2563eb;color:#fff;border:0;border-radius:8px;padding:12px 28px;font-size:16px;margin-top:12px}}</style></head><body>{msg}</body></html>")


# ===== 频道消息收发 =====
@app.post("/api/channels/{cid}/webhook")
def api_channel_webhook(cid: str, payload: dict = Body(default={})):
    ch = db.get_channel(cid)
    if not ch:
        raise HTTPException(404, "频道不存在")
    if not ch.get("enabled"):
        raise HTTPException(400, "该频道未启用，请先扫码/启用后再接入")
    return channels_mod.handle_webhook(cid, payload or {})


@app.get("/api/channels/{cid}/messages")
def api_channel_messages(cid: str, limit: int = 100):
    ch = db.get_channel(cid)
    if not ch:
        raise HTTPException(404, "频道不存在")
    return db.list_channel_msgs(cid, limit)


@app.delete("/api/channels/{cid}/messages")
def api_channel_messages_clear(cid: str):
    ch = db.get_channel(cid)
    if not ch:
        raise HTTPException(404, "频道不存在")
    db.clear_channel_msgs(cid)
    return {"ok": True}


@app.post("/api/channels/{cid}/send")
def api_channel_send(cid: str, body: dict = Body(default={})):
    """直接在频道内向指定发送者模拟回复（用于测试/手动触发）。"""
    ch = db.get_channel(cid)
    if not ch:
        raise HTTPException(404, "频道不存在")
    sender = (body or {}).get("sender") or "用户"
    text = (body or {}).get("text") or ""
    if not text.strip():
        raise HTTPException(400, "缺少 text 字段")
    reply = channels_mod.reply_to_channel(cid, sender, text)
    return {"ok": True, "reply": reply}


@app.post("/api/channels/wecom/send")
def api_wecom_send(body: dict = Body(default={})):
    """企业微信应用消息主动推送（出站，免公网）。body: {touser?, text}"""
    text = (body or {}).get("text") or ""
    if not text.strip():
        raise HTTPException(400, "缺少 text 字段")
    touser = (body or {}).get("touser") or "@all"
    ok, msg = channels_mod.wecom_send_text(text, touser=touser)
    if not ok:
        raise HTTPException(400, msg)
    return {"ok": True, "msg": msg}


# ================= 会话工具配置 =================
class ConvToolsBody(BaseModel):
    skill_ids: list = None
    mcp_ids: list = None
    connector_ids: list = None
    expert_id: str = ""
    workflow_id: str = ""


@app.get("/api/conversations/{cid}/tools")
def api_conv_tools_get(cid: str):
    ct = db.get_conv_tools(cid)
    # 附加完整信息
    ct["skills"] = db.list_skills()
    ct["mcps"] = db.list_mcp()
    ct["connectors"] = db.list_connectors()
    return ct


@app.post("/api/conversations/{cid}/tools")
def api_conv_tools_set(cid: str, body: ConvToolsBody):
    db.set_conv_tools(cid, body.skill_ids, body.mcp_ids, body.connector_ids,
                      expert_id=body.expert_id or None, workflow_id=body.workflow_id or None)
    return {"ok": True}


# ================= 上传文件（图片/视频/音频） =================
ALLOWED_MIME = {
    "image/": "img", "video/": "vid", "audio/": "aud",
    "text/": "txt", "application/pdf": "pdf", "application/json": "json",
}


@app.post("/api/upload")
async def api_upload(file: UploadFile = File(...)):
    mime = file.content_type or mimetypes.guess_type(file.filename or "")[0] or "application/octet-stream"
    ext = Path(file.filename or "file").suffix or ".bin"
    uid = uuid.uuid4().hex[:10]
    fname = f"{uid}{ext}"
    dest = UPLOAD_DIR / fname
    content = await file.read()
    if len(content) > 100 * 1024 * 1024:
        raise HTTPException(400, "文件过大（>100MB）")
    dest.write_bytes(content)
    db.add_upload(uid, file.filename or fname, mime, len(content), str(dest))
    return {"id": uid, "filename": fname, "original": file.filename, "mime": mime, "size": len(content)}


@app.get("/api/uploads")
def api_uploads():
    return db.list_uploads()


# ================= 语音合成 =================
@app.post("/api/asr")
async def api_asr(request: Request):
    """本地语音识别：浏览器 MediaRecorder 音频（webm/mp4 等） → 简体文本"""
    try:
        data = await request.body()
    except Exception:
        return JSONResponse({"ok": False, "msg": "读取音频失败"}, status_code=400)
    if not data:
        return JSONResponse({"ok": False, "msg": "空音频"}, status_code=400)
    if asr_mod._ensure_model() is None:
        return JSONResponse(
            {"ok": False, "msg": "本地语音模型不可用（faster-whisper 未安装或加载失败），请安装依赖后重启"},
            status_code=503,
        )
    text = asr_mod.transcribe(data)
    if not text:
        return JSONResponse({"ok": False, "msg": "未识别到语音，请重试"}, status_code=422)
    return {"ok": True, "text": text}


@app.post("/api/tts")
def api_tts(body: dict = Body(...)):
    text = (body.get("text") or "").strip()
    if not text or len(text) > 500:
        raise HTTPException(400, "文本为空或过长")
    ok, path = updater.tts_say(text)
    if not ok:
        raise HTTPException(500, "语音合成失败")
    return FileResponse(path, media_type="audio/mp4", filename="tts.m4a")


# ================= 全局设置 =================
@app.get("/api/settings")
def api_settings_get():
    return db.get_all_settings()


@app.post("/api/settings")
def api_settings_set(body: dict):
    for k, v in body.items():
        if k.startswith("search_") or k.startswith("update_") or k.startswith("auto_update"):
            db.set_setting(k, v)
    return {"ok": True}


@app.post("/api/settings/test-search")
def api_settings_test_search(body: dict):
    """测试搜索服务连通性"""
    import httpx
    search_url = body.get("search_service_url", "")
    search_engine = body.get("search_engine", "builtin")
    
    # 内置搜索直接测试
    if search_engine == "builtin":
        try:
            from search_engine.engine import search
            results = search("hello world", "bing", 3)
            if results and not any("error" in r for r in results):
                return {"ok": True, "msg": f"✅ 内置搜索正常！返回 {len(results)} 条结果"}
            return {"ok": False, "msg": "⚠️ 内置搜索返回为空，可能网络受限"}
        except Exception as e:
            return {"ok": False, "msg": f"❌ 内置搜索失败: {e}"}
    
    if not search_url:
        return {"ok": False, "msg": "未配置搜索服务地址"}
    try:
        sep = "&" if "?" in search_url else "?"
        url = f"{search_url}{sep}q=hello&format=json&language=zh-CN"
        resp = httpx.get(url, timeout=10, follow_redirects=True,
                         headers={"User-Agent": "Mozilla/5.0"})
        if resp.status_code == 200:
            data = resp.json()
            count = len(data.get("results", []))
            return {"ok": True, "msg": f"连接成功，返回 {count} 条结果"}
        return {"ok": False, "msg": f"HTTP {resp.status_code}"}
    except Exception as e:
        return {"ok": False, "msg": f"连接失败: {e}"}


# ================= 在线更新 =================
@app.get("/api/update/check")
def api_update_check(url: str = ""):
    return updater.check_update(url or None)


@app.post("/api/update/download")
def api_update_download(body: dict = Body(...)):
    url = (body.get("url") or "").strip()
    if not url:
        raise HTTPException(400, "缺少下载地址")
    ok, path, msg = updater.download_update(url)
    return {"ok": ok, "path": path, "msg": msg}


@app.get("/api/update/status")
def api_update_status():
    """获取更新状态"""
    return updater.get_update_status()


@app.get("/api/update/history")
def api_update_history():
    """获取更新历史"""
    return updater.get_update_history()


@app.post("/api/update/apply")
def api_update_apply(body: dict = Body(...)):
    """应用更新"""
    zip_path = body.get("zip_path", "")
    md5 = body.get("md5", "")
    if not zip_path:
        raise HTTPException(400, "缺少更新包路径")
    ok, msg = updater.apply_update(zip_path, md5)
    return {"ok": ok, "msg": msg}


@app.post("/api/update/rollback")
def api_update_rollback(body: dict = Body(...)):
    """回滚更新"""
    backup_name = body.get("backup_name", "")
    if not backup_name:
        raise HTTPException(400, "缺少备份名称")
    ok, msg = updater.rollback_update(backup_name)
    return {"ok": ok, "msg": msg}


@app.get("/api/update/backups")
def api_update_backups():
    """获取备份列表"""
    backup_dir = Path.home() / ".abcode" / "backups"
    if not backup_dir.exists():
        return []
    backups = []
    for item in backup_dir.iterdir():
        if item.is_dir() and item.name.startswith("backup_"):
            backups.append({
                "name": item.name,
                "time": item.stat().st_mtime,
                "size": sum(f.stat().st_size for f in item.rglob("*") if f.is_file()),
            })
    return sorted(backups, key=lambda x: x["time"], reverse=True)


@app.get("/api/version")
def api_version():
    return {"version": updater.VERSION, "platform": updater.get_platform(), "app": updater.APP_NAME}


@app.get("/api/time")
def api_time():
    """返回当前时间，供前端显示"""
    from time_utils import get_current_time_str
    return {"time": get_current_time_str(), "timezone": "Asia/Shanghai"}


# ================= 工作流 =================
@app.get("/api/workflows")
def api_list_workflows():
    """获取工作流列表"""
    return workflow_mod.list_workflows_summary()


@app.get("/api/workflows/{wid}")
def api_get_workflow(wid: str):
    """获取工作流详情"""
    wf = db.get_workflow(wid)
    if not wf:
        raise HTTPException(404, "工作流不存在")
    return wf


def _gen_wf_id(length=15):
    """生成15位随机工作流ID（字母+数字）"""
    chars = string.ascii_lowercase + string.digits
    return "wf_" + "".join(random.choices(chars, k=length))


@app.post("/api/workflows")
def api_save_workflow(body: dict):
    """保存工作流（创建或更新）"""
    wf_id = body.get("id") or _gen_wf_id()
    body["id"] = wf_id
    if not body.get("created_at"):
        body["created_at"] = time.time()
    # 兼容 nodes/edges 以 JSON 字符串或数组两种形式提交，避免双重序列化
    for k, fallback in (("nodes", []), ("edges", []), ("tags", []), ("config", {})):
        v = body.get(k)
        if isinstance(v, str):
            try:
                body[k] = json.loads(v)
            except Exception:
                body[k] = fallback
        elif v is None:
            body[k] = fallback
    db.save_workflow(body)
    return {"ok": True, "id": wf_id}


@app.delete("/api/workflows/{wid}")
def api_delete_workflow(wid: str):
    """删除工作流"""
    db.delete_workflow(wid)
    return {"ok": True}


@app.post("/api/workflows/{wid}/run")
def api_run_workflow(wid: str, body: dict = Body(...)):
    """执行工作流"""
    input_data = dict(body.get("input", {}))
    _merge_workflow_attachments(input_data, body.get("attachments"))
    result = workflow_mod.execute_workflow(wid, input_data)
    return result


def _merge_workflow_attachments(input_data, attachments):
    """把测试面板上传的附件(base64 data URL)注入工作流输入，供 LLM 节点做多模态"""
    if not attachments:
        return
    existing = input_data.get("_attachments") or []
    for att in attachments:
        existing.append({
            "name": att.get("name", ""),
            "type": att.get("type", att.get("mime", "")),
            "size": att.get("size", 0),
            "data": att.get("data", ""),
        })
    input_data["_attachments"] = existing


@app.post("/api/workflows/{wid}/run_stream")
def api_run_workflow_stream(wid: str, body: dict = Body(...)):
    """流式执行工作流（SSE）"""
    input_data = dict(body.get("input", {}))
    _merge_workflow_attachments(input_data, body.get("attachments"))

    def gen():
        try:
            yield from workflow_mod.execute_workflow_stream(wid, input_data)
        except Exception as e:
            yield f"data: {json.dumps({'error': f'未知错误: {e}'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.get("/api/workflows/{wid}/executions")
def api_workflow_executions(wid: str, limit: int = 50):
    """获取工作流执行历史"""
    return db.list_workflow_executions(wid, limit)


@app.get("/api/workflow/executions")
def api_all_workflow_executions(limit: int = 50):
    """获取所有工作流执行历史"""
    return db.list_workflow_executions(limit=limit)


@app.get("/api/workflow/executions/{eid}")
def api_workflow_execution_detail(eid: str):
    """获取工作流执行详情"""
    executions = db.list_workflow_executions()
    for e in executions:
        if e["id"] == eid:
            return e
    raise HTTPException(404, "执行记录不存在")


# ----- 工作流模板 -----
@app.get("/api/workflow/templates")
def api_list_workflow_templates(category: str = ""):
    """获取工作流模板列表"""
    return db.list_workflow_templates(category or None)


@app.get("/api/workflow/templates/{tid}")
def api_get_workflow_template(tid: str):
    """获取工作流模板详情"""
    tpl = db.get_workflow_template(tid)
    if not tpl:
        raise HTTPException(404, "模板不存在")
    return tpl


@app.post("/api/workflow/templates/{tid}/use")
def api_use_workflow_template(tid: str):
    """使用模板（从模板创建工作流）"""
    tpl = db.get_workflow_template(tid)
    if not tpl:
        raise HTTPException(404, "模板不存在")
    
    db.use_workflow_template(tid)
    
    # 从模板创建工作流
    wf_id = _gen_wf_id()
    wf = {
        "id": wf_id,
        "name": tpl["name"],
        "description": tpl.get("description", ""),
        "nodes": tpl.get("nodes", []),
        "edges": tpl.get("edges", []),
        "config": {},
        "enabled": True,
        "created_at": time.time(),
    }
    db.save_workflow(wf)
    
    return {"ok": True, "id": wf_id, "workflow": wf}


@app.post("/api/workflow/templates")
def api_save_workflow_template(body: dict):
    """保存工作流模板"""
    tpl_id = body.get("id") or f"tpl_{int(time.time() * 1000)}"
    body["id"] = tpl_id
    body.setdefault("created_at", time.time())
    conn = db.get_conn()
    conn.execute("""INSERT INTO workflow_templates (id, name, description, category, nodes, edges, icon, usage_count, created_at)
                    VALUES (?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(id) DO UPDATE SET
                      name=excluded.name, description=excluded.description, category=excluded.category,
                      nodes=excluded.nodes, edges=excluded.edges, icon=excluded.icon""",
                 (tpl_id, body.get("name", ""), body.get("description", ""),
                  body.get("category", "general"), json.dumps(body.get("nodes", [])),
                  json.dumps(body.get("edges", [])), body.get("icon", "🔧"),
                  body.get("usage_count", 0), body.get("created_at", time.time())))
    conn.commit()
    conn.close()
    return {"ok": True, "id": tpl_id}


@app.delete("/api/workflow/templates/{tid}")
def api_delete_workflow_template(tid: str):
    """删除工作流模板"""
    conn = db.get_conn()
    conn.execute("DELETE FROM workflow_templates WHERE id=?", (tid,))
    conn.commit()
    conn.close()
    return {"ok": True}


# ================= 智能体 =================
from agent_runtime import AgentManager, AgentConfig, MultiAgentOrchestrator

class AgentBody(BaseModel):
    id: str = ""
    name: str
    category: str = "general"
    icon: str = "🤖"
    description: str = ""
    system_prompt: str = ""
    model_preference: str = ""
    max_context: int = 128000
    temperature: float = 0.7
    top_p: float = 0.9
    builtin_tools: list = []
    skill_ids: list = []
    mcp_ids: list = []
    connector_ids: list = []
    workflow_id: str = ""
    kb_ids: list = []
    kb_top_k: int = 5
    kb_score_threshold: float = 0.5
    show_sources: bool = True
    memory_enabled: bool = True
    short_term_turns: int = 20
    long_term_summary_interval: int = 10
    user_profile_enabled: bool = True
    max_rounds: int = 10
    max_tokens_per_round: int = 4000
    stop_sequences: list = []
    sub_agents: list = []
    collaboration_mode: str = "sequential"
    prompt_templates: dict = {}
    response_format: str = "text"
    enable_reasoning: bool = False
    auto_approve_tools: bool = False
    enabled: bool = True


@app.get("/api/agents")
def api_list_agents(category: str = None):
    return AgentManager.list(category)


@app.get("/api/agents/{aid}")
def api_get_agent(aid: str):
    agent = AgentManager.get(aid)
    if not agent:
        raise HTTPException(404, "Agent not found")
    return agent.to_dict()


@app.post("/api/agents")
def api_create_agent(body: AgentBody):
    config = AgentConfig(**body.dict())
    AgentManager.create(config)
    return {"id": config.id}


@app.put("/api/agents/{aid}")
def api_update_agent(aid: str, body: AgentBody):
    existing = AgentManager.get(aid)
    if not existing:
        raise HTTPException(404, "Agent not found")
    if existing.is_builtin:
        raise HTTPException(400, "内置智能体不可修改")
    config = AgentConfig(**body.dict())
    config.id = aid
    config.version = existing.version
    config.created_by = existing.created_by
    config.created_at = existing.created_at
    AgentManager.update(config)
    return {"ok": True}


@app.delete("/api/agents/{aid}")
def api_delete_agent(aid: str):
    existing = AgentManager.get(aid)
    if not existing:
        raise HTTPException(404, "Agent not found")
    if existing.is_builtin:
        raise HTTPException(400, "内置智能体不可删除")
    AgentManager.delete(aid)
    return {"ok": True}


@app.post("/api/agents/{aid}/run")
def api_run_agent(aid: str, body: dict = Body(...)):
    """运行智能体（同步）"""
    user_input = body.get("message", "")
    session_id = body.get("session_id")
    user_id = body.get("user_id", "")
    attachments = body.get("attachments", [])
    
    runtime = AgentManager.create_runtime(aid, session_id, user_id)
    result = runtime.run_sync(user_input, attachments)
    return result


@app.post("/api/agents/{aid}/run_stream")
def api_run_agent_stream(aid: str, body: dict = Body(...)):
    """流式运行智能体（SSE）"""
    user_input = body.get("message", "")
    session_id = body.get("session_id")
    user_id = body.get("user_id", "")
    attachments = body.get("attachments", [])
    
    runtime = AgentManager.create_runtime(aid, session_id, user_id)
    
    def gen():
        try:
            for evt in runtime.run(user_input, attachments, stream=True):
                yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'error': str(e)}, ensure_ascii=False)}\n\n"
    
    return StreamingResponse(gen(), media_type="text/event-stream")


@app.post("/api/agents/multi/run")
def api_run_multi_agent(body: dict = Body(...)):
    """运行多Agent编排"""
    main_agent_id = body.get("main_agent_id")
    sub_agent_ids = body.get("sub_agent_ids", [])
    task = body.get("task", "")
    context = body.get("context", {})
    mode = body.get("mode")  # 可选：临时覆盖主Agent的协作模式
    
    if not main_agent_id:
        raise HTTPException(400, "缺少 main_agent_id")
    
    orchestrator = AgentManager.create_multi_agent_orchestrator(main_agent_id, sub_agent_ids)
    if mode in ("sequential", "parallel", "router", "planner_executor"):
        orchestrator.mode = mode
    result = orchestrator.execute(task, context)
    return result


# ================= 蜂群多 Agent（agno 引擎） =================
def _resolve_swarm_provider(provider_id: str = "") -> dict:
    """解析蜂群使用的供应商：优先指定 id，否则第一个启用的"""
    providers = db.list_providers()
    if not providers:
        raise HTTPException(400, "未配置模型供应商")
    if provider_id:
        for p in providers:
            if p["id"] == provider_id:
                return p
        raise HTTPException(404, f"供应商不存在: {provider_id}")
    return next((p for p in providers if p.get("enabled")), providers[0])


@app.get("/api/swarm/modes")
def api_swarm_modes():
    """蜂群支持的模式"""
    return {"modes": ["manager", "parallel", "pipeline", "debate"],
            "descriptions": {
                "manager": "蜂群：经理拆解任务，多名成员按依赖并行执行，最后汇总",
                "parallel": "全部成员并行处理同一任务",
                "pipeline": "链式顺序执行：前一个成员输出作为后一个的输入",
                "debate": "多名成员独立作答，综合评审给出结论",
            }}


@app.post("/api/swarm/run")
def api_swarm_run(body: dict = Body(...)):
    """运行蜂群多 Agent（同步）"""
    from swarm import SwarmRunner
    agent_ids = body.get("agent_ids", [])
    task = body.get("task", "")
    mode = body.get("mode", "manager")
    max_workers = body.get("max_workers", 4)
    provider_id = body.get("provider_id", "")
    manager_id = body.get("manager_id", "")
    merger_id = body.get("merger_id", "")
    model = body.get("model", "")  # 可选：覆盖蜂群使用的模型名

    if not agent_ids:
        raise HTTPException(400, "缺少 agent_ids")
    if not task:
        raise HTTPException(400, "缺少 task")

    configs = []
    for aid in agent_ids:
        cfg = AgentManager.get(aid)
        if cfg:
            configs.append(cfg)
    if not configs:
        raise HTTPException(404, "智能体不存在")

    provider = _resolve_swarm_provider(provider_id)
    runner = SwarmRunner(provider, configs, mode=mode, max_workers=max_workers,
                          manager_id=manager_id, merger_id=merger_id, model=model)
    return runner.run_sync(task, body.get("context", {}))


@app.post("/api/swarm/run_stream")
def api_swarm_run_stream(body: dict = Body(...)):
    """运行蜂群多 Agent（SSE 流式）"""
    from swarm import SwarmRunner
    agent_ids = body.get("agent_ids", [])
    task = body.get("task", "")
    mode = body.get("mode", "manager")
    max_workers = body.get("max_workers", 4)
    provider_id = body.get("provider_id", "")
    manager_id = body.get("manager_id", "")
    merger_id = body.get("merger_id", "")
    model = body.get("model", "")  # 可选：覆盖蜂群使用的模型名

    if not agent_ids:
        raise HTTPException(400, "缺少 agent_ids")
    if not task:
        raise HTTPException(400, "缺少 task")

    configs = []
    for aid in agent_ids:
        cfg = AgentManager.get(aid)
        if cfg:
            configs.append(cfg)
    if not configs:
        raise HTTPException(404, "智能体不存在")

    provider = _resolve_swarm_provider(provider_id)
    runner = SwarmRunner(provider, configs, mode=mode, max_workers=max_workers,
                          manager_id=manager_id, merger_id=merger_id, model=model)

    def gen():
        try:
            for evt in runner.run(task, body.get("context", {})):
                yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'error': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


# ================= 工具列表 =================
@app.get("/api/tools")
def api_tools():
    return build_tools(None)


# ================= 前端静态文件 =================
from fastapi.responses import FileResponse as _FR

@app.get("/")
def index():
    resp = _FR(FRONTEND_DIR / "index.html")
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp


app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

# 自定义静态文件：给所有前端资源加 no-cache
from starlette.staticfiles import StaticFiles as _SF

class NoCacheStaticFiles(_SF):
    async def get_response(self, path, scope):
        resp = await super().get_response(path, scope)
        if not path.endswith(".html"):
            resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        return resp

app.mount("/", NoCacheStaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "8900"))

    if getattr(sys, 'frozen', False) and os.name in ("nt", "posix"):
        # 桌面应用模式（默认，Windows/macOS 均适用）：打开原生态应用窗口，
        # Windows 用 WebView2、macOS 用 Cocoa/WebKit（pywebview），而非浏览器标签页
        if os.environ.get("ABCODE_DESKTOP", "1") == "1":
            try:
                from desktop_shell import run as run_desktop
                run_desktop(app, host="127.0.0.1", port=port)
                sys.exit(0)
            except Exception as _e:
                print(f"[ABcode] 桌面壳不可用（{_e}），回退浏览器模式")

        # 若 8900 已有服务在运行（上次实例未退出）：直接复用并打开浏览器，避免端口冲突崩溃
        try:
            import urllib.request
            urllib.request.urlopen(f"http://127.0.0.1:{port}", timeout=1)
            import webbrowser
            webbrowser.open(f"http://127.0.0.1:{port}")
            sys.exit(0)
        except Exception:
            pass

        # 服务起来后自动打开浏览器，避免用户只见黑窗口/无反应
        if os.environ.get("ABCODE_NO_BROWSER", "0") != "1":
            import threading

            def _open_browser_when_ready():
                import urllib.request
                url = f"http://127.0.0.1:{port}"
                for _ in range(20):
                    time.sleep(1)
                    try:
                        urllib.request.urlopen(url, timeout=2)
                        break
                    except Exception:
                        continue
                try:
                    import webbrowser
                    webbrowser.open(url)
                except Exception:
                    pass

            threading.Thread(target=_open_browser_when_ready, daemon=True).start()

    uvicorn.run(app, host="0.0.0.0", port=port)
