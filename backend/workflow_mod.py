"""ABcode 工作流引擎 - 参考 Dify / 阿里百炼，支持多种节点类型"""
import json
import re
import time
import uuid
import traceback

import db
import llm
import rag
import connector as connector_mod

# 节点类型
NODE_TYPES = {
    "start": "开始",
    "end": "结束",
    "llm": "LLM调用",
    "kb_search": "知识库检索",
    "classifier": "意图分类",
    "extractor": "参数提取",
    "tool": "工具调用",
    "connector": "数据连接",
    "condition": "条件分支",
    "variable": "变量操作",
    "code": "代码执行",
    "http": "HTTP请求",
    "text_process": "文本处理",
    "aggregator": "变量聚合",
    "template": "模板处理",
    "stop": "直接回复",
}

# 文本处理操作
TEXT_OPTS = {
    "upper": "转大写", "lower": "转小写", "capitalize": "首字母大写",
    "trim": "去除首尾空格", "strip_newlines": "去除换行",
    "replace": "替换文本", "extract_regex": "正则提取",
    "truncate": "截断", "length": "计算长度",
    "join": "拼接变量", "dedupe_lines": "去除重复行",
}

# 条件操作符
OPERATORS = {
    "eq": lambda a, b: a == b,
    "neq": lambda a, b: a != b,
    "contains": lambda a, b: str(b) in str(a),
    "not_contains": lambda a, b: str(b) not in str(a),
    "gt": lambda a, b: float(a) > float(b),
    "lt": lambda a, b: float(a) < float(b),
    "gte": lambda a, b: float(a) >= float(b),
    "lte": lambda a, b: float(a) <= float(b),
    "startswith": lambda a, b: str(a).startswith(str(b)),
    "endswith": lambda a, b: str(a).endswith(str(b)),
    "empty": lambda a, b: not a,
    "not_empty": lambda a, b: bool(a),
    "is_list": lambda a, b: isinstance(a, list),
    "default": lambda a, b: True,
}

OP_LABELS = {
    "eq": "等于", "neq": "不等于", "contains": "包含", "not_contains": "不包含",
    "gt": "大于", "lt": "小于", "gte": "大于等于", "lte": "小于等于",
    "startswith": "以…开头", "endswith": "以…结尾", "empty": "为空",
    "not_empty": "非空", "is_list": "是列表", "default": "默认分支",
}


def render_template(template, variables):
    """渲染模板字符串，替换 {{variable}} 占位符"""
    if template is None:
        return ""
    if not isinstance(template, str):
        return template
    if not template:
        return ""

    def replace_var(match):
        var_name = match.group(1).strip()
        # 支持点号路径 a.b
        keys = var_name.split(".")
        value = variables
        try:
            for k in keys:
                if isinstance(value, dict):
                    value = value.get(k, "")
                elif isinstance(value, list) and k.isdigit():
                    value = value[int(k)]
                else:
                    value = ""
                    break
        except Exception:
            value = ""
        if value is None:
            return ""
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False, indent=2)
        return str(value)

    return re.sub(r'\{\{([\w.]+)\}\}', replace_var, template)


