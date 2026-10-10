#!/bin/sh
set -eu

INSTALL_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/jot-app"
BIN_DIR="${XDG_BIN_HOME:-$HOME/.local/bin}"
DESKTOP_FILE="${XDG_DATA_HOME:-$HOME/.local/share}/applications/jot.desktop"
ICON_FILE="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/scalable/apps/jot.svg"

rm -rf "$INSTALL_DIR"
rm -f "$BIN_DIR/jot" "$DESKTOP_FILE" "$ICON_FILE"

printf '%s\n' "Jot application files removed."
printf '%s\n' "Your notes were kept in ${XDG_DATA_HOME:-$HOME/.local/share}/jot."
