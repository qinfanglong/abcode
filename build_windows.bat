@echo off
rem ABcode Windows 打包脚本
rem 使用 PyInstaller 打包成 .exe，可选 NSIS 制作安装包

echo [ABcode] 开始 Windows 打包...

cd /d %~dp0

rem 检查 Python 环境
if exist .venv\Scripts\python.exe (
    set PY=.venv\Scripts\python.exe
) else (
    set PY=python
)

rem 安装 PyInstaller 与桌面壳依赖及全部频道 SDK
%PY% -m pip install pyinstaller pywebview websockets lark-oapi slack_sdk paho-mqtt qq-botpy dingtalk-stream --quiet

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
    --hidden-import=webview ^
    --hidden-import=dingtalk_stream ^
    --hidden-import=websockets ^
    --hidden-import=lark_oapi ^
    --hidden-import=slack_sdk ^
    --hidden-import=paho.mqtt ^
    --hidden-import=botpy ^
    --hidden-import=faster_whisper ^
    --hidden-import=ctranslate2 ^
    --hidden-import=av ^
    backend\main.py

rem 复制启动脚本
echo [ABcode] 复制启动脚本...
copy start.bat dist\start.bat

rem 如果有 NSIS，制作安装包
where makensis >nul 2>nul
if %errorlevel% equ 0 (
    echo [ABcode] 发现 NSIS，制作安装包...
    copy build\start_windows.bat dist\
    copy build\icon.ico dist\
    mkdir dist\build 2>nul
    copy build\icon.ico dist\build\
    copy build\banner.bmp dist\build\
    makensis /DVERSION="0.9.0" build\installer.nsi
    echo [ABcode] 安装包生成: dist\ABcode-Setup-0.9.0.exe
) else (
    echo [ABcode] 未安装 NSIS，跳过安装包制作
    echo [ABcode] 如需安装包，请安装 NSIS: https://nsis.sourceforge.io/Download
)

echo [ABcode] 打包完成！文件在 dist\ 目录
echo [ABcode] 运行 dist\ABcode.exe 即可启动
pause
