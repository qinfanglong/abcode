#!/bin/bash
# ABcode 本地启动脚本
cd "$(dirname "$0")"
PORT="${PORT:-8900}"
.venv/bin/python -m uvicorn main:app --host 0.0.0.0 --port "$PORT" --app-dir backend
