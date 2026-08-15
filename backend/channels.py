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
                sender = (incoming.sender_staff_id or incoming.sender_id
                          or incoming.sender_nick or "钉钉用户")
                if not text:
                    return AckMessage.STATUS_OK, "OK"

                # AI 处理可能耗时，放入独立线程，避免阻塞 Stream 心跳
                handle_msg = threading.Thread(
                    target=self._respond, args=(text, sender, incoming), daemon=True)
                handle_msg.start()
            except Exception:
                pass
            return AckMessage.STATUS_OK, "OK"

        def _respond(self, text, sender, incoming):
            try:
                reply = reply_to_channel("dingtalk", sender, text)
                if not reply:
                    return
                # 使用 ChatbotHandler 自带回复能力：通过 sessionWebhook 把消息发回会话
                self.reply_text(reply, incoming)
            except Exception as e:
                print(f"[dingtalk] 回复失败: {e}")

    bot = _Bot()
    credential = dingtalk_stream.Credential(client_id, client_secret)
    client = dingtalk_stream.DingTalkStreamClient(credential)
    bot._client = client
    client.register_callback_handler(dingtalk_stream.ChatbotMessage.TOPIC, bot)
    client.start_forever()


# ================= 飞书/Feishu 机器人（长连接，免公网） =================
def start_feishu_runtime():
    """若飞书频道已启用且填了 AppId/AppSecret，则后台建立长连接（官方 WS，免公网）。"""
    try:
        channel = db.get_channel("feishu")
    except Exception:
        channel = None
    if not channel or not channel.get("enabled"):
        print("[channel] 飞书频道未启用，跳过")
        return
    cfg = channel.get("config") or {}
    app_id = (cfg.get("app_id") or "").strip()
    app_secret = (cfg.get("app_secret") or "").strip()
    if not app_id or not app_secret:
        print("[channel] 飞书已启用但未配置 AppId/AppSecret，无法收发消息")
        return
    threading.Thread(target=_feishu_stream_loop, args=(app_id, app_secret), daemon=True).start()
    print(f"[channel] 飞书长连接机器人已启动（AppId={app_id[:6]}...）")


def _feishu_stream_loop(app_id, app_secret):
    """飞书官方长连接主循环（lark-oapi ws.Client），事件收到后在独立线程里 AI 回复。"""
    import lark_oapi as lark
    from lark_oapi.api.im.v1 import (
        P2ImMessageReceiveV1,
        CreateMessageRequest,
        CreateMessageRequestBody,
    )

    def _on_message(event: P2ImMessageReceiveV1):
        try:
            msg = event.event.message
            if not msg or msg.message_type != "text":
                return
            content = msg.content or ""
            try:
                text = json.loads(content).get("text", "").strip()
            except Exception:
                text = ""
            if not text:
                return
            sender = event.event.sender
            sid = ""
            if sender and sender.sender_id:
                sid = (sender.sender_id.open_id or sender.sender_id.union_id
                       or sender.sender_id.user_id or "")
            # 机器人自己的消息不回
            if sender and sender.sender_type == "app":
                return
            chat_id = msg.chat_id or ""
            if not chat_id:
                return
            threading.Thread(
                target=_feishu_respond, args=(app_id, app_secret, chat_id, sid, text),
                daemon=True).start()
        except Exception as e:
            print(f"[feishu] 事件处理异常: {type(e).__name__}: {e}")

    handler = lark.EventDispatcherHandler.builder("", "").register_p2_im_message_receive_v1(_on_message).build()
    try:
        client = lark.ws.Client(
            app_id=app_id,
            app_secret=app_secret,
            event_handler=handler,
            log_level=lark.LogLevel.ERROR,
        )
        client.start()
    except Exception as e:
        print(f"[feishu] 长连接异常: {type(e).__name__}: {e}")


def _feishu_respond(app_id, app_secret, chat_id, sender, text):
    """AI 对话后把回复通过 im/v1/messages 发回会话。"""
    try:
        reply = reply_to_channel("feishu", f"feishu:{sender or chat_id}", text)
        if not reply:
            return
        import lark_oapi as lark
        from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody
        client = lark.Client.builder().app_id(app_id).app_secret(app_secret).build()
        req = CreateMessageRequest.builder() \
            .receive_id_type("chat_id") \
            .request_body(CreateMessageRequestBody.builder()
                          .receive_id(chat_id)
                          .msg_type("text")
                          .content(json.dumps({"text": reply[:4000]}, ensure_ascii=False))
                          .build()) \
            .build()
        resp = client.im.v1.message.create(req)
        if not resp.success():
            print(f"[feishu] 回复失败: {resp.code} {resp.msg}")
    except Exception as e:
        print(f"[feishu] 回复异常: {type(e).__name__}: {e}")


