import db, json

# 先删除可能存在的旧测试工作流
for wf in db.list_workflows():
    if wf.get("name") == "全节点功能验证":
        db.delete_workflow(wf["id"])

nodes = [
    {"id": "start", "type": "start", "label": "开始", "config": {"input_fields": ["patient_name", "phone_tail"]}},
    {"id": "llm", "type": "llm", "label": "LLM 解析", "config": {"prompt": "请将用户输入格式化为：姓名={patient_name}，尾号={phone_tail}", "model": "", "model_source": "free", "output_variable": "formatted_input"}},
    {"id": "variable", "type": "variable", "label": "设置变量", "config": {"action": "set", "variable": "query_condition", "value": "report_found"}},
    {"id": "kb_search", "type": "kb_search", "label": "检索报告", "config": {"query": "{{patient_name}} 报告", "top_k": 5, "kb_id": "default", "output_variable": "kb_results"}},
    {"id": "text_process", "type": "text_process", "label": "文本处理", "config": {"op": "upper", "input": "{{kb_results}}", "output_variable": "text_out"}},
    {"id": "json_parse", "type": "json_parse", "label": "JSON解析", "config": {"input": '{"result": "{{text_out}}", "count": 1}', "output_variable": "json_data"}},
    {"id": "code", "type": "code", "label": "代码执行", "config": {"language": "python", "code": "result = variables.get('json_data', {})\nresult['processed'] = True\nvariables['processed_data'] = result\nprint('代码执行成功')", "output_variable": "code_output"}},
    {"id": "aggregator", "type": "aggregator", "label": "变量聚合", "config": {"mode": "json", "variables": ["patient_name", "phone_tail", "formatted_input", "code_output"], "output_variable": "agg_result"}},
    {"id": "template", "type": "template", "label": "模板生成", "config": {"template": "患者：{{patient_name}}，尾号：{{phone_tail}}，处理结果：{{code_output}}", "output_variable": "final_template"}},
    {"id": "condition", "type": "condition", "label": "条件判断", "config": {"variable": "phone_tail", "conditions": [{"operator": "neq", "value": "", "target": "classifier"}], "output_variable": "cond_result"}},
    {"id": "classifier", "type": "classifier", "label": "意图分类", "config": {"input": "{{final_template}}", "categories": ["查报告", "其他", "咨询"], "conditions": [{"operator": "eq", "value": "查报告", "target": "extractor"}], "output_variable": "classifier_result"}},
    {"id": "extractor", "type": "extractor", "label": "参数提取", "config": {"input": "{{final_template}}", "fields": [{"name": "extracted_name", "type": "string", "description": "提取患者姓名"}, {"name": "extracted_tail", "type": "string", "description": "提取手机尾号"}], "output_variable": "extracted"}},
    {"id": "tool", "type": "tool", "label": "工具调用", "config": {"tool_name": "get_current_time", "arguments": {}, "output_variable": "tool_time"}},
    {"id": "connector", "type": "connector", "label": "数据查询", "config": {"connector_id": "conn_demo", "query": "SELECT * FROM orders LIMIT 5", "output_variable": "db_rows"}},
    {"id": "http", "type": "http", "label": "HTTP请求", "config": {"method": "GET", "url": "https://httpbin.org/get?patient={{patient_name}}", "headers": {}, "output_variable": "http_response"}},
    {"id": "memory_write", "type": "memory_write", "label": "记忆写入", "config": {"memory_key": "patient_{{patient_name}}", "content": "{{final_template}}", "namespace": "test", "output_variable": "mem_write_result"}},
    {"id": "memory_read", "type": "memory_read", "label": "记忆读取", "config": {"memory_key": "patient_{{patient_name}}", "namespace": "test", "output_variable": "mem_read_result"}},
    {"id": "kb_index", "type": "kb_index", "label": "知识入库", "config": {"kb_id": "default", "mode": "append", "title": "workflow_test_{{patient_name}}", "content": "{{final_template}} - 测试入库", "output_variable": "kb_index_result"}},
    {"id": "loop", "type": "loop", "label": "循环处理", "config": {"array_variable": "[1, 2, 3]", "item_variable": "loop_item", "output_variable": "loop_result"}},
    {"id": "iteration", "type": "iteration", "label": "遍历", "config": {"array_variable": "{{loop_result}}", "item_variable": "iter_item", "output_variable": "iter_result"}},
    {"id": "mcp_call", "type": "mcp_call", "label": "MCP调用", "config": {"mcp_server": "测试MCP", "tool_name": "get_weather", "arguments": {"city": "Beijing"}, "output_variable": "mcp_result"}},
    {"id": "webhook", "type": "webhook", "label": "Webhook", "config": {"method": "POST", "url": "https://httpbin.org/post", "body": '{"name": "{{patient_name}}"}', "headers": {"Content-Type": "application/json"}, "output_variable": "webhook_result"}},
    {"id": "email", "type": "email", "label": "邮件通知", "config": {"to": "test@example.com", "subject": "测试工作流", "body": "{{final_template}}", "output_variable": "email_result"}},
    {"id": "stop", "type": "stop", "label": "直接回复", "config": {"output_field": "final_template"}},
    {"id": "end", "type": "end", "label": "结束", "config": {"output_field": "final_template"}},
]

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
