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

    def _execute_node(self, node_id, _in_loop=False, _prev_output=None):
        """执行单个节点"""
        if self._stopped and not _in_loop:
            return self._final_output

        node = self.nodes.get(node_id)
        if not node:
            raise RuntimeError(f"节点不存在: {node_id}")

        node_type = node.get("type", "")
        config = node.get("config", {})
        loop_boundary = False

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
                if _in_loop and output == "" and _prev_output is not None:
                    # 循环体内 end 作为边界：若 output_field 未设置，取上一个节点的输出
                    output = _prev_output
            elif node_type == "stop":
                if _in_loop:
                    # 循环体内 stop：作为本次迭代边界，不终止主流程
                    output_field = config.get("output_field", "output")
                    output = self.variables.get(output_field, _prev_output if _prev_output is not None else "")
                    loop_boundary = True
                else:
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
            elif node_type == "loop":
                output = self._execute_loop(node, config)
            elif node_type == "iteration":
                output = self._execute_iteration(node, config)
            elif node_type == "kb_index":
                output = self._execute_kb_index(node, config)
            elif node_type == "memory_read":
                output = self._execute_memory_read(node, config)
            elif node_type == "memory_write":
                output = self._execute_memory_write(node, config)
            elif node_type == "memory_clear":
                output = self._execute_memory_clear(node, config)
            elif node_type == "mcp_call":
                output = self._execute_mcp_call(node, config)
            elif node_type == "json_parse":
                output = self._execute_json_parse(node, config)
            elif node_type == "email":
                output = self._execute_email(node, config)
            elif node_type == "webhook":
                output = self._execute_webhook(node, config)
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
                "duration_ms": duration_ms,
                "output": str(output)[:500] if output else ""
            })

            if self._stopped:
                return self._final_output

            # 循环体内 stop/end 边界：本次迭代到此为止，不再向后传播
            if loop_boundary:
                return output

            # 条件/分类/循环节点内部自行路由或已执行完子链
            if node_type in ("condition", "classifier", "loop"):
                return output

            next_node = self._get_next_node(node_id)
            if next_node:
                return self._execute_node(next_node, _in_loop=_in_loop, _prev_output=output)

            return output

        except Exception as e:
            # 仅当本节点仍处于 running 时才标记 failed（避免下游失败污染祖先状态）
            cur = self.nodes_status.get(node_id, {})
            if cur.get("status") == "running":
                duration_ms = int((time.time() - cur["started_at"]) * 1000)
                self.nodes_status[node_id] = {
                    "status": "failed",
                    "started_at": cur["started_at"],
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

    def _store_output(self, node_id, output, output_var=None):
        """把节点输出存到变量，支持指定变量名"""
        out_name = (output_var or "").strip() or (node_id + "_output")
        self.variables[out_name] = output
        if out_name != node_id + "_output":
            self.variables[node_id + "_output"] = output  # 兼容旧引用
        return out_name

    # ================= 节点执行 =================

    def _execute_start(self, node, config):
        """开始节点：收集入参。

        支持结构化参数定义：
          input_variables: [{ name, type(string/text/number/integer/float/boolean/select/multi_select/date/datetime/time/file/password/email/url/object/array),
                              default, required, options[] }]
        向后兼容 legacy 的 input_fields（逗号分隔字符串列表），统一作为 string 处理。
        """
        out = {}

        # 结构化参数（优先）
        for f in config.get("input_variables") or []:
            name = (f.get("name") or "").strip()
            if not name:
                continue
            ftype = f.get("type", "string") or "string"
            required = bool(f.get("required", False))
            default = f.get("default", "")
            options = f.get("options") or []

            value = self.variables.get(name)
            if value is None or value == "":
                value = default
            if value is None or value == "":
                if required:
                    raise RuntimeError(f"开始节点缺少必填参数: {name}")
                value = ""

            value = self._cast_input(value, ftype, options)
            out[name] = value

        # 向后兼容 legacy input_fields
        for f in (config.get("input_fields") or []):
            if f in out:
                continue
            out[f] = self.variables.get(f, self.variables.get("input", ""))

        # 若未定义任何字段，透传整个 input
        if not out:
            out["input"] = self.variables.get("input", "")
        return out

    @staticmethod
    def _cast_input(value, ftype, options=None):
        """根据类型对输入做强制/校验。支持：string/text/number/integer/float/boolean/select/multi_select/date/datetime/time/file/password/email/url/object/array"""
        options = options or []
        if value is None or value == "":
            return value
        # 已是对象/数组原样保留（如 object/array 类型）
        if isinstance(value, (dict, list)):
            if ftype == "object" and isinstance(value, dict):
                return value
            if ftype == "array" and isinstance(value, list):
                return value
            return value
        try:
            if ftype == "number":
                s = str(value).strip()
                if "." in s or "e" in s.lower():
                    return float(s)
                return int(s)
            elif ftype == "integer":
                return int(str(value).strip())
            elif ftype == "float":
                return float(str(value).strip())
            elif ftype == "boolean":
                if isinstance(value, str):
                    return value.lower() in ("true", "1", "yes", "on", "是")
                return bool(value)
            elif ftype == "select" and options:
                if str(value) not in [str(o) for o in options]:
                    return options[0]
                return value
            elif ftype == "multi_select":
                if isinstance(value, list):
                    return [str(v) for v in value]
                return [v.strip() for v in str(value).split(",") if v.strip()]
            elif ftype in ("date", "datetime", "time", "file",
                          "password", "email", "url", "text", "string"):
                return str(value)
            elif ftype == "object":
                import json as _json
                return _json.loads(str(value))
            elif ftype == "array":
                import json as _json
                return _json.loads(str(value))
        except Exception:
            return value
        return value

    def _execute_end(self, node, config):
        output_field = config.get("output_field", "output")
        if output_field in self.variables:
            return self.variables.get(output_field, "")
        # 兜底：output_field 变量不存在时，回退到「最后完成节点」的输出，避免空输出
        last_id, last_t = None, -1
        for nid, st in self.nodes_status.items():
            t = st.get("completed_at") or st.get("started_at") or 0
            if st.get("status") == "completed" and t >= last_t:
                last_t, last_id = t, nid
        if last_id:
            for cand in (last_id + "_output", last_id + "_results"):
                v = self.variables.get(cand, "")
                if v != "" and v is not None:
                    return v
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

    def _execute_loop(self, node, config):
        """循环节点：遍历数组，对每项设置 item/index 变量，执行循环体（下游链），收集结果"""
        array_expr = config.get("array_variable", "{{input}}")
        item_var = config.get("item_variable", "item") or "item"
        index_var = config.get("index_variable", "index") or "index"
        max_iter = int(config.get("max_iterations", 100) or 100)
        max_iter = max(1, min(max_iter, 1000))

        # 解析数组：支持 {{变量}} 模板或直接变量名
        raw = render_template(array_expr, self.variables)
        if isinstance(raw, str) and "{{" not in array_expr:
            raw = self.variables.get(array_expr.strip("{}").strip(), raw)
        if isinstance(raw, str):
            try:
                raw = json.loads(raw) if raw.strip().startswith("[") else raw.split(",")
            except Exception:
                raw = raw.split(",") if raw else []
        if not isinstance(raw, list):
            raw = [raw] if raw else []

        # 找到循环体起点（loop 的下游节点，跳过 start）
        body_start = self._get_next_node(node["id"])

        results = []
        loop_guard = getattr(self, "_loop_guard", 0) + 1
        if loop_guard > 50:
            raise RuntimeError("循环嵌套过深（>50），疑似死循环")
        self._loop_guard = loop_guard
        try:
            for idx, item in enumerate(raw[:max_iter]):
                self.variables[item_var] = item
                self.variables[index_var] = idx
                # 循环体内遇到 end/stop 作为边界：不终止主流程，取当时输出
                if body_start:
                    try:
                        out = self._execute_node(body_start, _in_loop=True, _prev_output=item)
                    except Exception:
                        raise
                else:
                    out = item
                results.append(out)
        finally:
            self._loop_guard = loop_guard - 1

        # 输出：结果数组 + 各变量
        self.variables[node["id"] + "_results"] = results
        self.variables[node["id"] + "_output"] = results
        self._store_output(node["id"], results)
        return results

    def _execute_iteration(self, node, config):
        """遍历节点：遍历数组，对每项执行下游链，收集结果（无次数限制版循环）"""
        array_expr = config.get("array_variable", "{{input}}")
        item_var = config.get("item_variable", "item") or "item"

        raw = render_template(array_expr, self.variables)
        if isinstance(raw, str) and "{{" not in array_expr:
            raw = self.variables.get(array_expr.strip("{}").strip(), raw)
        if isinstance(raw, str):
            try:
                raw = json.loads(raw) if raw.strip().startswith("[") else raw.split(",")
            except Exception:
                raw = raw.split(",") if raw else []
        if not isinstance(raw, list):
            raw = [raw] if raw else []

        body_start = self._get_next_node(node["id"])
        results = []
        loop_guard = getattr(self, "_loop_guard", 0) + 1
        if loop_guard > 50:
            raise RuntimeError("循环嵌套过深（>50），疑似死循环")
        self._loop_guard = loop_guard
        try:
            for idx, item in enumerate(raw):
                self.variables[item_var] = item
                self.variables["index"] = idx
                if body_start:
                    out = self._execute_node(body_start, _in_loop=True, _prev_output=item)
                else:
                    out = item
                results.append(out)
        finally:
            self._loop_guard = loop_guard - 1

        self.variables[node["id"] + "_results"] = results
        self.variables[node["id"] + "_output"] = results
        self._store_output(node["id"], results)
        return results

    def _execute_kb_index(self, node, config):
        """知识入库节点：把文本内容写入知识库"""
        kb_id = config.get("kb_id") or "default"
        mode = config.get("mode", "append")
        content = render_template(config.get("content", ""), self.variables) or str(self.variables.get("input", ""))
        title = render_template(config.get("title", ""), self.variables) or f"workflow_{node['id']}"

        if not content or not content.strip():
            raise RuntimeError("知识入库内容为空")

        # 确保知识库存在
        from rag import create_kb, list_kbs
        kbs = list_kbs()
        if kb_id not in [k["id"] for k in kbs]:
            create_kb(kb_id)

        filename = f"{title}.md"
        try:
            from rag import add_document
            doc_id, chunk_count, is_dup = add_document(filename, content.encode("utf-8"), kb_id=kb_id)
        except Exception as e:
            raise RuntimeError(f"知识入库失败: {e}")

        result = {
            "doc_id": doc_id, "chunks": chunk_count, "duplicate": is_dup, "kb_id": kb_id,
        }
        output = json.dumps(result, ensure_ascii=False)
        self.variables[node["id"] + "_doc_id"] = doc_id
        self._store_output(node["id"], output)
        return output

    def _execute_memory_read(self, node, config):
        """记忆读取节点：读取工作流记忆"""
        memory_key = render_template(config.get("memory_key", ""), self.variables) or str(self.variables.get("input", ""))
        namespace = config.get("namespace", "default")
        mem = self._memory_get(namespace, memory_key)
        self._store_output(node["id"], mem)
        return mem

    def _execute_memory_write(self, node, config):
        """记忆写入节点：保存值到工作流记忆"""
        memory_key = render_template(config.get("memory_key", ""), self.variables)
        content = render_template(config.get("content", ""), self.variables) or str(self.variables.get("input", ""))
        namespace = config.get("namespace", "default")
        if not memory_key:
            raise RuntimeError("记忆写入缺少 key")
        self._memory_set(namespace, memory_key, content)
        self._store_output(node["id"], content)
        return content

    def _execute_memory_clear(self, node, config):
        """记忆清除节点：清空工作流记忆"""
        namespace = config.get("namespace", "default")
        cleared = self._memory_clear(namespace)
        self._store_output(node["id"], str(cleared))
        return str(cleared)

    def _memory_load(self):
        """加载工作流记忆存储（按工作流隔离）"""
        import os
        mem_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "wf_memory")
        os.makedirs(mem_dir, exist_ok=True)
        wf_id = (self.workflow.get("id") or "default").replace("/", "_")
        path = os.path.join(mem_dir, f"{wf_id}.json")
        if not hasattr(self, "_mem_path"):
            self._mem_path = path
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _memory_save(self, data):
        try:
            with open(self._mem_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _memory_get(self, namespace, key):
        data = self._memory_load()
        ns = data.get(namespace, {})
        return ns.get(key, "")

    def _memory_set(self, namespace, key, value):
        data = self._memory_load()
        data.setdefault(namespace, {})[key] = value
        self._memory_save(data)

    def _memory_clear(self, namespace):
        data = self._memory_load()
        if namespace in data:
            del data[namespace]
            self._memory_save(data)
            return len(data)
        return len(data)

    def _execute_mcp_call(self, node, config):
        """MCP 调用节点：调用已配置的 MCP 服务器工具"""
        mcp_server = config.get("mcp_server", "")
        tool_name = config.get("tool_name", "")
        arguments = config.get("arguments", "{}")
        if isinstance(arguments, str):
            arguments = render_template(arguments, self.variables)
            try:
                arguments = json.loads(arguments) if arguments.strip() else {}
            except Exception:
                arguments = {"input": arguments}
        if not mcp_server or not tool_name:
            raise RuntimeError("MCP 调用缺少服务器或工具名")

        from mcp_client import execute_mcp_tool, get_client
        mcp_id = mcp_server
        # 支持传服务器名
        import db
        servers = db.list_mcp()
        for s in servers:
            if s["id"] == mcp_server or s["name"] == mcp_server:
                mcp_id = s["id"]
                break

        ok, result = execute_mcp_tool(mcp_id, tool_name, arguments)
        if not ok:
            raise RuntimeError(f"MCP 调用失败: {result}")
        output = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
        self.variables[node["id"] + "_result"] = result
        self._store_output(node["id"], output)
        return output

    def _execute_json_parse(self, node, config):
        """JSON 解析节点：解析 JSON 文本并输出结构化数据"""
        text = render_template(config.get("input", ""), self.variables) or str(self.variables.get("input", ""))
        try:
            data = json.loads(text)
        except Exception as e:
            raise RuntimeError(f"JSON 解析失败: {e}")
        # 把顶层字段展开到变量
        if isinstance(data, dict):
            for k, v in data.items():
                self.variables[k] = v
        output = json.dumps(data, ensure_ascii=False, indent=2)
        self.variables[node["id"] + "_data"] = data
        self._store_output(node["id"], output)
        return output

    def _execute_email(self, node, config):
        """邮件节点：通过 SMTP 发送邮件（从设置读取配置）"""
        to = render_template(config.get("to", ""), self.variables)
        subject = render_template(config.get("subject", ""), self.variables)
        body = render_template(config.get("body", ""), self.variables)
        if not to:
            raise RuntimeError("邮件缺少收件人")

        import db
        smtp_host = db.get_setting("smtp_host", "")
        smtp_port = int(db.get_setting("smtp_port", "465") or 465)
        smtp_user = db.get_setting("smtp_user", "")
        smtp_pass = db.get_setting("smtp_pass", "")
        from_addr = db.get_setting("smtp_from", smtp_user)

        # 无 SMTP 配置时：根据 dry_run 决定行为
        if not smtp_host or not smtp_user or not smtp_pass:
            if config.get("dry_run", False):
                output = f"[dry_run] 已生成邮件（未发送）：收件人={to}，主题={subject}"
                self._store_output(node["id"], output)
                return output
            raise RuntimeError("未配置 SMTP，请先到设置中配置邮箱")

        import smtplib
        from email.mime.text import MIMEText
        from email.header import Header
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = Header(subject, "utf-8")
        msg["From"] = from_addr
        msg["To"] = to
        try:
            if smtp_port == 465:
                server = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=30)
            else:
                server = smtplib.SMTP(smtp_host, smtp_port, timeout=30)
                server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(from_addr, [x.strip() for x in to.split(",")], msg.as_string())
            server.quit()
        except Exception as e:
            raise RuntimeError(f"邮件发送失败: {e}")

        output = f"已发送至 {to}"
        self._store_output(node["id"], output)
        return output

    def _execute_webhook(self, node, config):
        """Webhook 节点：发送 HTTP 回调"""
        url = render_template(config.get("url", ""), self.variables)
        method = config.get("method", "POST").upper()
        headers = config.get("headers", {})
        body = render_template(config.get("body", ""), self.variables) if config.get("body") else None
        if not url:
            raise RuntimeError("Webhook 缺少 URL")

        import httpx
        try:
            if method == "GET":
                resp = httpx.get(url, headers=headers, timeout=30)
            elif method == "PUT":
                resp = httpx.put(url, headers=headers, content=body, timeout=30)
            else:
                resp = httpx.post(url, headers=headers, content=body, timeout=30)
            output = resp.text
            self.variables[node["id"] + "_status"] = resp.status_code
            self._store_output(node["id"], output)
            return output
        except Exception as e:
            raise RuntimeError(f"Webhook 请求失败: {e}")

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
        self._store_output(node["id"], output, config.get("output_variable"))
        return output

    def _execute_kb_search(self, node, config):
        """知识库检索节点"""
        query = render_template(config.get("query", ""), self.variables) or str(self.variables.get("input", ""))
        top_k = int(config.get("top_k", 5) or 5)
        kb_id = config.get("kb_id") or None
        threshold = float(config.get("threshold", 0) or config.get("score_threshold", 0) or 0)
        req_start = time.time()
        results = rag.search(query, top_k=top_k, kb_id=kb_id, min_score=threshold)
        req_duration = int((time.time() - req_start) * 1000)
        # 输出格式：拼接文本
        lines = []
        for i, r in enumerate(results):
            lines.append(f"[{i+1}] 《{r['doc_name']}》 相关度{r['score']}\n{r['content']}")
        output = "\n\n".join(lines)
        self.node_requests[node["id"]] = {
            "request": {"query": query[:2000], "top_k": top_k, "kb_id": kb_id, "threshold": threshold},
            "response": {"results": [{"doc": r.get("doc_name", ""), "score": r.get("score", 0), "content": r.get("content", "")[:500]} for r in results[:10]]},
            "duration_ms": req_duration,
            "type": "kb_search",
        }
        # 结构化结果变量名：优先用面板配置的 output_variable，否则兼容默认 node_id_results
        out_var = (config.get("output_variable") or "").strip() or (node["id"] + "_results")
        self.variables[out_var] = results
        self.variables[node["id"] + "_results"] = results  # 兼容旧工作流
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

        import agent
        ok, result = agent.execute_tool(tool_name, rendered_args)
        if not ok:
            raise RuntimeError(f"工具调用失败: {result}")
        output = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
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
            # 常用内建白名单（exec 沙箱默认清空 builtins，这里放行常用函数）
            safe_builtins = {
                "str": str, "int": int, "float": float, "bool": bool, "len": len,
                "list": list, "dict": dict, "set": set, "tuple": tuple,
                "abs": abs, "min": min, "max": max, "sum": sum, "round": round,
                "sorted": sorted, "range": range, "enumerate": enumerate, "zip": zip,
                "any": any, "all": all, "isinstance": isinstance, "repr": repr,
                "print": print, "Exception": Exception, "__import__": __import__,
            }
            local_vars = {"variables": self.variables, "params": self.variables,
                          "json": json, "math": __import__("math")}
            try:
                exec(code, {"__builtins__": safe_builtins}, local_vars)
                # variables 是引用，直接改 dict 会生效；result 变量在 exec 局部作用域
                result_val = local_vars.get("result")
                if result_val is not None:
                    self.variables[node["id"] + "_output"] = result_val
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
        # 输出变量名：优先面板配置，否则 result（前端默认），兼容旧版 node_id_output
        out_var = (config.get("output_variable") or "").strip() or "result"
        # result 由 exec 写入 node_id_output；若用户代码直接写了目标变量则优先读它
        if out_var != node["id"] + "_output" and out_var in self.variables:
            output = self.variables[out_var]
        else:
            output = self.variables.get(node["id"] + "_output", "")
        self.node_requests[node["id"]] = {
            "request": {"language": language, "code": code[:2000]},
            "response": {"text": str(output)[:2000]},
            "duration_ms": req_duration,
            "type": "code",
        }
        self._store_output(node["id"], output, config.get("output_variable"))
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

        self._store_output(node["id"], output, config.get("output_variable"))
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
            if not isinstance(sep, str):
                sep = config.get("sep", "\n")
            if not isinstance(sep, str):
                sep = "\n"
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
        """获取下一个节点（支持带分支条件的边）

        优先跳过骨干 end 边（前端 ensureBackboneEdge 会强制保留 start→end / 节点→end 的骨架线），
        取真正的业务后继，避免因 edges 数组顺序把 start 直接导向 end 而跳过中间节点；
        仅当没有其他后继时才走向 end（end 是最终汇聚节点）。
        """
        candidates = [e for e in self.edges if (e.get("source") or e.get("from")) == node_id]
        if not candidates:
            return None
        non_end = [e for e in candidates if (e.get("target") or e.get("to")) != "end"]
        pool = non_end or candidates
        # 优先无 sourceHandle 的边（默认路径）
        for e in pool:
            if not e.get("sourceHandle"):
                return e.get("target") or e.get("to")
        # 否则取第一条
        return (pool[0].get("target") or pool[0].get("to"))


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
