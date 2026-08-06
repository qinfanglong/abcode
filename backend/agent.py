"""ABcode Agent 工具调用层 - 工具注册、执行、Agent 循环"""
import json
import time
import datetime
import subprocess
from pathlib import Path

# 工作目录（工具可访问的根，默认 ABcode 项目目录的 workspace 子目录）
WORKSPACE = Path(__file__).parent.parent / "workspace"
WORKSPACE.mkdir(exist_ok=True, parents=True)

# ============ 工具定义（OpenAI function calling 格式） ============
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_current_time",
            "description": "获取当前日期和时间",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "联网搜索，获取实时信息。当用户问需要最新信息的问题时使用。返回搜索结果摘要。",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "搜索关键词"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_url",
            "description": "抓取一个网页的文本内容，用于阅读文章、查看页面信息。",
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string", "description": "网页地址"}},
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "列出工作区目录中的文件",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "相对工作区的目录，默认空=根"}},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "读取工作区内的文本文件内容",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "相对工作区的文件路径"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "在工作区内写入文件（可用于保存代码、笔记等）",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "相对工作区的文件路径"},
                    "content": {"type": "string", "description": "文件内容"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_shell",
            "description": "在工作区内执行 shell 命令（只读/安全命令），获取输出",
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string", "description": "要执行的 shell 命令"}},
                "required": ["command"],
            },
        },
    },
]

TOOL_NAMES = {t["function"]["name"] for t in TOOLS}


def _safe_path(path_str):
    """将相对路径解析到工作区内，阻止越界"""
    p = (WORKSPACE / (path_str or "")).resolve()
    if not str(p).startswith(str(WORKSPACE.resolve())):
        raise PermissionError("路径超出工作区范围")
    return p


def execute_tool(name, args):
    """执行工具，返回 (ok, result_str)"""
    try:
        if name == "get_current_time":
            now = datetime.datetime.now()
            return True, now.strftime("%Y-%m-%d %H:%M:%S %A")

        elif name == "web_search":
            query = args.get("query", "")
            if not query:
                return False, "缺少 query 参数"
            return True, _web_search(query)

        elif name == "fetch_url":
            url = args.get("url", "")
            if not url:
                return False, "缺少 url 参数"
            return True, _fetch_url(url)

        elif name == "list_files":
            p = _safe_path(args.get("path", ""))
            if not p.exists():
                return False, f"目录不存在: {p}"
            items = []
            for child in sorted(p.iterdir()):
                kind = "dir" if child.is_dir() else "file"
                size = child.stat().st_size if child.is_file() else 0
                items.append(f"{kind}\t{size}\t{child.name}")
            return True, "\n".join(items) if items else "(空目录)"

        elif name == "read_file":
            p = _safe_path(args.get("path", ""))
            if not p.is_file():
                return False, f"文件不存在: {p}"
            content = p.read_text(encoding="utf-8", errors="ignore")
            return True, content[:8000] + ("\n...(截断)" if len(content) > 8000 else "")

        elif name == "write_file":
            p = _safe_path(args.get("path", ""))
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(args.get("content", ""), encoding="utf-8")
            return True, f"已写入 {p.relative_to(WORKSPACE)} ({p.stat().st_size} 字节)"

        elif name == "run_shell":
            cmd = args.get("command", "")
            if not cmd:
                return False, "缺少 command 参数"
            # 黑名单：禁止危险命令
            dangerous = ["rm -rf", "mkfs", "dd ", ":(){", "shutdown", "reboot"]
            if any(d in cmd for d in dangerous):
                return False, "危险命令被拦截"
            result = subprocess.run(cmd, shell=True, capture_output=True,
                                    text=True, timeout=30, cwd=WORKSPACE)
            out = (result.stdout or "") + (result.stderr or "")
            return True, (out[:4000] if out else "(无输出)") + f"\n[exit code: {result.returncode}]"

        else:
            return False, f"未知工具: {name}"
    except PermissionError as e:
        return False, str(e)
    except subprocess.TimeoutExpired:
        return False, "命令执行超时"
    except Exception as e:
        return False, f"工具执行错误: {e}"


