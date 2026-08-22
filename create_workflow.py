import json, time, urllib.request

workflow = {
    "name": "互联网医院报告查询",
    "description": "用户输入姓名和手机尾号查询医疗报告，包含所有节点类型的完整演示",
    "enabled": True,
    "tags": ["医院", "报告查询", "全节点演示"],
    "nodes": [
        {
            "id": "start_1",
            "type": "start",
            "label": "用户输入",
            "config": {
                "input_variables": [
                    {"name": "姓名", "type": "string", "default": "", "required": True, "options": []},
                    {"name": "手机尾号", "type": "string", "default": "", "required": True, "options": []}
                ]
            }
        },
        {
            "id": "llm_1",
            "type": "llm",
            "label": "意图解析",
            "config": {
                "model_source": "local",
                "model": "qwen3.5:9b",
                "system": "你是互联网医院的智能助手，帮助用户查询医疗报告。",
                "prompt": "用户输入了：姓名={{姓名}}，手机尾号={{手机尾号}}。请解析用户的查询意图，确认是要查询医疗报告。",
                "output_variable": "llm_1_output",
                "temperature": 0.3
            }
        },
        {
            "id": "variable_1",
            "type": "variable",
            "label": "设置查询参数",
            "config": {
                "action": "set",
                "variable": "query_params",
                "value": '{"name": "{{姓名}}", "phone_suffix": "{{手机尾号}}"}'
            }
        },
        {
            "id": "kb_search_1",
            "type": "kb_search",
            "label": "知识库检索",
            "config": {
                "kb_id": "default",
                "query": "{{姓名}} 手机尾号 {{手机尾号}} 报告",
                "top_k": 10,
                "threshold": 0.3,
                "output_variable": "kb_results"
            }
        },
        {
            "id": "condition_1",
            "type": "condition",
            "label": "判断是否有结果",
            "config": {
                "variable": "{{kb_results}}",
                "conditions": [
                    {"operator": "is_empty", "value": "", "target": "end_no_result"},
                    {"operator": "is_not_empty", "value": "", "target": "code_1"}
                ]
            }
        },
        {
            "id": "code_1",
            "type": "code",
            "label": "报告数据处理",
            "config": {
                "language": "python",
                "timeout": 30,
                "code": "import json\nkb_results = params.get('kb_results', '')\nname = params.get('姓名', '')\nphone = params.get('手机尾号', '')\nprint(json.dumps({'name': name, 'phone': phone, 'results_count': len(kb_results)}, ensure_ascii=False))",
                "output_variable": "processed_reports"
            }
        },
        {
            "id": "text_process_1",
            "type": "text_process",
            "label": "格式化报告",
            "config": {
                "op": "replace",
                "input": "{{processed_reports}}",
                "old": "results_count",
                "new": "found",
                "output_variable": "formatted_report"
            }
        },
        {
            "id": "aggregator_1",
            "type": "aggregator",
            "label": "聚合报告摘要",
            "config": {
                "mode": "text",
                "variables": ["姓名", "手机尾号", "processed_reports"],
                "separator": " | ",
                "output_variable": "final_result"
            }
        },
        {
            "id": "template_1",
            "type": "template",
            "label": "生成回复",
            "config": {
                "template": "您好 {{姓名}}，已为您查询到医疗报告信息。手机尾号：{{手机尾号}}。",
                "output_variable": "reply_text"
            }
        },
        {
            "id": "end_1",
            "type": "end",
            "label": "正常结束",
            "config": {
                "output_field": "final_output"
            }
        },
        {
            "id": "end_no_result",
            "type": "end",
            "label": "无结果结束",
            "config": {
                "output_field": "final_output"
            }
        }
    ],
    "edges": [
        {"source": "start_1", "target": "llm_1"},
        {"source": "llm_1", "target": "variable_1"},
        {"source": "variable_1", "target": "kb_search_1"},
        {"source": "kb_search_1", "target": "condition_1"},
        {"source": "condition_1", "target": "code_1", "condition": "is_not_empty"},
        {"source": "condition_1", "target": "end_no_result", "condition": "is_empty"},
        {"source": "code_1", "target": "text_process_1"},
        {"source": "text_process_1", "target": "aggregator_1"},
        {"source": "aggregator_1", "target": "template_1"},
        {"source": "template_1", "target": "end_1"}
    ],
    "created_at": time.time()
}

req = urllib.request.Request(
    'http://localhost:8900/api/workflows',
    data=json.dumps(workflow).encode('utf-8'),
    headers={'Content-Type': 'application/json'},
    method='POST'
)
with urllib.request.urlopen(req) as resp:
    result = json.loads(resp.read().decode('utf-8'))
    print('工作流创建成功:', result)
    wf_id = result.get('id')
    print('工作流ID:', wf_id)
