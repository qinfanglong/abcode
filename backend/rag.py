"""ABcode 知识库 RAG - 上传文档、分块、关键词检索（纯本地实现）"""
import hashlib
import json
import re
import time
import sqlite3
from pathlib import Path

from db import DB_PATH, get_conn

KB_DIR = Path(__file__).parent.parent / "data" / "kb"
KB_DIR.mkdir(parents=True, exist_ok=True)


def init_kb():
    conn = get_conn()
    conn.execute("""
    CREATE TABLE IF NOT EXISTS kb_docs (
        id TEXT PRIMARY KEY,
        name TEXT,
        size INTEGER,
        chunks INTEGER,
        created_at REAL
    )""")
    conn.execute("""
    CREATE TABLE IF NOT EXISTS kb_chunks (
        id TEXT PRIMARY KEY,
        doc_id TEXT,
        content TEXT,
        idx INTEGER
    )""")
    conn.commit()
    conn.close()


def _chunk_text(text, size=600, overlap=80):
    """将文本切成带重叠的分块"""
    text = re.sub(r"\n{3,}", "\n\n", text)
    chunks = []
    i = 0
    n = len(text)
    while i < n:
        end = min(i + size, n)
        chunks.append(text[i:end])
        if end >= n:
            break
        i = end - overlap
    return [c for c in chunks if c.strip()]


def add_document(filename: str, content: bytes):
    """添加文档，返回 (doc_id, chunk_count)"""
    text = content.decode("utf-8", errors="ignore")
    if len(text) < 20:
        return None, 0
    chunks = _chunk_text(text)
    if not chunks:
        return None, 0
    doc_id = hashlib.md5(f"{filename}{time.time()}".encode()).hexdigest()[:12]
    conn = get_conn()
    conn.execute("INSERT INTO kb_docs (id,name,size,chunks,created_at) VALUES (?,?,?,?,?)",
                 (doc_id, filename, len(content), len(chunks), time.time()))
    for i, c in enumerate(chunks):
        conn.execute("INSERT INTO kb_chunks (id,doc_id,content,idx) VALUES (?,?,?,?)",
                     (f"{doc_id}_{i}", doc_id, c, i))
    conn.commit()
    conn.close()
    return doc_id, len(chunks)


def list_docs():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM kb_docs ORDER BY created_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_doc(doc_id):
    conn = get_conn()
    conn.execute("DELETE FROM kb_chunks WHERE doc_id=?", (doc_id,))
    conn.execute("DELETE FROM kb_docs WHERE id=?", (doc_id,))
    conn.commit()
    conn.close()


def _tokenize(text):
    """简单分词：中文按字+词，英文按单词"""
    # 中文连续片段按 2-gram 处理（避免单字噪音），英文按词
    tokens = set()
    # 英文/数字词
    for w in re.findall(r"[a-zA-Z0-9_]{2,}", text.lower()):
        tokens.add(w)
    # 中文 bigram
    zh = re.findall(r"[\u4e00-\u9fff]+", text)
    for seg in zh:
        for i in range(len(seg) - 1):
            tokens.add(seg[i:i + 2])
    return tokens


def search(query, top_k=5):
    """关键词检索知识库，返回最相关片段列表"""
    q_tokens = _tokenize(query)
    if not q_tokens:
        return []
    conn = get_conn()
    rows = conn.execute("SELECT id, doc_id, content, idx FROM kb_chunks").fetchall()
    scored = []
    for r in rows:
        content = r["content"]
        c_tokens = _tokenize(content)
        if not c_tokens:
            continue
        inter = q_tokens & c_tokens
        if not inter:
            continue
        score = sum(1.0 / (1 + len(c_tokens)) * 100 for _ in inter)  # TF 近似 + IDF 简化
        # 长度惩罚：过长/过短片段降权
        score *= min(1.0, len(content) / 300)
        scored.append((score, r))
    conn.close()
    scored.sort(key=lambda x: -x[0])
    results = []
    for score, r in scored[:top_k]:
        # 找文档名
        conn2 = get_conn()
        doc = conn2.execute("SELECT name FROM kb_docs WHERE id=?", (r["doc_id"],)).fetchone()
        conn2.close()
        results.append({
            "doc_id": r["doc_id"],
            "doc_name": doc["name"] if doc else "未知",
            "content": r["content"].strip()[:800],
            "score": round(score, 2),
        })
    return results


def build_context(query, top_k=4):
    """构建 RAG 上下文文本，无匹配返回 None"""
    results = search(query, top_k)
    if not results:
        return None
    parts = [f"[{r['doc_name']}] {r['content']}" for r in results]
    return "\n\n---\n\n".join(parts)
