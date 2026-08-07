"""ABcode Agent 运行时 - 智能体配置、多Agent协作、记忆、执行引擬SVG代码开发助手、深度研究员、数据分析师、系统架构师、产品经理、内容创作专家、安全审计专家、专业翻译官
核心能力：
- Agent 定义：系统提示词、模型偏好、工具集、知识库、记忆策略
- 多Agent协作：Planner/Executor、顺序/并行/路由编排
- 记忆系统：短期对话历史、长期用户画像、实体记忆
- 运行时：状态机、断点续跑、流式事件、人工介入
"""
import json
import time
import uuid
import os
import threading
import sqlite3
from pathlib import Path
from typing import Dict, List, Any, Optional, Callable, Generator
from dataclasses import dataclass, field, asdict
from enum import Enum
from copy import deepcopy

import db
import llm
import rag
import agent
import skills as skills_mod
import mcp_client
import connector as connector_mod
from workflow_mod import WorkflowEngine


# ============================================================================
# 核心数据结构
# ============================================================================

class AgentStatus(Enum):
    IDLE = "idle"
    RUNNING = "running"
    WAITING_TOOL = "waiting_tool"
    WAITING_HUMAN = "waiting_human"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"


class MemoryType(Enum):
    SHORT_TERM = "short_term"      # 对话轮次
    LONG_TERM = "long_term"        # 用户画像、偏好
    ENTITY = "entity"              # 实体/事实记忆
    EPISODIC = "episodic"          # 事件/经历记忆
    SEMANTIC = "semantic"          # 语义知识


@dataclass
class AgentConfig:
    """智能体配置 - 对标百炼 Agent 定义"""
    id: str = ""
    name: str = "未命名智能体"
    description: str = ""
    icon: str = "🤖"
    category: str = "general"
    
    # 核心能力
    system_prompt: str = ""
    model_preference: str = ""           # 指定模型，空=自动
    max_context: int = 128000
    temperature: float = 0.7
    top_p: float = 0.9
    
    # 工具与技能
    builtin_tools: List[str] = field(default_factory=list)     # 内置工具名
    skill_ids: List[str] = field(default_factory=list)         # 技能插件
    mcp_ids: List[str] = field(default_factory=list)           # MCP 服务
    connector_ids: List[str] = field(default_factory=list)     # 数据连接器
    workflow_id: str = ""                                      # 绑定工作流
    
    # 知识库
    kb_ids: List[str] = field(default_factory=list)
    kb_top_k: int = 5
    kb_score_threshold: float = 0.5
    
    # 记忆策略
    memory_enabled: bool = True
    short_term_turns: int = 20           # 保留轮次
    long_term_summary_interval: int = 10  # 每 N 轮生成摘要
    user_profile_enabled: bool = True
    
    # 执行控制
    max_rounds: int = 10                 # 最大工具调用轮数
    max_tokens_per_round: int = 4000
    stop_sequences: List[str] = field(default_factory=list)
    
    # 多Agent协作
    sub_agents: List[str] = field(default_factory=list)  # 子Agent ID
    collaboration_mode: str = "sequential"  # sequential/parallel/router/planner_executor
    
    # 高级
    prompt_templates: Dict[str, str] = field(default_factory=dict)  # 提示词模板
    response_format: str = "text"        # text/json/markdown
    enable_reasoning: bool = False       # 显式推理模式
    auto_approve_tools: bool = False     # 自动批准工具调用
    
    # 元数据
    is_builtin: bool = False
    enabled: bool = True
    version: int = 1
    created_by: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    
    def to_dict(self) -> dict:
        d = asdict(self)
        return d
    
    @classmethod
    def from_dict(cls, d: dict) -> "AgentConfig":
        return cls(**{k: v for k, v in d.items() if k in cls.__annotations__})


@dataclass
class AgentState:
    """Agent 运行时状态"""
    agent_id: str
    session_id: str
    status: AgentStatus = AgentStatus.IDLE
    current_round: int = 0
    total_tokens: int = 0
    
    # 消息历史（短期记忆）
    messages: List[dict] = field(default_factory=list)
    
    # 变量上下文
    variables: Dict[str, Any] = field(default_factory=dict)
    
    # 工具调用栈
    tool_calls_stack: List[dict] = field(default_factory=list)
    
    # 等待人工介入
    pending_human_input: Optional[dict] = None
    
    # 子Agent 状态
    sub_agent_states: Dict[str, "AgentState"] = field(default_factory=dict)
    
    # 执行轨迹（用于调试/回放）
    trace: List[dict] = field(default_factory=list)
    
    # 错误信息
    last_error: str = ""
    
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    
    def to_dict(self) -> dict:
        d = asdict(self)
        d["status"] = self.status.value
        return d
    
    @classmethod
    def from_dict(cls, d: dict) -> "AgentState":
        d = d.copy()
        d["status"] = AgentStatus(d.get("status", "idle"))
        return cls(**d)


@dataclass
class MemoryEntry:
    """记忆条目"""
    id: str
    type: MemoryType
    session_id: str
    agent_id: str
    user_id: str = ""
    
    # 内容
    key: str = ""
    content: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    # 向量检索用
    embedding: List[float] = field(default_factory=list)
    
    # 时间
    importance: float = 1.0
    access_count: int = 0
    last_accessed: float = field(default_factory=time.time)
    created_at: float = field(default_factory=time.time)
    expires_at: float = 0  # 0=永不过期
    
    def to_dict(self) -> dict:
        d = asdict(self)
        d["type"] = self.type.value
        return d


# ============================================================================
# 记忆管理器
# ============================================================================

