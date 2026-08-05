"""
轻量搜索引擎 - 支持 Bing/百度/DuckDuckGo
使用 requests 库，兼容性更好
"""
import re
import requests
from urllib.parse import quote_plus
from html import unescape


def search_bing(query: str, max_results: int = 10) -> list:
    """通过 Bing 搜索"""
    url = f"https://www.bing.com/search?q={quote_plus(query)}&count={max_results}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        return _parse_bing_html(resp.text, max_results)
    except Exception as e:
        return [{"error": str(e)}]


def _parse_bing_html(html: str, max_results: int) -> list:
    results = []
    # 提取搜索结果 - 处理新的 Bing HTML 结构
    pattern = r'<li class="b_algo"[^>]*>(.*?)</li>'
    matches = re.findall(pattern, html, re.DOTALL)
    for match in matches[:max_results]:
        # 提取链接和标题 - 处理嵌套结构
        link_pattern = r'<a[^>]+href="(https?://[^"]+)"[^>]*>(.*?)</a>'
        link_matches = re.findall(link_pattern, match, re.DOTALL)
        if link_matches:
            # 取第一个有效链接
            url, title = link_matches[0]
            title = re.sub(r'<[^>]+>', '', title).strip()
            if title and url:
                # 提取摘要
                snippet = ""
                snippet_pattern = r'<p[^>]*>(.*?)</p>'
                snippet_match = re.search(snippet_pattern, match, re.DOTALL)
                if snippet_match:
                    snippet = re.sub(r'<[^>]+>', '', snippet_match.group(1)).strip()
                results.append({
                    "title": unescape(title),
                    "url": unescape(url),
                    "snippet": unescape(snippet)
                })
    return results


def search_baidu(query: str, max_results: int = 10) -> list:
    """通过百度搜索"""
    url = f"https://www.baidu.com/s?wd={quote_plus(query)}&rn={max_results}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    }
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        return _parse_baidu_html(resp.text, max_results)
    except Exception as e:
        return [{"error": str(e)}]


def _parse_baidu_html(html: str, max_results: int) -> list:
    results = []
    # 百度结果提取
    pattern = r'<h3[^>]*>.*?<a href="([^"]+)"[^>]*>(.*?)</a>'
    matches = re.findall(pattern, html, re.DOTALL)
    for url, title in matches[:max_results]:
        title_clean = re.sub(r'<[^>]+>', '', title)
        results.append({
            "title": unescape(title_clean),
            "url": unescape(url),
            "snippet": ""
        })
    return results


def search_duckduckgo(query: str, max_results: int = 10) -> list:
    """通过 DuckDuckGo Lite 搜索"""
    url = "https://lite.duckduckgo.com/lite/"
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    }
    data = {"q": query}
    try:
        resp = requests.post(url, headers=headers, data=data, timeout=15)
        return _parse_ddg_lite_html(resp.text, max_results)
    except Exception as e:
        return [{"error": str(e)}]


def _parse_ddg_lite_html(html: str, max_results: int) -> list:
    results = []
    # DuckDuckGo Lite 结果提取
    pattern = r'<a[^>]+rel="nofollow"[^>]+href="([^"]+)"[^>]*>(.*?)</a>'
    matches = re.findall(pattern, html, re.DOTALL)
    for url, title in matches[:max_results]:
        if url.startswith("http") and "duckduckgo" not in url:
            title_clean = re.sub(r'<[^>]+>', '', title)
            results.append({
                "title": unescape(title_clean),
                "url": unescape(url),
                "snippet": ""
            })
    return results


def search(query: str, engine: str = "bing", max_results: int = 10) -> list:
    """统一搜索接口"""
    engines = {
        "bing": search_bing,
        "baidu": search_baidu,
        "duckduckgo": search_duckduckgo,
    }
    search_fn = engines.get(engine, search_bing)
    return search_fn(query, max_results)
