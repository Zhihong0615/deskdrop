#!/usr/bin/env bash
set -euo pipefail
script_dir="$(cd "$(dirname "$0")" && pwd -P)"
if ! python3 -c 'import gi; gi.require_version("Gtk", "4.0"); from gi.repository import Gtk' >/dev/null 2>&1; then
  message='DeskDrop 需要 GTK 4 和 Python GObject。请在 Ubuntu 安装 python3-gi 与 gir1.2-gtk-4.0。'
  if command -v zenity >/dev/null 2>&1; then
    zenity --error --title='DeskDrop' --text="$message" 2>/dev/null || true
  else
    printf '%s\n' "$message" >&2
  fi
  exit 1
fi
exec "$script_dir/deskdrop-client.py" "$@"