class MemoryManager:
    """记忆管理 - 短期/长期/实体/语义记忆"""
    
    def __init__(self, agent_config: AgentConfig):
        self.config = agent_config
        self._cache: Dict[str, List[MemoryEntry]] = {}
    
    def _get_conn(self):
        return db.get_conn()
    
    def _ensure_tables(self):
        conn = self._get_conn()
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS agent_memories (
            id TEXT PRIMARY KEY,
            agent_id TEXT,
            session_id TEXT,
            user_id TEXT,
            type TEXT,
            key TEXT,
            content TEXT,
            role TEXT DEFAULT '',
            metadata TEXT DEFAULT '{}',
            embedding TEXT DEFAULT '[]',
            importance REAL DEFAULT 1.0,
            access_count INTEGER DEFAULT 0,
            last_accessed REAL,
            created_at REAL,
            expires_at REAL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_mem_agent_session ON agent_memories(agent_id, session_id);
        CREATE INDEX IF NOT EXISTS idx_mem_user ON agent_memories(user_id);
        CREATE INDEX IF NOT EXISTS idx_mem_type ON agent_memories(type);
        """)
        # 迁移：添加 role 列
        try:
            conn.execute("SELECT role FROM agent_memories LIMIT 1")
        except sqlite3.OperationalError:
            conn.execute("ALTER TABLE agent_memories ADD COLUMN role TEXT DEFAULT ''")
        conn.commit()
        conn.close()
    
    def add(self, entry: MemoryEntry) -> str:
        """添加记忆"""
        self._ensure_tables()
        conn = self._get_conn()
        conn.execute("""INSERT INTO agent_memories 
            (id, agent_id, session_id, user_id, type, key, content, metadata, embedding, importance, access_count, last_accessed, created_at, expires_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (entry.id, entry.agent_id, entry.session_id, entry.user_id,
             entry.type.value, entry.key, entry.content,
             json.dumps(entry.metadata), json.dumps(entry.embedding),
             entry.importance, entry.access_count, entry.last_accessed,
             entry.created_at, entry.expires_at))
        conn.commit()
        conn.close()
        return entry.id
    
    def get(self, memory_id: str) -> Optional[MemoryEntry]:
        self._ensure_tables()
        conn = self._get_conn()
        row = conn.execute("SELECT * FROM agent_memories WHERE id=?", (memory_id,)).fetchone()
        conn.close()
        if not row:
            return None
        return self._row_to_entry(row)
    
    def search(self, agent_id: str, session_id: str = "", user_id: str = "",
               memory_type: MemoryType = None, query: str = "",
               limit: int = 10) -> List[MemoryEntry]:
        """检索记忆（关键词+向量混合，简化版仅关键词）"""
        self._ensure_tables()
        conn = self._get_conn()
        
        sql = "SELECT * FROM agent_memories WHERE agent_id=?"
        params = [agent_id]
        
        if session_id:
            sql += " AND session_id=?"
            params.append(session_id)
        if user_id:
            sql += " AND user_id=?"
            params.append(user_id)
        if memory_type:
            sql += " AND type=?"
            params.append(memory_type.value)
        if query:
            sql += " AND (content LIKE ? OR key LIKE ?)"
            params.extend([f"%{query}%", f"%{query}%"])
        
        sql += " ORDER BY importance DESC, last_accessed DESC LIMIT ?"
        params.append(limit)
        
        rows = conn.execute(sql, params).fetchall()
        conn.close()
        return [self._row_to_entry(r) for r in rows]
    
    def get_short_term(self, session_id: str, agent_id: str, turns: int = None) -> List[dict]:
        """获取短期对话历史"""
        turns = turns or self.config.short_term_turns
        conn = self._get_conn()
        rows = conn.execute("""
            SELECT role, content, created_at FROM agent_memories
            WHERE agent_id=? AND session_id=? AND type=?
            ORDER BY created_at DESC LIMIT ?
        """, (agent_id, session_id, MemoryType.SHORT_TERM.value, turns * 2)).fetchall()
        conn.close()
        # 转为 messages 格式（倒序取后正序）
        msgs = []
        for r in reversed(rows):
            msgs.append({"role": r["role"], "content": r["content"]})
        return msgs
    
    def save_conversation_turn(self, session_id: str, agent_id: str, user_id: str,
                               user_msg: str, assistant_msg: str):
        """保存一轮对话到短期记忆"""
        turn_id = f"turn_{int(time.time()*1000)}"
        # 用户消息
        self.add(MemoryEntry(
            id=f"{turn_id}_user", type=MemoryType.SHORT_TERM,
            session_id=session_id, agent_id=agent_id, user_id=user_id,
            key="user", content=user_msg, metadata={"turn_id": turn_id}
        ))
        # 助手消息
        self.add(MemoryEntry(
            id=f"{turn_id}_assistant", type=MemoryType.SHORT_TERM,
            session_id=session_id, agent_id=agent_id, user_id=user_id,
            key="assistant", content=assistant_msg, metadata={"turn_id": turn_id}
        ))
        
        # 定期生成长期摘要
        if self.config.long_term_summary_interval > 0:
            self._maybe_generate_summary(session_id, agent_id, user_id)
    
    def _maybe_generate_summary(self, session_id: str, agent_id: str, user_id: str):
        """生成长期记忆摘要"""
        conn = self._get_conn()
        count = conn.execute("""
            SELECT COUNT(*) as c FROM agent_memories
            WHERE agent_id=? AND session_id=? AND type=?
        """, (agent_id, session_id, MemoryType.SHORT_TERM.value)).fetchone()["c"]
        conn.close()
        
        if count % (self.config.long_term_summary_interval * 2) == 0:
            # 触发生成摘要（异步）
            pass
    
    def update_user_profile(self, user_id: str, agent_id: str, profile: Dict[str, Any]):
        """更新用户画像（长期记忆）"""
        for key, value in profile.items():
            self.add(MemoryEntry(
                id=f"profile_{user_id}_{key}_{int(time.time())}",
                type=MemoryType.LONG_TERM,
                session_id="", agent_id=agent_id, user_id=user_id,
                key=f"profile.{key}", content=json.dumps(value, ensure_ascii=False),
                metadata={"profile_key": key}, importance=2.0
            ))
    
    def get_user_profile(self, user_id: str, agent_id: str) -> Dict[str, Any]:
        """获取用户画像"""
        entries = self.search(agent_id, user_id=user_id, memory_type=MemoryType.LONG_TERM, query="profile", limit=50)
        profile = {}
        for e in entries:
            if e.key.startswith("profile."):
                k = e.key.split(".", 1)[1]
                try:
                    profile[k] = json.loads(e.content)
                except:
                    profile[k] = e.content
        return profile
    
    def _row_to_entry(self, row) -> MemoryEntry:
        d = dict(row)
        d["type"] = MemoryType(d["type"])
        d["metadata"] = json.loads(d["metadata"] or "{}")
        d["embedding"] = json.loads(d["embedding"] or "[]")
        return MemoryEntry(**d)
    
    def cleanup_expired(self, agent_id: str):
        """清理过期记忆"""
        self._ensure_tables()
        conn = self._get_conn()
        conn.execute("DELETE FROM agent_memories WHERE agent_id=? AND expires_at>0 AND expires_at<?",
                     (agent_id, time.time()))
        conn.commit()
        conn.close()


# ============================================================================
# 工具注册表 - 整合内置/技能/MCP/连接器
# ============================================================================

class ToolRegistry:
    """统一工具注册表"""
    
    def __init__(self, agent_config: AgentConfig):
        self.config = agent_config
        self._tool_map: Dict[str, dict] = {}  # name -> tool_def
        self._executor_map: Dict[str, tuple] = {}  # name -> (type, name)
        self._built_tools = False
    
    def build(self) -> List[dict]:
        """构建 OpenAI tools 格式列表"""
        if self._built_tools:
            return list(self._tool_map.values())
        
        tools = []
        
        # 1. 内置工具
        for tool_name in self.config.builtin_tools:
            if tool_name in self._tool_map:
                continue
            if tool_name in agent.TOOL_NAMES:
                t = next(t for t in agent.TOOLS if t["function"]["name"] == tool_name)
                tools.append(t)
                self._tool_map[tool_name] = t
                self._executor_map[tool_name] = ("builtin", tool_name)
        
        # 2. 技能插件工具
        if self.config.skill_ids:
            skill_tools = skills_mod.skill_tools_for(self.config.skill_ids)
            for t in skill_tools:
                name = t["function"]["name"]
                if name in self._tool_map:
                    continue
                tools.append(t)
                self._tool_map[name] = t
                self._executor_map[name] = ("skill", name)
        
        # 3. MCP 工具
        if self.config.mcp_ids:
            mcp_tools = mcp_client.mcp_tools_for(self.config.mcp_ids)
            for t in mcp_tools:
                name = t["function"]["name"]
                if name in self._tool_map:
                    continue
                tools.append(t)
                self._tool_map[name] = t
                self._executor_map[name] = ("mcp", name)
        
        # 4. 数据连接器工具
        if self.config.connector_ids:
            conn_tools = connector_mod.connector_tools_for(self.config.connector_ids)
            for t in conn_tools:
                name = t["function"]["name"]
                if name in self._tool_map:
                    continue
                tools.append(t)
                self._tool_map[name] = t
                self._executor_map[name] = ("connector", name)
        
        # 4.5 绑定工作流工具
        if self.config.workflow_id and "run_workflow" not in self._tool_map:
            wf_tool = {
                "type": "function",
                "function": {
                    "name": "run_workflow",
                    "description": "运行绑定的工作流，input 为工作流入参（JSON 对象）",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "input": {"type": "object", "description": "工作流输入参数，键为开始节点配置的 input_fields"}
                        },
                        "required": ["input"]
                    }
                }
            }
            tools.append(wf_tool)
            self._tool_map["run_workflow"] = wf_tool
            self._executor_map["run_workflow"] = ("workflow", self.config.workflow_id)
        
        self._built_tools = True
        return tools
    
    def execute(self, tool_name: str, args: dict) -> tuple:
        """执行工具"""
        if tool_name not in self._executor_map:
            return False, f"工具未注册: {tool_name}"
        
        exec_type, exec_name = self._executor_map[tool_name]
        
        try:
            if exec_type == "builtin":
                return agent.execute_tool(exec_name, args)
            elif exec_type == "skill":
                smap = skills_mod.build_tool_map()
                if exec_name in smap:
                    return skills_mod.execute_skill_tool(smap[exec_name][1], exec_name, args)
                return False, f"技能工具不存在: {exec_name}"
            elif exec_type == "mcp":
                mmap = mcp_client.build_tool_map()
                if exec_name in mmap:
                    return mcp_client.execute_mcp_tool(mmap[exec_name][1], exec_name, args)
                return False, f"MCP工具不存在: {exec_name}"
            elif exec_type == "connector":
                cmap = connector_mod.build_tool_map()
                if exec_name in cmap:
                    return connector_mod.execute_connector_tool(cmap[exec_name][1], exec_name, args)
                return False, f"连接器工具不存在: {exec_name}"
            elif exec_type == "workflow":
                from workflow_mod import execute_workflow
                result = execute_workflow(exec_name, args.get("input") or {})
                if result.get("success"):
                    return True, result.get("output", "")
                return False, result.get("error", "工作流执行失败")
        except Exception as e:
            return False, f"工具执行异常: {e}"
        
        return False, f"未知执行类型: {exec_type}"
    
    def get_tool_def(self, name: str) -> Optional[dict]:
        return self._tool_map.get(name)


