import db, json

for wf in db.list_workflows():
    if wf.get("name") == "逐步测试2":
        db.delete_workflow(wf["id"])

# 逐步测试2：加入 HTTP/知识库/记忆/循环
step2 = {
    "id": "step_test2",
    "name": "逐步测试2",
    "description": "逐步测试节点链2",
    "nodes": [
        {"id": "start", "type": "start", "label": "开始", "config": {"input_fields": ["name"]}},
        {"id": "text_process", "type": "text_process", "label": "文本处理", "config": {"op": "upper", "input": "{{name}}", "output_variable": "text_out"}},
        {"id": "http", "type": "http", "label": "HTTP请求", "config": {"method": "GET", "url": "https://httpbin.org/get?q={{name}}", "headers": {}, "output_variable": "http_out"}},
        {"id": "json_parse", "type": "json_parse", "label": "JSON解析", "config": {"input": '{"http_status": 200, "name": "{{name}}"}', "output_variable": "json_data"}},
        {"id": "memory_write", "type": "memory_write", "label": "记忆写入", "config": {"memory_key": "name_{{name}}", "content": "{{name}}", "namespace": "test2", "output_variable": "mem_w"}},
        {"id": "memory_read", "type": "memory_read", "label": "记忆读取", "config": {"memory_key": "name_{{name}}", "namespace": "test2", "output_variable": "mem_r"}},
        {"id": "loop", "type": "loop", "label": "循环", "config": {"array_variable": "[1,2,3]", "item_variable": "x", "index_variable": "i", "max_iterations": 5, "output_variable": "loop_out"}},
        {"id": "end", "type": "end", "label": "结束", "config": {"output_field": "loop_out"}},
    ],
    "edges": [
        {"id": "e1", "source": "start", "target": "text_process"},
        {"id": "e2", "source": "text_process", "target": "http"},
        {"id": "e3", "source": "http", "target": "json_parse"},
        {"id": "e4", "source": "json_parse", "target": "memory_write"},
        {"id": "e5", "source": "memory_write", "target": "memory_read"},
        {"id": "e6", "source": "memory_read", "target": "loop"},
        {"id": "e7", "source": "loop", "target": "end"},
    ],
    "tags": ["测试"],
    "enabled": True,
    "created_at": 1785900000,
}
print('创建逐步工作流2:', db.save_workflow(step2))
