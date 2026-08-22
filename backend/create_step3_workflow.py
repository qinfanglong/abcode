import db, json

for wf in db.list_workflows():
    if wf.get("name") == "逐步测试3":
        db.delete_workflow(wf["id"])

# 逐步测试3：加入 LLM/分类/提取/工具/连接器
step3 = {
    "id": "step_test3",
    "name": "逐步测试3",
    "description": "逐步测试节点链3",
    "nodes": [
        {"id": "start", "type": "start", "label": "开始", "config": {"input_fields": ["name"]}},
        {"id": "text_process", "type": "text_process", "label": "文本处理", "config": {"op": "upper", "input": "{{name}}", "output_variable": "text_out"}},
        {"id": "llm", "type": "llm", "label": "LLM", "config": {"prompt": "一句话总结：{{name}}", "model": "qwen3.5:2b", "model_source": "local", "output_variable": "llm_out"}},
        {"id": "classifier", "type": "classifier", "label": "分类", "config": {"input": "{{llm_out}}", "categories": ["A", "B"], "model": "qwen3.5:2b", "model_source": "local", "output_variable": "cls_out"}},
        {"id": "extractor", "type": "extractor", "label": "提取", "config": {"input": "{{llm_out}}", "fields": [{"name": "x", "type": "string", "description": "x"}], "model": "qwen3.5:2b", "model_source": "local", "output_variable": "ext_out"}},
        {"id": "tool", "type": "tool", "label": "工具", "config": {"tool_name": "get_current_time", "arguments": {}, "output_variable": "tool_out"}},
        {"id": "connector", "type": "connector", "label": "连接器", "config": {"connector_id": "conn_demo", "query": "SELECT * FROM orders LIMIT 1", "output_variable": "conn_out"}},
        {"id": "end", "type": "end", "label": "结束", "config": {"output_field": "conn_out"}},
    ],
    "edges": [
        {"id": "e1", "source": "start", "target": "text_process"},
        {"id": "e2", "source": "text_process", "target": "llm"},
        {"id": "e3", "source": "llm", "target": "classifier"},
        {"id": "e4", "source": "classifier", "target": "extractor"},
        {"id": "e5", "source": "extractor", "target": "tool"},
        {"id": "e6", "source": "tool", "target": "connector"},
        {"id": "e7", "source": "connector", "target": "end"},
    ],
    "tags": ["测试"],
    "enabled": True,
    "created_at": 1785900000,
}
print('创建逐步工作流3:', db.save_workflow(step3))