# ================= 企业微信（主动推送，免公网） =================
_WECOM_TOKEN_CACHE = {}  # (corp_id, secret) -> (token, expire_ts)

def start_wecom_runtime():
    """企业微信没有长连接接收；若配置完整则就绪「应用消息主动推送」（出站）。
    入站仍走通用 Webhook（外部分发器转 POST JSON）。"""
    try:
        channel = db.get_channel("wecom")
    except Exception:
        channel = None
    if not channel or not channel.get("enabled"):
        print("[channel] 企业微信频道未启用，跳过")
        return
    cfg = channel.get("config") or {}
    corp_id = (cfg.get("corp_id") or "").strip()
    secret = (cfg.get("secret") or "").strip()
    agent_id = (cfg.get("agent_id") or "").strip()
    if not corp_id or not secret or not agent_id:
        print("[channel] 企业微信已启用但未配置 corp_id/agent_id/secret，仅保留通用 Webhook 入站")
        return
    print(f"[channel] 企业微信应用推送已就绪（corp_id={corp_id[:6]}..., agent_id={agent_id}）")


def _wecom_token(corp_id, secret):
    cached = _WECOM_TOKEN_CACHE.get((corp_id, secret))
    if cached and cached[1] > time.time() + 600:
        return cached[0]
    import requests
    try:
        r = requests.get(
            "https://qyapi.weixin.qq.com/cgi-bin/gettoken",
            params={"corpid": corp_id, "corpsecret": secret}, timeout=10,
        )
        data = r.json()
        if data.get("errcode") != 0:
            print(f"[wecom] 获取 token 失败: {data.get('errmsg')}")
            return None
        token = data.get("access_token")
        _WECOM_TOKEN_CACHE[(corp_id, secret)] = (token, time.time())
        return token
    except Exception as e:
        print(f"[wecom] 获取 token 异常: {type(e).__name__}: {e}")
        return None


def wecom_send_text(text, touser="@all"):
    """向企业微信应用成员推送文本消息（出站，免公网）。返回 (ok, msg)。"""
    try:
        channel = db.get_channel("wecom")
    except Exception:
        channel = None
    if not channel or not channel.get("enabled"):
        return False, "企业微信频道未启用"
    cfg = channel.get("config") or {}
    corp_id = (cfg.get("corp_id") or "").strip()
    secret = (cfg.get("secret") or "").strip()
    agent_id = (cfg.get("agent_id") or "").strip()
    if not all([corp_id, secret, agent_id]):
        return False, "企业微信未配置 corp_id/agent_id/secret"
    token = _wecom_token(corp_id, secret)
    if not token:
        return False, "获取 access_token 失败"
    import requests
    try:
        r = requests.post(
            f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={token}",
            json={
                "touser": touser, "msgtype": "text",
                "agentid": int(agent_id),
                "text": {"content": text[:2000]}, "safe": 0,
            },
            timeout=10,
        )
        data = r.json()
        if data.get("errcode") != 0:
            return False, f"发送失败: {data.get('errmsg')}"
        return True, "ok"
    except Exception as e:
        return False, f"发送异常: {type(e).__name__}: {e}"


# ================= Discord Bot（Gateway 长连接，免公网） =================
def start_discord_runtime():
    """若 Discord 频道已启用且填了 Bot Token，则后台连 Gateway 长连接。"""
    try:
        channel = db.get_channel("discord")
    except Exception:
        channel = None
    if not channel or not channel.get("enabled"):
        print("[channel] Discord 频道未启用，跳过")
        return
    cfg = channel.get("config") or {}
    token = (cfg.get("bot_token") or "").strip()
    if not token:
        print("[channel] Discord 已启用但未配置 Bot Token，无法收发消息")
        return
    threading.Thread(target=_discord_stream_loop, args=(token,), daemon=True).start()
    print(f"[channel] Discord Bot 长连接已启动（Token 尾号 ...{token[-6:]}）")


