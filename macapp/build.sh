#!/bin/zsh
# Costruisce Quantizer.app (finestra nativa per la GUI) in macapp/build/.
# Uso: macapp/build.sh            -> solo build
#      macapp/build.sh --install  -> build e copia in /Applications (Launchpad)
set -euo pipefail

cd "$(dirname "$0")"
ROOT="$(cd .. && pwd)"
APP="build/Quantizer.app"

echo "▸ Compilo l'app…"
rm -rf build
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources" build/tools
swiftc -O -o "$APP/Contents/MacOS/Quantizer" main.swift -framework Cocoa -framework WebKit

echo "▸ Disegno l'icona…"
swiftc -O -o build/tools/make-icon make-icon.swift -framework AppKit
build/tools/make-icon build/icon-1024.png >/dev/null
mkdir -p build/AppIcon.iconset
for s in 16 32 128 256 512; do
  sips -z $s $s build/icon-1024.png --out "build/AppIcon.iconset/icon_${s}x${s}.png" >/dev/null
  sips -z $((s * 2)) $((s * 2)) build/icon-1024.png --out "build/AppIcon.iconset/icon_${s}x${s}@2x.png" >/dev/null
done
iconutil -c icns build/AppIcon.iconset -o "$APP/Contents/Resources/AppIcon.icns"

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key>               <string>Quantizer</string>
  <key>CFBundleDisplayName</key>        <string>Quantizer</string>
  <key>CFBundleIdentifier</key>         <string>com.giodex.quantizer</string>
  <key>CFBundleExecutable</key>         <string>Quantizer</string>
  <key>CFBundleIconFile</key>           <string>AppIcon</string>
  <key>CFBundlePackageType</key>        <string>APPL</string>
  <key>CFBundleVersion</key>            <string>1.0</string>
  <key>CFBundleShortVersionString</key> <string>1.0</string>
  <key>LSMinimumSystemVersion</key>     <string>14.0</string>
  <key>LSApplicationCategoryType</key>  <string>public.app-category.music</string>
  <key>NSHighResolutionCapable</key>    <true/>
  <key>NSAppTransportSecurity</key>
  <dict><key>NSAllowsLocalNetworking</key><true/></dict>
  <key>QuantizerRoot</key>              <string>${ROOT}</string>
</dict>
</plist>
PLIST

codesign --force --deep --sign - "$APP" >/dev/null 2>&1
echo "✓ $ROOT/macapp/$APP"

if [[ "${1:-}" == "--install" ]]; then
  rm -rf /Applications/Quantizer.app
  ditto "$APP" /Applications/Quantizer.app
  echo "✓ installata in /Applications/Quantizer.app"
fi
