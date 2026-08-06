#!/bin/bash
# ABcode Mac 打包脚本 - 生成 .app 和 .dmg

set -e

echo "[ABcode] 开始 Mac 打包..."

cd "$(dirname "$0")"

# 获取版本号（从 git tag 或默认）
VERSION=$(git describe --tags --always --dirty 2>/dev/null | sed 's/^v//' || echo "0.4.0")
echo "[ABcode] 版本: $VERSION"

# 创建 .app 结构
APP_DIR="dist/ABcode.app"
mkdir -p "$APP_DIR/Contents/MacOS"
mkdir -p "$APP_DIR/Contents/Resources"

# 复制前端和后端
cp -r frontend "$APP_DIR/Contents/Resources/"
cp -r backend "$APP_DIR/Contents/Resources/"

# 复制虚拟环境（预装依赖）
if [ -d ".venv" ]; then
    cp -r .venv "$APP_DIR/Contents/Resources/"
fi

# 复制图标
if [ -f "build/icon.icns" ]; then
    cp build/icon.icns "$APP_DIR/Contents/Resources/AppIcon.icns"
elif [ -f "build/icon.ico" ]; then
    # 尝试转换 ico 到 icns
    if command -v sips &> /dev/null; then
        sips -s format icns build/icon.ico --out "$APP_DIR/Contents/Resources/AppIcon.icns" 2>/dev/null || true
    fi
fi

# 创建启动脚本
cat > "$APP_DIR/Contents/MacOS/ABcode" << 'EOF'
#!/bin/bash
cd "$(dirname "$0")/../Resources"

# 检查 Python
if ! command -v python3 &> /dev/null; then
    osascript -e 'display dialog "错误: 未找到 Python3，请先安装 Python 3.9+" buttons {"OK"} default button "OK" with icon stop'
    exit 1
fi

# 创建虚拟环境
if [ ! -d ".venv" ]; then
    echo "创建虚拟环境..."
    python3 -m venv .venv
fi

# 激活虚拟环境
source .venv/bin/activate

# 安装依赖
echo "安装依赖..."
pip install -r backend/requirements.txt --quiet

# 启动后端
echo "启动 ABcode..."
open "http://127.0.0.1:8900"
python3 -m uvicorn main:app --host 0.0.0.0 --port 8900 --app-dir backend
EOF

chmod +x "$APP_DIR/Contents/MacOS/ABcode"

# 创建 Info.plist
cat > "$APP_DIR/Contents/Info.plist" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key>
    <string>ABcode</string>
    <key>CFBundleIdentifier</key>
    <string>com.abcode.app</string>
    <key>CFBundleName</key>
    <string>ABcode</string>
    <key>CFBundleDisplayName</key>
    <string>ABcode</string>
    <key>CFBundleVersion</key>
    <string>$VERSION</string>
    <key>CFBundleShortVersionString</key>
    <string>$VERSION</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleSignature</key>
    <string>????</string>
    <key>LSMinimumSystemVersion</key>
    <string>10.15</string>
    <key>NSHighResolutionCapable</key>
    <true/>
    <key>CFBundleIconFile</key>
    <string>AppIcon</string>
</dict>
</plist>
EOF

echo "[ABcode] .app 打包完成: $APP_DIR"

# 创建 DMG
DMG_NAME="ABcode-mac-${VERSION}.dmg"
DMG_DIR="dist/dmg_temp"
DMG_PATH="dist/$DMG_NAME"

echo "[ABcode] 创建 DMG 安装包..."

# 清理旧的临时目录
rm -rf "$DMG_DIR"
mkdir -p "$DMG_DIR"

# 复制 .app 到临时目录
cp -R "$APP_DIR" "$DMG_DIR/"

# 创建 Applications 文件夹的软链接
ln -s /Applications "$DMG_DIR/Applications"

# 创建 DMG
hdiutil create -volname "ABcode $VERSION" \
    -srcfolder "$DMG_DIR" \
    -ov -format UDZO \
    "$DMG_PATH"

# 清理临时目录
rm -rf "$DMG_DIR"

echo "[ABcode] DMG 创建完成: $DMG_PATH"
echo "[ABcode] 大小: $(du -h "$DMG_PATH" | cut -f1)"

# 同时生成 zip 用于 GitHub Release
cd dist && zip -r "ABcode-mac-${VERSION}.zip" ABcode.app

echo "[ABcode] 所有打包完成！"