class WorkflowEngine:
    """工作流执行引擎"""

    def __init__(self, workflow):
        self.workflow = workflow
        self.nodes = {n["id"]: n for n in workflow.get("nodes", [])}
        self.edges = workflow.get("edges", [])
        self.variables = {}
        self.nodes_status = {}
        self.execution_id = str(int(time.time() * 1000))
        self.tokens_used = 0
        self.start_time = None
        self._stopped = False
        self._final_output = None
        self._event_callback = None  # 流式回调
        self.node_requests = {}  # 节点请求/响应观测 {node_id: {request, response, duration_ms}}

    def set_event_callback(self, callback):
        """设置流式事件回调"""
        self._event_callback = callback

    def _emit_event(self, event_type, data):
        """发送流式事件"""
        if self._event_callback:
            self._event_callback(event_type, data)

    def execute(self, input_data=None):
        """执行工作流"""
        self.start_time = time.time()
        self.variables = dict(input_data or {})

        start_node = None
        for n in self.workflow.get("nodes", []):
            if n["type"] == "start":
                start_node = n
                break

        if not start_node:
            return {"success": False, "error": "没有找到开始节点", "output": ""}

        try:
            output = self._execute_node(start_node["id"])
            final_output = self._final_output if self._stopped else output
            return {
                "success": True,
                "output": final_output if final_output is not None else "",
                "variables": self.variables,
                "nodes_status": self.nodes_status,
                "tokens_used": self.tokens_used,
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "traceback": traceback.format_exc(),
                "variables": self.variables,
                "nodes_status": self.nodes_status,
            }

    def _execute_node(self, node_id):
        """执行单个节点"""
        if self._stopped:
            return self._final_output

        node = self.nodes.get(node_id)
        if not node:
            raise RuntimeError(f"节点不存在: {node_id}")

        node_type = node.get("type", "")
        config = node.get("config", {})

        self.nodes_status[node_id] = {"status": "running", "started_at": time.time()}
        self._emit_event("node_status", {
            "node_id": node_id, "type": node_type,
            "label": node.get("label", node_type), "status": "running"
        })

        try:
            if node_type == "start":
                output = self._execute_start(node, config)
            elif node_type == "end":
                output = self._execute_end(node, config)
            elif node_type == "stop":
                output = self._execute_stop(node, config)
            elif node_type == "llm":
                output = self._execute_llm(node, config)
            elif node_type == "kb_search":
                output = self._execute_kb_search(node, config)
            elif node_type == "classifier":
                output = self._execute_classifier(node, config)
            elif node_type == "extractor":
                output = self._execute_extractor(node, config)
            elif node_type == "tool":
                output = self._execute_tool(node, config)
            elif node_type == "connector":
                output = self._execute_connector(node, config)
            elif node_type == "condition":
                output = self._execute_condition(node, config)
            elif node_type == "variable":
                output = self._execute_variable(node, config)
            elif node_type == "code":
                output = self._execute_code(node, config)
            elif node_type == "http":
                output = self._execute_http(node, config)
            elif node_type == "text_process":
                output = self._execute_text_process(node, config)
            elif node_type == "aggregator":
                output = self._execute_aggregator(node, config)
            elif node_type == "template":
                output = self._execute_template(node, config)
            else:
                raise RuntimeError(f"未知节点类型: {node_type}")

            duration_ms = int((time.time() - self.nodes_status[node_id]["started_at"]) * 1000)
            self.nodes_status[node_id] = {
                "status": "completed",
                "started_at": self.nodes_status[node_id]["started_at"],
                "completed_at": time.time(),
                "output": str(output)[:500] if output else "",
            }
            self._emit_event("node_status", {
                "node_id": node_id, "type": node_type,
                "label": node.get("label", node_type), "status": "completed",
                "duration_ms": duration_ms
            })

            if self._stopped:
                return self._final_output

            # 条件/分类节点内部自行路由
            if node_type in ("condition", "classifier"):
                return output

            next_node = self._get_next_node(node_id)
            if next_node:
                return self._execute_node(next_node)

            return output

        except Exception as e:
            duration_ms = int((time.time() - self.nodes_status[node_id]["started_at"]) * 1000)
            self.nodes_status[node_id] = {
                "status": "failed",
                "started_at": self.nodes_status[node_id]["started_at"],
                "completed_at": time.time(),
                "error": str(e),
            }
            self._emit_event("node_status", {
                "node_id": node_id, "type": node_type,
                "label": node.get("label", node_type), "status": "failed",
                "error": str(e), "duration_ms": duration_ms
            })
            raise

    # ================= LLM 辅助 =================

    def _pick_provider(self, model="", model_source=""):
        """选择供应商：优先匹配指定模型，否则取第一个启用的"""
        # 本地模型：从 Ollama 读取
        if model_source == "local" and model:
            local_provider = {
                "id": "ollama_local",
                "name": "Ollama (本地)",
                "type": "ollama",
                "base_url": "http://localhost:11434",
                "enabled": True,
            }
            return local_provider, model
        
        providers = db.list_providers()
        if model:
            for p in providers:
                if model in (p.get("models") or []):
                    return p, model
            # 模型未在供应商列表里，尝试找到包含该模型的
            for p in providers:
                if p.get("default_model") == model:
                    return p, model
        if providers:
            p = next((x for x in providers if x.get("enabled")), providers[0])
            m = model or p.get("default_model", "") or (p.get("models") or [""])[0]
            return p, m
        return None, ""

    def _call_llm(self, prompt, model="", system="", temperature=None, max_tokens=None, model_source=""):
        """调用 LLM 并返回文本（修复：使用 stream_chat）"""
        provider, m = self._pick_provider(model, model_source)
        if not provider:
            raise RuntimeError("没有可用的LLM供应商，请先在设置中配置")
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": self._build_prompt_content(prompt, provider)})

        parts = []
        for evt in llm.stream_chat(provider, m, messages, tools=None):
            if evt.get("type") == "text":
                parts.append(evt["content"])
            elif evt.get("type") == "usage":
                self.tokens_used += evt.get("total_tokens", 0) or 0
        text = "".join(parts)
        self.tokens_used += max(1, len(text) // 4)
        return text

    def _build_prompt_content(self, prompt, provider=None):
        """把测试面板附件转成多模态 content；云端用 image_url，本地 Ollama 用 image data"""
        attachments = self.variables.get("_attachments") or []
        # 只当存在图片附件时才构建多模态 content
        images = [a for a in attachments if (a.get("type") or "").startswith("image/")]
        if not images:
            return prompt
        # 判断是否为 Ollama 本地模型
        base = (provider or {}).get("base_url", "").lower()
        is_ollama = "ollama" in base or ":11434" in base or (provider or {}).get("type") == "ollama"
        content = [{"type": "text", "text": prompt or ""}]
        for img in images:
            data = img.get("data", "")
            if data.startswith("data:"):
                # 去掉 data:image/xxx;base64, 前缀，取纯 base64
                raw = data.split(",", 1)[1] if "," in data else data
            else:
                raw = data
            if is_ollama:
                content.append({"type": "image", "data": raw})
            else:
                mime = img.get("type", "image/jpeg")
                content.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{raw}"}})
        return content

    def _store_output(self, node_id, output):
        """把节点输出存到变量，支持指定变量名"""
        output_var = node_id + "_output"
        self.variables[output_var] = output
        return output_var

    # ================= 节点执行 =================

    def _execute_start(self, node, config):
        input_fields = config.get("input_fields", [])
        out = {}
        for f in input_fields:
            out[f] = self.variables.get(f, self.variables.get("input", ""))
        # 如果只有 input 字段，直接透传
        return out

    def _execute_end(self, node, config):
        output_field = config.get("output_field", "output")
        return self.variables.get(output_field, "")

    def _execute_stop(self, node, config):
        """直接回复 / 提前终止：结束工作流并输出指定变量"""
        output_field = config.get("output_field", "output")
        value = self.variables.get(output_field, self._store_output(node["id"], ""))
        if output_field in self.variables:
            value = self.variables[output_field]
        self._stopped = True
        self._final_output = value
        self._store_output(node["id"], value)
        return value

    def _execute_llm(self, node, config):
        prompt = render_template(config.get("prompt", ""), self.variables)
        model = config.get("model", "")
        model_source = config.get("model_source", "")
        system = render_template(config.get("system", ""), self.variables)
        req_start = time.time()
        provider, m = self._pick_provider(model, model_source)
        # 构建请求记录
        req_body = {
            "model": m,
            "provider": provider.get("name", "") if provider else "",
            "provider_type": provider.get("type", "") if provider else "",
            "system": system[:500] if system else "",
            "prompt": prompt[:2000],
            "messages_preview": [{"role": "user", "content": prompt[:500]}],
        }
        output = self._call_llm(prompt, model=model, system=system, model_source=model_source)
        req_duration = int((time.time() - req_start) * 1000)
        self.node_requests[node["id"]] = {
            "request": req_body,
            "response": {"text": output[:2000]},
            "duration_ms": req_duration,
            "type": "llm",
        }
        self._store_output(node["id"], output)
        return output

    def _execute_kb_search(self, node, config):
        """知识库检索节点"""
        query = render_template(config.get("query", ""), self.variables) or str(self.variables.get("input", ""))
        top_k = int(config.get("top_k", 5) or 5)
        kb_id = config.get("kb_id") or None
        req_start = time.time()
        results = rag.search(query, top_k=top_k, kb_id=kb_id)
        req_duration = int((time.time() - req_start) * 1000)
        # 输出格式：拼接文本
        lines = []
        for i, r in enumerate(results):
            lines.append(f"[{i+1}] 《{r['doc_name']}》 相关度{r['score']}\n{r['content']}")
        output = "\n\n".join(lines)
        self.node_requests[node["id"]] = {
            "request": {"query": query[:2000], "top_k": top_k, "kb_id": kb_id},
            "response": {"results": [{"doc": r.get("doc_name", ""), "score": r.get("score", 0), "content": r.get("content", "")[:500]} for r in results[:10]]},
            "duration_ms": req_duration,
            "type": "kb_search",
        }
        self.variables[node["id"] + "_results"] = results  # 结构化结果
        self._store_output(node["id"], output)
        return output

    def _execute_classifier(self, node, config):
        """意图分类节点：LLM 分类后按条件路由"""
        text = render_template(config.get("input", ""), self.variables) or str(self.variables.get("input", ""))
        categories = config.get("categories", [])
        cat_str = "\n".join(f"{i+1}. {c}" for i, c in enumerate(categories)) if categories else ""
        prompt = config.get("prompt", "") or (
            f"请判断以下内容属于哪个类别，只输出类别名称（不输出编号）：\n\n可选类别：\n{cat_str}\n\n内容：\n{text}")
        model = config.get("model", "")
        result = self._call_llm(prompt, model=model).strip()
        # 去掉编号前缀
        m = re.match(r'^[\d\.\-\s]+(.*)$', result)
        if m:
            result = m.group(1).strip()
        self._store_output(node["id"], result)
        self.variables[node["id"] + "_category"] = result
        # 按条件路由
        conditions = config.get("conditions", [])
        target = self._route(conditions, result)
        if target:
            return self._execute_node(target)
        # 无匹配则走默认边
        next_node = self._get_next_node(node["id"])
        if next_node:
            return self._execute_node(next_node)
        return result

    def _execute_extractor(self, node, config):
        """参数提取节点：LLM 提取结构化字段"""
        text = render_template(config.get("input", ""), self.variables) or str(self.variables.get("input", ""))
        fields = config.get("fields", [])
        field_str = "\n".join(f"- {f['name']} ({f.get('type', 'string')}): {f.get('description', '')}" for f in fields)
        prompt = config.get("prompt", "") or (
            f"请从以下内容中提取信息，只返回 JSON 对象，不要包含其他文字。\n\n需要提取的字段：\n{field_str}\n\n内容：\n{text}")
        model = config.get("model", "")
        result = self._call_llm(prompt, model=model).strip()
        # 尝试解析 JSON
        try:
            json_start = result.find("{")
            json_end = result.rfind("}")
            if json_start >= 0 and json_end > json_start:
                data = json.loads(result[json_start:json_end + 1])
            else:
                data = {"result": result}
        except Exception:
            data = {"result": result}
        for f in fields:
            name = f.get("name", "")
            if name and name in data:
                self.variables[name] = data[name]
            elif name:
                self.variables[name] = data.get("result", "")
        self.variables[node["id"] + "_data"] = data
        output = json.dumps(data, ensure_ascii=False)
        self._store_output(node["id"], output)
        return output

    def _execute_tool(self, node, config):
        tool_name = config.get("tool_name", "")
        arguments = config.get("arguments", {})

        rendered_args = {}
        for k, v in arguments.items():
            if isinstance(v, str):
                rendered_args[k] = render_template(v, self.variables)
            else:
                rendered_args[k] = v

        from backend import agent
        result = agent.execute_tool(tool_name, rendered_args)
        output = result.get("output", "")
        self._store_output(node["id"], output)
        return output

    def _execute_connector(self, node, config):
        """数据连接器节点：查询已配置的数据源"""
        cid = config.get("connector_id", "")
        query = render_template(config.get("query", ""), self.variables) or "SELECT 1"
        if not cid:
            raise RuntimeError("未选择数据连接器")
        req_start = time.time()
        ok, result = connector_mod.query_connector(cid, query, limit=int(config.get("limit", 50) or 50))
        req_duration = int((time.time() - req_start) * 1000)
        if not ok:
            self.node_requests[node["id"]] = {
                "request": {"connector_id": cid, "query": query[:2000]},
                "response": {"error": result},
                "duration_ms": req_duration,
                "type": "connector",
            }
            raise RuntimeError(f"连接器查询失败: {result}")
        output = result
        self.node_requests[node["id"]] = {
            "request": {"connector_id": cid, "query": query[:2000]},
            "response": {"text": output[:2000]},
            "duration_ms": req_duration,
            "type": "connector",
        }
        # 尝试解析为结构化列表
        try:
            if config.get("parse_json"):
                lines = output.splitlines()
                parsed = [json.loads(l) for l in lines if l.startswith("{")]
                self.variables[node["id"] + "_rows"] = parsed
        except Exception:
            pass
        self._store_output(node["id"], output)
        return output

    def _execute_condition(self, node, config):
        variable_name = config.get("variable", "")
        conditions = config.get("conditions", [])
        value = self.variables.get(variable_name, self.variables.get("input", ""))
        target = self._route(conditions, value)
        if target:
            return self._execute_node(target)
        next_node = self._get_next_node(node["id"])
        if next_node:
            return self._execute_node(next_node)
        return None

    def _route(self, conditions, value):
        """按条件列表路由到目标节点（百炼风格）"""
        for cond in conditions:
            op = cond.get("operator", "default")
            cond_value = cond.get("value", "")
            target = cond.get("target", "")
            op_func = OPERATORS.get(op)
            if not op_func:
                continue
            try:
                if op_func(value, cond_value):
                    return target
            except Exception:
                continue
        return None

    def _execute_variable(self, node, config):
        action = config.get("action", "set")
        var_name = config.get("variable", "")
        value_template = config.get("value", "")
        value = render_template(value_template, self.variables)

        if action == "set":
            self.variables[var_name] = value
        elif action == "append":
            current = self.variables.get(var_name, "")
            self.variables[var_name] = str(current) + str(value)
        elif action == "increment":
            current = float(self.variables.get(var_name, 0) or 0)
            self.variables[var_name] = current + float(value or 0)
        elif action == "list_push":
            lst = self.variables.get(var_name, [])
            if not isinstance(lst, list):
                lst = [lst] if lst else []
            lst.append(value)
            self.variables[var_name] = lst
        elif action == "delete":
            self.variables.pop(var_name, None)

        return self.variables.get(var_name)

    def _execute_code(self, node, config):
        code = config.get("code", "")
        language = config.get("language", "python")
        req_start = time.time()

        if language == "python":
            local_vars = {"variables": self.variables, "json": json, "math": __import__("math")}
            try:
                exec(code, {"__builtins__": {}}, local_vars)
                self.variables = local_vars.get("variables", self.variables)
            except Exception as e:
                req_duration = int((time.time() - req_start) * 1000)
                self.node_requests[node["id"]] = {
                    "request": {"language": language, "code": code[:2000]},
                    "response": {"error": str(e)},
                    "duration_ms": req_duration,
                    "type": "code",
                }
                raise RuntimeError(f"代码执行错误: {e}")

        req_duration = int((time.time() - req_start) * 1000)
        output_var = node["id"] + "_output"
        output = self.variables.get(output_var, "")
        self.node_requests[node["id"]] = {
            "request": {"language": language, "code": code[:2000]},
            "response": {"text": str(output)[:2000]},
            "duration_ms": req_duration,
            "type": "code",
        }
        return output

    def _execute_http(self, node, config):
        url = render_template(config.get("url", ""), self.variables)
        method = config.get("method", "GET")
        headers = config.get("headers", {})
        body = render_template(config.get("body", ""), self.variables) if config.get("body") else None

        req_start = time.time()
        import httpx
        try:
            req_body = {"url": url, "method": method, "headers": headers, "body": (body or "")[:2000]}
            if method.upper() == "GET":
                resp = httpx.get(url, headers=headers, timeout=30)
            elif method.upper() == "POST":
                resp = httpx.post(url, headers=headers, content=body, timeout=30)
            elif method.upper() == "PUT":
                resp = httpx.put(url, headers=headers, content=body, timeout=30)
            elif method.upper() == "DELETE":
                resp = httpx.delete(url, headers=headers, timeout=30)
            else:
                raise RuntimeError(f"不支持的HTTP方法: {method}")
            output = resp.text
            req_duration = int((time.time() - req_start) * 1000)
            self.node_requests[node["id"]] = {
                "request": req_body,
                "response": {"status": resp.status_code, "headers": dict(resp.headers), "body": resp.text[:2000]},
                "duration_ms": req_duration,
                "type": "http",
            }
            self.variables[node["id"] + "_status"] = resp.status_code
            self._store_output(node["id"], output)
            return output
        except Exception as e:
            req_duration = int((time.time() - req_start) * 1000)
            self.node_requests[node["id"]] = {
                "request": {"url": url, "method": method},
                "response": {"error": str(e)},
                "duration_ms": req_duration,
                "type": "http",
            }
            raise RuntimeError(f"HTTP请求失败: {e}")

    def _execute_text_process(self, node, config):
        """文本处理节点"""
        op = config.get("op", "upper")
        text = render_template(config.get("input", ""), self.variables) or str(self.variables.get("input", ""))
        output = text

        if op == "upper":
            output = text.upper()
        elif op == "lower":
            output = text.lower()
        elif op == "capitalize":
            output = text.strip().capitalize()
        elif op == "trim":
            output = text.strip()
        elif op == "strip_newlines":
            output = re.sub(r'\s*\n\s*', '', text)
        elif op == "replace":
            old = config.get("old", "")
            new = config.get("new", "")
            output = text.replace(old, new)
        elif op == "extract_regex":
            pattern = config.get("pattern", "")
            try:
                m = re.search(pattern, text)
                output = m.group(1) if m and m.groups() else (m.group(0) if m else "")
            except re.error as e:
                raise RuntimeError(f"正则错误: {e}")
        elif op == "truncate":
            n = int(config.get("length", 100) or 100)
            output = text[:n]
        elif op == "length":
            output = str(len(text))
        elif op == "join":
            sep = config.get("separator", "\n")
            var_list = config.get("variable", "")
            val = self.variables.get(var_list, [])
            if isinstance(val, list):
                output = sep.join(str(x) for x in val)
            else:
                output = str(val)
        elif op == "dedupe_lines":
            seen = set()
            lines = []
            for line in text.splitlines():
                if line not in seen:
                    seen.add(line)
                    lines.append(line)
            output = "\n".join(lines)

        self._store_output(node["id"], output)
        return output

    def _execute_aggregator(self, node, config):
        """变量聚合节点：将多个变量合并为列表或字符串"""
        vars_list = config.get("variables", [])
        mode = config.get("mode", "list")
        items = []
        for v in vars_list:
            val = self.variables.get(v, "")
            items.append(val)

        if mode == "list":
            output = items
        elif mode == "text":
            sep = config.get("separator", "\n")
            output = sep.join(str(x) for x in items if x != "")
        elif mode == "json":
            output = json.dumps({v: self.variables.get(v, "") for v in vars_list}, ensure_ascii=False)
        else:
            output = items

        self.variables[node["id"] + "_aggregated"] = output
        self._store_output(node["id"], output)
        return output

    def _execute_template(self, node, config):
        template = config.get("template", "")
        output_var = config.get("output_variable", node["id"] + "_output")
        output = render_template(template, self.variables)
        self.variables[output_var] = output
        return output

    def _get_next_node(self, node_id):
        """获取下一个节点（支持带分支条件的边）"""
        candidates = [e for e in self.edges if e.get("source") == node_id]
        if not candidates:
            return None
        # 优先无 sourceHandle 的边（默认路径）
        for e in candidates:
            if not e.get("sourceHandle"):
                return e.get("target")
        # 否则取第一条
        return candidates[0].get("target")


def execute_workflow(workflow_id, input_data=None):
    """执行工作流"""
    workflow = db.get_workflow(workflow_id)
    if not workflow:
        return {"success": False, "error": "工作流不存在"}

    if not workflow.get("enabled", True):
        return {"success": False, "error": "工作流已禁用"}

    execution_id = str(int(time.time() * 1000))
    execution = {
        "id": execution_id,
        "workflow_id": workflow_id,
        "input": input_data or {},
        "status": "running",
        "started_at": time.time(),
    }
    db.save_workflow_execution(execution)

    engine = WorkflowEngine(workflow)
    result = engine.execute(input_data)

    execution.update({
        "output": result.get("output", ""),
        "status": "completed" if result.get("success") else "failed",
        "nodes_status": engine.nodes_status,
        "error": result.get("error", ""),
        "completed_at": time.time(),
        "duration_ms": int((time.time() - execution["started_at"]) * 1000),
        "tokens_used": engine.tokens_used,
        "node_requests": getattr(engine, "node_requests", {}),
    })

    db.save_workflow_execution(execution)

    return {
        "execution_id": execution_id,
        "success": result.get("success", False),
        "output": result.get("output", ""),
        "error": result.get("error", ""),
        "duration_ms": execution["duration_ms"],
        "tokens_used": engine.tokens_used,
        "node_requests": getattr(engine, "node_requests", {}),
    }


def get_workflow_status(execution_id):
    """获取工作流执行状态"""
    executions = db.list_workflow_executions()
    for e in executions:
        if e["id"] == execution_id:
            return e
    return None


def list_workflows_summary():
    """获取工作流列表摘要"""
    workflows = db.list_workflows()
    result = []
    for wf in workflows:
        executions = db.list_workflow_executions(wf["id"], limit=1)
        last_exec = executions[0] if executions else None
        result.append({
            "id": wf["id"],
            "name": wf["name"],
            "description": wf.get("description", ""),
            "enabled": wf.get("enabled", True),
            "node_count": len(wf.get("nodes", [])),
            "tags": wf.get("tags", []),
            "last_execution": last_exec,
            "created_at": wf.get("created_at"),
            "updated_at": wf.get("updated_at"),
        })
    return result


def execute_workflow_stream(workflow_id, input_data=None):
    """流式执行工作流（SSE事件生成器）"""
    import json as _json
    import time as _time

    workflow = db.get_workflow(workflow_id)
    if not workflow:
        yield f"data: {_json.dumps({'error': '工作流不存在'}, ensure_ascii=False)}\n\n"
        return

    if not workflow.get("enabled", True):
        yield f"data: {_json.dumps({'error': '工作流已禁用'}, ensure_ascii=False)}\n\n"
        return

    execution_id = str(int(_time.time() * 1000))
    execution = {
        "id": execution_id,
        "workflow_id": workflow_id,
        "input": input_data or {},
        "status": "running",
        "started_at": _time.time(),
    }
    db.save_workflow_execution(execution)

    engine = WorkflowEngine(workflow)

    # 设置流式事件回调
    events_queue = []

    def on_event(evt_type, data):
        events_queue.append({"type": evt_type, "data": data})

    engine.set_event_callback(on_event)

    start_time = _time.time()
    try:
        # 异步执行引擎（在单独线程中）
        import threading
        result_holder = [None]
        error_holder = [None]

        def run_engine():
            try:
                result_holder[0] = engine.execute(input_data)
            except Exception as e:
                error_holder[0] = e

        t = threading.Thread(target=run_engine, daemon=True)
        t.start()

        # 轮询事件并发送
        while t.is_alive():
            while events_queue:
                evt = events_queue.pop(0)
                yield f"data: {_json.dumps(evt, ensure_ascii=False)}\n\n"
            _time.sleep(0.05)

        # 排空剩余事件
        while events_queue:
            evt = events_queue.pop(0)
            yield f"data: {_json.dumps(evt, ensure_ascii=False)}\n\n"

        if error_holder[0]:
            raise error_holder[0]

        result = result_holder[0] or {"success": False, "error": "未知错误"}

        # 保存执行记录
        duration_ms = int((_time.time() - start_time) * 1000)
        execution.update({
            "output": result.get("output", ""),
            "status": "completed" if result.get("success") else "failed",
            "nodes_status": engine.nodes_status,
            "error": result.get("error", ""),
            "completed_at": _time.time(),
            "duration_ms": duration_ms,
            "tokens_used": engine.tokens_used,
        })
        db.save_workflow_execution(execution)

        yield f"data: {_json.dumps({'done': True, 'duration_ms': duration_ms, 'tokens_used': engine.tokens_used, 'output': result.get('output', ''), 'node_results': engine.nodes_status}, ensure_ascii=False)}\n\n"

    except Exception as e:
        duration_ms = int((_time.time() - start_time) * 1000)
        execution.update({
            "output": "",
            "status": "failed",
            "nodes_status": engine.nodes_status,
            "error": str(e),
            "completed_at": _time.time(),
            "duration_ms": duration_ms,
            "tokens_used": engine.tokens_used,
        })
        db.save_workflow_execution(execution)
        yield f"data: {_json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"
