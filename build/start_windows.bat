@echo off
rem ABcode Windows 启动脚本

echo [ABcode] 正在启动...

cd /d "%~dp0"

rem 检查 Python
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [ABcode] 未检测到 Python，请先安装 Python 3.9+
    echo [ABcode] 下载地址: https://www.python.org/downloads/
    pause
    exit /b 1
)

rem 创建虚拟环境
if not exist ".venv" (
    echo [ABcode] 创建虚拟环境...
    python -m venv .venv
)

rem 激活虚拟环境
call .venv\Scripts\activate.bat

rem 安装依赖
echo [ABcode] 安装依赖...
pip install -r backend\requirements.txt --quiet

rem 启动后端
echo [ABcode] 启动服务...
start "" "http://127.0.0.1:8900"
python -m uvicorn main:app --host 0.0.0.0 --port 8900 --app-dir backend