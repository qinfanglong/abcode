"""ABcode 搜索代理服务 - 自建搜索引擎
支持 SearXNG 协议兼容格式，聚合 Bing/Google/DuckDuckGo
启动: python3 search_service.py (默认端口 8080)
"""
import json
import re
import time
import hashlib
import os
from pathlib import Path
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import httpx
import uvicorn

app = FastAPI(title="ABcode Search Service", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# 简单内存缓存
_cache = {}
CACHE_TTL = 600  # 10分钟

USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# 代理配置（可选，用于访问被墙的搜索引擎）
HTTP_PROXY = os.environ.get("HTTP_PROXY", os.environ.get("http_proxy", ""))
HTTPS_PROXY = os.environ.get("HTTPS_PROXY", os.environ.get("https_proxy", ""))

def _get_client():
    """获取 httpx 客户端，支持代理"""
    proxy = None
    if HTTPS_PROXY:
        proxy = HTTPS_PROXY
    elif HTTP_PROXY:
        proxy = HTTP_PROXY
    return httpx.Client(proxy=proxy, timeout=15, follow_redirects=True)


def _cache_key(engine, query):
    return hashlib.md5(f"{engine}:{query}".encode()).hexdigest()


def _get_cached(key):
    if key in _cache:
        ts, data = _cache[key]
        if time.time() - ts < CACHE_TTL:
            return data
        del _cache[key]
    return None


def _set_cache(key, data):
    _cache[key] = (time.time(), data)
    # 清理过期缓存
    if len(_cache) > 500:
        now = time.time()
        expired = [k for k, (ts, _) in _cache.items() if now - ts > CACHE_TTL]
        for k in expired[:100]:
            del _cache[k]


# ====== DuckDuckGo HTML 解析 ======
def search_ddg(query, max_results=8):
    """DuckDuckGo HTML 搜索"""
    key = _cache_key("ddg", query)
    cached = _get_cached(key)
    if cached:
        return cached

    try:
        client = _get_client()
        resp = client.post(
            "https://html.duckduckgo.com/html/",
            data={"q": query},
            headers={"User-Agent": USER_AGENT},
        )
        if resp.status_code != 200:
            return []

        results = []
        for m in re.finditer(
            r'<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>.*?'
            r'<a[^>]*class="result__snippet"[^>]*>(.*?)</a>',
            resp.text,
            re.S,
        ):
            href = m.group(1)
            title = re.sub(r"<[^>]+>", "", m.group(2)).strip()
            snippet = re.sub(r"<[^>]+>", "", m.group(3)).strip()
            if href.startswith("//"):
                href = "https:" + href
            results.append({"title": title, "url": href, "content": snippet})
            if len(results) >= max_results:
                break

        _set_cache(key, results)
        return results
    except Exception:
        return []


# ====== Bing 搜索 ======
def search_bing(query, max_results=8):
    """Bing 搜索"""
    key = _cache_key("bing", query)
    cached = _get_cached(key)
    if cached:
        return cached

    try:
        client = _get_client()
        resp = client.get(
            f"https://www.bing.com/search?q={query}&count={max_results}",
            headers={"User-Agent": USER_AGENT},
        )
        if resp.status_code != 200:
            return []

        results = []
        # 使用更灵活的模式提取搜索结果
        # 查找所有外部链接
        link_pattern = r'<a[^>]*href="(https?://[^"]+)"[^>]*>(.*?)</a>'
        for m in re.finditer(link_pattern, resp.text, re.S):
            url = m.group(1)
            title_html = m.group(2)
            title = re.sub(r"<[^>]+>", "", title_html).strip()
            
            # 过滤掉 bing/microsoft 自身链接和太短的标题
            if (not title or len(title) < 5 or 
                "bing.com" in url or "microsoft.com" in url or
                "google.com" in url or "facebook.com" in url):
                continue
            
            # 尝试获取摘要（通常在链接后面的文本中）
            snippet = ""
            pos = m.end()
            snippet_match = re.search(r'<p[^>]*>(.*?)</p>', resp.text[pos:pos+500], re.S)
            if snippet_match:
                snippet = re.sub(r"<[^>]+>", "", snippet_match.group(1)).strip()[:200]
            
            results.append({"title": title, "url": url, "content": snippet})
            if len(results) >= max_results:
                break

        _set_cache(key, results)
        return results
    except Exception as e:
        import traceback
        traceback.print_exc()
        return []


# ====== Google 搜索 ======
def search_google(query, max_results=8):
    """Google 搜索（HTML 解析）"""
    key = _cache_key("google", query)
    cached = _get_cached(key)
    if cached:
        return cached

    try:
        client = _get_client()
        resp = client.get(
            f"https://www.google.com/search?q={query}&num={max_results}&hl=zh-CN",
            headers={"User-Agent": USER_AGENT},
        )
        if resp.status_code != 200:
            return []

        results = []
        # 解析 Google 搜索结果
        for m in re.finditer(
            r'<div class="[^"]*"[^>]*>.*?<a href="/url\?q=([^&"]+)"[^>]*>.*?<h3[^>]*>(.*?)</h3>.*?</a>.*?<span[^>]*>(.*?)</span>',
            resp.text,
            re.S,
        ):
            url = m.group(1)
            title = re.sub(r"<[^>]+>", "", m.group(2)).strip()
            snippet = re.sub(r"<[^>]+>", "", m.group(3)).strip()
            if url.startswith("/"):
                continue
            results.append({"title": title, "url": url, "content": snippet})
            if len(results) >= max_results:
                break

        _set_cache(key, results)
        return results
    except Exception:
        return []


# ====== 聚合搜索 ======
@app.get("/search")
def search(
    q: str = Query(..., description="搜索关键词"),
    format: str = Query("json", description="返回格式"),
    language: str = Query("zh-CN", description="语言"),
    engines: str = Query("bing,google,ddg", description="搜索引擎，逗号分隔（默认 Bing）"),
    max_results: int = Query(10, description="最大结果数"),
):
    """SearXNG 兼容的搜索接口"""
    engine_list = [e.strip() for e in engines.split(",") if e.strip()]
    all_results = []
    seen_urls = set()

    search_funcs = {
        "ddg": search_ddg,
        "bing": search_bing,
        "google": search_google,
    }

    for engine in engine_list:
        func = search_funcs.get(engine)
        if not func:
            continue
        try:
            results = func(q, max_results=max_results)
            for r in results:
                url = r.get("url", "")
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    r["engine"] = engine
                    all_results.append(r)
        except Exception:
            continue

    # 按引擎优先级排序（先出现的引擎优先）
    engine_priority = {e: i for i, e in enumerate(engine_list)}
    all_results.sort(key=lambda r: engine_priority.get(r.get("engine", ""), 99))

    return {
        "query": q,
        "number_of_results": len(all_results),
        "results": all_results[:max_results],
    }


@app.get("/health")
def health():
    return {"status": "ok", "service": "ABcode Search Service"}


if __name__ == "__main__":
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    print(f"🔍 ABcode Search Service 启动于 http://0.0.0.0:{port}")
    print(f"   搜索接口: http://localhost:{port}/search?q=hello&format=json")
    uvicorn.run(app, host="0.0.0.0", port=port)
