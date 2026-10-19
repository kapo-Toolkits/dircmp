#!/usr/bin/env bash
# Install (or remove) a dircmp launcher for the current user:
# application menu entry, icon, and optionally a desktop shortcut.
#
#   packaging/linux/install-launcher.sh [--exec PATH] [--no-desktop]
#   packaging/linux/install-launcher.sh --uninstall
#
# By default the launcher runs the repo's dircmp.sh (which sets itself up on first
# use), falling back to a dircmp-gui found on PATH.
set -euo pipefail

APP_ID="io.github.kapo_toolkits.dircmp"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ICON_SRC="$REPO_DIR/dircmp/gui/resources/dircmp.svg"
DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
APPS_DIR="$DATA_HOME/applications"
ICON_DIR="$DATA_HOME/icons/hicolor/scalable/apps"
DESKTOP_DIR="$(xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Desktop")"

exec_path=""
want_desktop=1
uninstall=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        --exec) exec_path="$2"; shift 2 ;;
        --no-desktop) want_desktop=0; shift ;;
        --uninstall) uninstall=1; shift ;;
        -h|--help) sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
done

refresh() {
    command -v update-desktop-database >/dev/null && update-desktop-database -q "$APPS_DIR" || true
    command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -q -t "$DATA_HOME/icons/hicolor" || true
}

if [[ $uninstall -eq 1 ]]; then
    rm -f "$APPS_DIR/$APP_ID.desktop" "$ICON_DIR/$APP_ID.svg" "$DESKTOP_DIR/$APP_ID.desktop"
    refresh
    echo "dircmp launcher removed."
    exit 0
fi

if [[ -z "$exec_path" ]]; then
    if [[ -x "$REPO_DIR/dircmp.sh" ]]; then
        exec_path="$REPO_DIR/dircmp.sh"
    elif command -v dircmp-gui >/dev/null; then
        exec_path="$(command -v dircmp-gui)"
    else
        echo "dircmp-gui not found. Install first: python -m venv .venv && .venv/bin/pip install -e '.[gui]'" >&2
        exit 1
    fi
fi

mkdir -p "$APPS_DIR" "$ICON_DIR"
install -m 644 "$ICON_SRC" "$ICON_DIR/$APP_ID.svg"

entry="$APPS_DIR/$APP_ID.desktop"
cat > "$entry" <<EOF
[Desktop Entry]
Type=Application
Name=dircmp
GenericName=Folder Comparison
GenericName[ka]=საქაღალდეების შედარება
Comment=Deep comparison of two or more folders
Comment[ka]=ორი, სამი და მეტი საქაღალდის სიღრმისეული შედარება
Exec="$exec_path" %F
Icon=$APP_ID
Terminal=false
Categories=Utility;FileTools;
Keywords=compare;diff;folder;directory;backup;შედარება;საქაღალდე;
StartupWMClass=dircmp
EOF
chmod 755 "$entry"
echo "menu entry: $entry"

if [[ $want_desktop -eq 1 && -d "$DESKTOP_DIR" ]]; then
    shortcut="$DESKTOP_DIR/$APP_ID.desktop"
    install -m 755 "$entry" "$shortcut"
    # XFCE and GNOME only run desktop launchers they consider trusted.
    if command -v gio >/dev/null; then
        gio set -t string "$shortcut" metadata::xfce-exe-checksum "$(sha256sum "$shortcut" | cut -d' ' -f1)" 2>/dev/null || true
        gio set "$shortcut" metadata::trusted true 2>/dev/null || true
    fi
    echo "desktop shortcut: $shortcut"
fi

refresh
echo "launcher runs: $exec_path"

# Qt >= 6.5 needs libxcb-cursor on X11; without it the window never appears.
ld_cache=$("$(command -v ldconfig || echo /sbin/ldconfig)" -p 2>/dev/null || true)
if [[ "${XDG_SESSION_TYPE:-x11}" != "wayland" && "$ld_cache" != *libxcb-cursor.so.0* ]]; then
    echo
    echo "WARNING: libxcb-cursor0 is missing, so the Qt GUI cannot start on X11. Install it:"
    echo "  sudo apt install libxcb-cursor0      # Debian/Ubuntu/Mint"
    echo "  sudo dnf install xcb-util-cursor     # Fedora"
fi
