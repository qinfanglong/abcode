"""测试用 MCP 服务器（stdio 传输） - 实现 JSON-RPC 协议"""
import json
import sys
import datetime

TOOLS = [
    {
        "name": "get_weather",
        "description": "获取城市天气（模拟数据）",
        "inputSchema": {
            "type": "object",
            "properties": {"city": {"type": "string", "description": "城市名"}},
            "required": ["city"],
        },
    },
    {
        "name": "get_stock_price",
        "description": "获取股票价格（模拟数据）",
        "inputSchema": {
            "type": "object",
            "properties": {"symbol": {"type": "string", "description": "股票代码"}},
            "required": ["symbol"],
        },
    },
]


def call_tool(name, args):
    if name == "get_weather":
        city = args.get("city", "未知")
        return {"content": [{"type": "text", "text": f"{city} 今天晴，25℃，微风，适合出行。"}]}
    if name == "get_stock_price":
        symbol = args.get("symbol", "未知")
        return {"content": [{"type": "text", "text": f"{symbol} 当前价格 123.45 元，涨 2.3%。"}]}
    return {"content": [{"type": "text", "text": "未知工具"}], "isError": True}


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except Exception:
            continue
        mid = msg.get("id")
        method = msg.get("method")
        params = msg.get("params", {})

        if method == "initialize":
            result = {
                "protocolVersion": params.get("protocolVersion", "2024-11-05"),
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "test-mcp-server", "version": "1.0.0"},
            }
        elif method == "notifications/initialized":
            continue  # 无响应
        elif method == "tools/list":
            result = {"tools": TOOLS}
        elif method == "tools/call":
            result = call_tool(params.get("name"), params.get("arguments", {}))
        elif method == "ping":
            result = {}
        else:
            result = {}

        resp = {"jsonrpc": "2.0", "id": mid, "result": result}
        sys.stdout.write(json.dumps(resp) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
