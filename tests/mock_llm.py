"""Mock OpenAI 兼容服务器 - 支持流式 + 工具调用，用于本地测试"""
import json
import time
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

app = FastAPI()

MODELS = {
    "data": [{"id": "mock-chat", "object": "model"}, {"id": "mock-reasoner", "object": "model"}, {"id": "mock-tools", "object": "model"}]
}


@app.get("/models")
def models():
    return MODELS


def _gen_text(model, last):
    if model == "mock-reasoner":
        return ("这是 reasoning 模型的回复。\n\n你的问题是：\n" + last +
                "\n\n```python\nprint('hello from mock')\n```\n\n"
                "我支持 **Markdown** 渲染、代码高亮和流式输出。")
    if model == "mock-tools":
        return None  # 触发工具调用
    return ("你好！我是 ABcode 的 Mock 模型。\n\n"
            "你刚才问的是：**" + last + "**\n\n"
            "```python\n"
            "def greet(name):\n"
            "    return f'Hello, {name}!'\n"
            "```\n\n"
            "这是一段流式测试输出，前端应该能看到打字机效果。")


@app.post("/chat/completions")
async def chat(request: Request):
    body = await request.json()
    model = body.get("model", "mock-chat")
    stream = body.get("stream", False)
    msgs = body.get("messages", [])
    tools = body.get("tools", [])
    last = msgs[-1]["content"] if msgs else ""

    # 判断是否有工具消息（第二轮）
    has_tool_msgs = any(m.get("role") == "tool" for m in msgs)

    def build_result():
        if model == "mock-tools" and not has_tool_msgs:
            # 第一轮：调用工具
            return {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_mock_1",
                            "type": "function",
                            "function": {
                                "name": "get_current_time",
                                "arguments": json.dumps({}),
                            },
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        # 普通回复或工具结果后的回复
        return {
            "message": {
                "role": "assistant",
                "content": _gen_text(model, last) or "工具调用完成！我获取到了信息。",
            },
            "finish_reason": "stop",
        }

    if not stream:
        return {"id": "mock", "object": "chat.completion", "model": model,
                "choices": [{"index": 0, **build_result()}]}

    # 流式
    def sse():
        if model == "mock-tools" and not has_tool_msgs:
            # 流式工具调用：先发一个空的 assistant delta 声明 tool_calls
            yield f"data: {json.dumps({'id':'mock','choices':[{'delta':{'role':'assistant','tool_calls':[{'index':0,'id':'call_mock_1','type':'function','function':{'name':'get_current_time','arguments':''}}]}}]}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'id':'mock','choices':[{'delta':{'tool_calls':[{'index':0,'function':{'arguments':json.dumps({})}}]}}]}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
            return
        text = _gen_text(model, last) or "工具调用完成！我获取到了信息。"
        for ch in text:
            time.sleep(0.02)
            yield f"data: {json.dumps({'id':'mock','choices':[{'delta':{'content':ch}}]}, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(sse(), media_type="text/event-stream")
