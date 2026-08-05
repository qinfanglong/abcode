@echo off
rem ABcode Windows 启动脚本
rem 用法: start.bat [端口]   默认端口 8900

set PORT=8900
if not "%1"=="" set PORT=%1

cd /d %~dp0

if exist .venv\Scripts\python.exe (
    set PY=.venv\Scripts\python.exe
) else (
    set PY=python
)

echo [ABcode] 启动后端: http://127.0.0.1:%PORT%
start "" http://127.0.0.1:%PORT%
%PY% -m uvicorn main:app --host 0.0.0.0 --port %PORT% --app-dir backend