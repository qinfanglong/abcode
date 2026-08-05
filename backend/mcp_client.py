"""ABcode MCP 客户端 - 连接 MCP 服务器（stdio / HTTP / SSE / WebSocket / Unix Socket / TCP），发现并使用工具"""
import json
import os
import socket
import subprocess
import threading
import time
import uuid

import db

MCP_VERSION = "2024-11-05"


class MCPClient:
    """单个 MCP 服务器连接"""

    def __init__(self, server):
        self.server = server
        self.proc = None
        self.http_session = None
        self._lock = threading.Lock()
        self._pending = {}       # id -> event
        self._reader = None
        self._tools_cache = None
        self._connected = False
        self._transport = None   # 具体的传输对象

    # ---------- 连接管理 ----------
    def connect(self):
        if self._connected:
            return
        
        transport = self.server.get("transport", "stdio")
        
        if transport == "stdio":
            self._connect_stdio()
        elif transport == "http":
            self._connect_http()
        elif transport == "sse":
            self._connect_sse()
        elif transport == "websocket":
            self._connect_websocket()
        elif transport == "unix":
            self._connect_unix()
        elif transport == "tcp":
            self._connect_tcp()
        else:
            raise RuntimeError(f"不支持的传输协议: {transport}")
        
        # initialize
        resp = self._request("initialize", {
            "protocolVersion": MCP_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "abcode", "version": "0.3.0"},
        })
        self._notify("notifications/initialized", {})
        self._connected = True

    def _connect_stdio(self):
        cmd = self.server.get("command", "")
        args = self.server.get("args", [])
        if not cmd:
            raise RuntimeError("MCP stdio 需要 command")
        self.proc = subprocess.Popen(
            [cmd, *args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self._reader = threading.Thread(target=self._read_loop_stdio, daemon=True)
        self._reader.start()

    def _read_loop_stdio(self):
        while self.proc and self.proc.poll() is None:
            line = self.proc.stdout.readline()
            if not line:
                break
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except Exception:
                continue
            mid = msg.get("id")
            if mid is not None and mid in self._pending:
                self._pending[mid].set()
                self._pending[mid].result = msg
                self._pending[mid].done = True

    def _connect_http(self):
        url = self.server.get("url", "")
        if not url:
            raise RuntimeError("MCP HTTP 需要 url")
        import httpx
        self._transport = httpx.Client(timeout=30)
        self._http_url = url.rstrip("/")

    def _connect_sse(self):
        """SSE (Server-Sent Events) 连接"""
        url = self.server.get("url", "")
        if not url:
            raise RuntimeError("MCP SSE 需要 url")
        import httpx
        self._http_url = url.rstrip("/")
        # SSE 使用同一URL，通过 Accept header 区分
        self._transport = httpx.Client(timeout=60)
        # 启动 SSE 监听线程
        self._sse_running = True
        self._sse_thread = threading.Thread(target=self._sse_listen, daemon=True)
        self._sse_thread.start()

    def _sse_listen(self):
        """监听 SSE 事件流"""
        try:
            import httpx
            headers = self.server.get("headers", {})
            headers["Accept"] = "text/event-stream"
            
            with httpx.stream("GET", self._http_url, headers=headers, timeout=60) as resp:
                if resp.status_code != 200:
                    return
                
                event_type = ""
                data_lines = []
                
                for line in resp.iter_lines():
                    if not self._sse_running:
                        break
                    
                    if line.startswith("event:"):
                        event_type = line[6:].strip()
                    elif line.startswith("data:"):
                        data_lines.append(line[5:].strip())
                    elif line == "":
                        # 空行表示事件结束
                        if data_lines:
                            data = "\n".join(data_lines)
                            self._handle_sse_event(event_type, data)
                        event_type = ""
                        data_lines = []
        except Exception as e:
            print(f"SSE 监听错误: {e}")

    def _handle_sse_event(self, event_type, data):
        """处理 SSE 事件"""
        try:
            msg = json.loads(data)
            mid = msg.get("id")
            if mid is not None and mid in self._pending:
                self._pending[mid].set()
                self._pending[mid].result = msg
                self._pending[mid].done = True
        except Exception:
            pass

    def _connect_websocket(self):
        """WebSocket 连接"""
        url = self.server.get("url", "")
        if not url:
            raise RuntimeError("MCP WebSocket 需要 url")
        
        # 将 http:// 转换为 ws://，https:// 转换为 wss://
        ws_url = url
        if ws_url.startswith("http://"):
            ws_url = "ws://" + ws_url[7:]
        elif ws_url.startswith("https://"):
            ws_url = "wss://" + ws_url[8:]
        elif not ws_url.startswith("ws://") and not ws_url.startswith("wss://"):
            ws_url = "ws://" + ws_url
        
        self._ws_url = ws_url
        # WebSocket 需要专门的库，这里用简单的实现
        # 实际项目中建议使用 websockets 库
        import httpx
        self._transport = httpx.Client(timeout=30)
        self._http_url = url.rstrip("/")

    def _connect_unix(self):
        """Unix Socket 连接"""
        socket_path = self.server.get("url", "")
        if not socket_path:
            raise RuntimeError("MCP Unix Socket 需要 socket 路径")
        
        if not os.path.exists(socket_path):
            raise RuntimeError(f"Unix Socket 不存在: {socket_path}")
        
        self._unix_socket_path = socket_path
        self._connect_socket()

    def _connect_tcp(self):
        """TCP 连接"""
        url = self.server.get("url", "")
        if not url:
            raise RuntimeError("MCP TCP 需要 host:port")
        
        # 解析 host:port
        if ":" in url:
            host, port = url.rsplit(":", 1)
            port = int(port)
        else:
            host = url
            port = 8080
        
        self._tcp_host = host
        self._tcp_port = port
        self._connect_socket()

    def _connect_socket(self):
        """通用 Socket 连接（Unix/TCP）"""
        if hasattr(self, '_unix_socket_path'):
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.connect(self._unix_socket_path)
        else:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.connect((self._tcp_host, self._tcp_port))
        
        self._socket = sock
        self._socket_lock = threading.Lock()
        
        # 启动接收线程
        self._socket_running = True
        self._reader = threading.Thread(target=self._read_loop_socket, daemon=True)
        self._reader.start()

    def _read_loop_socket(self):
        """Socket 接收循环"""
        buffer = ""
        while self._socket_running:
            try:
                data = self._socket.recv(4096)
                if not data:
                    break
                
                buffer += data.decode("utf-8")
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        msg = json.loads(line)
                    except Exception:
                        continue
                    mid = msg.get("id")
                    if mid is not None and mid in self._pending:
                        self._pending[mid].set()
                        self._pending[mid].result = msg
                        self._pending[mid].done = True
            except Exception as e:
                print(f"Socket 接收错误: {e}")
                break

    def _notify(self, method, params):
        msg = {"jsonrpc": "2.0", "method": method, "params": params}
        transport = self.server.get("transport", "stdio")
        
        if transport == "stdio":
            if self.proc and self.proc.poll() is None:
                self.proc.stdin.write(json.dumps(msg) + "\n")
                self.proc.stdin.flush()
        elif transport in ("http", "sse", "websocket"):
            try:
                headers = self.server.get("headers", {})
                self._transport.post(self._http_url + "/", json=msg, headers=headers)
            except Exception:
                pass
        elif transport in ("unix", "tcp"):
            with self._socket_lock:
                self._socket.send((json.dumps(msg) + "\n").encode("utf-8"))

    def _request(self, method, params, timeout=30):
        rid = str(uuid.uuid4())
        msg = {"jsonrpc": "2.0", "id": rid, "method": method, "params": params}
        transport = self.server.get("transport", "stdio")
        
        with self._lock:
            if transport == "stdio":
                if not self.proc or self.proc.poll() is not None:
                    raise RuntimeError("MCP 进程已退出")
                evt = threading.Event()
                evt.result = None
                evt.done = False
                self._pending[rid] = evt
                self.proc.stdin.write(json.dumps(msg) + "\n")
                self.proc.stdin.flush()
                if not evt.wait(timeout):
                    self._pending.pop(rid, None)
                    raise RuntimeError(f"MCP 请求超时: {method}")
                self._pending.pop(rid, None)
                return evt.result.get("result")
            
            elif transport in ("http", "sse", "websocket"):
                headers = self.server.get("headers", {})
                try:
                    resp = self._transport.post(self._http_url + "/", json=msg, headers=headers)
                    if resp.status_code != 200:
                        raise RuntimeError(f"MCP HTTP {resp.status_code}")
                    data = resp.json()
                    if "result" in data:
                        return data["result"]
                    raise RuntimeError(f"MCP 错误: {data.get('error')}")
                except Exception as e:
                    raise RuntimeError(f"MCP HTTP 请求失败: {e}")
            
            elif transport in ("unix", "tcp"):
                evt = threading.Event()
                evt.result = None
                evt.done = False
                self._pending[rid] = evt
                try:
                    with self._socket_lock:
                        self._socket.send((json.dumps(msg) + "\n").encode("utf-8"))
                except Exception as e:
                    self._pending.pop(rid, None)
                    raise RuntimeError(f"MCP Socket 发送失败: {e}")
                
                if not evt.wait(timeout):
                    self._pending.pop(rid, None)
                    raise RuntimeError(f"MCP 请求超时: {method}")
                self._pending.pop(rid, None)
                return evt.result.get("result")
            
            else:
                raise RuntimeError(f"不支持的传输协议: {transport}")

    # ---------- 工具 ----------
    def list_tools(self):
        if self._tools_cache is None:
            result = self._request("tools/list", {})
            tools = result.get("tools", []) if result else []
            self._tools_cache = tools
        return self._tools_cache

    def call_tool(self, name, arguments):
        result = self._request("tools/call", {"name": name, "arguments": arguments or {}})
        if not result:
            return False, "无返回"
        # MCP 返回 content 数组
        content = result.get("content", [])
        parts = []
        for c in content:
            if c.get("type") == "text":
                parts.append(c.get("text", ""))
            elif c.get("type") == "image":
                parts.append("[图片]")
            else:
                parts.append(json.dumps(c, ensure_ascii=False))
        ok = not result.get("isError", False)
        return ok, "\n".join(parts)

    def close(self):
        try:
            transport = self.server.get("transport", "stdio")
            
            if transport == "stdio" and self.proc:
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=3)
                except Exception:
                    self.proc.kill()
            
            elif transport in ("http", "sse", "websocket"):
                if hasattr(self, '_transport') and self._transport:
                    self._transport.close()
                if transport == "sse":
                    self._sse_running = False
            
            elif transport in ("unix", "tcp"):
                self._socket_running = False
                if hasattr(self, '_socket') and self._socket:
                    self._socket.close()
        except Exception:
            pass


# ---------- 全局客户端管理 ----------
_clients = {}
_clients_lock = threading.Lock()


def get_client(mid):
    server = db.get_mcp(mid)
    if not server or not server["enabled"]:
        return None
    with _clients_lock:
        client = _clients.get(mid)
        if client is None:
            client = MCPClient(server)
            _clients[mid] = client
    return client


def close_client(mid):
    with _clients_lock:
        client = _clients.pop(mid, None)
        if client:
            client.close()


def mcp_tools_for(ids=None):
    """获取指定 MCP 服务器的工具定义；ids=None 表示全部启用"""
    servers = db.list_mcp()
    if ids is not None:
        servers = [s for s in servers if s["id"] in ids]
    out = []
    for s in servers:
        if not s["enabled"]:
            continue
        try:
            client = get_client(s["id"])
            if not client:
                continue
            client.connect()
            for t in client.list_tools():
                out.append({
                    "type": "function",
                    "function": {
                        "name": t.get("name"),
                        "description": t.get("description", ""),
                        "parameters": t.get("inputSchema", {"type": "object", "properties": {}}),
                    },
                })
        except Exception:
            continue
    return out


def execute_mcp_tool(mcp_id, tool_name, args):
    try:
        client = get_client(mcp_id)
        if not client:
            return False, "MCP 服务器不可用"
        client.connect()
        return client.call_tool(tool_name, args)
    except Exception as e:
        return False, f"MCP 调用错误: {e}"


def build_tool_map(ids=None):
    """构建 {tool_name: ("mcp", mcp_id)}"""
    mapping = {}
    servers = db.list_mcp()
    if ids is not None:
        servers = [s for s in servers if s["id"] in ids]
    for s in servers:
        if not s["enabled"]:
            continue
        try:
            client = get_client(s["id"])
            if not client:
                continue
            client.connect()
            for t in client.list_tools():
                mapping[t.get("name")] = ("mcp", s["id"])
        except Exception:
            continue
    return mapping


def test_mcp(server):
    """测试 MCP 连接，返回 (ok, msg)"""
    try:
        client = MCPClient(server)
        client.connect()
        tools = client.list_tools()
        names = [t.get("name", "") for t in tools][:10]
        client.close()
        return True, f"连接成功，发现 {len(tools)} 个工具: {', '.join(names)}"
    except Exception as e:
        return False, str(e)
