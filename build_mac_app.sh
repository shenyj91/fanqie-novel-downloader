# macOS app 手动构建脚本（无需 PyInstaller，直接生成标准 .app 包）

#!/bin/bash
set -e

cd "$(dirname "$0")"
SRC="$(pwd)"
APP="dist/番茄短篇下载器.app"

echo "==> 清理旧构建"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

echo "==> 生成 Info.plist"
cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>CFBundleDevelopmentRegion</key>
	<string>zh_CN</string>
	<key>CFBundleDisplayName</key>
	<string>番茄短篇下载器</string>
	<key>CFBundleExecutable</key>
	<string>launcher</string>
	<key>CFBundleIdentifier</key>
	<string>local.syj.fanqie-short-downloader</string>
	<key>CFBundleInfoDictionaryVersion</key>
	<string>6.0</string>
	<key>CFBundleName</key>
	<string>番茄短篇下载器</string>
	<key>CFBundlePackageType</key>
	<string>APPL</string>
	<key>CFBundleShortVersionString</key>
	<string>1.0.0</string>
	<key>CFBundleVersion</key>
	<string>1</string>
	<key>LSMinimumSystemVersion</key>
	<string>12.0</string>
	<key>NSHighResolutionCapable</key>
	<true/>
	<key>NSPrincipalClass</key>
	<string>NSApplication</string>
	<key>LSUIElement</key>
	<false/>
</dict>
</plist>
PLIST

echo "==> 生成启动器"
cat > "$APP/Contents/MacOS/launcher" <<'LAUNCH'
#!/bin/bash
cd "$(dirname "$0")/../Resources"
CANDIDATES=(
  "/Users/syj/.workbuddy/binaries/python/versions/3.11.9/bin/python3"
  "/usr/bin/python3"
  "$(command -v python3 2>/dev/null)"
)
PY=""
for c in "${CANDIDATES[@]}"; do
  if [ -x "$c" ] && "$c" -c "import tkinter" >/dev/null 2>&1; then
    PY="$c"; break
  fi
done
if [ -z "$PY" ]; then
  osascript -e 'display alert "无法启动" message "未找到带 tkinter 的 Python 3，请安装 Python 3.9+"' >/dev/null 2>&1
  exit 1
fi
exec "$PY" gui_short.py "$@"
LAUNCH
chmod +x "$APP/Contents/MacOS/launcher"

echo "==> 拷贝代码"
cp gui_short.py "$APP/Contents/Resources/"
cp -r fanqie_core "$APP/Contents/Resources/"
find "$APP" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true

echo "==> 完成: $APP"
