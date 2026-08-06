#!/bin/bash
# ABcode Mac 打包脚本

echo "[ABcode] 开始 Mac 打包..."

cd "$(dirname "$0")"

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

# 创建启动脚本
cat > "$APP_DIR/Contents/MacOS/ABcode" << 'EOF'
#!/bin/bash
cd "$(dirname "$0")/../Resources"

# 检查 Python
if ! command -v python3 &> /dev/null; then
    echo "错误: 未找到 Python3"
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
    <string>0.4.0</string>
    <key>CFBundleShortVersionString</key>
    <string>0.4.0</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleSignature</key>
    <string>????</string>
    <key>LSMinimumSystemVersion</key>
    <string>10.15</string>
    <key>NSHighResolutionCapable</key>
    <true/>
</dict>
</plist>
EOF

echo "[ABcode] Mac 打包完成！"
echo "[ABcode] 应用位置: $APP_DIR"
echo "[ABcode] 双击 ABcode 即可运行"