def _web_search(query):
    """网页搜索：优先使用自建搜索服务，回退 DuckDuckGo"""
    import httpx
    import re
    import json as _json

    # 优先使用自建搜索服务
    try:
        import db
        search_url = db.get_setting("search_service_url", "")
        search_engine = db.get_setting("search_engine", "builtin")
        search_api_key = db.get_setting("search_api_key", "")
    except Exception:
        search_url = ""
        search_engine = "builtin"
        search_api_key = ""

    # 如果没有配置自建服务，使用内置搜索
    if not search_url:
        search_engine = "builtin"

    # 内置搜索：直接调用本地搜索引擎模块
    if search_engine == "builtin":
        try:
            from search_engine.engine import search_multi
            results = search_multi(query, engines=["baidu", "bing", "sogou"], max_results=8)
            if results:
                lines = []
                for r in results[:8]:
                    title = r.get("title", "")
                    url = r.get("url", "")
                    snippet = r.get("snippet", "")
                    if title and url:
                        lines.append(f"- {title}\n  {url}\n  {snippet[:200] if snippet else ''}")
                return "\n".join(lines) if lines else "内置搜索未返回结果"
        except Exception as e:
            # 内置搜索失败，继续尝试其他方式
            pass

    if search_url:
        try:
            headers = {"User-Agent": "Mozilla/5.0"}
            if search_api_key:
                headers["Authorization"] = f"Bearer {search_api_key}"

            if search_engine == "searxng":
                # SearXNG API: GET /search?q=xxx&format=json
                sep = "&" if "?" in search_url else "?"
                url = f"{search_url}{sep}q={query}&format=json&language=zh-CN"
                import sys
                print(f"[SEARCH] Calling: {url}", file=sys.stderr)
                resp = httpx.get(url, timeout=30, headers=headers, follow_redirects=True)
                print(f"[SEARCH] Status: {resp.status_code}", file=sys.stderr)
                if resp.status_code == 200:
                    data = resp.json()
                    results = []
                    for r in data.get("results", [])[:8]:
                        title = r.get("title", "")
                        href = r.get("url", "")
                        content = r.get("content", "")
                        if title and href:
                            results.append(f"- {title}\n  {href}\n  {content[:200]}")
                    if results:
                        return "\n".join(results)
                    return "自建搜索服务未返回结果"

            elif search_engine == "google_cse":
                # Google Custom Search JSON API
                sep = "&" if "?" in search_url else "?"
                url = f"{search_url}{sep}q={query}&num=8"
                resp = httpx.get(url, timeout=15, headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    results = []
                    for r in data.get("items", [])[:8]:
                        title = r.get("title", "")
                        link = r.get("link", "")
                        snippet = r.get("snippet", "")
                        if title and link:
                            results.append(f"- {title}\n  {link}\n  {snippet[:200]}")
                    if results:
                        return "\n".join(results)

            else:
                # 自定义 API：GET {url}?q={query}，期望返回 JSON 数组
                sep = "&" if "?" in search_url else "?"
                url = f"{search_url}{sep}q={query}"
                resp = httpx.get(url, timeout=15, headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    # 支持两种格式：直接数组 或 {results: [...]}
                    items = data if isinstance(data, list) else data.get("results", data.get("data", []))
                    results = []
                    for r in items[:8]:
                        title = r.get("title", r.get("name", ""))
                        link = r.get("url", r.get("link", r.get("href", "")))
                        snippet = r.get("snippet", r.get("content", r.get("description", "")))
                        if title:
                            results.append(f"- {title}\n  {link}\n  {snippet[:200]}")
                    if results:
                        return "\n".join(results)

        except Exception as e:
            # 自建服务失败，回退 DuckDuckGo
            pass

    # 回退：DuckDuckGo
    try:
        url = "https://html.duckduckgo.com/html/"
        resp = httpx.post(url, data={"q": query}, timeout=15,
                          headers={"User-Agent": "Mozilla/5.0"})
        if resp.status_code != 200:
            return f"搜索失败 HTTP {resp.status_code}"
        results = []
        for m in re.finditer(r'<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', resp.text):
            href, title = m.group(1), re.sub(r"<[^>]+>", "", m.group(2)).strip()
            if href.startswith("//"):
                href = "https:" + href
            results.append(f"- {title}\n  {href}")
            if len(results) >= 8:
                break
        if not results:
            return "未找到搜索结果"
        return "\n".join(results)
    except Exception as e:
        return f"搜索失败: {e}"


def _fetch_url(url):
    """抓取网页正文文本"""
    import httpx
    import re
    try:
        resp = httpx.get(url, timeout=15, follow_redirects=True,
                         headers={"User-Agent": "Mozilla/5.0"})
        if resp.status_code != 200:
            return f"抓取失败 HTTP {resp.status_code}"
        html = resp.text
        # 去 script/style
        html = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:5000]
    except Exception as e:
        return f"抓取失败: {e}"


def build_messages(history, user_msg, rag_context=None, thinking_mode=False):
    """组装消息：系统提示 + RAG 上下文 + 历史 + 当前问题"""
    from time_utils import get_current_time_str, TIME_PROMPT_TPL
    sys_prompt = (
        "你是 ABcode，一个 AI Agent 助手。你可以使用工具来完成任务："
        "联网搜索实时信息、抓取网页、读写工作区文件、执行安全命令。"
        "需要时主动调用工具，不要编造信息。回答用中文，简洁清晰。"
    )
    # 注入实时时间
    sys_prompt += TIME_PROMPT_TPL.format(time=get_current_time_str())
    if thinking_mode:
        sys_prompt += (
            "\n\n请先在 <thinking> 标签内展示你的思考过程（推理、分析、权衡），"
            "然后再给出最终回答。思考过程要简洁，突出关键推理步骤。"
            "示例格式：\n<thinking>\n用户想了解 X，我需要先查 Y...\n</thinking>\n\n最终回答..."
        )
    if rag_context:
        sys_prompt += f"\n\n以下是从你的知识库中检索到的参考资料，优先依据这些内容回答：\n{rag_context}"
    messages = [{"role": "system", "content": sys_prompt}]
    for h in history[-12:]:
        if h.get("role") in ("user", "assistant"):
            messages.append({"role": h["role"], "content": h["content"]})
    messages.append({"role": "user", "content": user_msg})
    return messages