def _discord_stream_loop(token):
    """Discord Gateway v10 长连接：识别 -> 心跳 -> MESSAGE_CREATE -> AI 回复。"""
    try:
        import asyncio
    except Exception:
        return

    async def _listen():
        import websockets
        import json as _json

        INTENTS = (1 << 9) | (1 << 12) | (1 << 15)  # GUILD_MESSAGES | DIRECT_MESSAGES | MESSAGE_CONTENT

        while True:
            try:
                async for ws in websockets.connect(
                    "wss://gateway.discord.gg/?v=10&encoding=json", max_size=2 ** 22, ping_interval=None,
                ):
                    seq = None
                    try:
                        hello = _json.loads(await ws.recv())
                        hb_interval = (hello.get("d") or {}).get("heartbeat_interval", 41250) / 1000.0
                        await ws.send(_json.dumps({
                            "op": 2,
                            "d": {
                                "token": token,
                                "intents": INTENTS,
                                "properties": {"os": "macos", "browser": "abcode", "device": "abcode"},
                            },
                        }))
                        # 心跳协程
                        hb_task = asyncio.ensure_future(_discord_heartbeat(ws, hb_interval, lambda: seq))
                        try:
                            async for raw in ws:
                                try:
                                    msg = _json.loads(raw)
                                except Exception:
                                    continue
                                if msg.get("op") == 0:
                                    seq = msg.get("s", seq)
                                    if msg.get("t") == "MESSAGE_CREATE":
                                        d = msg.get("d") or {}
                                        author = d.get("author") or {}
                                        if author.get("bot"):
                                            continue
                                        text = (d.get("content") or "").strip()
                                        channel_id = d.get("channel_id") or ""
                                        if not text or not channel_id:
                                            continue
                                        sender = author.get("username") or author.get("global_name") or f"dc{author.get('id','')}"
                                        threading.Thread(
                                            target=_discord_converse, args=(token, channel_id, sender, text),
                                            daemon=True).start()
                                elif msg.get("op") == 11:  # HEARTBEAT_ACK
                                    pass
                        finally:
                            hb_task.cancel()
                    except Exception as e:
                        print(f"[discord] 连接内异常: {type(e).__name__}: {e}")
                        await asyncio.sleep(3)
            except Exception as e:
                print(f"[discord] 连接失败: {type(e).__name__}: {e}")
                await asyncio.sleep(5)

    asyncio.run(_listen())


async def _discord_heartbeat(ws, interval, seq_getter):
    """周期发送 op1 心跳。"""
    try:
        import json as _json
        while True:
            await asyncio.sleep(interval)
            await ws.send(_json.dumps({"op": 1, "d": seq_getter()}))
    except Exception:
        pass


def _discord_converse(token, channel_id, sender, text):
    """AI 对话后把回复发送到频道。"""
    try:
        reply = reply_to_channel("discord", sender, text)
        if reply:
            _discord_send_text(token, channel_id, reply)
    except Exception as e:
        print(f"[discord] 对话异常: {type(e).__name__}: {e}")


def _discord_send_text(token, channel_id, text):
    """通过 REST 发消息到指定频道。返回 (ok, err)。"""
    import requests
    try:
        r = requests.post(
            f"https://discord.com/api/v10/channels/{channel_id}/messages",
            headers={"Authorization": f"Bot {token}"},
            json={"content": text[:2000]},
            timeout=10,
        )
        if r.status_code not in (200, 201):
            return False, f"HTTP {r.status_code}: {r.text[:150]}"
        return True, ""
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


# ================= OneBot（QQ 生态，正向 WebSocket） =================
def start_onebot_runtime():
    """若 OneBot 频道已启用且填了 ws_url，则后台连正向 WebSocket。"""
    try:
        channel = db.get_channel("onebot")
    except Exception:
        channel = None
    if not channel or not channel.get("enabled"):
        print("[channel] OneBot 频道未启用，跳过")
        return
    cfg = channel.get("config") or {}
    ws_url = (cfg.get("ws_url") or "").strip()
    access_token = (cfg.get("access_token") or "").strip()
    if not ws_url:
        print("[channel] OneBot 已启用但未配置 ws_url（如 ws://127.0.0.1:6700），无法收发消息")
        return
    threading.Thread(target=_onebot_stream_loop, args=(ws_url, access_token), daemon=True).start()
    print(f"[channel] OneBot 正向 WS 已启动（{ws_url}）")


