"""ABcode 知识库 RAG - 上传文档、分块、BM25 关键词检索（纯本地实现）
支持格式：文本类（txt/md/csv/json/log/py/js/html/css/yaml/xml），二进制文件提示不支持
"""
import hashlib
import json
import math
import re
import time
import sqlite3
from pathlib import Path

from db import DB_PATH, get_conn

KB_DIR = Path(__file__).parent.parent / "data" / "kb"
KB_DIR.mkdir(parents=True, exist_ok=True)

# 支持的文本扩展名（按类型分组，用于图标/标签展示）
TEXT_EXTS = {
    "txt": "文本", "md": "Markdown", "markdown": "Markdown", "csv": "CSV",
    "tsv": "TSV", "json": "JSON", "log": "日志", "py": "Python", "js": "JS",
    "ts": "TS", "html": "HTML", "css": "CSS", "yaml": "YAML", "yml": "YAML",
    "xml": "XML", "ini": "配置", "conf": "配置", "sh": "Shell", "sql": "SQL",
    "c": "C", "cpp": "C++", "h": "头文件", "java": "Java", "go": "Go",
    "rs": "Rust", "php": "PHP", "rb": "Ruby", "vue": "Vue", "jsx": "JSX",
    "tsx": "TSX", "toml": "TOML", "rst": "RST", "tex": "LaTeX",
}
UNSUPPORTED_EXTS = {"pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "zip", "rar", "7z", "png", "jpg", "jpeg", "gif", "bmp", "webp", "mp3", "mp4", "avi", "mov", "wav"}

# 二进制文件魔数检测（即使扩展名伪装成 txt 也能识别）
_BINARY_MAGICS = [
    (b"PK\x03\x04", "ZIP/OOXML"),      # zip, docx, xlsx, pptx
    (b"%PDF", "PDF"),
    (b"\x89PNG", "PNG"),
    (b"\xff\xd8\xff", "JPEG"),
    (b"GIF8", "GIF"),
    (b"BM", "BMP"),
    (b"RIFF", "WAV/AVI"),
    (b"\x00\x00\x01\xba", "MPEG"),
    (b"\x1f\x8b", "GZIP"),
    (b"7z\xbc\xaf\x27\x1c", "7ZIP"),
    (b"Rar!", "RAR"),
]


def _is_binary(content: bytes):
    """通过魔数检测二进制内容"""
    head = content[:8]
    for magic, _name in _BINARY_MAGICS:
        if head.startswith(magic):
            return True
    # 文本启发式：含大量空字节视为二进制
    if len(content) > 0 and content.count(b"\x00") > len(content) * 0.05:
        return True
    return False


def _binary_name(content: bytes):
    """返回检测到的二进制格式名称（用于错误提示）"""
    head = content[:8]
    for magic, name in _BINARY_MAGICS:
        if head.startswith(magic):
            return name
    return "未知二进制"


def init_kb():
    conn = get_conn()
    conn.execute("""
    CREATE TABLE IF NOT EXISTS kb_docs (
        id TEXT PRIMARY KEY,
        name TEXT,
        size INTEGER,
        chunks INTEGER,
        created_at REAL,
        ext TEXT DEFAULT ''
    )""")
    conn.execute("""
    CREATE TABLE IF NOT EXISTS kb_chunks (
        id TEXT PRIMARY KEY,
        doc_id TEXT,
        content TEXT,
        idx INTEGER
    )""")
    # 为检索加速建索引
    try:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_kb_chunks_doc ON kb_chunks(doc_id)")
    except Exception:
        pass
    # 迁移：老库没有 ext 列时补上
    try:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(kb_docs)").fetchall()]
        if "ext" not in cols:
            conn.execute("ALTER TABLE kb_docs ADD COLUMN ext TEXT DEFAULT ''")
    except Exception:
        pass
    conn.commit()
    conn.close()


def _ext(name: str) -> str:
    """取扩展名（小写，无点）"""
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def _decode_content(filename: str, content: bytes):
    """按文件类型解码为纯文本。返回 (text, ext)；不支持返回 (None, ext)"""
    ext = _ext(filename)
    if ext in UNSUPPORTED_EXTS:
        return None, ext
    # 魔数检测：伪装成文本的二进制文件也拒绝（避免污染知识库）
    if _is_binary(content):
        return None, ext
    # 尝试多种编码
    for enc in ("utf-8", "utf-8-sig", "gb18030", "latin-1"):
        try:
            return content.decode(enc), ext
        except (UnicodeDecodeError, ValueError):
            continue
    return content.decode("utf-8", errors="ignore"), ext


def _chunk_text(text, size=600, overlap=80):
    """将文本切成带重叠的分块；优先按段落/行边界切，避免把句子切断"""
    text = re.sub(r"\r\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    if len(text) <= size:
        return [t for t in [text.strip()] if t]
    # 段落切分
    paras = re.split(r"\n\s*\n", text)
    chunks = []
    buf = ""
    for p in paras:
        p = p.strip()
        if not p:
            continue
        if len(buf) + len(p) + 2 <= size:
            buf = f"{buf}\n\n{p}" if buf else p
        else:
            if buf:
                chunks.append(buf)
            if len(p) > size:
                # 超长段落按句号/逗号再切
                for sub in _split_long(p, size, overlap):
                    chunks.append(sub)
                buf = ""
            else:
                buf = p
    if buf:
        chunks.append(buf)
    return [c for c in chunks if c.strip()]


def _split_long(para, size, overlap):
    """把超长段落按句子边界切成多块"""
    parts = re.split(r"(?<=[。！？!?；;])", para)
    out = []
    buf = ""
    for s in parts:
        if len(buf) + len(s) <= size:
            buf += s
        else:
            if buf:
                out.append(buf)
            # 超长句硬切
            while len(s) > size:
                out.append(s[:size])
                s = s[size - overlap:]
            buf = s
    if buf:
        out.append(buf)
    return out


def add_document(filename: str, content: bytes):
    """添加文档，返回 (doc_id, chunk_count)；不支持格式或内容过少返回 (None, 0)"""
    text, ext = _decode_content(filename, content)
    if text is None:
        return None, 0
    if len(text.strip()) < 20:
        return None, 0
    chunks = _chunk_text(text)
    if not chunks:
        return None, 0
    doc_id = hashlib.md5(f"{filename}{time.time()}".encode()).hexdigest()[:12]
    conn = get_conn()
    conn.execute("INSERT INTO kb_docs (id,name,size,chunks,created_at,ext) VALUES (?,?,?,?,?,?)",
                 (doc_id, filename, len(content), len(chunks), time.time(), ext))
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
    out = []
    for r in rows:
        d = dict(r)
        d["type"] = TEXT_EXTS.get(d.get("ext", ""), "文档")
        out.append(d)
    return out


def delete_doc(doc_id):
    conn = get_conn()
    conn.execute("DELETE FROM kb_chunks WHERE doc_id=?", (doc_id,))
    conn.execute("DELETE FROM kb_docs WHERE id=?", (doc_id,))
    conn.commit()
    conn.close()


def rename_doc(doc_id, new_name):
    conn = get_conn()
    conn.execute("UPDATE kb_docs SET name=? WHERE id=?", (new_name, doc_id))
    conn.commit()
    conn.close()


def get_doc(doc_id):
    """获取单个文档（含分块列表），供详情查看"""
    conn = get_conn()
    doc = conn.execute("SELECT * FROM kb_docs WHERE id=?", (doc_id,)).fetchone()
    if not doc:
        conn.close()
        return None
    chunks = conn.execute(
        "SELECT idx, content FROM kb_chunks WHERE doc_id=? ORDER BY idx", (doc_id,)).fetchall()
    conn.close()
    d = dict(doc)
    d["type"] = TEXT_EXTS.get(d.get("ext", ""), "文档")
    d["chunk_list"] = [dict(c) for c in chunks]
    return d


# ================= BM25 检索 =================
_K1 = 1.5
_B = 0.75


def _tokenize(text, for_query=False):
    """分词：英文/数字按词，中文按 bigram（查询时可选保留单字用于短查询容错），返回 (tokens, counts)"""
    tokens = []
    # 英文/数字词
    for w in re.findall(r"[a-zA-Z0-9_]{2,}", text.lower()):
        tokens.append(w)
    # 中文：先尝试整词 bigram，同时保留 1-gram 用于短查询容错
    zh = re.findall(r"[\u4e00-\u9fff]+", text)
    for seg in zh:
        if len(seg) <= 2:
            tokens.append(seg)
        else:
            for i in range(len(seg) - 1):
                tokens.append(seg[i:i + 2])
            # 单字只用于索引（提高召回）；查询侧默认过滤，避免高频单字噪音
            if not for_query:
                for ch in seg:
                    tokens.append(ch)
    return tokens


def _bm25_index():
    """构建内存索引：df[term]、doc_lens、doc_terms[doc_id] -> {term: count}"""
    conn = get_conn()
    rows = conn.execute("SELECT id, doc_id, content, idx FROM kb_chunks").fetchall()
    conn.close()
    df = {}
    doc_terms = {}
    doc_lens = {}
    for r in rows:
        ch_id = r["id"]
        terms = _tokenize(r["content"])
        if not terms:
            continue
        cnt = {}
        for t in terms:
            cnt[t] = cnt.get(t, 0) + 1
        doc_terms[ch_id] = cnt
        doc_lens[ch_id] = len(terms)
        for t in cnt:
            df[t] = df.get(t, 0) + 1
    return df, doc_terms, doc_lens, rows


def search(query, top_k=5):
    """BM25 关键词检索，返回最相关片段列表（含命中词高亮信息）"""
    q_terms = _tokenize(query, for_query=True)
    # 短查询（无 bigram 命中可能）时回退到含单字的完整分词
    if len(q_terms) <= 1 and len(re.findall(r"[\u4e00-\u9fff]", query)) >= 1:
        q_terms = _tokenize(query, for_query=False)
    q_terms = list(dict.fromkeys(q_terms))  # 去重保序
    if not q_terms:
        return []
    df, doc_terms, doc_lens, rows = _bm25_index()
    N = max(len(doc_terms), 1)
    avg_len = (sum(doc_lens.values()) / N) if N else 0

    scored = []
    for ch_id, cnt in doc_terms.items():
        score = 0.0
        hits = []
        dl = doc_lens[ch_id]
        for t in q_terms:
            f = cnt.get(t, 0)
            if not f:
                continue
            n = df.get(t, 1)
            idf = math.log(1 + (N - n + 0.5) / (n + 0.5))
            tf = (f * (_K1 + 1)) / (f + _K1 * (1 - _B + _B * (dl / avg_len if avg_len else 1)))
            score += idf * tf
            hits.append(t)
        if score > 0:
            scored.append((score, ch_id, hits))

    scored.sort(key=lambda x: -x[0])
    # 元数据缓存
    doc_names = {}
    conn2 = get_conn()
    for r in conn2.execute("SELECT id, name, ext FROM kb_docs").fetchall():
        doc_names[r["id"]] = {"name": r["name"], "ext": r["ext"]}
    conn2.close()

    results = []
    for score, ch_id, hits in scored[:top_k]:
        meta = next((r for r in rows if r["id"] == ch_id), None)
        if not meta:
            continue
        doc = doc_names.get(meta["doc_id"], {"name": "未知", "ext": ""})
        content = meta["content"].strip()
        results.append({
            "doc_id": meta["doc_id"],
            "doc_name": doc["name"],
            "doc_type": TEXT_EXTS.get(doc.get("ext", ""), "文档"),
            "chunk_id": ch_id,
            "chunk_idx": meta["idx"],
            "content": content[:1200],
            "hits": hits[:8],
            "score": round(score, 2),
        })
    return results


def search_with_highlight(query, top_k=5):
    """检索 + 生成命中词高亮 HTML 片段（<mark>），前端可直接展示"""
    results = search(query, top_k)
    q_terms = _tokenize(query, for_query=True)
    if len(q_terms) <= 1 and len(re.findall(r"[\u4e00-\u9fff]", query)) >= 1:
        q_terms = _tokenize(query, for_query=False)
    # 高亮用长度>=2 的词（单字 token 只做召回，不做高亮，避免噪音/嵌套）
    hl_terms = [t for t in q_terms if len(t) >= 2]
    hl_terms.sort(key=len, reverse=True)
    for r in results:
        content = r["content"]
        # 找出所有命中位置，合并重叠区间
        spans = []
        for t in hl_terms:
            for m in re.finditer(re.escape(t), content, flags=re.IGNORECASE):
                spans.append([m.start(), m.end()])
        if spans:
            spans.sort()
            merged = []
            for s, e in spans:
                if merged and s <= merged[-1][1]:
                    merged[-1][1] = max(merged[-1][1], e)
                else:
                    merged.append([s, e])
            parts = []
            pos = 0
            for s, e in merged:
                parts.append(content[pos:s])
                parts.append(f"<mark>{content[s:e]}</mark>")
                pos = e
            parts.append(content[pos:])
            r["highlight"] = "".join(parts)
        else:
            r["highlight"] = content
    return results


def build_context(query, top_k=4):
    """构建 RAG 上下文文本，无匹配返回 None"""
    results = search(query, top_k)
    if not results:
        return None
    parts = [f"[{r['doc_name']}] {r['content']}" for r in results]
    return "\n\n---\n\n".join(parts)
