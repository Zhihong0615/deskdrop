#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
applications_dir="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
pin_dock=0

case "${1:-}" in
  "") ;;
  --pin-dock) pin_dock=1 ;;
  *)
    echo "Usage: $0 [--pin-dock]" >&2
    exit 2
    ;;
esac

mkdir -p "$applications_dir"

desktop_quote() {
  local value=${1//\\/\\\\}
  value=${value//\"/\\\"}
  printf '"%s"' "$value"
}

install_entry() {
  local id=$1 name=$2 comment=$3 icon=$4 script=$5
  shift 5
  local exec_line temp_file arg
  exec_line="$(desktop_quote "$project_dir/$script")"
  for arg in "$@"; do
    exec_line+=" $arg"
  done
  temp_file="$(mktemp "$applications_dir/.deskdrop.XXXXXX")"
  cat > "$temp_file" <<EOF
[Desktop Entry]
Type=Application
Name=$name
Comment=$comment
Exec=$exec_line
Icon=$project_dir/$icon
Terminal=false
Categories=Network;
StartupNotify=true
EOF
  chmod 644 "$temp_file"
  mv -f "$temp_file" "$applications_dir/$id.desktop"
}

install_entry deskdrop 'DeskDrop' 'Open the native DeskDrop chat and file room' deskdrop.svg deskdrop-app.sh --host
install_entry deskdrop-send 'DeskDrop on this computer' 'Open the native DeskDrop chat room' deskdrop.svg deskdrop-app.sh
install_entry deskdrop-install-receiver-autostart 'Install DeskDrop Receiver Autostart' 'Start the file receiver automatically after login' deskdrop.svg install-autostart.sh receiver
install_entry deskdrop-install-sender-autostart 'Install DeskDrop Client Autostart' 'Open the native chat room automatically after login' deskdrop.svg install-autostart.sh sender
install_entry deskdrop-remove-autostart 'Remove DeskDrop Autostart' 'Disable DeskDrop automatic startup' deskdrop.svg remove-autostart.sh
rm -f "$applications_dir/deskdrop-configure-sender.desktop"

if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$applications_dir" >/dev/null 2>&1 || true
fi

if (( pin_dock )); then
  if ! command -v gsettings >/dev/null 2>&1 || ! gsettings list-schemas | grep -qx org.gnome.shell; then
    echo 'Dock pinning is available on GNOME desktops only.' >&2
    exit 1
  fi
  favorites="$(gsettings get org.gnome.shell favorite-apps)"
  if [[ "$favorites" != *"'deskdrop.desktop'"* ]]; then
    if [[ "$favorites" == '@as []' ]]; then
      favorites="['deskdrop.desktop']"
    else
      favorites="${favorites%]}, 'deskdrop.desktop']"
    fi
    gsettings set org.gnome.shell favorite-apps "$favorites"
  fi
fi

echo "Installed DeskDrop launchers in $applications_dir"
echo 'Search for DeskDrop in the applications menu to open the native chat and file room.'
if (( pin_dock )); then
  echo 'DeskDrop has been added to the GNOME Dock favorites.'
else
  echo 'Run this script with --pin-dock to add DeskDrop to the GNOME Dock.'
fi