def _onebot_stream_loop(ws_url, access_token):
    """OneBot v11 正向 WebSocket：收 message 事件 -> AI 回复 -> send_msg action。"""
    try:
        import asyncio
    except Exception:
        return

    def _cq_strip(text):
        """去掉 CQ 码（如 [CQ:image,...]），合并多余空格，仅保留纯文本。"""
        import re
        return re.sub(r"\s+", " ", re.sub(r"\[CQ:[^\]]*\]", "", text)).strip()

    async def _listen():
        import websockets
        import json as _json

        headers = {"Authorization": f"Bearer {access_token}"} if access_token else {}

        while True:
            try:
                async for ws in websockets.connect(ws_url, max_size=2 ** 22, extra_headers=headers, ping_interval=None):
                    send_queue = asyncio.Queue()
                    async def _sender():
                        while True:
                            action = await send_queue.get()
                            try:
                                await ws.send(_json.dumps(action))
                            except Exception as e:
                                print(f"[onebot] 发送 action 失败: {e}")
                            finally:
                                send_queue.task_done()
                    sender_task = asyncio.ensure_future(_sender())
                    try:
                        print(f"[onebot] 已连接 {ws_url}")
                        async for raw in ws:
                            try:
                                evt = _json.loads(raw)
                            except Exception:
                                continue
                            if evt.get("post_type") != "message":
                                continue
                            text = _cq_strip((evt.get("raw_message") or evt.get("message") or ""))
                            if not text:
                                continue
                            uid = evt.get("user_id") or ""
                            self_id = evt.get("self_id") or ""
                            if uid and uid == self_id:
                                continue
                            threading.Thread(
                                target=_onebot_converse,
                                args=(send_queue, evt, text), daemon=True).start()
                    finally:
                        sender_task.cancel()
                        await asyncio.sleep(2)
            except Exception as e:
                print(f"[onebot] 连接失败: {type(e).__name__}: {e}")
                await asyncio.sleep(5)

    # send_queue 由 _onebot_converse 通过 put_nowait 跨线程写入（线程安全）
    asyncio.run(_listen())


def _onebot_converse(send_queue, evt, text):
    """AI 对话后通过 send_msg action 发回。"""
    try:
        uid = evt.get("user_id") or ""
        reply = reply_to_channel("onebot", f"onebot:{uid}", text)
        if not reply:
            return
        params = {"user_id": uid}
        if evt.get("message_type") == "group":
            params["group_id"] = evt.get("group_id") or uid
        action = {
            "action": "send_msg",
            "params": {**params, "message": reply[:2000]},
            "echo": f"abcode_{int(time.time()*1000)}",
        }
        try:
            send_queue.put_nowait(action)
        except Exception as e:
            print(f"[onebot] 队列投递失败: {e}")
    except Exception as e:
        print(f"[onebot] 对话异常: {type(e).__name__}: {e}")


# ================= Slack（Socket Mode，免公网） =================
def start_slack_runtime():
    """若 Slack 频道已启用且填了 App Token + Bot Token，则后台跑 Socket Mode 长连接。"""
    try:
        channel = db.get_channel("slack")
    except Exception:
        channel = None
    if not channel or not channel.get("enabled"):
        print("[channel] Slack 频道未启用，跳过")
        return
    cfg = channel.get("config") or {}
    app_token = (cfg.get("app_token") or "").strip()
    bot_token = (cfg.get("bot_token") or "").strip()
    if not app_token or not bot_token:
        print("[channel] Slack 已启用但未配置 App Token / Bot Token（Socket Mode 需 xapp- / xoxb-），无法收发消息")
        return
    threading.Thread(target=_slack_stream_loop, args=(app_token, bot_token), daemon=True).start()
    print(f"[channel] Slack Socket Mode 已启动（Bot Token 尾号 ...{bot_token[-6:]}）")


