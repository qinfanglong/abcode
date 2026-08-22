import db, json

# 先删除可能存在的旧测试工作流
for wf in db.list_workflows():
    if wf.get("name") == "全节点功能验证":
        db.delete_workflow(wf["id"])

# 创建全节点测试工作流（优化版：使用小模型加快执行）
nodes = [
    # === 1. 开始节点（结构化参数） ===
    {"id": "start", "type": "start", "label": "开始", "config": {
        "input_variables": [
            {"name": "patient_name", "type": "string", "required": True, "default": "张三"},
            {"name": "phone_tail", "type": "string", "required": True, "default": "1234"},
        ]
    }},
    # === 2. LLM 调用（使用本地小模型） ===
    {"id": "llm", "type": "llm", "label": "LLM 解析", "config": {
        "prompt": "格式化输入：姓名={{patient_name}}，尾号={{phone_tail}}，输出一句话总结",
        "model": "qwen3.5:2b",
        "model_source": "local",
        "output_variable": "formatted_input"
    }},
    # === 3. 变量操作 ===
    {"id": "variable", "type": "variable", "label": "设置变量", "config": {
        "action": "set", "variable": "query_condition", "value": "report_found"
    }},
    # === 4. 知识库检索 ===
    {"id": "kb_search", "type": "kb_search", "label": "检索报告", "config": {
        "query": "{{patient_name}} 报告", "top_k": 3, "kb_id": "default",
        "output_variable": "kb_results"
    }},
    # === 5. 文本处理（先去除换行再转大写） ===
    {"id": "text_process", "type": "text_process", "label": "文本处理", "config": {
        "op": "strip_newlines", "input": "{{kb_results}}", "output_variable": "text_out"
    }},
    # === 6. JSON 解析（使用已知安全的 JSON） ===
    {"id": "json_parse", "type": "json_parse", "label": "JSON解析", "config": {
        "input": '{"report": "体检报告", "patient": "{{patient_name}}", "items": [1, 2, 3]}',
        "output_variable": "json_data"
    }},
    # === 7. 代码执行 ===
    {"id": "code", "type": "code", "label": "代码执行", "config": {
        "language": "python",
        "code": "result = {'status': 'ok', 'processed': True}\nvariables['code_output'] = result",
        "output_variable": "code_output"
    }},
    # === 8. 变量聚合 ===
    {"id": "aggregator", "type": "aggregator", "label": "变量聚合", "config": {
        "mode": "json", "variables": ["patient_name", "phone_tail", "code_output"],
        "output_variable": "agg_result"
    }},
    # === 9. 模板生成 ===
    {"id": "template", "type": "template", "label": "模板生成", "config": {
        "template": "患者：{{patient_name}}，尾号：{{phone_tail}}，状态：{{code_output}}",
        "output_variable": "final_template"
    }},
    # === 10. 条件分支（百炼风格） ===
    {"id": "condition", "type": "condition", "label": "条件判断", "config": {
        "variable": "phone_tail",
        "conditions": [{"operator": "neq", "value": "", "target": "classifier"}],
        "output_variable": "cond_result"
    }},
    # === 11. 意图分类 ===
    {"id": "classifier", "type": "classifier", "label": "意图分类", "config": {
        "input": "{{final_template}}",
        "categories": ["查报告", "其他"],
        "conditions": [{"operator": "eq", "value": "查报告", "target": "extractor"}],
        "model": "qwen3.5:2b", "model_source": "local",
        "output_variable": "classifier_result"
    }},
    # === 12. 参数提取 ===
    {"id": "extractor", "type": "extractor", "label": "参数提取", "config": {
        "input": "{{final_template}}",
        "fields": [
            {"name": "extracted_name", "type": "string", "description": "提取患者姓名"},
            {"name": "extracted_tail", "type": "string", "description": "提取手机尾号"}
        ],
        "model": "qwen3.5:2b", "model_source": "local",
        "output_variable": "extracted"
    }},
    # === 13. 工具调用 ===
    {"id": "tool", "type": "tool", "label": "工具调用", "config": {
        "tool_name": "get_current_time", "arguments": {},
        "output_variable": "tool_time"
    }},
    # === 14. 数据连接（SQLite） ===
    {"id": "connector", "type": "connector", "label": "数据查询", "config": {
        "connector_id": "conn_demo",
        "query": "SELECT * FROM orders LIMIT 3",
        "output_variable": "db_rows"
    }},
    # === 15. HTTP 请求 ===
    {"id": "http", "type": "http", "label": "HTTP请求", "config": {
        "method": "GET",
        "url": "https://httpbin.org/get?patient={{patient_name}}",
        "headers": {},
        "output_variable": "http_response"
    }},
    # === 16. 记忆写入 ===
    {"id": "memory_write", "type": "memory_write", "label": "记忆写入", "config": {
        "memory_key": "patient_{{patient_name}}",
        "content": "{{final_template}}",
        "namespace": "test",
        "output_variable": "mem_write_result"
    }},
    # === 17. 记忆读取 ===
    {"id": "memory_read", "type": "memory_read", "label": "记忆读取", "config": {
        "memory_key": "patient_{{patient_name}}",
        "namespace": "test",
        "output_variable": "mem_read_result"
    }},
    # === 18. 知识入库 ===
    {"id": "kb_index", "type": "kb_index", "label": "知识入库", "config": {
        "kb_id": "default", "mode": "append",
        "title": "workflow_test_{{patient_name}}",
        "content": "{{final_template}} - 测试入库",
        "output_variable": "kb_index_result"
    }},
    # === 19. 循环处理 ===
    {"id": "loop", "type": "loop", "label": "循环处理", "config": {
        "array_variable": "{{agg_result.items}}",
        "item_variable": "loop_item",
        "index_variable": "loop_index",
        "max_iterations": 5,
        "output_variable": "loop_result"
    }},
    # === 20. 遍历 ===
    {"id": "iteration", "type": "iteration", "label": "遍历", "config": {
        "array_variable": "{{loop_result}}",
        "item_variable": "iter_item",
        "output_variable": "iter_result"
    }},
    # === 21. MCP 调用 ===
    {"id": "mcp_call", "type": "mcp_call", "label": "MCP调用", "config": {
        "mcp_server": "测试MCP",
        "tool_name": "get_weather",
        "arguments": {"city": "Beijing"},
        "output_variable": "mcp_result"
    }},
    # === 22. Webhook ===
    {"id": "webhook", "type": "webhook", "label": "Webhook", "config": {
        "method": "POST",
        "url": "https://httpbin.org/post",
        "body": '{"name": "{{patient_name}}", "status": "ok"}',
        "headers": {"Content-Type": "application/json"},
        "output_variable": "webhook_result"
    }},
    # === 23. 邮件（需 SMTP 配置） ===
    {"id": "email", "type": "email", "label": "邮件通知", "config": {
        "to": "test@example.com",
        "subject": "测试工作流",
        "body": "{{final_template}}",
        "dry_run": True,
        "output_variable": "email_result"
    }},
    # === 24. 直接回复 ===
    {"id": "stop", "type": "stop", "label": "直接回复", "config": {
        "output_field": "final_template"
    }},
    # === 25. 结束节点 ===
    {"id": "end", "type": "end", "label": "结束", "config": {
        "output_field": "final_template"
    }},
]

