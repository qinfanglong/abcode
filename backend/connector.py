"""ABcode 数据连接器 - 连接 SQLite/MySQL/PostgreSQL/CSV/JSON/HTTP 数据源，供 Agent 查询"""
import csv
import io
import json
import os
import sqlite3
import sys
from pathlib import Path

import db

# 连接器数据目录：源码模式在仓库根 data/connectors；frozen 模式在 exe 旁 data/connectors
if getattr(sys, 'frozen', False):
    _CONN_ROOT = Path(sys.executable).parent / "data" / "connectors"
else:
    _CONN_ROOT = Path(__file__).parent.parent / "data" / "connectors"

DATA_DIR = Path(os.environ.get("ABCODE_CONNECTORS", _CONN_ROOT))
DATA_DIR.mkdir(parents=True, exist_ok=True)

# 支持的连接器类型
CONNECTOR_TYPES = {
    "sqlite": "SQLite",
    "mysql": "MySQL",
    "postgres": "PostgreSQL",
    "csv": "CSV 文件",
    "json": "JSON 文件",
    "http": "HTTP API",
}


def init_builtins():
    """内置示例连接器（幂等）"""
    existing = db.list_connectors()
    if not existing:
        # 示例：内存 SQLite（演示用）
        db.upsert_connector({
            "id": "conn_demo",
            "name": "示例数据源 (SQLite)",
            "type": "sqlite",
            "config": {"path": str(DATA_DIR / "demo.db"), "readonly": True},
            "enabled": 1,
        })


def _load_connector(c):
    cfg = c.get("config", {})
    ctype = c.get("type", "sqlite")
    if ctype == "sqlite":
        path = cfg.get("path", "")
        if not path:
            return None
        p = Path(path)
        if not p.exists() or p.stat().st_size == 0:
            # 创建演示库
            _create_demo_db(p)
        return sqlite3.connect(str(p))
    return None