def _slack_stream_loop(app_token, bot_token):
    """Slack Socket Mode：message 事件 -> AI 回复 -> chat.postMessage。"""
    try:
        from slack_sdk.socket_mode import SocketModeClient
        from slack_sdk import WebClient
        from slack_sdk.socket_mode.response import SocketModeResponse
    except Exception as e:
        print(f"[slack] 缺少 slack_sdk: {type(e).__name__}: {e}")
        return

    def _on_message(client, req):
        try:
            if req.type != "events_api":
                client.send_socket_mode_response(SocketModeResponse(envelope_id=req.envelope_id))
                return
            evt = req.payload.get("event") or {}
            if evt.get("type") != "message":
                client.send_socket_mode_response(SocketModeResponse(envelope_id=req.envelope_id))
                return
            if evt.get("subtype") in ("channel_join", "channel_leave", "message_changed", "bot_message", "message_deleted"):
                client.send_socket_mode_response(SocketModeResponse(envelope_id=req.envelope_id))
                return
            text = (evt.get("text") or "").strip()
            channel_id = evt.get("channel") or ""
            user = evt.get("user") or ""
            if not text or not channel_id:
                client.send_socket_mode_response(SocketModeResponse(envelope_id=req.envelope_id))
                return
            # 立即 ack，避免重试风暴
            client.send_socket_mode_response(SocketModeResponse(envelope_id=req.envelope_id))
            threading.Thread(
                target=_slack_respond, args=(bot_token, channel_id, user, text),
                daemon=True).start()
        except Exception as e:
            print(f"[slack] 事件异常: {type(e).__name__}: {e}")

    def _slack_respond(bot_token, channel_id, user, text):
        try:
            reply = reply_to_channel("slack", f"slack:{user}", text)
            if not reply:
                return
            web = WebClient(token=bot_token)
            web.chat_postMessage(channel=channel_id, text=reply[:4000])
        except Exception as e:
            print(f"[slack] 回复异常: {type(e).__name__}: {e}")

    try:
        client = SocketModeClient(
            app_token=app_token,
            web_client=WebClient(token=bot_token),
        )
        client.message_listener = _on_message
        client.connect()
        import time as _t
        while True:
            _t.sleep(30)
    except Exception as e:
        print(f"[slack] Socket Mode 异常: {type(e).__name__}: {e}")


# ================= Matrix（HTTP sync 长轮询，免公网） =================
def start_matrix_runtime():
    """若 Matrix 频道已启用且填了 Homeserver + Access Token，则后台 sync 长轮询。"""
    try:
        channel = db.get_channel("matrix")
    except Exception:
        channel = None
    if not channel or not channel.get("enabled"):
        print("[channel] Matrix 频道未启用，跳过")
        return
    cfg = channel.get("config") or {}
    homeserver = (cfg.get("homeserver") or "").strip().rstrip("/")
    access_token = (cfg.get("access_token") or "").strip()
    if not homeserver or not access_token:
        print("[channel] Matrix 已启用但未配置 Homeserver/Access Token，无法收发消息")
        return
    threading.Thread(target=_matrix_sync_loop, args=(homeserver, access_token), daemon=True).start()
    print(f"[channel] Matrix sync 已启动（Homeserver={homeserver}）")


def _matrix_sync_loop(homeserver, access_token):
    """Matrix client-server API sync 长轮询：m.room.message -> AI 回复 -> send 消息。"""
    import requests
    import urllib.parse as _up

    def _whoami():
        try:
            r = requests.get(f"{homeserver}/_matrix/client/v3/account/whoami",
                             headers={"Authorization": f"Bearer {access_token}"}, timeout=10)
            return (r.json() or {}).get("user_id") or ""
        except Exception:
            return ""

    own_user_id = _whoami()
    since = ""
    while True:
        try:
            url = f"{homeserver}/_matrix/client/v3/sync?timeout=30000"
            if since:
                url += f"&since={_up.quote(since)}"
            r = requests.get(url, headers={"Authorization": f"Bearer {access_token}"}, timeout=40)
            if r.status_code != 200:
                print(f"[matrix] sync HTTP {r.status_code}: {r.text[:150]}")
                time.sleep(5)
                continue
            data = r.json()
            since = data.get("next_batch") or since
            rooms = data.get("rooms", {}).get("join", {})
            for room_id, room in rooms.items():
                for evt in room.get("timeline", {}).get("events", []):
                    if evt.get("type") != "m.room.message":
                        continue
                    content = evt.get("content") or {}
                    if content.get("msgtype") != "m.text":
                        continue  # 只回文本
                    text = (content.get("body") or "").strip()
                    sender = evt.get("sender") or ""
                    if not text or not room_id:
                        continue
                    # 忽略自己的消息（防回环）
                    username = sender.split(":", 1)[0].lstrip("@")
                    if sender == own_user_id:
                        continue
                    threading.Thread(
                        target=_matrix_respond,
                        args=(homeserver, access_token, room_id, username, text),
                        daemon=True).start()
        except Exception as e:
            print(f"[matrix] sync 异常: {type(e).__name__}: {e}")
            time.sleep(5)