# ============================================================================
# Agent 运行时引擎
# ============================================================================

class AgentRuntime:
    """Agent 执行引擎 - 核心运行循环"""
    
    def __init__(self, agent_config: AgentConfig, session_id: str = None, user_id: str = ""):
        self.config = agent_config
        self.session_id = session_id or f"sess_{int(time.time()*1000)}"
        self.user_id = user_id
        
        # 组件
        self.memory = MemoryManager(agent_config)
        self.tools = ToolRegistry(agent_config)
        
        # 状态
        self.state = AgentState(
            agent_id=agent_config.id,
            session_id=self.session_id,
            status=AgentStatus.IDLE
        )
        
        # 事件回调
        self.event_callbacks: List[Callable[[str, dict], None]] = []
        
        # 线程锁
        self._lock = threading.RLock()
        
        # 供应商/模型缓存
        self._provider = None
        self._model = None
    
    def on_event(self, callback: Callable[[str, dict], None]):
        """注册事件回调：event_type, data"""
        self.event_callbacks.append(callback)
    
    def _emit(self, event_type: str, data: dict):
        for cb in self.event_callbacks:
            try:
                cb(event_type, data)
            except Exception:
                pass
    
    def _pick_provider_model(self) -> tuple:
        """选择供应商和模型"""
        if self._provider and self._model:
            return self._provider, self._model
        
        providers = db.list_providers()
        if not providers:
            raise RuntimeError("未配置模型供应商")
        
        model = self.config.model_preference
        if model:
            for p in providers:
                if model in (p.get("models") or []):
                    self._provider, self._model = p, model
                    return p, model
            for p in providers:
                if p.get("default_model") == model:
                    self._provider, self._model = p, model
                    return p, model
        
        p = next((x for x in providers if x.get("enabled")), providers[0])
        m = p.get("default_model", "") or (p.get("models") or [""])[0]
        self._provider, self._model = p, m
        return p, m
    
    def _build_system_prompt(self) -> str:
        """构建系统提示词"""
        from time_utils import get_current_time_str, TIME_PROMPT_TPL
        prompt = self.config.system_prompt or (
            "你是 ABcode 智能体助手。你可以使用工具完成任务："
            "联网搜索、抓取网页、读写文件、执行命令、查询数据库。"
            "需要时主动调用工具，不要编造信息。回答用中文，简洁清晰。"
        )
        # 注入实时时间
        prompt += TIME_PROMPT_TPL.format(time=get_current_time_str())
        
        # 推理模式
        if self.config.enable_reasoning:
            prompt += (
                "\n\n请先在 <reasoning> 标签内展示思考过程（分析、规划、权衡），"
                "然后再给出最终回答。格式：\n<reasoning>\n...\n</reasoning>\n\n回答..."
            )
        
        # 记忆/用户画像
        if self.config.memory_enabled and self.config.user_profile_enabled:
            profile = self.memory.get_user_profile(self.user_id, self.config.id)
            if profile:
                prompt += f"\n\n用户画像：{json.dumps(profile, ensure_ascii=False)}"
        
        return prompt
    
    def _build_messages(self, user_input: str, attachments: List[dict] = None) -> List[dict]:
        """构建消息列表：系统提示 + 短期记忆 + RAG + 当前输入"""
        messages = [{"role": "system", "content": self._build_system_prompt()}]
        
        # 短期记忆
        if self.config.memory_enabled:
            history = self.memory.get_short_term(self.session_id, self.config.id, self.config.short_term_turns)
            messages.extend(history)
        
        # RAG 知识库
        rag_context = ""
        self._last_sources = []
        if self.config.kb_ids:
            results = []
            for kb_id in self.config.kb_ids:
                try:
                    results.extend(rag.search(user_input, top_k=self.config.kb_top_k, kb_id=kb_id,
                                              min_score=self.config.kb_score_threshold))
                except Exception:
                    continue
            results.sort(key=lambda r: -r["score"])
            results = results[:self.config.kb_top_k]
            if results:
                lines = []
                for i, r in enumerate(results):
                    lines.append(f"[{i+1}] 《{r['doc_name']}》 相关度{r['score']:.2f}\n{r['content']}")
                    self._last_sources.append({
                        "doc_id": r.get("doc_id", ""),
                        "doc_name": r.get("doc_name", ""),
                        "score": r.get("score", 0),
                        "snippet": r.get("snippet", r.get("content", ""))[:200],
                    })
                if lines:
                    rag_context = "\n\n".join(lines)
        
        # 当前用户输入（支持多模态附件）
        content = user_input
        if attachments:
            content = self._build_multimodal_content(user_input, attachments)
        
        messages.append({"role": "user", "content": content})
        
        # RAG 作为系统消息追加
        if rag_context:
            messages.insert(1, {"role": "system", "content": f"参考资料：\n{rag_context}"})
        
        return messages
    
    def _build_multimodal_content(self, text: str, attachments: List[dict]) -> List[dict]:
        base = os.environ.get("ABCODE_PUBLIC_BASE", "http://127.0.0.1:8900")
        content = [{"type": "text", "text": text or ""}]
        for att in attachments:
            mime = att.get("mime", att.get("type", ""))
            url = f"{base}/uploads/{att.get('filename', '')}"
            if mime.startswith("image/"):
                content.append({"type": "image_url", "image_url": {"url": url}})
            elif mime.startswith("video/"):
                content.append({"type": "text", "text": f"[视频: {att.get('filename')}]"})
            elif mime.startswith("audio/"):
                content.append({"type": "text", "text": f"[音频: {att.get('filename')}]"})
            else:
                content.append({"type": "text", "text": f"[文件: {att.get('filename')}]"})
        return content
    
    def run(self, user_input: str, attachments: List[dict] = None,
            stream: bool = True) -> Generator[dict, None, None]:
        """运行 Agent - 同步生成器"""
        with self._lock:
            self.state.status = AgentStatus.RUNNING
            self.state.current_round = 0
            self._emit("agent_start", {"session_id": self.session_id, "input": user_input})
        
        try:
            tools = self.tools.build()
            provider, model = self._pick_provider_model()
            
            for round_idx in range(self.config.max_rounds):
                with self._lock:
                    self.state.current_round = round_idx + 1
                    self._emit("round_start", {"round": round_idx + 1})
                
                messages = self._build_messages(user_input if round_idx == 0 else "", attachments if round_idx == 0 else None)
                
                # 调用 LLM
                assistant_parts = []
                tool_calls = []
                
                for evt in llm.stream_chat(provider, model, messages, tools=tools):
                    if evt["type"] == "text":
                        assistant_parts.append(evt["content"])
                        if stream:
                            yield {"type": "delta", "content": evt["content"]}
                    elif evt["type"] == "tool_calls":
                        tool_calls = evt["tool_calls"]
                    elif evt["type"] == "usage":
                        with self._lock:
                            self.state.total_tokens += evt.get("total_tokens", 0) or 0
                
                text = "".join(assistant_parts)
                
                # 保存助手消息
                with self._lock:
                    self.state.messages.append({"role": "assistant", "content": text})
                    self._emit("assistant_message", {"content": text})
                
                if text.strip() and self.config.memory_enabled:
                    self.memory.save_conversation_turn(
                        self.session_id, self.config.id, self.user_id,
                        user_input if round_idx == 0 else "", text
                    )
                
                if not tool_calls:
                    # 结束
                    with self._lock:
                        self.state.status = AgentStatus.COMPLETED
                    yield {"type": "done", "content": text, "total_tokens": self.state.total_tokens,
                           "sources": getattr(self, "_last_sources", [])}
                    return
                
                # 执行工具
                for tc in tool_calls:
                    name = tc.get("name", "")
                    args_str = tc.get("args", "{}")
                    try:
                        args = json.loads(args_str) if args_str else {}
                    except:
                        args = {}
                    
                    with self._lock:
                        self.state.tool_calls_stack.append({"name": name, "args": args, "id": tc.get("id")})
                        self._emit("tool_start", {"name": name, "args": args, "call_id": tc.get("id")})
                    
                    ok, result = self.tools.execute(name, args)
                    
                    result_text = result[:2000] if isinstance(result, str) else json.dumps(result, ensure_ascii=False)[:2000]
                    
                    with self._lock:
                        self._emit("tool_result", {"name": name, "ok": ok, "result": result_text, "call_id": tc.get("id")})
                    
                    # 工具结果加入消息
                    messages.append({"role": "assistant", "content": text})
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.get("id", f"{name}_{round_idx}"),
                        "content": json.dumps({"ok": ok, "result": result}, ensure_ascii=False)
                    })
                    
                    # 记录轨迹
                    with self._lock:
                        self.state.trace.append({
                            "round": round_idx + 1,
                            "tool": name,
                            "args": args,
                            "result": result_text,
                            "ok": ok,
                            "timestamp": time.time()
                        })
                
                # 继续下一轮（user_input 置空，继续对话）
                user_input = ""
            
            # 达到最大轮数
            with self._lock:
                self.state.status = AgentStatus.FAILED
                self.state.last_error = "超过最大工具调用轮数"
            yield {"type": "error", "error": "超过最大工具调用轮数"}
            
        except Exception as e:
            with self._lock:
                self.state.status = AgentStatus.FAILED
                self.state.last_error = str(e)
            yield {"type": "error", "error": str(e)}
    
    def run_sync(self, user_input: str, attachments: List[dict] = None) -> dict:
        """同步运行，返回最终结果"""
        final_text = ""
        for evt in self.run(user_input, attachments, stream=False):
            if evt["type"] == "delta":
                final_text += evt["content"]
            elif evt["type"] == "done":
                return {"success": True, "output": final_text or evt.get("content", ""), "tokens": evt.get("total_tokens", 0)}
            elif evt["type"] == "error":
                return {"success": False, "error": evt["error"]}
        return {"success": False, "error": "未知错误"}
    
    def pause(self):
        with self._lock:
            self.state.status = AgentStatus.PAUSED
    
    def resume(self):
        with self._lock:
            if self.state.status == AgentStatus.PAUSED:
                self.state.status = AgentStatus.RUNNING
    
    def get_state(self) -> dict:
        with self._lock:
            return self.state.to_dict()
    
    def save_state(self) -> str:
        """序列化状态用于断点续跑"""
        return json.dumps(self.get_state(), ensure_ascii=False)
    
    @classmethod
    def load_state(cls, state_json: str, agent_config: AgentConfig) -> "AgentRuntime":
        """从状态恢复"""
        runtime = cls(agent_config)
        state_data = json.loads(state_json)
        runtime.state = AgentState.from_dict(state_data)
        return runtime


