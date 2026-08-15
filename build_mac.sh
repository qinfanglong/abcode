#!/bin/bash
# ABcode Mac Build Script - 创建 .app + DMG 安装包
# 用法: ./build_mac.sh

set -e

VERSION="${VERSION:-v0.8.0}"
VERSION_CLEAN="${VERSION#v}"
APP_NAME="ABcode"
BUILD_DIR="build_mac"
DIST_DIR="dist"

echo "=========================================="
echo "Building ABcode for macOS ${VERSION}"
echo "=========================================="

# 清理旧构建
rm -rf "${BUILD_DIR}"
rm -rf "${DIST_DIR}"
mkdir -p "${BUILD_DIR}"
mkdir -p "${DIST_DIR}"

# 1. 创建虚拟环境并安装依赖
echo "[1/6] Creating virtual environment and installing dependencies..."
python3 -m venv "${BUILD_DIR}/.venv"
source "${BUILD_DIR}/.venv/bin/activate"
pip install --upgrade pip
pip install -r backend/requirements.txt
pip install pyinstaller

# 2. PyInstaller 打包为单文件
echo "[2/6] Building executable with PyInstaller..."
pyinstaller \
  --onefile \
  --name "${APP_NAME}" \
  --add-data "frontend:frontend" \
  --add-data "backend:backend" \
  --add-data "backend/requirements.txt:." \
  --hidden-import=uvicorn \
  --hidden-import=fastapi \
  --hidden-import=sqlite3 \
  --hidden-import=websockets \
  --hidden-import=httpx \
  --hidden-import=webview \
  --hidden-import=desktop_shell \
  --hidden-import=dingtalk_stream \
  --hidden-import=lark_oapi \
  --hidden-import=slack_sdk \
  --hidden-import=paho.mqtt \
  --hidden-import=botpy \
  --hidden-import=faster_whisper \
  --hidden-import=ctranslate2 \
  --hidden-import=av \
  --hidden-import=onnxruntime \
  --hidden-import=hf_xet \
  backend/main.py

# 3. 创建 .app 结构
echo "[3/6] Creating .app bundle..."
APP_DIR="${BUILD_DIR}/${APP_NAME}.app"
mkdir -p "${APP_DIR}/Contents/MacOS"
mkdir -p "${APP_DIR}/Contents/Resources"

# 复制可执行文件
cp "dist/${APP_NAME}" "${APP_DIR}/Contents/MacOS/"

# 使用现有的 macapp/Info.plist 和 AppIcon.icns
echo "  Copying Info.plist and icon from macapp/"
cp "macapp/Info.plist" "${APP_DIR}/Contents/Info.plist"
# 更新版本号
/usr/libexec/PlistBuddy -c "Set :CFBundleVersion ${VERSION_CLEAN}" "${APP_DIR}/Contents/Info.plist" 2>/dev/null || true
/usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString ${VERSION_CLEAN}" "${APP_DIR}/Contents/Info.plist" 2>/dev/null || true

if [ -f "macapp/AppIcon.icns" ]; then
    cp "macapp/AppIcon.icns" "${APP_DIR}/Contents/Resources/AppIcon.icns"
    /usr/libexec/PlistBuddy -c "Set :CFBundleIconFile AppIcon" "${APP_DIR}/Contents/Info.plist" 2>/dev/null || true
fi

# 4. 代码签名（可选，需要开发者证书）
echo "[4/6] Code signing (ad-hoc for local testing)..."
codesign --force --deep --sign - "${APP_DIR}" 2>/dev/null || echo "  Ad-hoc signing skipped (no certificate)"

# 5. 创建 DMG
echo "[5/6] Creating DMG installer..."
DMG_NAME="${APP_NAME}-mac-${VERSION_CLEAN}"
DMG_PATH="${DIST_DIR}/${DMG_NAME}.dmg"

# 创建临时 DMG 目录
DMG_TEMP="${BUILD_DIR}/dmg_temp"
mkdir -p "${DMG_TEMP}"
cp -R "${APP_DIR}" "${DMG_TEMP}/"
# 创建 Applications 符号链接
ln -s /Applications "${DMG_TEMP}/Applications"

# 创建 DMG
hdiutil create -volname "${APP_NAME} ${VERSION_CLEAN}" \
  -srcfolder "${DMG_TEMP}" \
  -ov -format UDZO \
  "${DMG_PATH}"

# 6. 创建便携版 ZIP
echo "[6/6] Creating portable ZIP..."
ZIP_NAME="${APP_NAME}-mac-${VERSION_CLEAN}.zip"
cd "${BUILD_DIR}"
zip -r "../${DIST_DIR}/${ZIP_NAME}" "${APP_NAME}.app" -q
cd ..

# 清理
rm -rf "${BUILD_DIR}"

echo ""
echo "=========================================="
echo "Build complete!"
echo "=========================================="
echo "DMG: ${DMG_PATH}"
echo "ZIP: ${DIST_DIR}/${ZIP_NAME}"
echo ""
ls -lh "${DIST_DIR}/"