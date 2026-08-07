"""ABcode 频道消息运行时。

让「扫码接入」后的频道真正可用：
- webhook 入站：收到 JSON 消息 -> 触发 AI 对话 -> 返回/推送回复（通用、立即可测）
- 钉钉 Stream：官方长连接机器人（无需公网回调），单聊/群聊均可对话
- 每个发送者保留最近上下文，对话带 Agent 工具能力
"""
import json
import time
import threading

import db
import llm
import agent

# 每个频道的会话上下文（内存）：(cid, sender) -> [ (role, content), ... ]
_CONTEXTS = {}
_CONTEXT_MAX = 14


def _pick_provider_model():
    """选一个可用供应商与默认模型（同定时任务逻辑）"""
    providers = db.list_providers()
    if not providers:
        return None, None
    provider = next((p for p in providers if p.get("enabled")), providers[0])
    model = provider.get("default_model", "") or ""
    if not model and provider.get("models"):
        model = provider["models"][0]
    return provider, model


def _context_hist(cid, sender):
    hist = _CONTEXTS.get((cid, sender), [])
    return [{"role": r, "content": c} for r, c in hist[-_CONTEXT_MAX:]]


def _run_agent(messages, provider, model):
    """频道对话工具循环：模型 <-> 工具，最多 5 轮"""
    sys_prompt = (
        "你是 ABcode，一个 AI Agent 助手。你可以使用工具来完成任务："
        "联网搜索实时信息、抓取网页、读写工作区文件、执行安全命令。"
        "需要时主动调用工具，不要编造信息。回答用中文，简洁清晰。"
        "本条消息来自即时通讯频道，请给出可直接发送的纯文本答复，不要用 Markdown 代码块包裹。"
    )
    try:
        from time_utils import get_current_time_str, TIME_PROMPT_TPL
        sys_prompt += TIME_PROMPT_TPL.format(time=get_current_time_str())
    except Exception:
        pass

    msgs = [{"role": "system", "content": sys_prompt}] + list(messages)
    tools = list(agent.TOOLS)

    from main import dispatch_tool  # 运行时引入，避免循环依赖

    max_rounds = 5
    for round_idx in range(max_rounds):
        parts = []
        tool_objs = []
        for evt in llm.stream_chat(provider, model, msgs, tools=tools):
            if evt.get("type") == "text":
                parts.append(evt.get("content", ""))
            elif evt.get("type") == "tool_calls":
                tool_objs = evt.get("tool_calls", [])
        text = "".join(parts)
        msgs.append({"role": "assistant", "content": text or "(调用工具)"})
        if not tool_objs:
            return text or "(无回复)"

        tool_msgs = []
        for tc in tool_objs:
            name = tc.get("name", "")
            args_str = tc.get("args", "") or "{}"
            try:
                args = json.loads(args_str) if args_str else {}
            except Exception:
                args = {}
            try:
                ok, result = dispatch_tool(name, args)
            except Exception as e:
                ok, result = False, f"工具执行异常: {type(e).__name__}: {e}"
            if result is None:
                result = ""
            if not isinstance(result, str):
                try:
                    result = json.dumps(result, ensure_ascii=False)
                except Exception:
                    result = str(result)
            tool_msgs.append({
                "role": "tool",
                "tool_call_id": tc.get("id", f"{name}_{round_idx}"),
                "content": json.dumps({"ok": ok, "result": result}, ensure_ascii=False),
            })
        msgs.extend(tool_msgs)

    msgs.append({"role": "user", "content": "（请基于以上工具调用获得的信息直接给出最终回答，不要再调用工具。）"})
    out = []
    try:
        for evt in llm.stream_chat(provider, model, msgs, tools=None):
            if evt.get("type") == "text":
                out.append(evt.get("content", ""))
    except Exception:
        pass
    return "".join(out) or "(已调用工具，暂无文字回复)"


def reply_to_channel(cid, sender, text):
    """核心：频道收到消息 -> 对话 -> 记录 -> 返回回复文本。可被 webhook 与钉钉共用手动调用。"""
    db.add_channel_msg(cid, sender, "user", text)
    reply = _do_converse(cid, sender, text)
    db.add_channel_msg(cid, sender, "assistant", reply)
    return reply


