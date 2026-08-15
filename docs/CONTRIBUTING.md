# 参与贡献

欢迎！无论是报告 bug、提需求、改文档还是写代码，都感谢你的参与。

## 开发环境搭建

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
# 启动后端（前端静态页面由后端直接服务）
python -m uvicorn main:app --host 0.0.0.0 --port 8900 --app-dir backend
# 浏览器访问 http://127.0.0.1:8900/docs 查看 API 文档
```

后端改动后会自动 reload（开发模式）。前端是纯静态文件，改完刷新即可。

## 代码约定

- **后端**：Python 3.9+，FastAPI + SQLite。新增依赖请更新 `backend/requirements.txt`。
  - 新功能尽量做成独立的 `xxx.py` 模块，由 `main.py` 引入并注册路由。
  - 数据库表结构变更：在 `main.py` 的迁移逻辑里增加 `ALTER TABLE`（幂等）。
- **前端**：原生 HTML/CSS/JS，**禁止引入外网 CDN**。所有第三方资源内置到 `frontend/vendor/`。
  - 新增页面/弹窗遵循现有代码风格，公共交互函数放在 `frontend/js/common.js`。
- 提交前确保 `.venv`、`data/`、`*.app`、`*.zip`、`__pycache__/` 不出现在提交里（已在 `.gitignore`）。

## 测试

```bash
# Mock 模型服务器（用于本地开发/无 Key 测试）
python tests/mock_llm.py &
PORT=8900 python -m uvicorn main:app --app-dir backend

# MCP 测试服务器
python tests/mcp_test_server.py &
```

## 提 PR 流程

1. Fork 本仓库，新建特性分支 `feat/xxx`
2. 提交改动（遵循上文约定）
3. 打开 PR，在描述中说明改动目的与验证方式
4. 等待 review

## 版本号约定

采用 `主.次.修订`。破坏性变更升主版本；新功能升次版本；bug 修复升修订版本。
更新版本号后，同步更新 `CHANGELOG.md`，并在 `macapp/build.sh` 中同步版本号。