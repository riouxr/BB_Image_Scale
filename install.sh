#!/usr/bin/env bash
# BB Image Scale — add the app to the desktop menu for the current user.
#   ./install.sh            install (uses dist/BBImageScale if built, else source)
#   ./install.sh --uninstall
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="$HOME/.local/bin"
APP_DIR="$HOME/.local/share/applications"
ICON_DIR="$HOME/.local/share/icons/hicolor/scalable/apps"

LAUNCHER="$BIN_DIR/bb-image-scale"
DESKTOP="$APP_DIR/bb-image-scale.desktop"
ICON="$ICON_DIR/bb-image-scale.svg"

if [[ "${1:-}" == "--uninstall" ]]; then
    rm -f "$LAUNCHER" "$DESKTOP" "$ICON"
    command -v update-desktop-database >/dev/null 2>&1 && \
        update-desktop-database "$APP_DIR" >/dev/null 2>&1 || true
    echo "[OK] BB Image Scale removed."
    exit 0
fi

mkdir -p "$BIN_DIR" "$APP_DIR" "$ICON_DIR"

if [[ -x "$HERE/dist/BBImageScale" ]]; then
    TARGET="$HERE/dist/BBImageScale"
    WMCLASS="BBImageScale"
    echo "[OK] Using the built binary: dist/BBImageScale"
else
    TARGET="$HERE/run.sh"
    WMCLASS="bb_image_scale.py"
    echo "[OK] Using the source launcher: run.sh  (run ./build_binary.sh for a standalone binary)"
fi

cat > "$LAUNCHER" <<LAUNCH
#!/usr/bin/env bash
exec "$TARGET" "\$@"
LAUNCH
chmod +x "$LAUNCHER"

install -m 644 "$HERE/bb-image-scale.svg" "$ICON"

sed -e "s|^Exec=.*|Exec=$LAUNCHER %F|" \
    -e "s|^StartupWMClass=.*|StartupWMClass=$WMCLASS|" \
    "$HERE/bb-image-scale.desktop" > "$DESKTOP"
chmod 644 "$DESKTOP"

command -v update-desktop-database >/dev/null 2>&1 && \
    update-desktop-database "$APP_DIR" >/dev/null 2>&1 || true
command -v gtk-update-icon-cache >/dev/null 2>&1 && \
    gtk-update-icon-cache -f -t "$HOME/.local/share/icons/hicolor" >/dev/null 2>&1 || true

echo "[OK] Installed:"
echo "     launcher  $LAUNCHER"
echo "     desktop   $DESKTOP"
echo "     icon      $ICON"
echo
case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *) echo "[NOTE] $BIN_DIR is not on your PATH — the menu entry still works." ;;
esac
echo "Look for \"BB Image Scale\" in the Activities menu, or drop files onto its icon."