def _do_converse(cid, sender, text):
    provider, model = _pick_provider_model()
    if not provider:
        return "⚠️ 尚未配置模型供应商，请在 ABcode 设置中添加后重试。"
    msgs = _context_hist(cid, sender)
    msgs.append({"role": "user", "content": text})
    try:
        reply = _run_agent(msgs, provider, model)
    except Exception as e:
        return f"⚠️ 处理消息出错：{type(e).__name__}: {e}"

    ctx = _CONTEXTS.setdefault((cid, sender), [])
    ctx.append(("user", text))
    ctx.append(("assistant", reply))
    if len(ctx) > _CONTEXT_MAX * 2:
        ctx[:] = ctx[-_CONTEXT_MAX * 2:]
    return reply


# ================= 钉钉 Stream 机器人 =================
def start_dingtalk_runtime():
    """若钉钉频道已启用且填了 AppKey/AppSecret，则在后台建立 Stream 长连接。"""
    try:
        channel = db.get_channel("dingtalk")
    except Exception:
        channel = None
    if not channel or not channel.get("enabled"):
        print("[channel] 钉钉频道未启用，跳过 Stream 连接")
        return
    cfg = channel.get("config") or {}
    app_key = (cfg.get("app_key") or cfg.get("client_id") or "").strip()
    app_secret = (cfg.get("app_secret") or cfg.get("client_secret") or "").strip()
    if not app_key or not app_secret:
        print("[channel] 钉钉已启用但未配置 AppKey/AppSecret，扫码仅能启用，无法收发消息")
        return
    threading.Thread(target=_dingtalk_stream_loop, args=(app_key, app_secret), daemon=True).start()
    print(f"[channel] 钉钉 Stream 机器人已启动（ClientId={app_key[:6]}...）")


def _dingtalk_stream_loop(client_id, client_secret):
    """钉钉 Stream 连接主循环（使用官方 SDK，占用线程直至退出；分页重连交给 SDK）。"""
    import dingtalk_stream
    from dingtalk_stream import AckMessage

    class _Bot(dingtalk_stream.ChatbotHandler):
        async def process(self, callback):
            try:
                incoming = dingtalk_stream.ChatbotMessage.from_dict(callback.data)
                content = getattr(incoming, "text", None)
                text = (content.content.strip() if content and content.content else "").strip()
                sender = getattr(incoming, "sender", None) or "钉钉用户"
                if not text:
                    return AckMessage.STATUS_OK, "OK"

                # AI 处理可能耗时，放入独立线程，避免阻塞 Stream 心跳
                handle_msg = threading.Thread(
                    target=self._respond, args=(text, sender), daemon=True)
                handle_msg.start()
            except Exception:
                pass
            return AckMessage.STATUS_OK, "OK"

        def _respond(self, text, sender):
            try:
                reply = reply_to_channel("dingtalk", sender, text)
                if getattr(self, "_client", None) and getattr(self, "_conversation", None):
                    try:
                        self._client.reply_text(reply, self._conversation)
                    except Exception:
                        pass
            except Exception:
                pass

    bot = _Bot()
    credential = dingtalk_stream.Credential(client_id, client_secret)
    client = dingtalk_stream.DingTalkStreamClient(credential)
    bot._client = client
    client.register_callback_handler(dingtalk_stream.ChatbotMessage.TOPIC, bot)
    client.start_forever()


# ================= 通用 Webhook 入站 =================
def handle_webhook(cid, payload):
    """通用 HTTP 入站：payload 为 dict，取 sender 与 text 字段。"""
    sender = (payload.get("sender") or payload.get("from") or "用户").strip() or "用户"
    text = (payload.get("text") or payload.get("message") or payload.get("content") or "").strip()
    if not text:
        return {"ok": False, "error": "缺少 text 字段"}
    reply = reply_to_channel(cid, sender, text)
    return {"ok": True, "reply": reply, "sender": sender}