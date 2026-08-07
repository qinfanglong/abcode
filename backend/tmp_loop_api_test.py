import requests, json

# 直接测试执行引擎是否支持 loop 节点
wf = {
    "nodes": [
        {"id": "start", "type": "start", "label": "开始", "x": 100, "y": 200, "config": {"input_fields": ["items"]}},
        {"id": "loop1", "type": "loop", "label": "循环", "x": 300, "y": 200, "config": {"array_variable": "{{items}}", "item_variable": "item", "index_variable": "index", "max_iterations": 100}},
        {"id": "tp1", "type": "text_process", "label": "转大写", "x": 550, "y": 200, "config": {"input": "{{item}}", "op": "upper", "output_variable": "upcased"}},
        {"id": "end", "type": "end", "label": "结束", "x": 800, "y": 200, "config": {"output_field": "loop1_results"}}
    ],
    "edges": [
        {"source": "start", "target": "loop1"},
        {"source": "loop1", "target": "tp1"},
        {"source": "tp1", "target": "end"}
    ]
}
r = requests.post("http://127.0.0.1:8900/api/workflow/test", json={"nodes": wf["nodes"], "edges": wf["edges"], "input": {"items": ["a", "b"]}})
print("状态:", r.status_code)
try:
    d = r.json()
    print("success:", d.get("success"))
    print("output:", d.get("output"))
    print("error:", str(d.get("error"))[:200])
except Exception as e:
    print("响应:", r.text[:300])
