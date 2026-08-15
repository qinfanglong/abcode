"""ABcode 蜂群多Agent引擎 — 基于 agno（Python 3.9 兼容的最快主流轻量 agent 框架）

核心思想：Manager 拆解任务 → N 个 Worker 按依赖并行执行（蜂群）→ Merger 汇总。
单 worker 内部由 agno 直接驱动 OpenAI 兼容协议（Ollama/百炼），无多余编排层，延迟低。

模式：
- manager   : 经理拆解 + 依赖拓扑并行执行 + 汇总（默认，蜂群）
- parallel  : 全部 agent 并行处理同一任务 + 汇总
- pipeline  : 链式顺序执行（前序输出作为后序输入）
- debate    : 多 agent 独立作答 + 批判性综合

事件流（与 agent_runtime 兼容，前端可直接复用）：
  swarm_start -> manager_plan? -> (worker_start/worker_done)* -> delta* -> done
"""
import json
import time
import uuid
import re
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Any, Optional, Generator, Callable

logger = logging.getLogger("abcode.swarm")

# agno 必须在主线程导入（Python 3.9 下 agno 模块级 asyncio.Lock() 需要事件循环，
# 若在 FastAPI 工作线程首次导入会 RuntimeError）。main.py 已顶层 import swarm。
from agno.agent import Agent  # noqa: E402
from agno.models.openai import OpenAIChat  # noqa: E402


def _agno():
    return {"Agent": Agent, "OpenAIChat": OpenAIChat}


def _extract_json(text: str):
    """从模型输出中提取 JSON（容忍 markdown 代码块与前后说明文字）"""
    if not text or not text.strip():
        return None
    s = text.strip()
    try:
        return json.loads(s)
    except Exception:
        pass
    m = re.search(r"```(?:json)?\s*(.*?)```", s, re.S)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except Exception:
            pass
    for start, end in (("{", "}"), ("[", "]")):
        i, j = s.find(start), s.rfind(end)
        if i != -1 and j > i:
            try:
                return json.loads(s[i:j + 1])
            except Exception:
                pass
    return None


# ---------------------------------------------------------------------------
# 工具包装：OpenAI tools JSON -> agno python 函数
# ---------------------------------------------------------------------------
_TYPE_ANN = {"string": "str", "integer": "int", "number": "float",
             "boolean": "bool", "object": "dict", "array": "list"}

_TIME_PROMPT = None


def _time_prompt() -> str:
    """注入当前时间（模型常编造年份/时间，必须显式提供）"""
    global _TIME_PROMPT
    if _TIME_PROMPT is None:
        try:
            from time_utils import get_current_time_str, TIME_PROMPT_TPL
            _TIME_PROMPT = TIME_PROMPT_TPL.format(time=get_current_time_str())
        except Exception:
            _TIME_PROMPT = ""
    return _TIME_PROMPT


def _make_tool_fn(tool_def: dict, executor: Callable[[str, dict], tuple]):
    """把 OpenAI 格式工具定义包装成 agno 可识别的 python 函数（带签名+docstring）"""
    fn = tool_def.get("function", {})
    name = fn.get("name", "")
    desc = fn.get("description", "")
    params = fn.get("parameters", {}) or {}
    props = params.get("properties", {}) or {}
    required = params.get("required", []) or []

    arg_defs = []
    doc_args = []
    for pname, pinfo in props.items():
        ann = _TYPE_ANN.get(pinfo.get("type", "string"), "str")
        if pname in required:
            arg_defs.append(f"{pname}: {ann}")
        else:
            arg_defs.append(f"{pname}: {ann} = None")
        doc_args.append(f"        {pname}: {pinfo.get('description', '')}")

    doc = desc
    if doc_args:
        doc += "\n\n    Args:\n" + "\n".join(doc_args)
    doc += "\n\n    返回 JSON 字符串。"

    def _exec_wrap(kw: dict) -> str:
        try:
            ok, result = executor(name, kw)
            if ok:
                return result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
            return json.dumps({"error": str(result)}, ensure_ascii=False)
        except Exception as e:
            logger.exception("swarm tool %s failed", name)
            return json.dumps({"error": f"{type(e).__name__}: {e}"}, ensure_ascii=False)

    ns = {"_exec_wrap": _exec_wrap, "str": str, "int": int, "float": float,
          "bool": bool, "dict": dict, "list": list}
    code = f"def {name}({', '.join(arg_defs)}) -> str:\n    \"\"\"{doc}\"\"\"\n    kw = {{"
    for pname in props:
        code += f"'{pname}': {pname}, "
    code = code.rstrip(", ") + "}\n    return _exec_wrap(kw)\n"
    try:
        exec(code, ns)
        return ns[name]
    except Exception as e:
        logger.warning("tool %s 包装失败: %s", name, e)
        return None