# ============================================================================
# 多Agent协作编排器
# ============================================================================

class MultiAgentOrchestrator:
    """多Agent协作编排 - 支持 Planner/Executor、并行、路由模式"""
    
    def __init__(self, main_agent: AgentConfig, sub_agents: List[AgentConfig] = None):
        self.main_agent = main_agent
        self.sub_agents = {a.id: a for a in (sub_agents or [])}
        self.mode = main_agent.collaboration_mode
    
    def execute(self, task: str, context: dict = None) -> dict:
        """执行多Agent任务"""
        context = context or {}
        
        if self.mode == "sequential":
            return self._run_sequential(task, context)
        elif self.mode == "parallel":
            return self._run_parallel(task, context)
        elif self.mode == "router":
            return self._run_router(task, context)
        elif self.mode == "planner_executor":
            return self._run_planner_executor(task, context)
        else:
            return self._run_sequential(task, context)
    
    def _run_planner_executor(self, task: str, context: dict) -> dict:
        """Planner + Executor 模式（百炼标准模式）"""
        # 1. Planner 分解任务
        planner_config = self.sub_agents.get("planner") or self.main_agent
        planner = AgentRuntime(planner_config)
        
        plan_prompt = f"""请将以下任务分解为可执行的子任务列表，返回 JSON 格式：
任务：{task}
上下文：{json.dumps(context, ensure_ascii=False)}

返回格式：
{{
  "subtasks": [
    {{"id": "1", "description": "...", "agent": "agent_id或role", "depends_on": []}},
    ...
  ]
}}"""
        
        plan_result = planner.run_sync(plan_prompt)
        if not plan_result["success"]:
            return {"success": False, "error": "Planner 失败: " + plan_result["error"]}
        
        try:
            plan = json.loads(plan_result["output"])
            subtasks = plan.get("subtasks", [])
        except:
            return {"success": False, "error": "Planner 返回格式错误"}
        
        # 2. 按依赖顺序执行子任务
        results = {}
        completed = set()
        
        for subtask in subtasks:
            # 等待依赖完成
            for dep in subtask.get("depends_on", []):
                if dep not in completed:
                    return {"success": False, "error": f"依赖未满足: {dep}"}
            
            # 选择执行 Agent
            agent_id = subtask.get("agent", "")
            executor_config = self.sub_agents.get(agent_id) or self.main_agent
            executor = AgentRuntime(executor_config)
            
            # 注入上下文
            exec_prompt = f"""任务：{subtask['description']}
上下文：{json.dumps({**context, **results}, ensure_ascii=False)}
请完成此子任务。"""
            
            exec_result = executor.run_sync(exec_prompt)
            if not exec_result["success"]:
                return {"success": False, "error": f"子任务 {subtask['id']} 失败: {exec_result['error']}"}
            
            results[subtask["id"]] = exec_result["output"]
            completed.add(subtask["id"])
        
        # 3. 汇总结果
        merger_config = self.sub_agents.get("merger") or self.main_agent
        merger = AgentRuntime(merger_config)
        merge_prompt = f"""请整合以下子任务结果，生成最终回答：
原始任务：{task}
子任务结果：
{json.dumps(results, ensure_ascii=False, indent=2)}"""
        
        merge_result = merger.run_sync(merge_prompt)
        if not merge_result["success"]:
            return {"success": True, "output": json.dumps(results, ensure_ascii=False), "subtask_results": results}
        
        return {"success": True, "output": merge_result["output"], "subtask_results": results}
    
    def _run_sequential(self, task: str, context: dict) -> dict:
        """顺序执行所有子Agent"""
        results = {}
        for agent_id, config in self.sub_agents.items():
            runtime = AgentRuntime(config)
            prompt = f"{task}\n上下文：{json.dumps({**context, **results}, ensure_ascii=False)}"
            result = runtime.run_sync(prompt)
            if not result["success"]:
                return {"success": False, "error": f"{agent_id} 失败: {result['error']}"}
            results[agent_id] = result["output"]
        return {"success": True, "output": json.dumps(results, ensure_ascii=False), "subtask_results": results}
    
    def _run_parallel(self, task: str, context: dict) -> dict:
        """并行执行所有子Agent"""
        import concurrent.futures
        
        def run_agent(agent_id, config):
            runtime = AgentRuntime(config)
            prompt = f"{task}\n上下文：{json.dumps(context, ensure_ascii=False)}"
            return agent_id, runtime.run_sync(prompt)
        
        results = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(self.sub_agents)) as executor:
            futures = [executor.submit(run_agent, aid, cfg) for aid, cfg in self.sub_agents.items()]
            for f in concurrent.futures.as_completed(futures):
                agent_id, result = f.result()
                if not result["success"]:
                    return {"success": False, "error": f"{agent_id} 失败: {result['error']}"}
                results[agent_id] = result["output"]
        return {"success": True, "output": json.dumps(results, ensure_ascii=False), "subtask_results": results}
    
    def _run_router(self, task: str, context: dict) -> dict:
        """路由模式：主Agent决定调用哪个子Agent"""
        runtime = AgentRuntime(self.main_agent)
        route_prompt = f"""任务：{task}
可用子Agent：{list(self.sub_agents.keys())}
请判断需要调用哪个子Agent，返回 JSON：{{"agent": "agent_id", "reason": "...", "input": "传给子Agent的输入"}}
只返回 JSON。"""
        
        route_result = runtime.run_sync(route_prompt)
        if not route_result["success"]:
            return {"success": False, "error": "路由失败"}
        
        try:
            route = json.loads(route_result["output"])
            agent_id = route.get("agent", "")
            sub_input = route.get("input", task)
        except:
            return {"success": False, "error": "路由返回格式错误"}
        
        if agent_id not in self.sub_agents:
            return {"success": False, "error": f"未知子Agent: {agent_id}"}
        
        sub_runtime = AgentRuntime(self.sub_agents[agent_id])
        sub_result = sub_runtime.run_sync(sub_input)
        if not sub_result["success"]:
            return {"success": False, "error": f"子Agent {agent_id} 失败: {sub_result['error']}"}
        
        return {"success": True, "output": sub_result["output"], "routed_to": agent_id}