def test_connector(c):
    """测试连接器是否可用，返回 (ok, message)"""
    ctype = c.get("type", "sqlite")
    cfg = c.get("config", {})
    try:
        if ctype == "sqlite":
            path = cfg.get("path", "")
            if not path:
                return False, "缺少数据库文件路径"
            p = Path(path)
            if not p.exists():
                return False, f"文件不存在: {path}"
            conn = sqlite3.connect(str(p))
            conn.execute("SELECT 1")
            conn.close()
            return True, f"SQLite 连接成功，{p.stat().st_size} bytes"
        elif ctype == "mysql":
            import pymysql
            conn = pymysql.connect(host=cfg.get("host", "localhost"), port=int(cfg.get("port", 3306)),
                                   user=cfg.get("user", ""), password=cfg.get("password", ""),
                                   database=cfg.get("database", ""), connect_timeout=5)
            conn.close()
            return True, f"MySQL 连接成功 ({cfg.get('host')}:{cfg.get('port', 3306)}/{cfg.get('database')})"
        elif ctype == "postgres":
            import psycopg2
            conn = psycopg2.connect(host=cfg.get("host", "localhost"), port=int(cfg.get("port", 5432)),
                                    user=cfg.get("user", ""), password=cfg.get("password", ""),
                                    dbname=cfg.get("database", ""), connect_timeout=5)
            conn.close()
            return True, f"PostgreSQL 连接成功 ({cfg.get('host')}:{cfg.get('port', 5432)}/{cfg.get('database')})"
        elif ctype == "csv":
            path = cfg.get("path", "")
            if not path or not Path(path).exists():
                return False, f"文件不存在: {path}"
            with open(path, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                next(reader, None)
            return True, f"CSV 可读: {Path(path).name}"
        elif ctype == "json":
            path = cfg.get("path", "")
            if not path or not Path(path).exists():
                return False, f"文件不存在: {path}"
            with open(path, encoding="utf-8") as f:
                json.load(f)
            return True, f"JSON 可读: {Path(path).name}"
        elif ctype == "http":
            import httpx
            url = cfg.get("url", "")
            if not url:
                return False, "缺少 API 地址"
            resp = httpx.get(url, timeout=8)
            return (True, f"HTTP {resp.status_code}") if resp.status_code == 200 else (False, f"HTTP {resp.status_code}")
        return False, f"不支持的连接器类型: {ctype}"
    except ImportError as e:
        return False, f"缺少依赖库: {e.name} (pip install {e.name})"
    except Exception as e:
        return False, f"连接失败: {e}"


def _create_demo_db(path):
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE IF NOT EXISTS products (id INTEGER PRIMARY KEY, name TEXT, price REAL, stock INTEGER)")
    conn.execute("CREATE TABLE IF NOT EXISTS orders (id INTEGER PRIMARY KEY, product TEXT, qty INTEGER, total REAL)")
    conn.executemany("INSERT INTO products (name, price, stock) VALUES (?,?,?)",
                     [("苹果", 5.5, 100), ("香蕉", 3.2, 200), ("牛奶", 12.8, 50), ("面包", 8.9, 80)])
    conn.executemany("INSERT INTO orders (product, qty, total) VALUES (?,?,?)",
                     [("苹果", 3, 16.5), ("牛奶", 2, 25.6), ("面包", 5, 44.5)])
    conn.commit()
    conn.close()


def query_connector(cid, query, limit=50):
    """查询连接器，返回 (ok, result_str)"""
    c = next((x for x in db.list_connectors() if x["id"] == cid), None)
    if not c:
        return False, "连接器不存在"
    if not c["enabled"]:
        return False, "连接器未启用"
    ctype = c.get("type", "sqlite")
    try:
        if ctype == "sqlite":
            conn = _load_connector(c)
            if not conn:
                return False, "SQLite 连接失败"
            try:
                cur = conn.execute(query)
                cols = [d[0] for d in cur.description] if cur.description else []
                rows = cur.fetchmany(limit)
                conn.close()
                if not cols:
                    return True, f"执行成功，影响 {cur.rowcount} 行" if cur.rowcount else "执行成功"
                # 格式化结果
                lines = []
                for r in rows:
                    lines.append(json.dumps(dict(zip(cols, r)), ensure_ascii=False))
                return True, "列: " + ", ".join(cols) + "\n" + "\n".join(lines) if lines else ("列: " + ", ".join(cols) + "\n(无数据)")
            except Exception as e:
                conn.close()
                return False, f"SQL 错误: {e}"
        elif ctype == "mysql":
            import pymysql
            conn = pymysql.connect(host=c["config"].get("host", "localhost"), port=int(c["config"].get("port", 3306)),
                                   user=c["config"].get("user", ""), password=c["config"].get("password", ""),
                                   database=c["config"].get("database", ""), connect_timeout=8)
            with conn.cursor() as cur:
                cur.execute(query)
                cols = [d[0] for d in cur.description] if cur.description else []
                rows = cur.fetchmany(limit)
            conn.close()
            if not cols:
                return True, "执行成功"
            lines = [json.dumps(dict(zip(cols, r)), ensure_ascii=False, default=str) for r in rows]
            return True, "列: " + ", ".join(cols) + "\n" + "\n".join(lines) if lines else ("列: " + ", ".join(cols) + "\n(无数据)")
        elif ctype == "postgres":
            import psycopg2
            conn = psycopg2.connect(host=c["config"].get("host", "localhost"), port=int(c["config"].get("port", 5432)),
                                    user=c["config"].get("user", ""), password=c["config"].get("password", ""),
                                    dbname=c["config"].get("database", ""), connect_timeout=8)
            cur = conn.cursor()
            cur.execute(query)
            cols = [d[0] for d in cur.description] if cur.description else []
            rows = cur.fetchmany(limit)
            conn.close()
            if not cols:
                return True, "执行成功"
            lines = [json.dumps(dict(zip(cols, r)), ensure_ascii=False, default=str) for r in rows]
            return True, "列: " + ", ".join(cols) + "\n" + "\n".join(lines) if lines else ("列: " + ", ".join(cols) + "\n(无数据)")
        elif ctype == "csv":
            path = c["config"].get("path", "")
            rows = []
            with open(path, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for i, row in enumerate(reader):
                    if i >= limit:
                        break
                    rows.append(json.dumps(row, ensure_ascii=False))
            return True, "\n".join(rows) if rows else "(无数据)"
        elif ctype == "json":
            path = c["config"].get("path", "")
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                return True, json.dumps(data[:limit], ensure_ascii=False, indent=1)
            return True, json.dumps(data, ensure_ascii=False, indent=1)
        elif ctype == "http":
            import httpx
            url = c["config"].get("url", "")
            resp = httpx.get(url, timeout=15)
            if resp.status_code != 200:
                return False, f"HTTP {resp.status_code}"
            data = resp.json()
            if isinstance(data, list):
                return True, json.dumps(data[:limit], ensure_ascii=False, indent=1)
            return True, json.dumps(data, ensure_ascii=False, indent=1)
        else:
            return False, f"不支持的连接器类型: {ctype}"
    except ImportError as e:
        return False, f"缺少依赖库: {e.name} (pip install {e.name})"
    except Exception as e:
        return False, f"查询错误: {e}"


def list_tables(cid):
    """列出数据源表，供前端展示"""
    c = next((x for x in db.list_connectors() if x["id"] == cid), None)
    if not c:
        return []
    ctype = c.get("type", "sqlite")
    try:
        if ctype == "sqlite":
            conn = _load_connector(c)
            if not conn:
                return []
            rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            conn.close()
            return [r[0] for r in rows]
        elif ctype == "mysql":
            import pymysql
            conn = pymysql.connect(host=c["config"].get("host", "localhost"), port=int(c["config"].get("port", 3306)),
                                   user=c["config"].get("user", ""), password=c["config"].get("password", ""),
                                   database=c["config"].get("database", ""), connect_timeout=5)
            with conn.cursor() as cur:
                cur.execute("SHOW TABLES")
                rows = [r[0] for r in cur.fetchall()]
            conn.close()
            return rows
        elif ctype == "postgres":
            import psycopg2
            conn = psycopg2.connect(host=c["config"].get("host", "localhost"), port=int(c["config"].get("port", 5432)),
                                    user=c["config"].get("user", ""), password=c["config"].get("password", ""),
                                    dbname=c["config"].get("database", ""), connect_timeout=5)
            cur = conn.cursor()
            cur.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'")
            rows = [r[0] for r in cur.fetchall()]
            conn.close()
            return rows
    except Exception:
        return []
    return []


def build_tool_map(ids=None):
    """构建 {tool_name: ("connector", cid)}"""
    mapping = {}
    connectors = db.list_connectors()
    if ids is not None:
        connectors = [c for c in connectors if c["id"] in ids]
    for c in connectors:
        if not c["enabled"]:
            continue
        name = f"query_{c['id']}"
        mapping[name] = ("connector", c["id"])
    return mapping


def connector_tools_for(ids=None):
    """生成连接器查询工具定义"""
    out = []
    connectors = db.list_connectors()
    if ids is not None:
        connectors = [c for c in connectors if c["id"] in ids]
    for c in connectors:
        if not c["enabled"]:
            continue
        tables = ""
        if c.get("type") == "sqlite":
            t = list_tables(c["id"])
            tables = f" 可用表: {', '.join(t)}" if t else ""
        out.append({
            "type": "function",
            "function": {
                "name": f"query_{c['id']}",
                "description": f"查询数据连接器「{c['name']}」（{c['type']}）。{tables} 对 SQLite 用 SELECT 查询并限制返回行数。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": f"查询语句/表达式。对 {c['type']} 类型使用 SQL 或数据查询"},
                    },
                    "required": ["query"],
                },
            },
        })
    return out


def execute_connector_tool(cid, tool_name, args):
    query = args.get("query", "")
    return query_connector(cid, query)
