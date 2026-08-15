#!/bin/bash
# ABcode macOS Nuitka 打包脚本
# 产出高混淆单二进制，逆向难度远高于 PyInstaller

set -euo pipefail

echo "[ABcode] 开始 macOS Nuitka 打包..."

cd "$(dirname "$0")"

# 检查 Python 环境（要求 CPython 3.10+，Nuitka 不支持 Apple Python）
if command -v python3 &>/dev/null; then
    PY=$(command -v python3)
else
    echo "[ABcode] 错误：未找到 python3"
    exit 1
fi

$PY --version || true
$PY -c "import sys; exit(0 if sys.version_info >= (3, 10) else 1)" || {
    echo "[ABcode] 错误：Nuitka 需要 CPython 3.10+，请从 python.org 安装"
    exit 1
}

# 安装 Nuitka 与必要插件
$PY -m pip install nuitka imageio --quiet

# 清理旧构建
rm -rf build_nuitka dist/ABcode

# Nuitka 编译（standalone 目录，便于调试缺失的动态库）
echo "[ABcode] Nuitka 编译中，这可能需要数分钟..."
$PY -m nuitka \
    --standalone \
    --macos-app-name="ABcode" \
    --macos-app-icon=frontend/abcode_logo.svg \
    --include-data-dir=frontend=frontend \
    --include-data-dir=backend=backend \
    --include-data-file=backend/requirements.txt=requirements.txt \
    --include-module=uvicorn \
    --include-module=fastapi \
    --include-module=sqlite3 \
    --include-module=lxml \
    --include-module=httpx \
    --include-module=requests \
    --include-module=uvloop \
    --include-module=watchfiles \
    --include-module=websockets \
    --output-dir=build_nuitka \
    --output-filename=ABcode \
    backend/main.py

# 修复 conda/Homebrew 带来的动态库依赖（_ssl.so 等）
# 如果运行时提示缺少 libssl.3.dylib / libcrypto.3.dylib，取消下面注释即可自动复制
# DYLD_LIBRARY_PATH 在 macOS 12+ 受到限制，这里用 install_name_tool 重写路径
if [ -d build_nuitka/ABcode.dist ]; then
    LIBSSL=$(find /opt/homebrew /usr/local -name "libssl.3.dylib" 2>/dev/null | head -n1 || true)
    LIBCRYPTO=$(find /opt/homebrew /usr/local -name "libcrypto.3.dylib" 2>/dev/null | head -n1 || true)
    if [ -n "${LIBSSL}" ] && [ -f "build_nuitka/ABcode.dist/_ssl.so" ]; then
        install_name_tool -change @rpath/libssl.3.dylib @loader_path/libssl.3.dylib build_nuitka/ABcode.dist/_ssl.so || true
        install_name_tool -change @rpath/libcrypto.3.dylib @loader_path/libcrypto.3.dylib build_nuitka/ABcode.dist/_ssl.so || true
        cp "${LIBSSL}" build_nuitka/ABcode.dist/ || true
        cp "${LIBCRYPTO}" build_nuitka/ABcode.dist/ || true
    fi
fi

# 移动到 dist 目录
mv build_nuitka/ABcode.dist/ABcode dist/ABcode 2>/dev/null || mv build_nutka/ABcode dist/ABcode 2>/dev/null || true

echo "[ABcode] 打包完成！文件：dist/ABcode"
echo "[ABcode] 运行 ./dist/ABcode 即可启动"
