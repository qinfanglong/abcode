import db, json

for wf in db.list_workflows():
    if wf.get("name") in ("全节点功能验证", "最小冒烟测试"):
        db.delete_workflow(wf["id"])

# 最小冒烟测试：start -> text_process -> end
minimal = {
    "id": "minimal_smoke",
    "name": "最小冒烟测试",
    "description": "仅 start+text_process+end，用于快速验证基础链路",
    "nodes": [
        {"id": "start", "type": "start", "label": "开始", "config": {"input_fields": ["name"]}},
        {"id": "text_process", "type": "text_process", "label": "文本处理", "config": {"op": "upper", "input": "{{name}}", "output_variable": "text_out"}},
        {"id": "end", "type": "end", "label": "结束", "config": {"output_field": "text_out"}},
    ],
    "edges": [
        {"id": "e1", "source": "start", "target": "text_process"},
        {"id": "e2", "source": "text_process", "target": "end"},
    ],
    "tags": ["测试", "冒烟"],
    "enabled": True,
    "created_at": 1785900000,
}
print('创建最小工作流:', db.save_workflow(minimal))
