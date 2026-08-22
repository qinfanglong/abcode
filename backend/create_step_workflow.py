import db, json

for wf in db.list_workflows():
    if wf.get("name") == "逐步测试":
        db.delete_workflow(wf["id"])

# 逐步测试：start -> text_process -> json_parse -> end
step = {
    "id": "step_test",
    "name": "逐步测试",
    "description": "逐步测试节点链",
    "nodes": [
        {"id": "start", "type": "start", "label": "开始", "config": {"input_fields": ["name"]}},
        {"id": "text_process", "type": "text_process", "label": "文本处理", "config": {"op": "upper", "input": "{{name}}", "output_variable": "text_out"}},
        {"id": "json_parse", "type": "json_parse", "label": "JSON解析", "config": {"input": '{"msg": "{{text_out}}"}', "output_variable": "json_data"}},
        {"id": "end", "type": "end", "label": "结束", "config": {"output_field": "json_data"}},
    ],
    "edges": [
        {"id": "e1", "source": "start", "target": "text_process"},
        {"id": "e2", "source": "text_process", "target": "json_parse"},
        {"id": "e3", "source": "json_parse", "target": "end"},
    ],
    "tags": ["测试"],
    "enabled": True,
    "created_at": 1785900000,
}
print('创建逐步工作流:', db.save_workflow(step))