# ============================================================================
# Agent 管理器 - CRUD 和运行时工厂
# ============================================================================

class AgentManager:
    """Agent 配置管理和运行时工厂"""
    
    @staticmethod
    def _ensure_tables():
        conn = db.get_conn()
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS agents (
            id TEXT PRIMARY KEY,
            name TEXT,
            description TEXT DEFAULT '',
            icon TEXT DEFAULT '🤖',
            category TEXT DEFAULT 'general',
            system_prompt TEXT DEFAULT '',
            model_preference TEXT DEFAULT '',
            max_context INTEGER DEFAULT 128000,
            temperature REAL DEFAULT 0.7,
            top_p REAL DEFAULT 0.9,
            builtin_tools TEXT DEFAULT '[]',
            skill_ids TEXT DEFAULT '[]',
            mcp_ids TEXT DEFAULT '[]',
            connector_ids TEXT DEFAULT '[]',
            workflow_id TEXT DEFAULT '',
            kb_ids TEXT DEFAULT '[]',
            kb_top_k INTEGER DEFAULT 5,
            kb_score_threshold REAL DEFAULT 0.5,
            memory_enabled INTEGER DEFAULT 1,
            short_term_turns INTEGER DEFAULT 20,
            long_term_summary_interval INTEGER DEFAULT 10,
            user_profile_enabled INTEGER DEFAULT 1,
            max_rounds INTEGER DEFAULT 10,
            max_tokens_per_round INTEGER DEFAULT 4000,
            stop_sequences TEXT DEFAULT '[]',
            sub_agents TEXT DEFAULT '[]',
            collaboration_mode TEXT DEFAULT 'sequential',
            prompt_templates TEXT DEFAULT '{}',
            response_format TEXT DEFAULT 'text',
            enable_reasoning INTEGER DEFAULT 0,
            auto_approve_tools INTEGER DEFAULT 0,
            is_builtin INTEGER DEFAULT 0,
            enabled INTEGER DEFAULT 1,
            version INTEGER DEFAULT 1,
            created_by TEXT DEFAULT '',
            created_at REAL,
            updated_at REAL
        );
        CREATE TABLE IF NOT EXISTS agent_sessions (
            id TEXT PRIMARY KEY,
            agent_id TEXT,
            user_id TEXT,
            state TEXT DEFAULT '{}',
            status TEXT DEFAULT 'active',
            created_at REAL,
            updated_at REAL
        );
        """)
        # 兼容旧表：补充新增列
        cols = [r[1] for r in conn.execute("PRAGMA table_info(agents)").fetchall()]
        if cols and "workflow_id" not in cols:
            try:
                conn.execute("ALTER TABLE agents ADD COLUMN workflow_id TEXT DEFAULT ''")
            except Exception:
                pass
        conn.commit()
        conn.close()
    
    @staticmethod
    def create(config: AgentConfig) -> AgentConfig:
        AgentManager._ensure_tables()
        if not config.id:
            config.id = f"agent_{uuid.uuid4().hex[:8]}"
        config.created_at = time.time()
        config.updated_at = time.time()
        
        conn = db.get_conn()
        conn.execute("""INSERT INTO agents 
            (id,name,description,icon,category,system_prompt,model_preference,max_context,temperature,top_p,
             builtin_tools,skill_ids,mcp_ids,connector_ids,workflow_id,kb_ids,kb_top_k,kb_score_threshold,
             memory_enabled,short_term_turns,long_term_summary_interval,user_profile_enabled,
             max_rounds,max_tokens_per_round,stop_sequences,sub_agents,collaboration_mode,
             prompt_templates,response_format,enable_reasoning,auto_approve_tools,
             is_builtin,enabled,version,created_by,created_at,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (config.id, config.name, config.description, config.icon, config.category,
             config.system_prompt, config.model_preference, config.max_context, config.temperature, config.top_p,
             json.dumps(config.builtin_tools), json.dumps(config.skill_ids), json.dumps(config.mcp_ids),
             json.dumps(config.connector_ids), config.workflow_id, json.dumps(config.kb_ids), config.kb_top_k, config.kb_score_threshold,
             1 if config.memory_enabled else 0, config.short_term_turns, config.long_term_summary_interval,
             1 if config.user_profile_enabled else 0, config.max_rounds, config.max_tokens_per_round,
             json.dumps(config.stop_sequences), json.dumps(config.sub_agents), config.collaboration_mode,
             json.dumps(config.prompt_templates), config.response_format,
             1 if config.enable_reasoning else 0, 1 if config.auto_approve_tools else 0,
             1 if config.is_builtin else 0, 1 if config.enabled else 0, config.version,
             config.created_by, config.created_at, config.updated_at))
        conn.commit()
        conn.close()
        return config
    
    @staticmethod
    def get(agent_id: str) -> Optional[AgentConfig]:
        AgentManager._ensure_tables()
        conn = db.get_conn()
        row = conn.execute("SELECT * FROM agents WHERE id=?", (agent_id,)).fetchone()
        conn.close()
        if not row:
            return None
        return AgentManager._row_to_config(row)
    
    @staticmethod
    def list(category: str = None, enabled_only: bool = True) -> List[AgentConfig]:
        AgentManager._ensure_tables()
        conn = db.get_conn()
        if category:
            sql = "SELECT * FROM agents WHERE category=? AND enabled=? ORDER BY updated_at DESC"
            rows = conn.execute(sql, (category, 1 if enabled_only else 0)).fetchall()
        else:
            sql = "SELECT * FROM agents WHERE enabled=? ORDER BY updated_at DESC"
            rows = conn.execute(sql, (1 if enabled_only else 0,)).fetchall()
        conn.close()
        return [AgentManager._row_to_config(r) for r in rows]
    
    @staticmethod
    def update(config: AgentConfig) -> AgentConfig:
        AgentManager._ensure_tables()
        config.updated_at = time.time()
        config.version += 1
        
        conn = db.get_conn()
        conn.execute("""UPDATE agents SET
            name=?, description=?, icon=?, category=?, system_prompt=?, model_preference=?,
            max_context=?, temperature=?, top_p=?, builtin_tools=?, skill_ids=?, mcp_ids=?,
            connector_ids=?, workflow_id=?, kb_ids=?, kb_top_k=?, kb_score_threshold=?,
            memory_enabled=?, short_term_turns=?, long_term_summary_interval=?, user_profile_enabled=?,
            max_rounds=?, max_tokens_per_round=?, stop_sequences=?, sub_agents=?, collaboration_mode=?,
            prompt_templates=?, response_format=?, enable_reasoning=?, auto_approve_tools=?,
            enabled=?, version=?, updated_at=?
            WHERE id=?""",
            (config.name, config.description, config.icon, config.category, config.system_prompt,
             config.model_preference, config.max_context, config.temperature, config.top_p,
             json.dumps(config.builtin_tools), json.dumps(config.skill_ids), json.dumps(config.mcp_ids),
             json.dumps(config.connector_ids), config.workflow_id, json.dumps(config.kb_ids), config.kb_top_k, config.kb_score_threshold,
             1 if config.memory_enabled else 0, config.short_term_turns, config.long_term_summary_interval,
             1 if config.user_profile_enabled else 0, config.max_rounds, config.max_tokens_per_round,
             json.dumps(config.stop_sequences), json.dumps(config.sub_agents), config.collaboration_mode,
             json.dumps(config.prompt_templates), config.response_format,
             1 if config.enable_reasoning else 0, 1 if config.auto_approve_tools else 0,
             1 if config.enabled else 0, config.version, config.updated_at, config.id))
        conn.commit()
        conn.close()
        return config
    
    @staticmethod
    def delete(agent_id: str):
        AgentManager._ensure_tables()
        conn = db.get_conn()
        conn.execute("DELETE FROM agents WHERE id=? AND is_builtin=0", (agent_id,))
        conn.commit()
        conn.close()
    
    @staticmethod
    def create_runtime(agent_id: str, session_id: str = None, user_id: str = "") -> AgentRuntime:
        """创建运行时实例"""
        config = AgentManager.get(agent_id)
        if not config:
            raise ValueError(f"Agent 不存在: {agent_id}")
        return AgentRuntime(config, session_id, user_id)
    
    @staticmethod
    def create_multi_agent_orchestrator(main_agent_id: str, sub_agent_ids: List[str] = None) -> MultiAgentOrchestrator:
        """创建多Agent编排器"""
        main_config = AgentManager.get(main_agent_id)
        if not main_config:
            raise ValueError(f"主Agent不存在: {main_agent_id}")
        sub_configs = []
        if sub_agent_ids:
            for sid in sub_agent_ids:
                cfg = AgentManager.get(sid)
                if cfg:
                    sub_configs.append(cfg)
        return MultiAgentOrchestrator(main_config, sub_configs)
    
    @staticmethod
    def _row_to_config(row) -> AgentConfig:
        d = dict(row)
        # 解析 JSON 字段
        for k in ("builtin_tools", "skill_ids", "mcp_ids", "connector_ids", "kb_ids",
                  "stop_sequences", "sub_agents", "prompt_templates"):
            try:
                d[k] = json.loads(d[k] or "[]") if k != "prompt_templates" else json.loads(d[k] or "{}")
            except:
                d[k] = [] if k != "prompt_templates" else {}
        # 布尔字段
        for k in ("memory_enabled", "user_profile_enabled", "enable_reasoning", "auto_approve_tools", "is_builtin", "enabled"):
            d[k] = bool(d.get(k, 0))
        return AgentConfig.from_dict(d)


