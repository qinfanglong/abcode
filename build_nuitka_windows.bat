@echo off
rem ABcode Windows Nuitka 打包脚本
rem 产出高混淆单 exe，逆向难度远高于 PyInstaller

echo [ABcode] 开始 Windows Nuitka 打包...

cd /d %~dp0

rem 检查 Python 环境（要求 CPython 3.10+，Nuitka 不支持 Apple Python）
if exist .venv\Scripts\python.exe (
    set PY=.venv\Scripts\python.exe
) else (
    set PY=python
)

%PY% --version
%PY% -c "import sys; print('Nuitka supported:', sys.version_info >= (3, 10))" || (
    echo [ABcode] 错误：Nuitka 需要 CPython 3.10+，请从 python.org 安装
    pause
    exit /b 1
)

rem 安装 Nuitka 与必要插件、频道 SDK
%PY% -m pip install nuitka imageio websockets lark-oapi slack_sdk paho-mqtt qq-botpy dingtalk-stream --quiet

rem 清理旧构建
if exist build_nuitka\ rd /s /q build_nuitka\
if exist dist\ABcode.exe del /f /q dist\ABcode.exe

rem Nuitka 编译（单 exe + 前端/后端资源打包）
echo [ABcode] Nuitka 编译中，这可能需要数分钟...
%PY% -m nuitka ^
    --onefile ^
    --windows-console-mode=disable ^
    --windows-icon-from-ico=frontend\abcode_logo.ico ^
    --include-data-dir=frontend=frontend ^
    --include-data-dir=backend=backend ^
    --include-data-file=backend\requirements.txt=requirements.txt ^
    --include-module=uvicorn ^
    --include-module=fastapi ^
    --include-module=sqlite3 ^
    --include-module=lxml ^
    --include-module=httpx ^
    --include-module=requests ^
    --include-module=uvloop ^
    --include-module=watchfiles ^
    --include-module=websockets ^
    --include-module=webview ^
    --include-module=dingtalk_stream ^
    --include-module=lark_oapi ^
    --include-module=slack_sdk ^
    --include-module=paho.mqtt ^
    --include-module=botpy ^
    --include-module=desktop_shell ^
    --remove-output ^
    --output-dir=build_nuitka ^
    --output-filename=ABcode.exe ^
    backend\main.py

if errorlevel 1 (
    echo [ABcode] 编译失败
    pause
    exit /b 1
)

rem 移动到 dist 目录
move /Y build_nuitka\ABcode.exe dist\ABcode.exe >nul

echo [ABcode] 打包完成！文件：dist\ABcode.exe
echo [ABcode] 运行 dist\ABcode.exe 即可启动
pause
