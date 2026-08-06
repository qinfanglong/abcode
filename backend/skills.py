"""ABcode 技能插件系统 - 用户自定义技能，注册为 Agent 工具"""
import ast
import hashlib
import inspect
import json
import re
import time
import types

import db

# 内置技能代码库
BUILTIN_SKILLS = [
    {
        "id": "skill_web_search",
        "name": "联网搜索",
        "description": "多引擎联网搜索（百度/Bing/搜狗），自动聚合去重，国内网络可用",
        "code": '''"""
ABCODE_SKILL
name: 联网搜索
description: 多引擎联网搜索（百度/Bing/搜狗），自动聚合去重
"""
import re
import time
import concurrent.futures
from urllib.parse import quote_plus
import requests

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
HDRS = {"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"}

def web_search(query: str, engines: str = "baidu,bing,sogou", max_results: int = 8):
    """
    联网搜索，返回聚合结果。
    query: 搜索关键词
    engines: 逗号分隔的引擎列表，可选 baidu/bing/sogou/duckduckgo
    max_results: 最大返回条数
    """
    engine_list = [e.strip() for e in engines.split(",") if e.strip()]
    all_results = []
    seen = set()

    def _bing(q):
        try:
            r = requests.get(f"https://www.bing.com/search?q={quote_plus(q)}&count=8", headers=HDRS, timeout=8)
            out = []
            for m in re.finditer(r'<li class="b_algo"[^>]*>(.*?)</li>', r.text, re.S):
                link = re.search(r'<a[^>]+href="(https?://[^"]+)"[^>]*>(.*?)</a>', m.group(1), re.S)
                if link:
                    t = re.sub(r'<[^>]+>', '', link.group(2)).strip()
                    if t and len(t) > 4:
                        out.append({"title": t, "url": link.group(1), "snippet": "", "engine": "bing"})
            return out
        except: return []

    def _baidu(q):
        try:
            r = requests.get(f"https://www.baidu.com/s?wd={quote_plus(q)}&rn=8", headers=HDRS, timeout=8)
            out = []
            for url, title in re.findall(r'<h3[^>]*>.*?<a href="([^"]+)"[^>]*>(.*?)</a>', r.text, re.S):
                t = re.sub(r'<[^>]+>', '', title).strip()
                if t and url.startswith("http"):
                    out.append({"title": t, "url": url, "snippet": "", "engine": "baidu"})
            return out
        except: return []

    def _sogou(q):
        try:
            r = requests.get(f"https://www.sogou.com/web?query={quote_plus(q)}", headers=HDRS, timeout=8)
            out = []
            for m in re.finditer(r'<h3[^>]*>.*?<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', r.text, re.S):
                t = re.sub(r'<[^>]+>', '', m.group(2)).strip()
                if t and m.group(1).startswith("http"):
                    out.append({"title": t, "url": m.group(1), "snippet": "", "engine": "sogou"})
            return out
        except: return []

    def _ddg(q):
        try:
            r = requests.post("https://html.duckduckgo.com/html/", data={"q": q}, headers=HDRS, timeout=8)
            out = []
            for m in re.finditer(r'<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', r.text, re.S):
                href = m.group(1)
                if href.startswith("//"): href = "https:" + href
                t = re.sub(r'<[^>]+>', '', m.group(2)).strip()
                if t and "duckduckgo" not in href:
                    out.append({"title": t, "url": href, "snippet": "", "engine": "duckduckgo"})
            return out
        except: return []

    fns = {"bing": _bing, "baidu": _baidu, "sogou": _sogou, "duckduckgo": _ddg}

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(engine_list)) as pool:
        futs = {pool.submit(fns.get(e, _bing), query): e for e in engine_list}
        done, _ = concurrent.futures.wait(futs, timeout=10)
        for f in done:
            try:
                for r in f.result(timeout=0):
                    url = r.get("url", "")
                    if url and url not in seen and not r.get("error"):
                        seen.add(url)
                        all_results.append(r)
            except: pass

    return "\\n".join(f"[{r['engine']}] {r['title']}\\n{r['url']}" for r in all_results[:max_results]) or "未找到结果"
''',
    },
    {
        "id": "skill_calc",
        "name": "数学计算器",
        "description": "执行复杂数学计算（支持 sin/cos/sqrt/pow/log 等）",
        "code": '''"""
ABCODE_SKILL
name: 数学计算器
description: 执行复杂数学计算（支持 sin/cos/sqrt/pow/log 等）
"""
import math

def calc(expr: str):
    """计算数学表达式，expr 如: sqrt(16) + 2**3*sin(0.5)"""
    s = expr.replace("^", "**")
    s = s.replace("sin(", "math.sin(").replace("cos(", "math.cos(")
    s = s.replace("tan(", "math.tan(").replace("sqrt(", "math.sqrt(")
    s = s.replace("log(", "math.log(").replace("log10(", "math.log10(")
    s = s.replace("abs(", "abs(").replace("pi", "math.pi").replace("e", "math.e")
    result = eval(s, {"__builtins__": {}}, {"math": math, "abs": abs, "round": round, "min": min, "max": max})
    return f"{expr} = {result}"
''',
    },
    {
        "id": "skill_text",
        "name": "文本处理",
        "description": "文本统计、字数统计、关键词提取、翻译占位等",
        "code": '''"""
ABCODE_SKILL
name: 文本处理
description: 文本统计、字数统计、关键词提取
"""
import re

def count_words(text: str):
    """统计文本的中英文单词数、字符数、行数"""
    words = len(re.findall(r"[\\w\\u4e00-\\u9fff]+", text))
    chars = len(text)
    lines = len(text.splitlines())
    return f"单词数: {words}\\n字符数: {chars}\\n行数: {lines}"

def extract_keywords(text: str, top_n: int = 5):
    """提取文本中的高频关键词，返回前 top_n 个"""
    tokens = re.findall(r"[\\u4e00-\\u9fff]{2,}|[a-zA-Z]{3,}", text)
    from collections import Counter
    return "、".join([w for w, _ in Counter(tokens).most_common(top_n)])
''',
    },
]