def _matrix_respond(homeserver, access_token, room_id, sender, text):
    import requests
    import uuid
    try:
        reply = reply_to_channel("matrix", f"matrix:{sender}", text)
        if not reply:
            return
        txn = str(uuid.uuid4())
        url = f"{homeserver}/_matrix/client/v3/rooms/{room_id}/send/m.room.message/{txn}"
        r = requests.put(
            url,
            headers={"Authorization": f"Bearer {access_token}"},
            json={"msgtype": "m.text", "body": reply[:4000]},
            timeout=10,
        )
        if r.status_code not in (200, 201):
            print(f"[matrix] 回复失败 HTTP {r.status_code}: {r.text[:150]}")
    except Exception as e:
        print(f"[matrix] 回复异常: {type(e).__name__}: {e}")


# ================= MQTT（订阅-发布） =================
def start_mqtt_runtime():
    """若 MQTT 频道已启用且填了 broker_url，则后台订阅 topic 并支持回复。"""
    try:
        channel = db.get_channel("mqtt")
    except Exception:
        channel = None
    if not channel or not channel.get("enabled"):
        print("[channel] MQTT 频道未启用，跳过")
        return
    cfg = channel.get("config") or {}
    broker_url = (cfg.get("broker_url") or "").strip()
    topic = (cfg.get("topic") or "").strip()
    if not broker_url or not topic:
        print("[channel] MQTT 已启用但未配置 broker_url/topic，无法收发消息")
        return
    username = (cfg.get("username") or "").strip()
    password = (cfg.get("password") or "").strip()
    threading.Thread(
        target=_mqtt_loop, args=(broker_url, username, password, topic),
        daemon=True).start()
    print(f"[channel] MQTT 已启动（{broker_url} -> {topic}）")


def _mqtt_loop(broker_url, username, password, topic):
    """连接 broker，订阅 topic；收到非自身消息 -> AI 回复 -> 发布带 abcode: 前缀。"""
    try:
        import paho.mqtt.client as mqtt
    except Exception as e:
        print(f"[mqtt] 缺少 paho-mqtt: {type(e).__name__}: {e}")
        return

    import urllib.parse as _up
    parsed = _up.urlparse(broker_url if "://" in broker_url else f"mqtt://{broker_url}")
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 1883
    use_tls = parsed.scheme in ("mqtts", "ssl", "tls")

    client = mqtt.Client(client_id=f"abcode_{int(time.time()) % 100000}")
    if username:
        client.username_pw_set(username, password)
    client.reconnect_delay_set(1, 30)

    def _on_connect(c, userdata, flags, rc):
        c.subscribe(topic, qos=0)
        print(f"[mqtt] 已连接 {host}:{port}，订阅 {topic}")

    def _on_message(c, userdata, msg):
        try:
            payload = (msg.payload or b"").decode("utf-8", "ignore").strip()
            if not payload:
                return
            # 跳过自己发布的回复（回环防护）
            if payload.startswith("abcode:"):
                return
            threading.Thread(
                target=_mqtt_respond, args=(c, topic, payload),
                daemon=True).start()
        except Exception as e:
            print(f"[mqtt] 消息处理异常: {type(e).__name__}: {e}")

    def _mqtt_respond(c, topic, text):
        try:
            reply = reply_to_channel("mqtt", "mqtt", text)
            if reply:
                c.publish(topic, f"abcode:{reply[:4000]}", qos=0)
        except Exception as e:
            print(f"[mqtt] 对话异常: {type(e).__name__}: {e}")

    client.on_connect = _on_connect
    client.on_message = _on_message
    try:
        if use_tls:
            client.tls_set()
        client.connect(host, port, keepalive=60)
        client.loop_forever()
    except Exception as e:
        print(f"[mqtt] 连接异常: {type(e).__name__}: {e}")


# ================= QQ 官方机器人（botpy，WebSocket 免公网） =================
def start_qq_runtime():
    """若 QQ 频道已启用且填了 AppID/Token/Secret，则后台跑 botpy 机器人。"""
    try:
        channel = db.get_channel("qq")
    except Exception:
        channel = None
    if not channel or not channel.get("enabled"):
        print("[channel] QQ 频道未启用，跳过")
        return
    cfg = channel.get("config") or {}
    appid = (cfg.get("bot_appid") or "").strip()
    token = (cfg.get("bot_token") or "").strip()
    secret = (cfg.get("bot_secret") or "").strip()
    if not appid or not token:
        print("[channel] QQ 已启用但未配置 AppID/Token（bottoken），无法收发消息")
        return
    threading.Thread(target=_qq_bot_loop, args=(appid, token, secret), daemon=True).start()
    print(f"[channel] QQ 机器人已启动（AppID={appid}）")


