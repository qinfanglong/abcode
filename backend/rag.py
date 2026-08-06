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
    "pdf": "PDF", "docx": "Word", "doc": "Word",
}
UNSUPPORTED_EXTS = {"xls", "xlsx", "ppt", "pptx", "zip", "rar", "7z", "png", "jpg", "jpeg", "gif", "bmp", "webp", "mp3", "mp4", "avi", "mov", "wav"}

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
    CREATE TABLE IF NOT EXISTS kb (
        id TEXT PRIMARY KEY,
        name TEXT,
        created_at REAL
    )""")
    conn.execute("""
    CREATE TABLE IF NOT EXISTS kb_docs (
        id TEXT PRIMARY KEY,
        name TEXT,
        size INTEGER,
        chunks INTEGER,
        created_at REAL,
        ext TEXT DEFAULT '',
        content_hash TEXT DEFAULT '',
        kb_id TEXT DEFAULT 'default'
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
        conn.execute("CREATE INDEX IF NOT EXISTS idx_kb_docs_kb ON kb_docs(kb_id)")
    except Exception:
        pass
    # 迁移：老库补列
    try:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(kb_docs)").fetchall()]
        if "ext" not in cols:
            conn.execute("ALTER TABLE kb_docs ADD COLUMN ext TEXT DEFAULT ''")
        if "content_hash" not in cols:
            conn.execute("ALTER TABLE kb_docs ADD COLUMN content_hash TEXT DEFAULT ''")
        if "kb_id" not in cols:
            conn.execute("ALTER TABLE kb_docs ADD COLUMN kb_id TEXT DEFAULT 'default'")
    except Exception:
        pass
    # 确保默认知识库存在
    cnt = conn.execute("SELECT COUNT(*) FROM kb").fetchone()[0]
    if cnt == 0:
        conn.execute("INSERT INTO kb (id, name, created_at) VALUES ('default', '默认知识库', ?)", (time.time(),))
    conn.commit()
    conn.close()


# ================= 多知识库 =================
def list_kbs():
    """列出全部知识库（含文档/分块统计）"""
    conn = get_conn()
    rows = conn.execute("SELECT * FROM kb ORDER BY created_at ASC").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["doc_count"] = conn.execute("SELECT COUNT(*) FROM kb_docs WHERE kb_id=?", (d["id"],)).fetchone()[0]
        d["chunk_count"] = conn.execute(
            "SELECT COUNT(*) FROM kb_chunks WHERE doc_id IN (SELECT id FROM kb_docs WHERE kb_id=?)",
            (d["id"],)).fetchone()[0]
        out.append(d)
    conn.close()
    return out


def create_kb(name: str) -> str:
    """创建知识库，返回 id"""
    name = (name or "").strip() or "新建知识库"
    kb_id = hashlib.md5(f"{name}{time.time()}".encode()).hexdigest()[:12]
    conn = get_conn()
    conn.execute("INSERT INTO kb (id, name, created_at) VALUES (?,?,?)", (kb_id, name, time.time()))
    conn.commit()
    conn.close()
    return kb_id


def delete_kb(kb_id: str):
    """删除知识库（连同其文档与分块）"""
    conn = get_conn()
    doc_ids = [r[0] for r in conn.execute("SELECT id FROM kb_docs WHERE kb_id=?", (kb_id,)).fetchall()]
    if doc_ids:
        marks = ",".join("?" * len(doc_ids))
        conn.execute(f"DELETE FROM kb_chunks WHERE doc_id IN ({marks})", doc_ids)
    conn.execute("DELETE FROM kb_docs WHERE kb_id=?", (kb_id,))
    conn.execute("DELETE FROM kb WHERE id=?", (kb_id,))
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
    if ext not in ("pdf", "docx") and _is_binary(content):
        return None, ext
    # 专用解析器
    if ext == "pdf":
        text = _parse_pdf(content)
        return (text, ext) if text and text.strip() else (None, ext)
    if ext == "docx":
        text = _parse_docx(content)
        return (text, ext) if text and text.strip() else (None, ext)
    # 尝试多种编码
    for enc in ("utf-8", "utf-8-sig", "gb18030", "latin-1"):
        try:
            return content.decode(enc), ext
        except (UnicodeDecodeError, ValueError):
            continue
    return content.decode("utf-8", errors="ignore"), ext


def _parse_pdf(content: bytes):
    """用 pypdf 提取 PDF 文本（已安装则用，未安装时优雅降级返回 None）"""
    try:
        from pypdf import PdfReader
        import io
        reader = PdfReader(io.BytesIO(content))
        parts = []
        for page in reader.pages:
            try:
                t = page.extract_text() or ""
                if t.strip():
                    parts.append(t)
            except Exception:
                continue
        return "\n\n".join(parts)
    except Exception:
        return None


def _parse_docx(content: bytes):
    """用标准库 zipfile + 正则解析 docx 的 document.xml 文本（无需 python-docx）"""
    try:
        import zipfile
        import io
        import xml.etree.ElementTree as ET
        with zipfile.ZipFile(io.BytesIO(content)) as z:
            if "word/document.xml" not in z.namelist():
                return None
            xml_data = z.read("word/document.xml")
        # 命名空间感知解析：w:t 是文本节点，w:p 是段落
        ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        root = ET.fromstring(xml_data)
        parts = []
        for p in root.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p"):
            texts = [t.text or "" for t in p.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t")]
            line = "".join(texts).strip()
            if line:
                parts.append(line)
        return "\n".join(parts)
    except Exception:
        return None


def _chunk_text(text, size=600, overlap=80, ext=""):
    """将文本切成带重叠的分块；优先按段落/行边界切，避免把句子切断。
    ext 为 md/markdown 时启用标题感知分块：按 #/##/### 标题切分，标题跟随其内容，
    超长章节内部再按段落切，保证每个分块保留所属标题上下文。
    """
    text = re.sub(r"\r\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    if len(text) <= size:
        return [t for t in [text.strip()] if t]

    # Markdown 标题感知分块
    if ext in ("md", "markdown"):
        chunks = _chunk_markdown(text, size, overlap)
        if chunks:
            return chunks

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


def _chunk_markdown(text, size, overlap):
    """按 Markdown 标题切分。返回分块列表；若无标题结构返回 []（回退普通切分）"""
    lines = text.split("\n")
    # 识别标题行（# 开头，且不是 ### 代码块内——粗略处理）
    sections = []  # [(title, [content_lines])]
    cur_title = None
    cur_lines = []
    has_title = False
    in_code = False
    for ln in lines:
        stripped = ln.strip()
        if stripped.startswith("```"):
            in_code = not in_code
        if not in_code and re.match(r"^#{1,6}\s+\S", stripped):
            has_title = True
            if cur_title is not None or cur_lines:
                sections.append((cur_title, cur_lines))
            cur_title = ln.strip()
            cur_lines = []
            continue
        cur_lines.append(ln)
    if cur_title is not None or cur_lines:
        sections.append((cur_title, cur_lines))
    if not has_title:
        return []
    # 组装：标题+内容，超长 section 内部再切
    chunks = []
    for title, body_lines in sections:
        section_text = "\n".join(body_lines).strip()
        prefix = title + "\n\n" if title else ""
        if not section_text and not prefix:
            continue
        if len(prefix) + len(section_text) <= size:
            chunks.append((prefix + section_text).strip())
        else:
            # 超长章节：段落级切分，每块保留标题前缀
            paras = [p.strip() for p in re.split(r"\n\s*\n", section_text) if p.strip()]
            buf = prefix
            for p in paras:
                if len(buf) + len(p) + 2 <= size:
                    buf = f"{buf}\n\n{p}" if buf.strip() else p
                else:
                    if buf.strip():
                        chunks.append(buf.strip())
                    if len(p) > size:
                        for sub in _split_long(p, size, overlap):
                            chunks.append((prefix + sub).strip())
                        buf = prefix
                    else:
                        buf = prefix + p
            if buf.strip():
                chunks.append(buf.strip())
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


def add_document(filename: str, content: bytes, kb_id: str = "default"):
    """添加文档到指定知识库，返回 (doc_id, chunk_count, is_dup)；不支持格式或内容过少返回 (None, 0, False)"""
    text, ext = _decode_content(filename, content)
    if text is None:
        return None, 0, False
    if len(text.strip()) < 20:
        return None, 0, False
    chunks = _chunk_text(text, ext=ext)
    if not chunks:
        return None, 0, False
    content_hash = hashlib.md5(content).hexdigest()
    # 去重检测：同一知识库内内容相同则跳过
    conn = get_conn()
    dup = conn.execute("SELECT id, name FROM kb_docs WHERE content_hash=? AND kb_id=?", (content_hash, kb_id)).fetchone()
    if dup:
        conn.close()
        return dup["id"], len(chunks), True
    doc_id = hashlib.md5(f"{filename}{time.time()}{kb_id}".encode()).hexdigest()[:12]
    conn.execute("INSERT INTO kb_docs (id,name,size,chunks,created_at,ext,content_hash,kb_id) VALUES (?,?,?,?,?,?,?,?)",
                 (doc_id, filename, len(content), len(chunks), time.time(), ext, content_hash, kb_id))
    for i, c in enumerate(chunks):
        conn.execute("INSERT INTO kb_chunks (id,doc_id,content,idx) VALUES (?,?,?,?)",
                     (f"{doc_id}_{i}", doc_id, c, i))
    conn.commit()
    conn.close()
    return doc_id, len(chunks), False


def find_duplicate(content: bytes, kb_id: str = "default"):
    """检查内容在指定知识库中是否已存在，返回 (doc_id, name) 或 None"""
    content_hash = hashlib.md5(content).hexdigest()
    conn = get_conn()
    row = conn.execute("SELECT id, name FROM kb_docs WHERE content_hash=? AND kb_id=?", (content_hash, kb_id)).fetchone()
    conn.close()
    return (row["id"], row["name"]) if row else None


def list_docs(kb_id: str = None):
    """列出文档；kb_id 为空时列出全部"""
    conn = get_conn()
    if kb_id:
        rows = conn.execute("SELECT * FROM kb_docs WHERE kb_id=? ORDER BY created_at DESC", (kb_id,)).fetchall()
    else:
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


def clear_all(kb_id: str = None):
    """清空知识库文档；kb_id 为空时清空全部"""
    conn = get_conn()
    if kb_id:
        doc_ids = [r[0] for r in conn.execute("SELECT id FROM kb_docs WHERE kb_id=?", (kb_id,)).fetchall()]
        if doc_ids:
            marks = ",".join("?" * len(doc_ids))
            conn.execute(f"DELETE FROM kb_chunks WHERE doc_id IN ({marks})", doc_ids)
        conn.execute("DELETE FROM kb_docs WHERE kb_id=?", (kb_id,))
    else:
        conn.execute("DELETE FROM kb_chunks")
        conn.execute("DELETE FROM kb_docs")
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


def _bm25_index(kb_id: str = None):
    """构建内存索引：df[term]、doc_lens、doc_terms[doc_id] -> {term: count}
    kb_id 非空时只索引该知识库的文档"""
    conn = get_conn()
    if kb_id:
        rows = conn.execute(
            "SELECT c.id, c.doc_id, c.content, c.idx FROM kb_chunks c "
            "JOIN kb_docs d ON c.doc_id=d.id WHERE d.kb_id=?",
            (kb_id,)).fetchall()
    else:
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


def _compute_signals(content, q_terms, q_pairs, bm25_score, dl, avg_len, chunk_idx):
    """计算切片的打分信号，返回 (signals, hits, positions)。
    - phrase: 相邻查询词对在切片中连续出现的比例（0~1）
    - coverage: 命中查询词数 / 查询词数（0~1）
    - position: 命中词靠前程度（命中位置越靠切片开头分越高，0~1）
    - density: 命中密度 = 命中次数 / 切片长度
    - head: 切片是否位于文档靠前部分（idx 越小分越高，0~1）
    """
    text_l = content.lower()
    total = len(q_terms)
    hit_set = set()
    positions = []
    hit_count = 0
    for t in q_terms:
        idx = text_l.find(t)
        if idx >= 0:
            hit_set.add(t)
            positions.append(idx)
            hit_count += text_l.count(t)
    coverage = len(hit_set) / total if total else 0.0
    # 短语连续命中：统计同时包含词对两个词的词对比例
    if q_pairs and len(content) > 1:
        hit_pairs = sum(1 for a, b in q_pairs if a in hit_set and b in hit_set)
        phrase = hit_pairs / len(q_pairs)
    else:
        phrase = coverage
    # 位置加权：第一个命中越靠前分越高（前 200 字符线性衰减）
    if positions:
        first = min(positions)
        position = max(0.0, 1.0 - first / 200.0)
    else:
        position = 0.0
    # 密度：命中次数相对切片长度（防止超长切片靠词频刷分）
    density = min(1.0, hit_count / max(dl, 1) * 6.0)
    # 文档头部加权：idx 越小越靠前
    head = max(0.0, 1.0 - chunk_idx * 0.02)
    return {
        "bm25": bm25_score,
        "phrase": round(phrase, 4),
        "coverage": round(coverage, 4),
        "position": round(position, 4),
        "density": round(density, 4),
        "head": round(head, 4),
    }, sorted(hit_set), positions


def search(query, top_k=5, kb_id: str = None, min_score: float = 0.0, diversify: bool = True):
    """混合打分检索（可限定知识库），返回最相关片段列表。
    - min_score: 阈值（0~1），低于该总分的片段被过滤
    - diversify: 启用 MMR 多样性，避免 top-k 结果集中在同一文档
    每项包含 breakdown 打分明细：bm25/phrase/coverage/position/density/head
    """
    q_terms = _tokenize(query, for_query=True)
    # 短查询（无 bigram 命中可能）时回退到含单字的完整分词
    if len(q_terms) <= 1 and len(re.findall(r"[\u4e00-\u9fff]", query)) >= 1:
        q_terms = _tokenize(query, for_query=False)
    q_terms = list(dict.fromkeys(q_terms))  # 去重保序
    if not q_terms:
        return []
    # 相邻词对（用于短语命中检测）
    q_pairs = [(q_terms[i], q_terms[i + 1]) for i in range(len(q_terms) - 1)]
    df, doc_terms, doc_lens, rows = _bm25_index(kb_id)
    N = max(len(doc_terms), 1)
    avg_len = (sum(doc_lens.values()) / N) if N else 0
    # 预缓存每块元数据（避免循环内反复查 rows）
    meta_by_id = {}
    for r in rows:
        meta_by_id[r["id"]] = r

    scored = []
    for ch_id, cnt in doc_terms.items():
        score = 0.0
        dl = doc_lens[ch_id]
        for t in q_terms:
            f = cnt.get(t, 0)
            if not f:
                continue
            n = df.get(t, 1)
            idf = math.log(1 + (N - n + 0.5) / (n + 0.5))
            tf = (f * (_K1 + 1)) / (f + _K1 * (1 - _B + _B * (dl / avg_len if avg_len else 1)))
            score += idf * tf
        if score > 0:
            meta = meta_by_id.get(ch_id)
            content = meta["content"].strip() if meta else ""
            signals, hits, positions = _compute_signals(
                content, q_terms, q_pairs, score, dl, avg_len, meta["idx"] if meta else 0)
            scored.append({"chunk_id": ch_id, "doc_id": meta["doc_id"] if meta else "",
                           "signals": signals, "hits": hits})

    if not scored:
        return []
    # BM25 min-max 归一化到 0~1（避免绝对值差异影响混合权重）
    bm25_vals = [s["signals"]["bm25"] for s in scored]
    b_min, b_max = min(bm25_vals), max(bm25_vals)
    if b_max == b_min:
        # 全部相同（通常只有一条命中）：唯一命中即最优
        for s in scored:
            s["signals"]["bm25_norm"] = 1.0 if s["signals"]["bm25"] > 0 else 0.0
    else:
        b_range = b_max - b_min
        for s in scored:
            s["signals"]["bm25_norm"] = round((s["signals"]["bm25"] - b_min) / b_range, 4)
    # 混合总分：BM25 主导 + 短语精确匹配 + 覆盖率 + 位置 + 头部 + 密度
    for s in scored:
        sg = s["signals"]
        total = (0.40 * sg["bm25_norm"]
                 + 0.20 * sg["phrase"]
                 + 0.15 * sg["coverage"]
                 + 0.10 * sg["position"]
                 + 0.10 * sg["head"]
                 + 0.05 * sg["density"])
        s["signals"]["total"] = round(total, 4)
        s["total"] = total

    # 阈值过滤
    if min_score > 0:
        scored = [s for s in scored if s["total"] >= min_score]

    # 排序：先按总分；若启用多样性，用贪心 MMR 重排
    if diversify and len(scored) > 1:
        picked = []
        remaining = scored[:]
        # 第一项选总分最高的
        remaining.sort(key=lambda x: -x["total"])
        picked.append(remaining.pop(0))
        while remaining and len(picked) < top_k:
            best = None
            best_val = -1
            for i, cand in enumerate(remaining):
                # 多样性惩罚：与已选中文档重合度（同文档 + 相似内容）
                dup_penalty = 0.0
                for p in picked:
                    if p["doc_id"] == cand["doc_id"]:
                        dup_penalty += 0.25
                val = cand["total"] - dup_penalty
                if val > best_val:
                    best_val = val
                    best = i
            picked.append(remaining.pop(best))
        scored = picked
    else:
        scored.sort(key=lambda x: -x["total"])

    scored = scored[:top_k]
    # 元数据缓存
    doc_names = {}
    conn2 = get_conn()
    for r in conn2.execute("SELECT id, name, ext FROM kb_docs").fetchall():
        doc_names[r["id"]] = {"name": r["name"], "ext": r["ext"]}
    conn2.close()

    results = []
    for s in scored:
        meta = meta_by_id.get(s["chunk_id"])
        if not meta:
            continue
        doc = doc_names.get(meta["doc_id"], {"name": "未知", "ext": ""})
        content = meta["content"].strip()
        results.append({
            "doc_id": meta["doc_id"],
            "doc_name": doc["name"],
            "doc_type": TEXT_EXTS.get(doc.get("ext", ""), "文档"),
            "chunk_id": s["chunk_id"],
            "chunk_idx": meta["idx"],
            "content": content[:1200],
            "snippet": _snippet(content, s["hits"], 400),
            "hits": s["hits"][:8],
            "score": round(s["total"], 4),
            "breakdown": s["signals"],
        })
    return results


def _snippet(content, hits, max_len=400):
    """生成以首个命中词为中心（往前找起点）的摘要片段，避免命中内容被截断看不到"""
    content = re.sub(r"\s+", " ", content).strip()
    if len(content) <= max_len:
        return content
    # 找到第一个命中词的位置
    pos = -1
    for t in hits:
        p = content.lower().find(t.lower())
        if p >= 0:
            pos = p
            break
    if pos < 0:
        return content[:max_len]
    # 从命中词前 150 字符开始，尽量从句子边界开始
    start = max(0, pos - 150)
    if start > 0:
        # 尝试在附近找上一个句号/换行，作为自然起点
        for sep in ("。", ". ", "！", "？", "；"):
            idx = content.rfind(sep, max(0, start - 60), pos)
            if idx > 0:
                start = idx + len(sep)
                break
    snippet = content[start:start + max_len]
    if start > 0:
        snippet = "…" + snippet
    if start + max_len < len(content):
        snippet += "…"
    return snippet


def search_with_highlight(query, top_k=5, kb_id: str = None, min_score: float = 0.0, diversify: bool = True):
    """检索 + 生成命中词高亮 HTML 片段（<mark>），前端可直接展示"""
    results = search(query, top_k, kb_id=kb_id, min_score=min_score, diversify=diversify)
    q_terms = _tokenize(query, for_query=True)
    if len(q_terms) <= 1 and len(re.findall(r"[\u4e00-\u9fff]", query)) >= 1:
        q_terms = _tokenize(query, for_query=False)
    # 高亮用长度>=2 的词（单字 token 只做召回，不做高亮，避免噪音/嵌套）
    hl_terms = [t for t in q_terms if len(t) >= 2]
    hl_terms.sort(key=len, reverse=True)
    for r in results:
        # 基于 snippet（命中词为中心的上下文片段）做高亮，避免命中内容被截断
        content = r["snippet"] or r["content"]
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


def build_context(query, top_k=4, per_doc=2, kb_id: str = None, min_score: float = 0.0):
    """构建 RAG 上下文文本（聊天注入用），无匹配返回 None。
    top_k 总片段数上限；per_doc 同一文档最多取片段数，避免单个文档垄断上下文。
    kb_id 非空时只从该知识库检索；min_score 为混合打分阈值。
    """
    results = search(query, top_k * 2, kb_id=kb_id, min_score=min_score)
    if not results:
        return None
    # 按文档聚合，每文档最多 per_doc 块
    picked = []
    counts = {}
    for r in results:
        doc_id = r["doc_id"]
        if counts.get(doc_id, 0) >= per_doc:
            continue
        counts[doc_id] = counts.get(doc_id, 0) + 1
        picked.append(r)
        if len(picked) >= top_k:
            break
    if not picked:
        return None
    parts = []
    for i, r in enumerate(picked, 1):
        parts.append(f"[{i}]《{r['doc_name']}》(相关度{r['score']:.2f})\n{r['content']}")
    return "\n\n---\n\n".join(parts)