# ---------------------------------------------------------------------------
# 蜂群执行器
# ---------------------------------------------------------------------------
class SwarmRunner:
    """蜂群多 Agent 执行器"""

    def __init__(self, provider: dict, agent_configs: List[Any],
                 mode: str = "manager", max_workers: int = 4,
                 manager_id: str = "", merger_id: str = "", model: str = ""):
        """
        provider     : db.list_providers() 中的一条（base_url/api_key/default_model）
        agent_configs: AgentConfig 列表（来自 agent_runtime）
        mode         : manager / parallel / pipeline / debate
        max_workers  : 蜂群并行 worker 数
        manager_id   : 指定拆解 agent（默认取第一个）
        merger_id    : 指定汇总 agent（默认取最后一个，manager 模式下可禁用传 "__none__"）
        model        : 可选，覆盖蜂群使用的模型名（不覆盖则用 provider 默认）
        """
        self.provider = provider
        self.agents = {c.id: c for c in agent_configs}
        self.agent_list = agent_configs
        self.mode = mode
        self.max_workers = max_workers
        self.manager_id = manager_id or (agent_configs[0].id if agent_configs else "")
        self.merger_id = merger_id or (agent_configs[-1].id if agent_configs else "")
        self.model_override = model
        self.total_tokens = 0

    # ---------- 模型与 Agent ----------
    def _base_url(self) -> str:
        base = (self.provider.get("base_url") or "").rstrip("/")
        low = base.lower()
        if "ollama" in low or ":11434" in low:
            return base + "/v1"
        return base

    def _model(self, model_name: str = "", max_tokens: int = 0, temperature: float = 0.7):
        m = model_name or self.model_override or self.provider.get("default_model") or ""
        if not m:
            models = self.provider.get("models") or []
            m = models[0] if models else ""
        AgentCls, OpenAIChat = _agno()["Agent"], _agno()["OpenAIChat"]  # noqa
        kw = dict(
            id=m,
            base_url=self._base_url(),
            api_key=self.provider.get("api_key") or "ollama",
            timeout=180,
        )
        if max_tokens:
            kw["max_tokens"] = max_tokens
        if temperature is not None:
            kw["temperature"] = temperature
        return OpenAIChat(**kw)

    def _build_agno_agent(self, cfg, with_tools: bool = True) -> Any:
        """AgentConfig -> agno Agent"""
        AgentCls, _ = _agno()["Agent"], _agno()["OpenAIChat"]  # noqa
        tools = []
        if with_tools:
            from agent_runtime import ToolRegistry
            reg = ToolRegistry(cfg)
            tool_defs = reg.build()
            for td in tool_defs:
                fn = _make_tool_fn(td, reg.execute)
                if fn:
                    tools.append(fn)
        return AgentCls(
            name=cfg.name or cfg.id,
            model=self._model(cfg.model_preference, cfg.max_tokens_per_round or 0, cfg.temperature),
            system_message=cfg.system_prompt or "你是 ABcode 蜂群 Worker。使用工具完成任务，给出简洁结论。",
            tools=tools or None,
            tool_call_limit=cfg.max_rounds or 10,
            markdown=True,
        )

    # ---------- 任务拆解 ----------
    def _manager_plan(self, task: str, context: dict) -> List[dict]:
        """经理拆解 -> subtasks: [{id, description, agent, depends_on}]"""
        cfg = self.agents.get(self.manager_id) or self.agent_list[0]
        mgr = self._build_agno_agent(cfg, with_tools=False)
        names = {a.id: f"{a.name}({a.description or '通用'})" for a in self.agent_list}
        prompt = (
            f"你是蜂群经理。将任务拆解为可并行执行的子任务，分配给最合适的成员。\n"
            f"任务：{task}\n"
            f"可用成员：{json.dumps(names, ensure_ascii=False)}\n"
            f"上下文：{json.dumps(context, ensure_ascii=False)[:2000]}\n"
            f"{_time_prompt()}\n\n"
            "只返回 JSON：{\"subtasks\":[{\"id\":\"1\",\"description\":\"...\","
            "\"agent\":\"成员id\",\"depends_on\":[]}]}\n"
            "要求：2-5 个子任务；每个子任务描述独立可执行；depends_on 列出依赖的子任务 id（无依赖为空数组）。"
        )
        resp = mgr.run(prompt)
        content = getattr(resp, "content", "") or ""
        plan = _extract_json(content)
        if not isinstance(plan, dict) or not isinstance(plan.get("subtasks"), list):
            return []
        subtasks = []
        for i, st in enumerate(plan["subtasks"][:8]):
            if not isinstance(st, dict) or not st.get("description"):
                continue
            aid = str(st.get("agent", "") or "")
            if aid not in self.agents:
                aid = self.agent_list[0].id
            subtasks.append({
                "id": str(st.get("id", str(i + 1))),
                "description": str(st["description"]),
                "agent": aid,
                "depends_on": st.get("depends_on", []) or [],
            })
        return subtasks

    # ---------- Worker ----------
    def _worker(self, cfg, prompt: str) -> str:
        worker = self._build_agno_agent(cfg, with_tools=True)
        resp = worker.run(prompt)
        return getattr(resp, "content", "") or ""

    # ---------- 汇总 ----------
    def _merger(self, task: str, results: dict, mode: str) -> Generator[dict, None, None]:
        cfg = self.agents.get(self.merger_id) or self.agent_list[-1]
        merger = self._build_agno_agent(cfg, with_tools=False)
        if mode == "debate":
            prompt = (
                f"你是综合评审。多个成员对同一任务给出了不同视角的答案，请批判性对比、去伪存真，"
                f"给出综合结论并说明关键分歧。\n任务：{task}\n各成员答案：\n"
                f"{json.dumps(results, ensure_ascii=False, indent=2)}"
            )
        else:
            prompt = (
                f"请整合以下子任务结果，组织成对原始任务的完整回答（保留关键细节，去掉重复）。\n"
                f"原始任务：{task}\n{_time_prompt()}\n子任务结果：\n"
                f"{json.dumps(results, ensure_ascii=False, indent=2)}"
            )
        stream = merger.run(prompt, stream=True)
        got = False
        for chunk in stream:
            d = getattr(chunk, "content", "") or ""
            if d:
                got = True
                yield {"type": "delta", "content": d}
        # 兜底：流式为空则返回最终内容
        if not got:
            resp = merger.run(prompt)
            final = getattr(resp, "content", "") or ""
            if final:
                yield {"type": "delta", "content": final}

    # ---------- 主入口 ----------
    def run(self, task: str, context: dict = None) -> Generator[dict, None, None]:
        context = context or {}
        agent_summary = [{"id": a.id, "name": a.name} for a in self.agent_list]
        yield {"type": "swarm_start", "mode": self.mode, "agents": agent_summary}

        if self.mode == "pipeline":
            yield from self._run_pipeline(task, context)
        elif self.mode == "parallel":
            yield from self._run_parallel(task, context)
        elif self.mode == "debate":
            yield from self._run_debate(task, context)
        else:
            yield from self._run_manager(task, context)

    def _run_manager(self, task: str, context: dict) -> Generator[dict, None, None]:
        """蜂群：manager 拆解 + 拓扑并行 + merger 汇总"""
        try:
            subtasks = self._manager_plan(task, context)
        except Exception as e:
            logger.exception("manager plan failed")
            subtasks = []

        if not subtasks:
            # 拆解失败回退：所有 agent 并行处理
            yield {"type": "manager_plan", "subtasks": [],
                   "fallback": "拆解失败，全部成员并行执行"}
            yield from self._run_parallel(task, context)
            return

        yield {"type": "manager_plan", "subtasks": subtasks}

        results: Dict[str, str] = {}
        remaining = list(subtasks)
        wave = 0
        while remaining:
            wave += 1
            ready = [st for st in remaining
                     if all(d in results for d in st.get("depends_on", []))]
            if not ready:
                # 依赖环保护：把剩余全部视为 ready
                ready = remaining
            for st in ready:
                remaining.remove(st)

            def do_one(st):
                cfg = self.agents.get(st["agent"])
                if cfg is None:
                    return st, "（成员不存在）"
                prompt = (
                    f"子任务：{st['description']}\n"
                    f"原始任务：{task}\n"
                    f"{_time_prompt()}\n"
                    f"已完成的相关结果：{json.dumps({k: v[:800] for k, v in results.items()}, ensure_ascii=False)[:2500]}"
                )
                return st, self._worker(cfg, prompt)

            with ThreadPoolExecutor(max_workers=min(self.max_workers, max(len(ready), 1))) as pool:
                futs = [pool.submit(do_one, st) for st in ready]
                for f in as_completed(futs):
                    st, out = f.result()
                    results[st["id"]] = out
                    self.total_tokens += 0
                    yield {"type": "worker_done", "agent_id": st["agent"],
                           "subtask_id": st["id"], "content": out}

        if self.merger_id == "__none__" or len(subtasks) == 1:
            # 单子任务直接作为最终结果，跳过 merger（省一次 LLM 调用）
            merged = "\n\n".join(f"【子任务 {k}】\n{v}" for k, v in results.items())
            yield {"type": "done", "content": merged, "subtask_results": results,
                   "mode": self.mode, "total_tokens": self.total_tokens}
            return

        yield {"type": "merger_start"}
        for evt in self._merger(task, results, "manager"):
            yield evt
        yield {"type": "done", "content": "", "subtask_results": results,
               "mode": self.mode, "total_tokens": self.total_tokens}

    def _run_parallel(self, task: str, context: dict) -> Generator[dict, None, None]:
        """全部成员并行处理同一任务"""
        cfg_list = list(self.agents.values())
        if not cfg_list:
            yield {"type": "done", "content": "没有可用成员", "subtask_results": {}}
            return

        def do_one(cfg):
            prompt = f"{task}\n上下文：{json.dumps(context, ensure_ascii=False)[:1500]}"
            return cfg.id, self._worker(cfg, prompt)

        results: Dict[str, str] = {}
        with ThreadPoolExecutor(max_workers=min(self.max_workers, len(cfg_list))) as pool:
            futs = [pool.submit(do_one, c) for c in cfg_list]
            for f in as_completed(futs):
                aid, out = f.result()
                results[aid] = out
                yield {"type": "worker_done", "agent_id": aid, "content": out}

        if self.merger_id == "__none__":
            merged = "\n\n".join(f"【{aid}】\n{v}" for aid, v in results.items())
            yield {"type": "done", "content": merged, "subtask_results": results,
                   "mode": self.mode, "total_tokens": self.total_tokens}
            return

        yield {"type": "merger_start"}
        for evt in self._merger(task, results, "manager"):
            yield evt
        yield {"type": "done", "content": "", "subtask_results": results,
               "mode": self.mode, "total_tokens": self.total_tokens}

    def _run_debate(self, task: str, context: dict) -> Generator[dict, None, None]:
        """辩论：多 agent 独立作答 + 综合评审"""
        cfg_list = list(self.agents.values())
        if not cfg_list:
            yield {"type": "done", "content": "没有可用成员", "subtask_results": {}}
            return

        def do_one(cfg):
            prompt = f"请从你的专业视角回答以下问题（尽量给出具体结论与依据）：\n{task}"
            return cfg.id, self._worker(cfg, prompt)

        results = {}
        with ThreadPoolExecutor(max_workers=min(self.max_workers, len(cfg_list))) as pool:
            futs = [pool.submit(do_one, c) for c in cfg_list]
            for f in as_completed(futs):
                aid, out = f.result()
                results[aid] = out
                yield {"type": "worker_done", "agent_id": aid, "content": out}

        if self.merger_id == "__none__":
            merged = "\n\n".join(f"【{aid}】\n{v}" for aid, v in results.items())
            yield {"type": "done", "content": merged, "subtask_results": results,
                   "mode": self.mode, "total_tokens": self.total_tokens}
            return

        yield {"type": "merger_start"}
        for evt in self._merger(task, results, "debate"):
            yield evt
        yield {"type": "done", "content": "", "subtask_results": results,
               "mode": self.mode, "total_tokens": self.total_tokens}

    def _run_pipeline(self, task: str, context: dict) -> Generator[dict, None, None]:
        """链式：前序输出作为后序输入"""
        carry = task
        results = {}
        for cfg in self.agent_list:
            yield {"type": "worker_start", "agent_id": cfg.id, "agent_name": cfg.name}
            prompt = f"{carry}\n上下文：{json.dumps(context, ensure_ascii=False)[:1200]}"
            out = self._worker(cfg, prompt)
            results[cfg.id] = out
            carry = f"上一环节输出：\n{out}\n\n请基于以上内容继续：{task}"
            yield {"type": "worker_done", "agent_id": cfg.id, "content": out}

        if self.merger_id != "__none__" and len(self.agent_list) > 1:
            yield {"type": "merger_start"}
            for evt in self._merger(task, results, "manager"):
                yield evt
        yield {"type": "done", "content": carry, "subtask_results": results,
               "mode": self.mode, "total_tokens": self.total_tokens}

    def run_sync(self, task: str, context: dict = None) -> dict:
        """同步执行（非流式），返回 {success, output, subtask_results, mode}"""
        out_parts = []
        results = {}
        for evt in self.run(task, context or {}):
            t = evt["type"]
            if t == "delta":
                out_parts.append(evt["content"])
            elif t == "worker_done":
                results[evt["agent_id"]] = evt["content"]
            elif t == "done":
                if evt.get("content"):
                    out_parts.append(evt["content"])
        return {"success": True, "output": "".join(out_parts),
                "subtask_results": results, "mode": self.mode}