def _qq_bot_loop(appid, token, secret):
    """botpy 客户端：处理 @机器人 与私信消息。"""
    try:
        import botpy
        from botpy.message import Message
        import asyncio
    except Exception as e:
        print(f"[qq] 缺少 qq-botpy: {type(e).__name__}: {e}")
        return

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    class _Client(botpy.Client):
        async def on_at_message_create(self, message: Message):
            try:
                text = (message.content or "").strip()
                # 去掉 @机器人 的 CQ 风格前缀
                import re
                text = re.sub(r"<@![0-9]+>", "", text).strip()
                if not text:
                    return
                sender = str(getattr(message.author, "id", "") or "")
                threading.Thread(target=_qq_respond, args=(message, loop, sender, text), daemon=True).start()
            except Exception as e:
                print(f"[qq] 群消息异常: {type(e).__name__}: {e}")

        async def on_direct_message_create(self, message: Message):
            try:
                text = (message.content or "").strip()
                if not text:
                    return
                sender = str(getattr(message.author, "id", "") or "")
                threading.Thread(target=_qq_respond, args=(message, loop, sender, text), daemon=True).start()
            except Exception as e:
                print(f"[qq] 私信异常: {type(e).__name__}: {e}")

    def _qq_respond(message, loop, sender, text):
        try:
            reply = reply_to_channel("qq", f"qq:{sender}", text)
            if not reply:
                return
            async def _send():
                try:
                    if _qq_from_dm(message):
                        await message.reply(content=reply[:2000])
                    else:
                        await message.reply(content=reply[:2000])
                except Exception as e:
                    print(f"[qq] 回复发送异常: {type(e).__name__}: {e}")
            asyncio.run_coroutine_threadsafe(_send(), loop)
        except Exception as e:
            print(f"[qq] 对话异常: {type(e).__name__}: {e}")

    def _qq_from_dm(message):
        # botpy 私信消息无 channel_id 时走私信通道；统一用 message.reply 即可
        return hasattr(message, "channel_id") and not message.channel_id

    try:
        intents = botpy.Intents(public_messages=True, direct_message=True)
        client = _Client(intents=intents)
        client.run(appid=appid, token=token, secret=secret or None)
    except Exception as e:
        print(f"[qq] botpy 异常: {type(e).__name__}: {e}")


# ================= Mattermost（WebSocket + REST，免公网） =================
def start_mattermost_runtime():
    """若 Mattermost 频道已启用且填了 server_url + access_token，则连 WebSocket。"""
    try:
        channel = db.get_channel("mattermost")
    except Exception:
        channel = None
    if not channel or not channel.get("enabled"):
        print("[channel] Mattermost 频道未启用，跳过")
        return
    cfg = channel.get("config") or {}
    server = (cfg.get("server_url") or "").strip().rstrip("/")
    token = (cfg.get("access_token") or "").strip()
    if not server or not token:
        print("[channel] Mattermost 已启用但未配置 server_url/access_token，无法收发消息")
        return
    threading.Thread(target=_mattermost_loop, args=(server, token), daemon=True).start()
    print(f"[channel] Mattermost 已启动（{server}）")


def _mattermost_loop(server, token):
    """Mattermost v4 WebSocket：authentication_challenge -> posted 事件 -> AI 回复。"""
    try:
        import asyncio
    except Exception:
        return

    async def _listen():
        import websockets
        import json as _json
        import requests

        ws_url = server.replace("https://", "wss://").replace("http://", "ws://") + "/api/v4/websocket"

        def _send_post(channel_id, text, sender):
            try:
                reply = reply_to_channel("mattermost", f"mm:{sender}", text)
                if not reply:
                    return
                r = requests.post(
                    f"{server}/api/v4/posts",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"channel_id": channel_id, "message": reply[:4000]},
                    timeout=10,
                )
                if r.status_code not in (200, 201):
                    print(f"[mattermost] 回复失败 HTTP {r.status_code}: {r.text[:150]}")
            except Exception as e:
                print(f"[mattermost] 对话异常: {type(e).__name__}: {e}")

        while True:
            try:
                async for ws in websockets.connect(ws_url, max_size=2 ** 22, ping_interval=None):
                    await ws.send(_json.dumps({
                        "seq": 1,
                        "action": "authentication_challenge",
                        "data": {"token": token},
                    }))
                    try:
                        async for raw in ws:
                            try:
                                evt = _json.loads(raw)
                            except Exception:
                                continue
                            if evt.get("event") != "posted":
                                continue
                            data = evt.get("data") or {}
                            post_raw = data.get("post") or ""
                            if isinstance(post_raw, str):
                                try:
                                    post = _json.loads(post_raw)
                                except Exception:
                                    post = {}
                            else:
                                post = post_raw or {}
                            text = (post.get("message") or "").strip()
                            channel_id = post.get("channel_id") or ""
                            if not text or not channel_id:
                                continue
                            # 跳过 webhook/系统消息（防回环）
                            props = post.get("props") or {}
                            if props.get("from_webhook") or props.get("from_bot"):
                                continue
                            sender = post.get("user_id") or "mm"
                            threading.Thread(
                                target=_send_post, args=(channel_id, text, sender),
                                daemon=True).start()
                    except Exception as e:
                        print(f"[mattermost] WS 内异常: {type(e).__name__}: {e}")
                        await asyncio.sleep(2)
            except Exception as e:
                print(f"[mattermost] WS 连接失败: {type(e).__name__}: {e}")
                await asyncio.sleep(5)

    asyncio.run(_listen())