def _parse_tool_func(func):
    """从函数签名 + docstring 生成 OpenAI 工具定义"""
    sig = inspect.signature(func)
    params = {"type": "object", "properties": {}, "required": []}
    doc = inspect.getdoc(func) or func.__name__
    for name, p in sig.parameters.items():
        ptype = "string"
        if p.annotation in (int, float):
            ptype = "number"
        elif p.annotation is bool:
            ptype = "boolean"
        desc = f"参数 {name}"
        params["properties"][name] = {"type": ptype, "description": desc}
        if p.default is inspect.Parameter.empty:
            params["required"].append(name)
    return {
        "type": "function",
        "function": {
            "name": func.__name__,
            "description": doc,
            "parameters": params,
        },
    }


def compile_skill(skill):
    """编译技能代码，返回 (模块, tools) 或抛异常"""
    code = skill.get("code", "")
    if not code.strip():
        return None, []
    # 去除 ABCODE_SKILL 文档块
    code = re.sub(r'"""ABCODE_SKILL.*?"""', "", code, flags=re.S)
    mod = types.ModuleType(f"skill_{skill['id']}")
    mod.__dict__["json"] = json
    mod.__dict__["re"] = re
    mod.__dict__["math"] = __import__("math")
    mod.__dict__["os"] = __import__("os")
    mod.__dict__["time"] = __import__("time")
    mod.__dict__["datetime"] = __import__("datetime")
    mod.__dict__["random"] = __import__("random")
    mod.__dict__["collections"] = __import__("collections")
    exec(compile(code, f"<skill:{skill['id']}>", "exec"), mod.__dict__)
    tools = []
    for name in dir(mod):
        if name.startswith("_"):
            continue
        obj = getattr(mod, name)
        if inspect.isfunction(obj) and obj.__module__ == mod.__name__:
            try:
                tools.append(_parse_tool_func(obj))
            except Exception:
                continue
    return mod, tools


def init_builtins():
    """初始化内置技能（幂等；内置技能总是同步最新代码，保留启停状态）"""
    for s in BUILTIN_SKILLS:
        existing = db.get_skill(s["id"])
        if existing:
            # 保留用户启停状态，更新最新代码
            db.upsert_skill({**s, "enabled": existing["enabled"], "builtin": 1})
        else:
            db.upsert_skill({**s, "builtin": 1, "enabled": 1})


def get_enabled_skills():
    return [s for s in db.list_skills() if s["enabled"]]


def skill_tools_for(ids=None):
    """获取指定技能的工具定义列表；ids=None 表示全部启用技能"""
    skills = db.list_skills()
    if ids is not None:
        skills = [s for s in skills if s["id"] in ids]
    skills = [s for s in skills if s["enabled"]]
    out = []
    for s in skills:
        try:
            _, tools = compile_skill(s)
            out.extend(tools)
        except Exception:
            continue
    return out


def execute_skill_tool(skill_id, tool_name, args):
    """执行技能中的工具，返回 (ok, result)"""
    skill = db.get_skill(skill_id)
    if not skill or not skill["enabled"]:
        return False, f"技能不存在或未启用: {skill_id}"
    try:
        mod, tools = compile_skill(skill)
        func = getattr(mod, tool_name, None)
        if not func or not callable(func):
            return False, f"技能 {skill['name']} 中没有工具 {tool_name}"
        result = func(**args)
        return True, str(result)
    except Exception as e:
        return False, f"技能执行错误: {e}"


def build_tool_map(ids=None):
    """构建 {tool_name: (kind, ref)} 映射，供统一分派"""
    mapping = {}
    skills = db.list_skills()
    if ids is not None:
        skills = [s for s in skills if s["id"] in ids]
    for s in skills:
        if not s["enabled"]:
            continue
        try:
            _, tools = compile_skill(s)
            for t in tools:
                mapping[t["function"]["name"]] = ("skill", s["id"])
        except Exception:
            continue
    return mapping