# ============================================================================
# 内置 Agent 预设
# ============================================================================

BUILTIN_AGENTS = [
    {
        "id": "agent_coder",
        "name": "代码开发助手",
        "category": "coding",
        "icon": "💻",
        "description": "专业的代码编写、调试、重构、测试智能体",
        "system_prompt": "你是一个资深软件工程师。擅长：代码编写、调试、重构、单元测试、代码审查。\n\n工作原则：\n1. 先理解需求，再动手写代码\n2. 遵循最佳实践和设计模式\n3. 写整洁、可测试、可维护的代码\n4. 主动使用工具验证代码正确性\n5. 提供清晰的注释和文档",
        "builtin_tools": ["shell", "file_read", "file_write", "list_files", "web_search"],
        "skill_ids": [],
        "mcp_ids": [],
        "connector_ids": [],
        "kb_ids": [],
        "enable_reasoning": True,
        "max_rounds": 15,
        "temperature": 0.3,
        "is_builtin": True,
    },
    {
        "id": "agent_researcher",
        "name": "深度研究员",
        "category": "research",
        "icon": "🔬",
        "description": "专业的文献调研、技术调研、趋势分析智能体",
        "system_prompt": "你是一个资深研究员。擅长：文献综述、技术调研、趋势分析、竞品分析、可行性研究。\n\n工作流程：\n1. 明确研究问题和范围\n2. 多源信息检索与验证\n3. 批判性分析与综合\n4. 结构化报告输出\n5. 引用来源，标注置信度",
        "builtin_tools": ["web_search", "fetch_url", "file_read", "file_write"],
        "enable_reasoning": True,
        "max_rounds": 20,
        "temperature": 0.4,
        "is_builtin": True,
    },
    {
        "id": "agent_data_analyst",
        "name": "数据分析师",
        "category": "analysis",
        "icon": "📊",
        "description": "专业的数据探索、统计分析、可视化、报表智能体",
        "system_prompt": "你是一个资深数据分析师。擅长：数据清洗、探索性分析、统计建模、可视化、仪表盘设计。\n\n工作流程：\n1. 理解业务问题\n2. 数据获取与质量评估\n3. 探索性分析（分布、相关性、异常值）\n4. 建模与验证\n5. 可视化洞察与行动建议",
        "builtin_tools": ["shell", "file_read", "file_write", "list_files"],
        "connector_ids": ["sqlite", "postgres", "mysql", "csv"],
        "enable_reasoning": True,
        "max_rounds": 15,
        "temperature": 0.3,
        "is_builtin": True,
    },
    {
        "id": "agent_architect",
        "name": "系统架构师",
        "category": "coding",
        "icon": "🏗️",
        "description": "专业的系统设计、技术选型、架构评审、性能优化智能体",
        "system_prompt": "你是一个资深系统架构师。擅长：分布式系统设计、微服务架构、技术选型、性能优化、容灾设计。\n\n工作原则：\n1. 业务驱动架构\n2. 权衡而非完美\n3. 显式记录决策依据（ADR）\n4. 关注非功能性需求\n5. 演进式架构",
        "builtin_tools": ["web_search", "file_read", "file_write", "shell"],
        "enable_reasoning": True,
        "max_rounds": 15,
        "temperature": 0.4,
        "is_builtin": True,
    },
    {
        "id": "agent_pm",
        "name": "产品经理",
        "category": "product",
        "icon": "🎯",
        "description": "专业的PRD撰写、需求分析、竞品分析、用户故事智能体",
        "system_prompt": "你是一个资深产品经理。擅长：PRD撰写、需求分析、用户研究、竞品分析、数据驱动决策。\n\n输出标准：\n1. PRD 包含：背景、目标、用户故事、功能规格、非功能需求、指标、里程碑\n2. 竞品分析：矩阵对比、差异化机会、进入建议\n3. 用户故事：INVEST 原则",
        "builtin_tools": ["web_search", "file_read", "file_write"],
        "enable_reasoning": True,
        "max_rounds": 15,
        "temperature": 0.5,
        "is_builtin": True,
    },
    {
        "id": "agent_writer",
        "name": "内容创作专家",
        "category": "writing",
        "icon": "✍️",
        "description": "专业的文案写作、文章创作、润色优化、多风格适配智能体",
        "system_prompt": "你是一个资深内容创作者。擅长：技术文档、博客文章、营销文案、产品文案、多语言本地化。\n\n风格适配：\n- 技术文档：准确、结构化、可执行\n- 博客文章：生动、有洞察、SEO友好\n- 营销文案：痛点导向、利益点清晰、行动召唤\n- 产品文案：简洁、人性化、品牌一致",
        "builtin_tools": ["file_read", "file_write", "web_search"],
        "enable_reasoning": False,
        "max_rounds": 10,
        "temperature": 0.7,
        "is_builtin": True,
    },
    {
        "id": "agent_security",
        "name": "安全审计专家",
        "category": "security",
        "icon": "🔒",
        "description": "专业的代码安全审计、漏洞挖掘、威胁建模、合规检查智能体",
        "system_prompt": "你是一个资深安全专家。擅长：代码审计、渗透测试、威胁建模、漏洞分析、安全加固、合规审计。\n\n方法论：\n1. 威胁建模（STRIDE）\n2. 代码静态分析（SAST）\n3. 依赖扫描（SCA）\n4. 运行时验证（DAST）\n5. 修复建议与验证",
        "builtin_tools": ["shell", "file_read", "web_search"],
        "enable_reasoning": True,
        "max_rounds": 15,
        "temperature": 0.2,
        "is_builtin": True,
    },
    {
        "id": "agent_translator",
        "name": "专业翻译官",
        "category": "language",
        "icon": "🌐",
        "description": "专业的多语言翻译、本地化、术语管理、术后编辑智能体",
        "system_prompt": "你是一个资深翻译专家。擅长：技术文档翻译、软件本地化、术语库管理、MTPE（机器翻译后编辑）。\n\n质量标准：\n1. 准确性：无误译、漏译、增译\n2. 流畅性：符合目标语言习惯\n3. 一致性：术语、风格、格式统一\n4. 专业性：领域术语准确\n5. 文化适配：本地化无文化冲突",
        "builtin_tools": ["file_read", "file_write"],
        "enable_reasoning": False,
        "max_rounds": 8,
        "temperature": 0.3,
        "is_builtin": True,
    },
]