# 创建边（线性路径）
edges = [
    {"id": "e1", "source": "start", "target": "llm"},
    {"id": "e2", "source": "llm", "target": "variable"},
    {"id": "e3", "source": "variable", "target": "kb_search"},
    {"id": "e4", "source": "kb_search", "target": "text_process"},
    {"id": "e5", "source": "text_process", "target": "json_parse"},
    {"id": "e6", "source": "json_parse", "target": "code"},
    {"id": "e7", "source": "code", "target": "aggregator"},
    {"id": "e8", "source": "aggregator", "target": "template"},
    {"id": "e9", "source": "template", "target": "condition"},
    {"id": "e10", "source": "condition", "target": "classifier"},
    {"id": "e11", "source": "classifier", "target": "extractor"},
    {"id": "e12", "source": "extractor", "target": "tool"},
    {"id": "e13", "source": "tool", "target": "connector"},
    {"id": "e14", "source": "connector", "target": "http"},
    {"id": "e15", "source": "http", "target": "memory_write"},
    {"id": "e16", "source": "memory_write", "target": "memory_read"},
    {"id": "e17", "source": "memory_read", "target": "kb_index"},
    {"id": "e18", "source": "kb_index", "target": "loop"},
    {"id": "e19", "source": "loop", "target": "iteration"},
    {"id": "e20", "source": "iteration", "target": "mcp_call"},
    {"id": "e21", "source": "mcp_call", "target": "webhook"},
    {"id": "e22", "source": "webhook", "target": "email"},
    {"id": "e23", "source": "email", "target": "stop"},
    {"id": "e24", "source": "stop", "target": "end"},
]

workflow = {
    "id": "all_nodes_test",
    "name": "全节点功能验证",
    "description": "包含所有 24 种节点类型的完整测试工作流，用于验证每个节点的功能是否正常。输入姓名和手机尾号即可触发完整执行链。",
    "nodes": nodes,
    "edges": edges,
    "tags": ["测试", "全节点", "DSL"],
    "enabled": True,
    "created_at": 1785900000,
}

wf_id = db.save_workflow(workflow)
print("创建成功:", wf_id)
print("节点数:", len(nodes))
print("边数:", len(edges))
