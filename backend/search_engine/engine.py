"""
ABcode 轻量搜索引擎 - 支持 Bing/百度/搜狗/DuckDuckGo
针对国内网络环境优化，超时快速跳过，不阻塞
"""
import re
import time
import concurrent.futures
from urllib.parse import quote_plus
from html import unescape

import requests


UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
HEADERS = {"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"}


# ==================== Bing ====================
def search_bing(query: str, max_results: int = 10) -> list:
    url = f"https://www.bing.com/search?q={quote_plus(query)}&count={max_results}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=8)
        resp.raise_for_status()
        return _parse_bing(resp.text, max_results)
    except Exception as e:
        return [{"error": f"Bing: {e}"}]


def _parse_bing(html: str, max_results: int) -> list:
    results = []
    for m in re.finditer(r'<li class="b_algo"[^>]*>(.*?)</li>', html, re.S):
        if len(results) >= max_results:
            break
        block = m.group(1)
        link = re.search(r'<a[^>]+href="(https?://[^"]+)"[^>]*>(.*?)</a>', block, re.S)
        if not link:
            continue
        url, title = link.group(1), re.sub(r'<[^>]+>', '', link.group(2)).strip()
        snippet = ""
        sp = re.search(r'<p[^>]*>(.*?)</p>', block, re.S)
        if sp:
            snippet = re.sub(r'<[^>]+>', '', sp.group(1)).strip()[:200]
        if title and url:
            results.append({"title": unescape(title), "url": unescape(url), "snippet": snippet})
    return results


# ==================== 百度 ====================
def search_baidu(query: str, max_results: int = 10) -> list:
    url = f"https://www.baidu.com/s?wd={quote_plus(query)}&rn={max_results}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=8)
        resp.raise_for_status()
        return _parse_baidu(resp.text, max_results)
    except Exception as e:
        return [{"error": f"Baidu: {e}"}]


def _parse_baidu(html: str, max_results: int) -> list:
    results = []
    # 尝试多种模式
    patterns = [
        r'<h3[^>]*>.*?<a href="([^"]+)"[^>]*>(.*?)</a>',
        r'<h3 class="t"[^>]*>.*?<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>',
    ]
    for pat in patterns:
        for url, title in re.findall(pat, html, re.S)[:max_results]:
            title_clean = re.sub(r'<[^>]+>', '', title).strip()
            if title_clean and url.startswith("http"):
                results.append({"title": unescape(title_clean), "url": unescape(url), "snippet": ""})
        if results:
            break
    return results[:max_results]


# ==================== 搜狗 ====================
def search_sogou(query: str, max_results: int = 10) -> list:
    url = f"https://www.sogou.com/web?query={quote_plus(query)}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=8)
        resp.raise_for_status()
        return _parse_sogou(resp.text, max_results)
    except Exception as e:
        return [{"error": f"Sogou: {e}"}]


def _parse_sogou(html: str, max_results: int) -> list:
    results = []
    for m in re.finditer(r'<h3[^>]*>.*?<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', html, re.S):
        if len(results) >= max_results:
            break
        url, title = m.group(1), re.sub(r'<[^>]+>', '', m.group(2)).strip()
        if title and url.startswith("http"):
            results.append({"title": unescape(title), "url": unescape(url), "snippet": ""})
    return results


# ==================== DuckDuckGo ====================
def search_ddg(query: str, max_results: int = 10) -> list:
    try:
        resp = requests.post(
            "https://html.duckduckgo.com/html/",
            data={"q": query},
            headers=HEADERS,
            timeout=8,
        )
        resp.raise_for_status()
        return _parse_ddg(resp.text, max_results)
    except Exception as e:
        return [{"error": f"DDG: {e}"}]


def _parse_ddg(html: str, max_results: int) -> list:
    results = []
    for m in re.finditer(
        r'<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>.*?'
        r'<a[^>]*class="result__snippet"[^>]*>(.*?)</a>',
        html, re.S,
    ):
        if len(results) >= max_results:
            break
        href = m.group(1)
        if href.startswith("//"):
            href = "https:" + href
        title = re.sub(r'<[^>]+>', '', m.group(2)).strip()
        snippet = re.sub(r'<[^>]+>', '', m.group(3)).strip()[:200]
        if title and "duckduckgo" not in href:
            results.append({"title": unescape(title), "url": href, "snippet": snippet})
    return results


# ==================== 引擎注册表 ====================
ENGINES = {
    "bing": search_bing,
    "baidu": search_baidu,
    "sogou": search_sogou,
    "duckduckgo": search_ddg,
}


def search(query: str, engine: str = "bing", max_results: int = 10) -> list:
    """单引擎搜索"""
    fn = ENGINES.get(engine, search_bing)
    return fn(query, max_results)


def search_multi(query: str, engines: list = None, max_results: int = 10,
                 timeout: int = 8) -> list:
    """多引擎并发搜索，自动去重、跳过超时引擎"""
    if not engines:
        engines = ["baidu", "bing", "sogou"]
    all_results = []
    seen = set()

    def _run(eng_name):
        fn = ENGINES.get(eng_name)
        if not fn:
            return []
        try:
            return fn(query, max_results)
        except Exception:
            return []

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(engines)) as pool:
        futures = {pool.submit(_run, e): e for e in engines}
        done, _ = concurrent.futures.wait(futures, timeout=timeout)
        for f in done:
            try:
                for r in f.result(timeout=0):
                    url = r.get("url", "")
                    if url and url not in seen and "error" not in r:
                        seen.add(url)
                        all_results.append(r)
            except Exception:
                pass

    return all_results[:max_results]
