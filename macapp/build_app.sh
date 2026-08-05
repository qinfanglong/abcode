#!/bin/bash
# ABcode Mac App 打包脚本
# 用法: ./macapp/build_app.sh
set -e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP_NAME="ABcode"
BUILD_DIR="$ROOT/macapp/build"
APP_DIR="$BUILD_DIR/$APP_NAME.app"
VERSION="0.2.0"

echo "=== 1. 编译 Swift 壳 ==="
mkdir -p "$BUILD_DIR"
xcrun swiftc "$ROOT/macapp/main.swift" \
  -o "$BUILD_DIR/ABcode-bin" \
  -framework Cocoa -framework WebKit \
  -Xlinker -sectcreate -Xlinker __TEXT -Xlinker __info_plist -Xlinker "$ROOT/macapp/Info.plist" \
  -O 2>&1 | tail -5

echo "=== 2. 构建 App 目录结构 ==="
rm -rf "$APP_DIR"
mkdir -p "$APP_DIR/Contents/MacOS"
mkdir -p "$APP_DIR/Contents/Resources/backend"
mkdir -p "$APP_DIR/Contents/Resources/frontend"
mkdir -p "$APP_DIR/Contents/Resources/site-packages"

cp "$BUILD_DIR/ABcode-bin" "$APP_DIR/Contents/MacOS/$APP_NAME"
cp "$ROOT/macapp/Info.plist" "$APP_DIR/Contents/Info.plist"
if [ -f "$ROOT/macapp/AppIcon.icns" ]; then
  cp "$ROOT/macapp/AppIcon.icns" "$APP_DIR/Contents/Resources/AppIcon.icns"
  /usr/libexec/PlistBuddy -c "Add :CFBundleIconFile string AppIcon" "$APP_DIR/Contents/Info.plist" 2>/dev/null || \
  /usr/libexec/PlistBuddy -c "Set :CFBundleIconFile AppIcon" "$APP_DIR/Contents/Info.plist" 2>/dev/null || true
fi

echo "=== 3. 复制后端代码 ==="
cp "$ROOT/backend/"*.py "$APP_DIR/Contents/Resources/backend/"
echo "backend 文件: $(ls "$APP_DIR/Contents/Resources/backend" | wc -l | tr -d ' ')"

echo "=== 4. 复制前端 ==="
cp "$ROOT/frontend/"*.html "$ROOT/frontend/"*.css "$ROOT/frontend/"*.js \
  "$APP_DIR/Contents/Resources/frontend/"
echo "frontend 文件: $(ls "$APP_DIR/Contents/Resources/frontend" | wc -l | tr -d ' ')"

echo "=== 5. 复制 Python 依赖 (site-packages) ==="
SP="$ROOT/.venv/lib/python3.9/site-packages"
if [ -d "$SP" ]; then
  # 排除大体积/无关包，加速拷贝
  cp -R "$SP"/* "$APP_DIR/Contents/Resources/site-packages/" 2>/dev/null || true
  # 清理不需要的
  rm -rf "$APP_DIR/Contents/Resources/site-packages"/{pip,setuptools,*.dist-info/*.pyc} 2>/dev/null || true
  echo "site-packages: $(du -sh "$APP_DIR/Contents/Resources/site-packages" | cut -f1)"
else
  echo "!! 未找到 venv site-packages，App 将依赖系统 Python 环境"
fi

echo "=== 6. 签名（adhoc）==="
codesign --force --deep --sign - "$APP_DIR" 2>&1 | tail -1 || true

echo "=== 7. 压缩为 zip ==="
cd "$BUILD_DIR"
rm -f "$APP_NAME-mac-$VERSION.zip"
zip -rqy "$APP_NAME-mac-$VERSION.zip" "$APP_NAME.app"
ZIP_SIZE=$(du -h "$APP_NAME-mac-$VERSION.zip" | cut -f1)
echo "=== 完成: $BUILD_DIR/$APP_NAME-mac-$VERSION.zip ($ZIP_SIZE) ==="
