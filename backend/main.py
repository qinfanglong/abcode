"""ABcode - AI Agent 工具主入口 v0.3.0"""
import json
import os
import time
import uuid
import mimetypes
from pathlib import Path
from fastapi import FastAPI, HTTPException, UploadFile, File, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import db
import llm
import agent
import rag
import cron as cron_mod
import skills as skills_mod
import mcp_client
import connector as connector_mod
import updater
import workflow as workflow_mod

app = FastAPI(title="ABcode", version=updater.VERSION)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

FRONTEND_DIR = Path(os.environ.get("ABCODE_FRONTEND", Path(__file__).parent.parent / "frontend"))
UPLOAD_DIR = Path(os.environ.get("ABCODE_UPLOADS", Path(__file__).parent.parent / "data" / "uploads"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


@app.on_event("startup")
def startup():
    db.init_db()
    rag.init_kb()
    cron_mod.init_cron()
    skills_mod.init_builtins()
    connector_mod.init_builtins()
    db.init_channels_table()
    db.init_workflows_table()
    app.state.scheduler = cron_mod.start_scheduler(run_cron_job)
    
    # 启动自动更新检查（每24小时检查一次）
    settings = db.get_all_settings()
    if settings.get("auto_update_enabled", "true").lower() == "true":
        interval = int(settings.get("auto_update_interval", "24"))
        updater.start_auto_check(interval)


def run_cron_job(job):
    """定时任务执行：调用模型，结果写入会话"""
    providers = db.list_providers()
    if not providers:
        return "无可用供应商"
    provider = next((p for p in providers if p["id"] == job["provider_id"]), None)
    if not provider:
        provider = next((p for p in providers if p["enabled"]), providers[0])
    model = job["model"] or provider.get("default_model", "") or (provider["models"][0] if provider.get("models") else "")
    if not model:
        return "未配置模型"
    messages = [{"role": "system", "content": "你是 ABcode，执行定时任务。"},
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
        
        return {"ok": False, "msg": f"HTTP {resp.status_code}", "models": []}
    except Exception as e:
        return {"ok": False, "msg": str(e), "models": []}


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


# ================= 专家套件 =================
class ExpertBody(BaseModel):
    id: str = ""
    name: str
    category: str = "general"
    icon: str = "🤖"
    description: str = ""
    system_prompt: str = ""
    tools: list = []
    model_preference: str = ""
    max_context: int = 0
    enabled: bool = True


@app.get("/api/experts")
def api_list_experts(category: str = None):
    return db.list_experts(category)


@app.get("/api/experts/{eid}")
def api_get_expert(eid: str):
    e = db.get_expert(eid)
    if not e:
        raise HTTPException(404, "Expert not found")
    return e


@app.post("/api/experts")
def api_create_expert(body: ExpertBody):
    eid = body.id or f"exp_{uuid.uuid4().hex[:8]}"
    db.upsert_expert({
        "id": eid, "name": body.name, "category": body.category, "icon": body.icon,
        "description": body.description, "system_prompt": body.system_prompt,
        "tools": body.tools, "model_preference": body.model_preference,
        "max_context": body.max_context, "enabled": body.enabled, "is_builtin": False,
    })
    return {"id": eid}


@app.put("/api/experts/{eid}")
def api_update_expert(eid: str, body: ExpertBody):
    e = db.get_expert(eid)
    is_builtin = e.get("is_builtin", False) if e else False
    db.upsert_expert({
        "id": eid, "name": body.name, "category": body.category, "icon": body.icon,
        "description": body.description, "system_prompt": body.system_prompt,
        "tools": body.tools, "model_preference": body.model_preference,
        "max_context": body.max_context, "enabled": body.enabled, "is_builtin": is_builtin,
    })
    return {"ok": True}


@app.delete("/api/experts/{eid}")
def api_delete_expert(eid: str):
    db.delete_expert(eid)
    return {"ok": True}


@app.post("/api/experts/{eid}/use")
def api_use_expert(eid: str):
    db.record_expert_usage(eid)
    return {"ok": True}


@app.post("/api/experts/{eid}/apply")
def api_apply_expert(eid: str, body: dict = None):
    """应用专家配置到当前会话"""
    e = db.get_expert(eid)
    if not e:
        raise HTTPException(404, "Expert not found")
    db.record_expert_usage(eid)
    return {
        "ok": True,
        "expert": e,
        "system_prompt": e.get("system_prompt", ""),
        "tools": e.get("tools", []),
        "model_preference": e.get("model_preference", ""),
    }


# ================= 搜索引擎 =================
from search_engine.engine import search as engine_search

class SearchBody(BaseModel):
    query: str
    engine: str = "bing"
    max_results: int = 10

@app.post("/api/search")
def api_search(body: SearchBody):
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

    # 根据开关决定是否启用知识库检索
    rag_context = rag.build_context(body.message) if body.kb_enabled else None

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
    messages = agent.build_messages(body.history, body.message, rag_context, body.thinking_mode)
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
            ok, result = dispatch_tool(name, args)
            yield f"data: {json.dumps({'tool_result': {'name': name, 'ok': ok, 'result': result[:2000]}}, ensure_ascii=False)}\n\n"
            tool_results_msgs.append({
                "role": "tool",
                "tool_call_id": tc.get("id", f"{name}_{round_idx}"),
                "content": json.dumps({"ok": ok, "result": result}, ensure_ascii=False),
            })

        messages.extend(tool_results_msgs)

    yield f"data: {json.dumps({'error': '工具调用轮数超限'}, ensure_ascii=False)}\n\n"


# ================= 知识库 RAG =================
@app.get("/api/kb/docs")
def api_kb_docs():
    return rag.list_docs()


@app.post("/api/kb/upload")
async def api_kb_upload(file: UploadFile = File(...)):
    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(400, "文件过大（>10MB）")
    doc_id, n = rag.add_document(file.filename, content)
    if not doc_id:
        raise HTTPException(400, "文档内容过少，无法建立知识库")
    return {"id": doc_id, "chunks": n, "name": file.filename}


@app.delete("/api/kb/docs/{doc_id}")
def api_kb_delete(doc_id: str):
    rag.delete_doc(doc_id)
    return {"ok": True}


@app.post("/api/kb/search")
def api_kb_search(body: dict):
    query = body.get("query", "")
    top_k = int(body.get("top_k", 5))
    return rag.search(query, top_k)


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


# ================= 会话工具配置 =================
class ConvToolsBody(BaseModel):
    skill_ids: list = None
    mcp_ids: list = None
    connector_ids: list = None


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
    db.set_conv_tools(cid, body.skill_ids, body.mcp_ids, body.connector_ids)
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
    search_engine = body.get("search_engine", "searxng")
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


@app.post("/api/workflows")
def api_save_workflow(body: dict):
    """保存工作流（创建或更新）"""
    wf_id = body.get("id") or f"wf_{int(time.time() * 1000)}"
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
    input_data = body.get("input", {})
    result = workflow_mod.execute_workflow(wid, input_data)
    return result


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
    wf_id = f"wf_{int(time.time() * 1000)}"
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


# ================= 工具列表 =================
@app.get("/api/tools")
def api_tools():
    return build_tools(None)


# ================= 前端静态文件 =================
@app.get("/")
def index():
    return FileResponse(FRONTEND_DIR / "index.html")


app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "8900"))
    uvicorn.run(app, host="0.0.0.0", port=port)
