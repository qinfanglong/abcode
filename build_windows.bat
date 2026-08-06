@echo off
rem ABcode Windows 打包脚本
rem 使用 PyInstaller 打包成 .exe

echo [ABcode] 开始 Windows 打包...

cd /d %~dp0

rem 检查 Python 环境
if exist .venv\Scripts\python.exe (
    set PY=.venv\Scripts\python.exe
) else (
    set PY=python
)

rem 安装 PyInstaller
%PY% -m pip install pyinstaller --quiet

rem 打包后端为单个 .exe
echo [ABcode] 打包后端...
%PY% -m PyInstaller ^
    --onefile ^
    --name ABcode ^
    --icon=build/icon.ico ^
    --add-data "frontend;frontend" ^
    --add-data "backend;backend" ^
    --add-data "backend/requirements.txt;." ^
    --hidden-import=uvicorn ^
    --hidden-import=fastapi ^
    --hidden-import=sqlite3 ^
    backend\main.py

rem 复制启动脚本
echo [ABcode] 复制启动脚本...
copy start.bat dist\start.bat

echo [ABcode] 打包完成！文件在 dist\ 目录
echo [ABcode] 运行 dist\ABcode.exe 即可启动
pause
