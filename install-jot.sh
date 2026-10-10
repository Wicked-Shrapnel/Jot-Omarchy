#!/bin/sh
set -eu

APP_NAME="Jot"
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
INSTALL_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/jot-app"
BIN_DIR="${XDG_BIN_HOME:-$HOME/.local/bin}"
DESKTOP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ICON_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/scalable/apps"

mkdir -p "$INSTALL_DIR" "$BIN_DIR" "$DESKTOP_DIR" "$ICON_DIR"
cp "$SCRIPT_DIR/jot.py" "$INSTALL_DIR/jot.py"
cp "$SCRIPT_DIR/launch-jot" "$INSTALL_DIR/launch-jot"
cp "$SCRIPT_DIR/jot.svg" "$ICON_DIR/jot.svg"
chmod +x "$INSTALL_DIR/launch-jot"
ln -sfn "$INSTALL_DIR/launch-jot" "$BIN_DIR/jot"

cat > "$DESKTOP_DIR/jot.desktop" <<EOF
[Desktop Entry]
Name=$APP_NAME
Comment=Lightweight colored notes
Exec=$INSTALL_DIR/launch-jot
Icon=jot
Terminal=false
Type=Application
Categories=Utility;Office;
StartupNotify=false
EOF

printf '%s\n' "Jot installed. Run it with: $BIN_DIR/jot"
printf '%s\n' "If $BIN_DIR is not in PATH, launch it from: $INSTALL_DIR/launch-jot"