def init_builtin_agents():
    """初始化内置智能体"""
    AgentManager._ensure_tables()
    conn = db.get_conn()
    for a in BUILTIN_AGENTS:
        config = AgentConfig(**a)
        conn.execute("""INSERT OR IGNORE INTO agents 
            (id,name,description,icon,category,system_prompt,model_preference,max_context,temperature,top_p,
             builtin_tools,skill_ids,mcp_ids,connector_ids,kb_ids,kb_top_k,kb_score_threshold,
             memory_enabled,short_term_turns,long_term_summary_interval,user_profile_enabled,
             max_rounds,max_tokens_per_round,stop_sequences,sub_agents,collaboration_mode,
             prompt_templates,response_format,enable_reasoning,auto_approve_tools,
             is_builtin,enabled,version,created_by,created_at,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (config.id, config.name, config.description, config.icon, config.category,
             config.system_prompt, config.model_preference, config.max_context, config.temperature, config.top_p,
             json.dumps(config.builtin_tools), json.dumps(config.skill_ids), json.dumps(config.mcp_ids),
             json.dumps(config.connector_ids), json.dumps(config.kb_ids), config.kb_top_k, config.kb_score_threshold,
             1 if config.memory_enabled else 0, config.short_term_turns, config.long_term_summary_interval,
             1 if config.user_profile_enabled else 0, config.max_rounds, config.max_tokens_per_round,
             json.dumps(config.stop_sequences), json.dumps(config.sub_agents), config.collaboration_mode,
             json.dumps(config.prompt_templates), config.response_format,
             1 if config.enable_reasoning else 0, 1 if config.auto_approve_tools else 0,
             1 if config.is_builtin else 0, 1 if config.enabled else 0, config.version,
             config.created_by, config.created_at, config.updated_at))
    conn.commit()
    conn.close()


# 在模块导入时自动初始化
init_builtin_agents()