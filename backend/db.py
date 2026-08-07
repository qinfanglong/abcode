"""ABcode 数据库层 - SQLite 存储会话、消息、供应商配置"""
import sqlite3
import json
import time
import os
from pathlib import Path

DB_PATH = Path(os.environ.get("ABCODE_DB", Path(__file__).parent.parent / "data" / "abcode.db"))
DB_PATH.parent.mkdir(parents=True, exist_ok=True)


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    conn = get_conn()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS conversations (
        id TEXT PRIMARY KEY,
        title TEXT DEFAULT '新对话',
        model TEXT DEFAULT '',
        created_at REAL,
        updated_at REAL
    );
    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        conv_id TEXT,
        role TEXT,
        content TEXT,
        attachments TEXT DEFAULT '[]',
        created_at REAL
    );
    CREATE TABLE IF NOT EXISTS providers (
        id TEXT PRIMARY KEY,
        name TEXT,
        base_url TEXT,
        api_key TEXT,
        models TEXT DEFAULT '[]',
        default_model TEXT DEFAULT '',
        enabled INTEGER DEFAULT 1,
        max_context INTEGER DEFAULT 0,
        created_at REAL
    );
    CREATE INDEX IF NOT EXISTS idx_msg_conv ON messages(conv_id);
    -- 会话工具配置（会话级启用哪些工具源）
    CREATE TABLE IF NOT EXISTS conv_tools (
        conv_id TEXT PRIMARY KEY,
        skill_ids TEXT DEFAULT '[]',
        mcp_ids TEXT DEFAULT '[]',
        connector_ids TEXT DEFAULT '[]',
        expert_id TEXT DEFAULT ''
    );
    -- 技能插件
    CREATE TABLE IF NOT EXISTS skills (
        id TEXT PRIMARY KEY,
        name TEXT,
        description TEXT,
        code TEXT DEFAULT '',
        enabled INTEGER DEFAULT 1,
        builtin INTEGER DEFAULT 0,
        created_at REAL
    );
    -- MCP 服务器
    CREATE TABLE IF NOT EXISTS mcp_servers (
        id TEXT PRIMARY KEY,
        name TEXT,
        transport TEXT DEFAULT 'stdio',
        command TEXT DEFAULT '',
        args TEXT DEFAULT '[]',
        url TEXT DEFAULT '',
        headers TEXT DEFAULT '{}',
        enabled INTEGER DEFAULT 1,
        created_at REAL
    );
    -- 数据连接器
    CREATE TABLE IF NOT EXISTS connectors (
        id TEXT PRIMARY KEY,
        name TEXT,
        type TEXT DEFAULT 'sqlite',
        config TEXT DEFAULT '{}',
        enabled INTEGER DEFAULT 1,
        created_at REAL
    );
    -- 上传文件
    CREATE TABLE IF NOT EXISTS uploads (
        id TEXT PRIMARY KEY,
        filename TEXT,
        mime TEXT,
        size INTEGER,
        path TEXT,
        created_at REAL
    );
    -- 全局设置（key-value）
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT,
        updated_at REAL
    );
    -- 频道管理
    CREATE TABLE IF NOT EXISTS channels (
        id TEXT PRIMARY KEY,
        name TEXT,
        type TEXT,
        icon TEXT DEFAULT '📡',
        builtin INTEGER DEFAULT 0,
        enabled INTEGER DEFAULT 1,
        bot_prefix TEXT DEFAULT '',
        config TEXT DEFAULT '{}',
        description TEXT DEFAULT '',
        created_at REAL
    );
    -- 团队成员
    CREATE TABLE IF NOT EXISTS team_members (
        id TEXT PRIMARY KEY,
        name TEXT,
        email TEXT DEFAULT '',
        role TEXT DEFAULT 'member',
        avatar TEXT DEFAULT '👤',
        status TEXT DEFAULT 'active',
        permissions TEXT DEFAULT '{}',
        created_at REAL
    );
    -- 共享对话
    CREATE TABLE IF NOT EXISTS shared_conversations (
        id TEXT PRIMARY KEY,
        conv_id TEXT,
        shared_by TEXT,
        shared_with TEXT DEFAULT '[]',
        permission TEXT DEFAULT 'view',
        expires_at REAL DEFAULT 0,
        created_at REAL
    );
    -- 团队活动日志
    CREATE TABLE IF NOT EXISTS team_activity (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT,
        action TEXT,
        target_type TEXT,
        target_id TEXT,
        details TEXT DEFAULT '{}',
        created_at REAL
    );
    -- 专家套件
    CREATE TABLE IF NOT EXISTS experts (
        id TEXT PRIMARY KEY,
        name TEXT,
        category TEXT DEFAULT 'general',
        icon TEXT DEFAULT '🤖',
        description TEXT DEFAULT '',
        system_prompt TEXT DEFAULT '',
        tools TEXT DEFAULT '[]',
        skill_ids TEXT DEFAULT '[]',
        mcp_ids TEXT DEFAULT '[]',
        kb_ids TEXT DEFAULT '[]',
        workflow_ids TEXT DEFAULT '[]',
        prompt_templates TEXT DEFAULT '{}',
        model_preference TEXT DEFAULT '',
        max_context INTEGER DEFAULT 0,
        auto_model INTEGER DEFAULT 1,
        is_builtin INTEGER DEFAULT 0,
        enabled INTEGER DEFAULT 1,
        created_at REAL
    );
    -- 专家使用统计
    CREATE TABLE IF NOT EXISTS expert_stats (
        expert_id TEXT PRIMARY KEY,
        usage_count INTEGER DEFAULT 0,
        avg_rating REAL DEFAULT 0,
        last_used REAL
    );
    -- 工作流
    CREATE TABLE IF NOT EXISTS workflows (
        id TEXT PRIMARY KEY,
        name TEXT,
        description TEXT DEFAULT '',
        category TEXT DEFAULT 'general',
        icon TEXT DEFAULT '🔄',
        nodes TEXT DEFAULT '[]',
        edges TEXT DEFAULT '[]',
        enabled INTEGER DEFAULT 1,
        version INTEGER DEFAULT 1,
        created_by TEXT DEFAULT '',
        created_at REAL,
        updated_at REAL
    );
    -- 工作流执行记录
    CREATE TABLE IF NOT EXISTS workflow_executions (
        id TEXT PRIMARY KEY,
        workflow_id TEXT,
        input TEXT DEFAULT '{}',
        output TEXT DEFAULT '',
        status TEXT DEFAULT 'running',
        nodes_status TEXT DEFAULT '{}',
        error TEXT DEFAULT '',
        started_at REAL,
        completed_at REAL,
        duration_ms INTEGER DEFAULT 0,
        tokens_used INTEGER DEFAULT 0
    );
    -- 工作流模板
    CREATE TABLE IF NOT EXISTS workflow_templates (
        id TEXT PRIMARY KEY,
        name TEXT,
        description TEXT DEFAULT '',
        category TEXT DEFAULT 'general',
        icon TEXT DEFAULT '📋',
        workflow_json TEXT DEFAULT '{}',
        tags TEXT DEFAULT '[]',
        is_builtin INTEGER DEFAULT 0,
        created_at REAL
    );
    -- 工作流测试用例
    CREATE TABLE IF NOT EXISTS workflow_test_cases (
        id TEXT PRIMARY KEY,
        workflow_id TEXT,
        name TEXT,
        input_data TEXT DEFAULT '{}',
        expected_output TEXT DEFAULT '',
        assertions TEXT DEFAULT '[]',
        created_at REAL
    );
    -- 工作流评论/注解
    CREATE TABLE IF NOT EXISTS workflow_comments (
        id TEXT PRIMARY KEY,
        workflow_id TEXT,
        node_id TEXT DEFAULT '',
        user_id TEXT,
        user_name TEXT,
        content TEXT,
        created_at REAL,
        resolved INTEGER DEFAULT 0
    );
    -- 工作流版本历史
    CREATE TABLE IF NOT EXISTS workflow_versions (
        id TEXT PRIMARY KEY,
        workflow_id TEXT,
        version INTEGER,
        nodes TEXT DEFAULT '[]',
        edges TEXT DEFAULT '[]',
        change_log TEXT DEFAULT '',
        created_by TEXT,
        created_at REAL
    );
    -- 共享工作空间
    CREATE TABLE IF NOT EXISTS shared_workspaces (
        id TEXT PRIMARY KEY,
        name TEXT,
        description TEXT DEFAULT '',
        icon TEXT DEFAULT '📁',
        owner_id TEXT,
        members TEXT DEFAULT '[]',
        settings TEXT DEFAULT '{}',
        created_at REAL
    );
    -- 工作空间成员权限
    CREATE TABLE IF NOT EXISTS workspace_members (
        id TEXT PRIMARY KEY,
        workspace_id TEXT,
        user_id TEXT,
        role TEXT DEFAULT 'editor',
        permissions TEXT DEFAULT '{}',
        joined_at REAL
    );
    -- 实时协作状态
    CREATE TABLE IF NOT EXISTS collaboration_sessions (
        id TEXT PRIMARY KEY,
        target_type TEXT,
        target_id TEXT,
        user_id TEXT,
        user_name TEXT,
        user_avatar TEXT DEFAULT '👤',
        cursor_position TEXT DEFAULT '{}',
        selection TEXT DEFAULT '{}',
        last_active REAL,
        status TEXT DEFAULT 'active'
    );
    """)
    # 迁移：给 messages 表添加 attachments 列（如果不存在）
    try:
        conn.execute("SELECT attachments FROM messages LIMIT 1")
    except sqlite3.OperationalError:
        conn.execute("ALTER TABLE messages ADD COLUMN attachments TEXT DEFAULT '[]'")
    # 迁移：给 providers 表添加 max_context 列（如果不存在）
    try:
        conn.execute("SELECT max_context FROM providers LIMIT 1")
    except sqlite3.OperationalError:
        conn.execute("ALTER TABLE providers ADD COLUMN max_context INTEGER DEFAULT 0")
    # 迁移：给 experts 表添加缺失列
    for col, col_type in [
        ("skill_ids", "TEXT DEFAULT '[]'"),
        ("mcp_ids", "TEXT DEFAULT '[]'"),
        ("kb_ids", "TEXT DEFAULT '[]'"),
        ("workflow_ids", "TEXT DEFAULT '[]'"),
        ("prompt_templates", "TEXT DEFAULT '{}'"),
        ("model_preference", "TEXT DEFAULT ''"),
        ("max_context", "INTEGER DEFAULT 0"),
        ("auto_model", "INTEGER DEFAULT 1"),
    ]:
        try:
            conn.execute(f"SELECT {col} FROM experts LIMIT 1")
        except sqlite3.OperationalError:
            conn.execute(f"ALTER TABLE experts ADD COLUMN {col} {col_type}")
    # 迁移：旧库 conv_tools 表可能缺少 expert_id 列（会导致保存会话工具配置报错）
    try:
        ct_cols = [r[1] for r in conn.execute("PRAGMA table_info(conv_tools)").fetchall()]
        if "expert_id" not in ct_cols:
            conn.execute("ALTER TABLE conv_tools ADD COLUMN expert_id TEXT DEFAULT ''")
    except Exception:
        pass
    conn.commit()
    conn.close()
    # 初始化默认搜索设置
    _init_default_search_settings()


def _init_default_search_settings():
    """初始化默认搜索设置（内置搜索）"""
    try:
        # 如果没有设置过搜索引擎，默认使用内置搜索
        current = get_setting("search_engine")
        if not current:
            set_setting("search_engine", "builtin")
    except Exception:
        pass

def create_conversation(title="新对话", model=""):
    cid = f"c{int(time.time()*1000)}"
    now = time.time()
    conn = get_conn()
    conn.execute("INSERT INTO conversations (id,title,model,created_at,updated_at) VALUES (?,?,?,?,?)",
                 (cid, title, model, now, now))
    conn.commit()
    conn.close()
    return cid


def list_conversations():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM conversations ORDER BY updated_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_conversation(cid):
    conn = get_conn()
    row = conn.execute("SELECT * FROM conversations WHERE id=?", (cid,)).fetchone()
    conn.close()
    return dict(row) if row else None


def update_conversation(cid, **kw):
    kw = {k: v for k, v in kw.items() if v is not None}
    if not kw:
        # 仅刷新 updated_at
        conn = get_conn()
        conn.execute("UPDATE conversations SET updated_at=? WHERE id=?", (time.time(), cid))
        conn.commit()
        conn.close()
        return
    conn = get_conn()
    sets = ",".join(f"{k}=?" for k in kw)
    conn.execute(f"UPDATE conversations SET {sets}, updated_at=? WHERE id=?",
                 (*kw.values(), time.time(), cid))
    conn.commit()
    conn.close()


def delete_conversation(cid):
    conn = get_conn()
    conn.execute("DELETE FROM messages WHERE conv_id=?", (cid,))
    conn.execute("DELETE FROM conversations WHERE id=?", (cid,))
    conn.commit()
    conn.close()


# ---------- 消息 ----------
def add_message(conv_id, role, content, attachments=None):
    conn = get_conn()
    cur = conn.execute("INSERT INTO messages (conv_id,role,content,attachments,created_at) VALUES (?,?,?,?,?)",
                       (conv_id, role, content, json.dumps(attachments or []), time.time()))
    conn.execute("UPDATE conversations SET updated_at=? WHERE id=?", (time.time(), conv_id))
    conn.commit()
    conn.close()
    return cur.lastrowid


def list_messages(conv_id):
    conn = get_conn()
    rows = conn.execute("SELECT * FROM messages WHERE conv_id=? ORDER BY id", (conv_id,)).fetchall()
    conn.close()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["attachments"] = json.loads(d["attachments"] or "[]")
        except Exception:
            d["attachments"] = []
        out.append(d)
    return out


def clear_messages(conv_id):
    """清空某会话的全部消息（用于压缩会话后重写）"""
    conn = get_conn()
    conn.execute("DELETE FROM messages WHERE conv_id=?", (conv_id,))
    conn.commit()
    conn.close()


# ---------- 供应商 ----------
def upsert_provider(p):
    conn = get_conn()
    conn.execute("""INSERT INTO providers (id,name,base_url,api_key,models,default_model,enabled,max_context,created_at)
                    VALUES (?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(id) DO UPDATE SET
                      name=excluded.name, base_url=excluded.base_url, api_key=excluded.api_key,
                      models=excluded.models, default_model=excluded.default_model, enabled=excluded.enabled,
                      max_context=excluded.max_context""",
                 (p["id"], p.get("name", ""), p.get("base_url", ""), p.get("api_key", ""),
                  json.dumps(p.get("models", [])), p.get("default_model", ""),
                  1 if p.get("enabled", True) else 0, p.get("max_context", 0), time.time()))
    conn.commit()
    conn.close()


def list_providers():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM providers ORDER BY created_at").fetchall()
    conn.close()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["models"] = json.loads(d["models"])
        except Exception:
            d["models"] = []
        out.append(d)
    return out


def delete_provider(pid):
    conn = get_conn()
    conn.execute("DELETE FROM providers WHERE id=?", (pid,))
    conn.commit()
    conn.close()


# ---------- 会话工具配置 ----------
def get_conv_tools(conv_id):
    conn = get_conn()
    row = conn.execute("SELECT * FROM conv_tools WHERE conv_id=?", (conv_id,)).fetchone()
    conn.close()
    if not row:
        return {"skill_ids": [], "mcp_ids": [], "connector_ids": [], "expert_id": ""}
    d = dict(row)
    for k in ("skill_ids", "mcp_ids", "connector_ids"):
        try:
            d[k] = json.loads(d[k] or "[]")
        except Exception:
            d[k] = []
    d["expert_id"] = d.get("expert_id", "") or ""
    return d


def set_conv_tools(conv_id, skill_ids=None, mcp_ids=None, connector_ids=None, expert_id=None):
    cur = get_conv_tools(conv_id)
    if skill_ids is not None:
        cur["skill_ids"] = skill_ids
    if mcp_ids is not None:
        cur["mcp_ids"] = mcp_ids
    if connector_ids is not None:
        cur["connector_ids"] = connector_ids
    if expert_id is not None:
        cur["expert_id"] = expert_id
    conn = get_conn()
    conn.execute("""INSERT INTO conv_tools (conv_id,skill_ids,mcp_ids,connector_ids,expert_id) VALUES (?,?,?,?,?)
                    ON CONFLICT(conv_id) DO UPDATE SET
                      skill_ids=excluded.skill_ids, mcp_ids=excluded.mcp_ids, connector_ids=excluded.connector_ids, expert_id=excluded.expert_id""",
                 (conv_id, json.dumps(cur["skill_ids"]), json.dumps(cur["mcp_ids"]), json.dumps(cur["connector_ids"]), cur["expert_id"]))
    conn.commit()
    conn.close()


# ---------- 技能插件 ----------
def upsert_skill(s):
    conn = get_conn()
    conn.execute("""INSERT INTO skills (id,name,description,code,enabled,builtin,created_at)
                    VALUES (?,?,?,?,?,?,?)
                    ON CONFLICT(id) DO UPDATE SET
                      name=excluded.name, description=excluded.description, code=excluded.code,
                      enabled=excluded.enabled""",
                 (s["id"], s.get("name", ""), s.get("description", ""), s.get("code", ""),
                  1 if s.get("enabled", True) else 0, 1 if s.get("builtin") else 0, time.time()))
    conn.commit()
    conn.close()


def list_skills():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM skills ORDER BY created_at").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_skill(sid):
    conn = get_conn()
    row = conn.execute("SELECT * FROM skills WHERE id=?", (sid,)).fetchone()
    conn.close()
    return dict(row) if row else None


def delete_skill(sid):
    conn = get_conn()
    conn.execute("DELETE FROM skills WHERE id=?", (sid,))
    conn.commit()
    conn.close()


# ---------- MCP 服务器 ----------
def upsert_mcp(m):
    conn = get_conn()
    conn.execute("""INSERT INTO mcp_servers (id,name,transport,command,args,url,headers,enabled,created_at)
                    VALUES (?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(id) DO UPDATE SET
                      name=excluded.name, transport=excluded.transport, command=excluded.command,
                      args=excluded.args, url=excluded.url, headers=excluded.headers, enabled=excluded.enabled""",
                 (m["id"], m.get("name", ""), m.get("transport", "stdio"),
                  m.get("command", ""), json.dumps(m.get("args", [])), m.get("url", ""),
                  json.dumps(m.get("headers", {})), 1 if m.get("enabled", True) else 0, time.time()))
    conn.commit()
    conn.close()


def list_mcp():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM mcp_servers ORDER BY created_at").fetchall()
    conn.close()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["args"] = json.loads(d["args"] or "[]")
        except Exception:
            d["args"] = []
        try:
            d["headers"] = json.loads(d["headers"] or "{}")
        except Exception:
            d["headers"] = {}
        out.append(d)
    return out


def get_mcp(mid):
    for m in list_mcp():
        if m["id"] == mid:
            return m
    return None


def delete_mcp(mid):
    conn = get_conn()
    conn.execute("DELETE FROM mcp_servers WHERE id=?", (mid,))
    conn.commit()
    conn.close()


# ---------- 数据连接器 ----------
def upsert_connector(c):
    conn = get_conn()
    conn.execute("""INSERT INTO connectors (id,name,type,config,enabled,created_at)
                    VALUES (?,?,?,?,?,?)
                    ON CONFLICT(id) DO UPDATE SET
                      name=excluded.name, type=excluded.type, config=excluded.config, enabled=excluded.enabled""",
                 (c["id"], c.get("name", ""), c.get("type", "sqlite"),
                  json.dumps(c.get("config", {})), 1 if c.get("enabled", True) else 0, time.time()))
    conn.commit()
    conn.close()


def list_connectors():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM connectors ORDER BY created_at").fetchall()
    conn.close()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["config"] = json.loads(d["config"] or "{}")
        except Exception:
            d["config"] = {}
        out.append(d)
    return out


def delete_connector(cid):
    conn = get_conn()
    conn.execute("DELETE FROM connectors WHERE id=?", (cid,))
    conn.commit()
    conn.close()


# ---------- 上传文件 ----------
def add_upload(uid, filename, mime, size, path):
    conn = get_conn()
    conn.execute("INSERT INTO uploads (id,filename,mime,size,path,created_at) VALUES (?,?,?,?,?,?)",
                 (uid, filename, mime, size, path, time.time()))
    conn.commit()
    conn.close()


def list_uploads():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM uploads ORDER BY created_at DESC LIMIT 100").fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ---------- 全局设置 ----------
def get_setting(key, default=None):
    conn = get_conn()
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else default


def set_setting(key, value):
    conn = get_conn()
    conn.execute("""INSERT INTO settings (key,value,updated_at) VALUES (?,?,?)
                    ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at""",
                 (key, str(value), time.time()))
    conn.commit()
    conn.close()


def get_all_settings():
    conn = get_conn()
    rows = conn.execute("SELECT key, value FROM settings").fetchall()
    conn.close()
    return {r["key"]: r["value"] for r in rows}


# ---------- 频道管理 ----------
BUILTIN_CHANNELS = [
    {"id": "console", "name": "控制台", "type": "console", "builtin": True, "icon": "🖥️", "description": "内置控制台"},
    {"id": "wechat", "name": "微信", "type": "wechat", "builtin": True, "icon": "💬", "description": "微信"},
    {"id": "dingtalk", "name": "钉钉", "type": "dingtalk", "builtin": False, "icon": "🔷", "description": "钉钉机器人"},
    {"id": "feishu", "name": "飞书", "type": "feishu", "builtin": False, "icon": "🐦", "description": "飞书机器人"},
    {"id": "telegram", "name": "Telegram", "type": "telegram", "builtin": False, "icon": "✈️", "description": "Telegram Bot"},
    {"id": "discord", "name": "Discord", "type": "discord", "builtin": False, "icon": "🎮", "description": "Discord Bot"},
    {"id": "qq", "name": "QQ", "type": "qq", "builtin": False, "icon": "🐧", "description": "QQ 机器人"},
    {"id": "imessage", "name": "iMessage", "type": "imessage", "builtin": False, "icon": "💬", "description": "iMessage"},
    {"id": "wecom", "name": "企业微信", "type": "wecom", "builtin": False, "icon": "🏢", "description": "企业微信"},
    {"id": "yuanbao", "name": "元宝", "type": "yuanbao", "builtin": False, "icon": "🟣", "description": "元宝"},
    {"id": "matrix", "name": "Matrix", "type": "matrix", "builtin": False, "icon": "🔮", "description": "Matrix"},
    {"id": "sip", "name": "SIP", "type": "sip", "builtin": False, "icon": "📞", "description": "SIP 语音"},
    {"id": "xiaoyi", "name": "小艺", "type": "xiaoyi", "builtin": False, "icon": "🎭", "description": "小艺"},
    {"id": "mattermost", "name": "Mattermost", "type": "mattermost", "builtin": False, "icon": "💬", "description": "Mattermost"},
    {"id": "mqtt", "name": "MQTT", "type": "mqtt", "builtin": False, "icon": "📡", "description": "MQTT"},
    {"id": "slack", "name": "Slack", "type": "slack", "builtin": False, "icon": "💼", "description": "Slack"},
    {"id": "voice", "name": "语音", "type": "voice", "builtin": False, "icon": "🔊", "description": "语音"},
    {"id": "onebot", "name": "OneBot", "type": "onebot", "builtin": False, "icon": "🤖", "description": "OneBot"},
]


def init_channels_table():
    """确保内置频道数据存在"""
    conn = get_conn()
    for ch in BUILTIN_CHANNELS:
        conn.execute("""INSERT INTO channels (id,name,type,icon,builtin,enabled,bot_prefix,config,description,created_at)
                        VALUES (?,?,?,?,?,?,?,?,?,?)
                        ON CONFLICT(id) DO UPDATE SET
                          name=excluded.name, type=excluded.type, icon=excluded.icon,
                          builtin=excluded.builtin, description=excluded.description""",
                     (ch["id"], ch["name"], ch["type"], ch["icon"], 1 if ch["builtin"] else 0,
                      1, "", "{}", ch["description"], time.time()))
    conn.commit()
    conn.close()


def list_channels():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM channels ORDER BY builtin DESC, created_at").fetchall()
    conn.close()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["config"] = json.loads(d["config"] or "{}")
        except Exception:
            d["config"] = {}
        out.append(d)
    return out


def get_channel(cid):
    conn = get_conn()
    row = conn.execute("SELECT * FROM channels WHERE id=?", (cid,)).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    try:
        d["config"] = json.loads(d["config"] or "{}")
    except Exception:
        d["config"] = {}
    return d


def init_channel_qr_codes_table():
    """确保频道扫码接入码表存在"""
    conn = get_conn()
    conn.execute("""CREATE TABLE IF NOT EXISTS channel_qr_codes (
        code TEXT PRIMARY KEY,
        cid TEXT,
        status TEXT DEFAULT 'pending',
        created_at REAL,
        expires_at REAL
    )""")
    conn.commit()
    conn.close()


def create_channel_qr(cid, code, expires_at):
    conn = get_conn()
    now = time.time()
    conn.execute("INSERT INTO channel_qr_codes (code, cid, status, created_at, expires_at) VALUES (?,?,?,?,?)",
                 (code, cid, "pending", now, expires_at))
    conn.commit()
    conn.close()


def get_channel_qr(code):
    conn = get_conn()
    row = conn.execute("SELECT * FROM channel_qr_codes WHERE code=?", (code,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_latest_channel_qr(cid):
    conn = get_conn()
    row = conn.execute("SELECT * FROM channel_qr_codes WHERE cid=? ORDER BY created_at DESC LIMIT 1", (cid,)).fetchone()
    conn.close()
    return dict(row) if row else None


def update_channel_qr_status(code, status):
    conn = get_conn()
    conn.execute("UPDATE channel_qr_codes SET status=? WHERE code=?", (status, code))
    conn.commit()
    conn.close()


def upsert_channel(ch):
    conn = get_conn()
    conn.execute("""INSERT INTO channels (id,name,type,icon,builtin,enabled,bot_prefix,config,description,created_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(id) DO UPDATE SET
                      name=excluded.name, type=excluded.type, icon=excluded.icon,
                      enabled=excluded.enabled, bot_prefix=excluded.bot_prefix,
                      config=excluded.config, description=excluded.description""",
                 (ch["id"], ch.get("name", ""), ch.get("type", ""), ch.get("icon", "📡"),
                  1 if ch.get("builtin") else 0, 1 if ch.get("enabled", True) else 0,
                  ch.get("bot_prefix", ""), json.dumps(ch.get("config", {})),
                  ch.get("description", ""), time.time()))
    conn.commit()
    conn.close()


def delete_channel(cid):
    conn = get_conn()
    conn.execute("DELETE FROM channels WHERE id=? AND builtin=0", (cid,))
    conn.commit()
    conn.close()


# ---------- 频道消息记录 ----------
def channel_msg_table():
    conn = get_conn()
    conn.execute("""CREATE TABLE IF NOT EXISTS channel_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        cid TEXT, sender TEXT, role TEXT, content TEXT, created_at REAL
    )""")
    conn.commit()
    conn.close()


def add_channel_msg(cid, sender, role, content):
    conn = get_conn()
    conn.execute("INSERT INTO channel_messages (cid,sender,role,content,created_at) VALUES (?,?,?,?,?)",
                 (cid, sender or "匿名", role, content, time.time()))
    # 每个频道仅保留最近 200 条，避免无限增长
    conn.execute("""DELETE FROM channel_messages WHERE cid=? AND id NOT IN
                  (SELECT id FROM channel_messages WHERE cid=? ORDER BY id DESC LIMIT 200)""",
                 (cid, cid))
    conn.commit()
    conn.close()


def list_channel_msgs(cid, limit=100):
    conn = get_conn()
    rows = conn.execute(
        "SELECT sender,role,content,created_at FROM channel_messages WHERE cid=? ORDER BY id DESC LIMIT ?",
        (cid, limit)).fetchall()
    conn.close()
    return [dict(r) for r in reversed(rows)]


def clear_channel_msgs(cid):
    conn = get_conn()
    conn.execute("DELETE FROM channel_messages WHERE cid=?", (cid,))
    conn.commit()
    conn.close()


# ================= 团队协作 =================
def list_team_members():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM team_members ORDER BY created_at").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_team_member(mid):
    conn = get_conn()
    row = conn.execute("SELECT * FROM team_members WHERE id=?", (mid,)).fetchone()
    conn.close()
    return dict(row) if row else None


def upsert_team_member(m):
    conn = get_conn()
    conn.execute("""INSERT INTO team_members (id,name,email,role,avatar,status,permissions,created_at)
                    VALUES (?,?,?,?,?,?,?,?)
                    ON CONFLICT(id) DO UPDATE SET
                      name=excluded.name, email=excluded.email, role=excluded.role,
                      avatar=excluded.avatar, status=excluded.status, permissions=excluded.permissions""",
                 (m["id"], m.get("name", ""), m.get("email", ""), m.get("role", "member"),
                  m.get("avatar", "👤"), m.get("status", "active"), json.dumps(m.get("permissions", {})),
                  time.time()))
    conn.commit()
    conn.close()


def delete_team_member(mid):
    conn = get_conn()
    conn.execute("DELETE FROM team_members WHERE id=?", (mid,))
    conn.commit()
    conn.close()


def log_team_activity(user_id, action, target_type, target_id, details=None):
    conn = get_conn()
    conn.execute("""INSERT INTO team_activity (user_id, action, target_type, target_id, details, created_at)
                    VALUES (?,?,?,?,?,?)""",
                 (user_id, action, target_type, target_id, json.dumps(details or {}), time.time()))
    conn.commit()
    conn.close()


def list_team_activity(limit=50):
    conn = get_conn()
    rows = conn.execute("SELECT * FROM team_activity ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ================= 共享对话 =================
def share_conversation(conv_id, shared_by, shared_with, permission="view"):
    import uuid
    sid = f"share_{uuid.uuid4().hex[:12]}"
    conn = get_conn()
    conn.execute("""INSERT INTO shared_conversations (id,conv_id,shared_by,shared_with,permission,created_at)
                    VALUES (?,?,?,?,?,?)""",
                 (sid, conv_id, shared_by, json.dumps(shared_with), permission, time.time()))
    conn.commit()
    conn.close()
    log_team_activity(shared_by, "share", "conversation", conv_id, {"shared_with": shared_with})
    return sid


def list_shared_conversations(user_id=None):
    conn = get_conn()
    if user_id:
        rows = conn.execute("SELECT * FROM shared_conversations WHERE shared_with LIKE ? ORDER BY created_at DESC",
                           (f'%"{user_id}"%',)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM shared_conversations ORDER BY created_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ================= 工作流 =================

def init_workflows_table():
    """初始化工作流相关表"""
    conn = get_conn()
    conn.executescript("""
    -- 工作流定义
    CREATE TABLE IF NOT EXISTS workflows (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        description TEXT DEFAULT '',
        nodes TEXT DEFAULT '[]',
        edges TEXT DEFAULT '[]',
        config TEXT DEFAULT '{}',
        enabled INTEGER DEFAULT 1,
        version INTEGER DEFAULT 1,
        tags TEXT DEFAULT '[]',
        created_at REAL,
        updated_at REAL
    );
    -- 工作流执行记录
    CREATE TABLE IF NOT EXISTS workflow_executions (
        id TEXT PRIMARY KEY,
        workflow_id TEXT NOT NULL,
        input TEXT DEFAULT '{}',
        output TEXT DEFAULT '',
        status TEXT DEFAULT 'pending',
        nodes_status TEXT DEFAULT '{}',
        node_requests TEXT DEFAULT '{}',
        error TEXT DEFAULT '',
        started_at REAL,
        completed_at REAL,
        duration_ms INTEGER DEFAULT 0,
        tokens_used INTEGER DEFAULT 0,
        FOREIGN KEY (workflow_id) REFERENCES workflows(id)
    );
    -- 工作流模板
    CREATE TABLE IF NOT EXISTS workflow_templates (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        description TEXT DEFAULT '',
        category TEXT DEFAULT 'general',
        nodes TEXT DEFAULT '[]',
        edges TEXT DEFAULT '[]',
        icon TEXT DEFAULT '🔧',
        usage_count INTEGER DEFAULT 0,
        created_at REAL
    );
    CREATE INDEX IF NOT EXISTS idx_wf_exec_workflow ON workflow_executions(workflow_id);
    CREATE INDEX IF NOT EXISTS idx_wf_exec_status ON workflow_executions(status);
    """)
    conn.commit()
    conn.close()
    # 迁移：为旧数据库添加 node_requests 列
    try:
        conn2 = get_conn()
        conn2.execute("ALTER TABLE workflow_executions ADD COLUMN node_requests TEXT DEFAULT '{}'")
        conn2.commit()
        conn2.close()
    except Exception:
        pass  # 列已存在，忽略
    # 初始化内置模板
    _init_workflow_templates()


def _init_workflow_templates():
    """初始化内置工作流模板"""
    builtin_templates = [
        {
            "id": "tpl_qa",
            "name": "问答助手",
            "description": "简单的问答工作流，接收问题并调用LLM回答",
            "category": "basic",
            "icon": "💬",
            "nodes": json.dumps([
                {"id": "start", "type": "start", "label": "开始", "x": 100, "y": 200, "config": {"input_fields": ["question"]}},
                {"id": "llm", "type": "llm", "label": "LLM回答", "x": 350, "y": 200, "config": {"prompt": "请回答以下问题：\n\n{{question}}", "model": ""}},
                {"id": "end", "type": "end", "label": "结束", "x": 600, "y": 200, "config": {"output_field": "answer"}},
            ]),
            "edges": json.dumps([
                {"source": "start", "target": "llm"},
                {"source": "llm", "target": "end"},
            ]),
        },
        {
            "id": "tpl_router",
            "name": "智能路由",
            "description": "根据输入内容智能路由到不同的处理分支",
            "category": "advanced",
            "icon": "🔀",
            "nodes": json.dumps([
                {"id": "start", "type": "start", "label": "开始", "x": 100, "y": 250, "config": {"input_fields": ["query"]}},
                {"id": "classifier", "type": "llm", "label": "意图分类", "x": 300, "y": 250, "config": {"prompt": "请判断以下查询属于哪个类别（编程/写作/其他），只回复类别名称：\n\n{{query}}", "model": ""}},
                {"id": "cond", "type": "condition", "label": "条件分支", "x": 500, "y": 250, "config": {"variable": "classifier_output", "conditions": [
                    {"operator": "contains", "value": "编程", "target": "code_llm"},
                    {"operator": "contains", "value": "写作", "target": "write_llm"},
                    {"operator": "default", "target": "default_llm"}
                ]}},
                {"id": "code_llm", "type": "llm", "label": "编程助手", "x": 700, "y": 100, "config": {"prompt": "你是编程助手，请回答：\n{{query}}", "model": ""}},
                {"id": "write_llm", "type": "llm", "label": "写作助手", "x": 700, "y": 250, "config": {"prompt": "你是写作助手，请回答：\n{{query}}", "model": ""}},
                {"id": "default_llm", "type": "llm", "label": "通用助手", "x": 700, "y": 400, "config": {"prompt": "请回答：\n{{query}}", "model": ""}},
                {"id": "end", "type": "end", "label": "结束", "x": 950, "y": 250, "config": {"output_field": "result"}},
            ]),
            "edges": json.dumps([
                {"source": "start", "target": "classifier"},
                {"source": "classifier", "target": "cond"},
                {"source": "cond", "target": "code_llm", "sourceHandle": "0"},
                {"source": "cond", "target": "write_llm", "sourceHandle": "1"},
                {"source": "cond", "target": "default_llm", "sourceHandle": "2"},
                {"source": "code_llm", "target": "end"},
                {"source": "write_llm", "target": "end"},
                {"source": "default_llm", "target": "end"},
            ]),
        },
        {
            "id": "tpl_rag",
            "name": "RAG检索增强",
            "description": "检索知识库后增强LLM回答",
            "category": "advanced",
            "icon": "📚",
            "nodes": json.dumps([
                {"id": "start", "type": "start", "label": "开始", "x": 100, "y": 200, "config": {"input_fields": ["question"]}},
                {"id": "retrieve", "type": "tool", "label": "知识检索", "x": 300, "y": 200, "config": {"tool_name": "kb_search", "arguments": {"query": "{{question}}", "top_k": 5}}},
                {"id": "llm", "type": "llm", "label": "LLM回答", "x": 550, "y": 200, "config": {"prompt": "基于以下参考资料回答用户问题。\n\n参考资料：\n{{retrieve_output}}\n\n用户问题：{{question}}\n\n请给出准确、详细的回答：", "model": ""}},
                {"id": "end", "type": "end", "label": "结束", "x": 800, "y": 200, "config": {"output_field": "answer"}},
            ]),
            "edges": json.dumps([
                {"source": "start", "target": "retrieve"},
                {"source": "retrieve", "target": "llm"},
                {"source": "llm", "target": "end"},
            ]),
        },
        {
            "id": "tpl_multi_agent",
            "name": "多Agent协作",
            "description": "多个Agent分工协作处理复杂任务",
            "category": "advanced",
            "icon": "🤖",
            "nodes": json.dumps([
                {"id": "start", "type": "start", "label": "开始", "x": 100, "y": 250, "config": {"input_fields": ["task"]}},
                {"id": "planner", "type": "llm", "label": "任务规划", "x": 300, "y": 250, "config": {"prompt": "请将以下任务分解为3个子任务，每行一个：\n\n{{task}}", "model": ""}},
                {"id": "agent1", "type": "llm", "label": "Agent-1", "x": 550, "y": 100, "config": {"prompt": "请完成以下子任务：\n{{planner_output}}\n\n你是第一个执行者，专注于分析部分：", "model": ""}},
                {"id": "agent2", "type": "llm", "label": "Agent-2", "x": 550, "y": 250, "config": {"prompt": "请完成以下子任务：\n{{planner_output}}\n\n你是第二个执行者，专注于实现部分：", "model": ""}},
                {"id": "agent3", "type": "llm", "label": "Agent-3", "x": 550, "y": 400, "config": {"prompt": "请完成以下子任务：\n{{planner_output}}\n\n你是第三个执行者，专注于测试部分：", "model": ""}},
                {"id": "merger", "type": "llm", "label": "结果整合", "x": 800, "y": 250, "config": {"prompt": "请整合以下三个Agent的输出，形成完整的结果：\n\nAgent-1输出：\n{{agent1_output}}\n\nAgent-2输出：\n{{agent2_output}}\n\nAgent-3输出：\n{{agent3_output}}", "model": ""}},
                {"id": "end", "type": "end", "label": "结束", "x": 1050, "y": 250, "config": {"output_field": "result"}},
            ]),
            "edges": json.dumps([
                {"source": "start", "target": "planner"},
                {"source": "planner", "target": "agent1"},
                {"source": "planner", "target": "agent2"},
                {"source": "planner", "target": "agent3"},
                {"source": "agent1", "target": "merger"},
                {"source": "agent2", "target": "merger"},
                {"source": "agent3", "target": "merger"},
                {"source": "merger", "target": "end"},
            ]),
        },
        {
            "id": "tpl_code_gen",
            "name": "代码生成器",
            "description": "根据需求描述生成代码并解释",
            "category": "coding",
            "icon": "💻",
            "nodes": json.dumps([
                {"id": "start", "type": "start", "label": "开始", "x": 100, "y": 200, "config": {"input_fields": ["requirement", "language"]}},
                {"id": "analyze", "type": "llm", "label": "需求分析", "x": 300, "y": 200, "config": {"prompt": "请分析以下需求，列出关键功能点：\n\n需求：{{requirement}}\n编程语言：{{language}}", "model": ""}},
                {"id": "codegen", "type": "llm", "label": "代码生成", "x": 550, "y": 200, "config": {"prompt": "根据以下分析，用{{language}}生成代码：\n\n分析结果：\n{{analyze_output}}\n\n请生成完整、可运行的代码：", "model": ""}},
                {"id": "explain", "type": "llm", "label": "代码解释", "x": 800, "y": 200, "config": {"prompt": "请解释以下代码的实现逻辑和关键点：\n\n{{codegen_output}}", "model": ""}},
                {"id": "end", "type": "end", "label": "结束", "x": 1050, "y": 200, "config": {"output_field": "result"}},
            ]),
            "edges": json.dumps([
                {"source": "start", "target": "analyze"},
                {"source": "analyze", "target": "codegen"},
                {"source": "codegen", "target": "explain"},
                {"source": "explain", "target": "end"},
            ]),
        },
        {
            "id": "tpl_content",
            "name": "内容创作",
            "description": "多步骤内容创作工作流",
            "category": "writing",
            "icon": "✍️",
            "nodes": json.dumps([
                {"id": "start", "type": "start", "label": "开始", "x": 100, "y": 200, "config": {"input_fields": ["topic", "style"]}},
                {"id": "outline", "type": "llm", "label": "大纲生成", "x": 300, "y": 200, "config": {"prompt": "请为以下主题生成文章大纲（3-5个要点）：\n\n主题：{{topic}}\n风格：{{style}}", "model": ""}},
                {"id": "draft", "type": "llm", "label": "初稿撰写", "x": 550, "y": 200, "config": {"prompt": "根据以下大纲撰写文章初稿：\n\n大纲：\n{{outline_output}}\n\n风格：{{style}}", "model": ""}},
                {"id": "polish", "type": "llm", "label": "润色优化", "x": 800, "y": 200, "config": {"prompt": "请润色优化以下文章，提升可读性和文采：\n\n{{draft_output}}", "model": ""}},
                {"id": "end", "type": "end", "label": "结束", "x": 1050, "y": 200, "config": {"output_field": "article"}},
            ]),
            "edges": json.dumps([
                {"source": "start", "target": "outline"},
                {"source": "outline", "target": "draft"},
                {"source": "draft", "target": "polish"},
                {"source": "polish", "target": "end"},
            ]),
        },
        {
            "id": "tpl_batch",
            "name": "批量处理",
            "description": "遍历输入数组，逐项调用LLM处理，收集结果",
            "category": "advanced",
            "icon": "🔄",
            "nodes": json.dumps([
                {"id": "start", "type": "start", "label": "开始", "x": 100, "y": 200, "config": {"input_fields": ["items"]}},
                {"id": "loop1", "type": "loop", "label": "循环", "x": 300, "y": 200, "config": {"array_variable": "{{items}}", "item_variable": "item", "index_variable": "index", "max_iterations": 100}},
                {"id": "llm1", "type": "llm", "label": "逐项处理", "x": 550, "y": 200, "config": {"prompt": "请处理以下内容，直接给出处理结果：\n\n{{item}}", "model": "", "output_variable": "processed"}},
                {"id": "end", "type": "end", "label": "结束", "x": 800, "y": 200, "config": {"output_field": "loop1_results"}},
            ]),
            "edges": json.dumps([
                {"source": "start", "target": "loop1"},
                {"source": "loop1", "target": "llm1"},
                {"source": "llm1", "target": "end"},
            ]),
        },
        {
            "id": "tpl_data_pipeline",
            "name": "数据处理管道",
            "description": "解析JSON→遍历转换→结果输出，展示iteration与json_parse",
            "category": "advanced",
            "icon": "📊",
            "nodes": json.dumps([
                {"id": "start", "type": "start", "label": "开始", "x": 100, "y": 200, "config": {"input_fields": ["raw"]}},
                {"id": "jp", "type": "json_parse", "label": "JSON解析", "x": 300, "y": 200, "config": {"input": "{{raw}}"}},
                {"id": "iter1", "type": "iteration", "label": "遍历", "x": 500, "y": 200, "config": {"array_variable": "{{data}}", "item_variable": "item"}},
                {"id": "tp1", "type": "text_process", "label": "转大写", "x": 700, "y": 200, "config": {"input": "{{item}}", "op": "upper", "output_variable": "upcased"}},
                {"id": "end", "type": "end", "label": "结束", "x": 900, "y": 200, "config": {"output_field": "iter1_results"}},
            ]),
            "edges": json.dumps([
                {"source": "start", "target": "jp"},
                {"source": "jp", "target": "iter1"},
                {"source": "iter1", "target": "tp1"},
                {"source": "tp1", "target": "end"},
            ]),
        },
    ]
    
    conn = get_conn()
    for t in builtin_templates:
        conn.execute("""INSERT INTO workflow_templates (id, name, description, category, nodes, edges, icon, usage_count, created_at)
                        VALUES (?,?,?,?,?,?,?,?,?)
                        ON CONFLICT(id) DO UPDATE SET
                          name=excluded.name, description=excluded.description,
                          category=excluded.category, nodes=excluded.nodes,
                          edges=excluded.edges, icon=excluded.icon""",
                     (t["id"], t["name"], t["description"], t["category"],
                      t["nodes"], t["edges"], t["icon"], 0, time.time()))
    conn.commit()
    conn.close()


# ----- 工作流 CRUD -----

def _decode_json(val, default):
    """安全解析 JSON 字段，兼容双重编码"""
    for _ in range(3):
        if isinstance(val, str):
            try:
                val = json.loads(val)
            except Exception:
                break
        else:
            break
    return val if val is not None else default


def list_workflows():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM workflows ORDER BY updated_at DESC").fetchall()
    conn.close()
    out = []
    for r in rows:
        d = dict(r)
        for k in ("nodes", "edges", "config", "tags"):
            d[k] = _decode_json(d.get(k), [] if k != "config" else {})
        out.append(d)
    return out


def get_workflow(wid):
    conn = get_conn()
    row = conn.execute("SELECT * FROM workflows WHERE id=?", (wid,)).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    for k in ("nodes", "edges", "config", "tags"):
        d[k] = _decode_json(d.get(k), [] if k != "config" else {})
    return d


def save_workflow(wf):
    conn = get_conn()
    now = time.time()
    conn.execute("""INSERT INTO workflows (id, name, description, nodes, edges, config, enabled, version, tags, created_at, updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(id) DO UPDATE SET
                      name=excluded.name, description=excluded.description, nodes=excluded.nodes,
                      edges=excluded.edges, config=excluded.config, enabled=excluded.enabled,
                      version=version+1, tags=excluded.tags, updated_at=excluded.updated_at""",
                 (wf["id"], wf.get("name", ""), wf.get("description", ""),
                  json.dumps(wf.get("nodes", [])), json.dumps(wf.get("edges", [])),
                  json.dumps(wf.get("config", {})), 1 if wf.get("enabled", True) else 0,
                  wf.get("version", 1), json.dumps(wf.get("tags", [])),
                  wf.get("created_at", now), now))
    conn.commit()
    conn.close()


def delete_workflow(wid):
    conn = get_conn()
    conn.execute("DELETE FROM workflows WHERE id=?", (wid,))
    conn.execute("DELETE FROM workflow_executions WHERE workflow_id=?", (wid,))
    conn.commit()
    conn.close()


def list_workflow_executions(wid=None, limit=50):
    conn = get_conn()
    if wid:
        rows = conn.execute("SELECT * FROM workflow_executions WHERE workflow_id=? ORDER BY started_at DESC LIMIT ?", (wid, limit)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM workflow_executions ORDER BY started_at DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    out = []
    for r in rows:
        d = dict(r)
        for k in ("input", "nodes_status", "node_requests"):
            try: d[k] = json.loads(d[k] or "{}")
            except: d[k] = {}
        out.append(d)
    return out


def save_workflow_execution(execution):
    conn = get_conn()
    # output/error 可能是 dict（start 节点输出对象），必须序列化后才能绑定 SQLite
    output_val = execution.get("output", "")
    if not isinstance(output_val, str):
        output_val = json.dumps(output_val, ensure_ascii=False, default=str)
    error_val = execution.get("error", "")
    if not isinstance(error_val, str):
        error_val = json.dumps(error_val, ensure_ascii=False, default=str)
    conn.execute("""INSERT INTO workflow_executions (id, workflow_id, input, output, status, nodes_status, node_requests, error, started_at, completed_at, duration_ms, tokens_used)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(id) DO UPDATE SET
                      output=excluded.output, status=excluded.status, nodes_status=excluded.nodes_status,
                      node_requests=excluded.node_requests, error=excluded.error, completed_at=excluded.completed_at,
                      duration_ms=excluded.duration_ms, tokens_used=excluded.tokens_used""",
                 (execution["id"], execution["workflow_id"],
                  json.dumps(execution.get("input", {})), output_val,
                  execution.get("status", "pending"), json.dumps(execution.get("nodes_status", {})),
                  json.dumps(execution.get("node_requests", {})),
                  error_val, execution.get("started_at", time.time()),
                  execution.get("completed_at"), execution.get("duration_ms", 0),
                  execution.get("tokens_used", 0)))
    conn.commit()
    conn.close()


# ----- 工作流模板 CRUD -----

def list_workflow_templates(category=None):
    conn = get_conn()
    if category and category != "all":
        rows = conn.execute("SELECT * FROM workflow_templates WHERE category=? ORDER BY usage_count DESC", (category,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM workflow_templates ORDER BY usage_count DESC").fetchall()
    conn.close()
    out = []
    for r in rows:
        d = dict(r)
        for k in ("nodes", "edges"):
            d[k] = _decode_json(d.get(k), [])
        out.append(d)
    return out


def get_workflow_template(tid):
    conn = get_conn()
    row = conn.execute("SELECT * FROM workflow_templates WHERE id=?", (tid,)).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    for k in ("nodes", "edges"):
        d[k] = _decode_json(d.get(k), [])
    return d


def use_workflow_template(tid):
    """使用模板，增加使用计数"""
    conn = get_conn()
    conn.execute("UPDATE workflow_templates SET usage_count=usage_count+1 WHERE id=?", (tid,))
    conn.commit()
    conn.close()
