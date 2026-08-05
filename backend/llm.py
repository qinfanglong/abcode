"""ABcode 模型调用层 - OpenAI 兼容接口 + Ollama，支持流式输出与工具调用"""
import json
import httpx


class ModelError(Exception):
    pass


def _openai_chat(provider, model, messages, stream=True, timeout=180, tools=None):
    """调用 OpenAI 兼容接口（DeepSeek/OpenAI/通义/Kimi/本地 vLLM 等）"""
    url = provider["base_url"].rstrip("/") + "/chat/completions"
    headers = {"Content-Type": "application/json"}
    if provider.get("api_key"):
        headers["Authorization"] = f"Bearer {provider['api_key']}"

    payload = {
        "model": model,
        "messages": messages,
        "stream": stream,
    }
    if tools:
        payload["tools"] = tools

    client = httpx.Client(timeout=timeout)
    try:
        with client.stream("POST", url, json=payload, headers=headers) as resp:
            if resp.status_code != 200:
                body = resp.read().decode("utf-8", "ignore")[:500]
                raise ModelError(f"HTTP {resp.status_code}: {body}")
            if not stream:
                data = resp.json()
                return data["choices"][0]["message"]
            # SSE 流式解析
            buffer = ""
            tool_calls = {}
            for chunk in resp.iter_text():
                buffer += chunk
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.strip()
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        obj = json.loads(data)
                        delta = obj["choices"][0]["delta"]
                        if "content" in delta and delta["content"]:
                            yield {"type": "text", "content": delta["content"]}
                        elif "reasoning_content" in delta and delta["reasoning_content"]:
                            yield {"type": "text", "content": delta["reasoning_content"]}
                        # 工具调用增量
                        if "tool_calls" in delta and delta["tool_calls"]:
                            for tc in delta["tool_calls"]:
                                idx = tc.get("index", 0)
                                if idx not in tool_calls:
                                    tool_calls[idx] = {"id": tc.get("id", ""), "name": "", "args": ""}
                                t = tool_calls[idx]
                                fn = tc.get("function", {})
                                if fn.get("name"):
                                    t["name"] += fn["name"]
                                if fn.get("arguments"):
                                    t["args"] += fn["arguments"]
                    except Exception:
                        continue
                else:
                    continue
                break
            # 流结束，若有工具调用则返回
            if tool_calls:
                yield {"type": "tool_calls", "tool_calls": list(tool_calls.values())}
    finally:
        client.close()


def _ollama_chat(provider, model, messages, stream=True, timeout=180, tools=None):
    """调用 Ollama 本地模型"""
    url = provider["base_url"].rstrip("/") + "/api/chat"
    payload = {
        "model": model,
        "messages": messages,
        "stream": stream,
    }
    if tools:
        payload["tools"] = tools
    client = httpx.Client(timeout=timeout)
    try:
        with client.stream("POST", url, json=payload) as resp:
            if resp.status_code != 200:
                body = resp.read().decode("utf-8", "ignore")[:500]
                raise ModelError(f"HTTP {resp.status_code}: {body}")
            if not stream:
                data = resp.json()
                return data.get("message", {})
            buffer = ""
            tool_calls = {}
            for chunk in resp.iter_text():
                buffer += chunk
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                        msg = obj.get("message", {})
                        if "content" in msg and msg["content"]:
                            yield {"type": "text", "content": msg["content"]}
                        if msg.get("tool_calls"):
                            for tc in msg["tool_calls"]:
                                idx = len(tool_calls)
                                tool_calls[idx] = {
                                    "id": tc.get("function", {}).get("name", "") + f"_{idx}",
                                    "name": tc.get("function", {}).get("name", ""),
                                    "args": json.dumps(tc.get("function", {}).get("arguments", {}), ensure_ascii=False),
                                }
                        if obj.get("done"):
                            break
                    except Exception:
                        continue
            if tool_calls:
                yield {"type": "tool_calls", "tool_calls": list(tool_calls.values())}
    finally:
        client.close()


def stream_chat(provider, model, messages, tools=None):
    """统一入口：根据 base_url 判断协议，流式返回事件"""
    base = provider["base_url"].lower()
    if "ollama" in base or ":11434" in base:
        yield from _ollama_chat(provider, model, messages, tools=tools)
    else:
        yield from _openai_chat(provider, model, messages, tools=tools)


def test_provider(provider, model):
    """测试供应商连接，返回 (ok, msg)"""
    try:
        if "ollama" in provider["base_url"].lower() or ":11434" in provider["base_url"].lower():
            url = provider["base_url"].rstrip("/") + "/api/tags"
            resp = httpx.get(url, timeout=10)
            if resp.status_code != 200:
                return False, f"Ollama HTTP {resp.status_code}"
            tags = resp.json().get("models", [])
            names = [t.get("name", "") for t in tags]
            return True, "已连接，本地模型: " + ", ".join(names[:10])
        else:
            url = provider["base_url"].rstrip("/") + "/models"
            headers = {}
            if provider.get("api_key"):
                headers["Authorization"] = f"Bearer {provider['api_key']}"
            resp = httpx.get(url, headers=headers, timeout=10)
            if resp.status_code != 200:
                return False, f"HTTP {resp.status_code}"
            data = resp.json()
            names = [m.get("id", "") for m in data.get("data", [])][:20]
            return True, "已连接，可用模型: " + ", ".join(names)
    except Exception as e:
        return False, str(e)