# ================= 通用 Webhook 入站 =================
def handle_webhook(cid, payload):
    """通用 HTTP 入站：payload 为 dict，取 sender 与 text 字段。"""
    sender = (payload.get("sender") or payload.get("from") or "用户").strip() or "用户"
    text = (payload.get("text") or payload.get("message") or payload.get("content") or "").strip()
    if not text:
        return {"ok": False, "error": "缺少 text 字段"}
    reply = reply_to_channel(cid, sender, text)
    return {"ok": True, "reply": reply, "sender": sender}


# ================= Telegram Bot（长轮询，免公网回调） =================
def start_telegram_runtime():
    """若 Telegram 频道已启用且填了 Bot Token，则后台起长轮询线程。"""
    try:
        channel = db.get_channel("telegram")
    except Exception:
        channel = None
    if not channel or not channel.get("enabled"):
        print("[channel] Telegram 频道未启用，跳过")
        return
    cfg = channel.get("config") or {}
    token = (cfg.get("bot_token") or "").strip()
    if not token:
        print("[channel] Telegram 已启用但未配置 Bot Token，无法收发消息")
        return
    threading.Thread(target=_telegram_poll_loop, args=(token,), daemon=True).start()
    print(f"[channel] Telegram Bot 长轮询已启动（Token 尾号 ...{token[-6:]}）")


def _telegram_api(token, method, **params):
    """调用 Telegram Bot API；失败返回 None。"""
    import requests
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/{method}",
            json=params, timeout=10,
        )
        if r.status_code != 200:
            # 401/403 常见于 token 无效或 bot 被停用；打印一次便于排查
            print(f"[telegram] API {method} HTTP {r.status_code}: {r.text[:200]}")
            return None
        data = r.json()
        if not data.get("ok"):
            print(f"[telegram] API {method} 失败: {data.get('description')}")
            return None
        return data.get("result")
    except Exception as e:
        print(f"[telegram] API {method} 异常: {type(e).__name__}: {e}")
        return None


def _telegram_send_reply(token, chat_id, text):
    """把回复发回 Telegram 会话（纯文本，消息较长时截断）。"""
    if not text:
        return
    text = text[:4000]
    _telegram_api(token, "sendMessage", chat_id=chat_id, text=text)


def _telegram_poll_loop(token):
    """长轮询 getUpdates：每条文本消息 -> reply_to_channel -> sendMessage。"""
    offset = 0
    while True:
        try:
            updates = _telegram_api(token, "getUpdates", timeout=25, offset=offset, allowed_updates=["message"])
            if updates is None:
                time.sleep(3)
                continue
            for up in updates:
                offset = up.get("update_id", offset) + 1
                msg = up.get("message") or {}
                text = (msg.get("text") or "").strip()
                if not text:
                    continue
                chat_id = msg.get("chat", {}).get("id")
                if chat_id is None:
                    continue
                user = msg.get("from") or {}
                sender = (user.get("username") or user.get("first_name")
                          or f"tg{user.get('id', '')}" or "Telegram用户")
                # 忽略机器人自己的消息（多实例防回环）
                if user.get("is_bot"):
                    continue
                reply = reply_to_channel("telegram", sender, text)
                _telegram_send_reply(token, chat_id, reply or "（无回复）")
        except Exception as e:
            print(f"[telegram] 轮询异常: {type(e).__name__}: {e}")
            time.sleep(3)