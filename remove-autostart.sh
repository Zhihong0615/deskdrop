#!/usr/bin/env bash
set -euo pipefail

if command -v systemctl >/dev/null 2>&1 && systemctl --user show-environment >/dev/null 2>&1; then
  systemctl --user disable --now deskdrop.service >/dev/null 2>&1 || true
  rm -f "${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/deskdrop.service"
  rm -f "${XDG_BIN_HOME:-$HOME/.local/bin}/deskdrop-service-start"
  systemctl --user daemon-reload || true
fi
rm -f "${XDG_CONFIG_HOME:-$HOME/.config}/autostart/deskdrop-sender.desktop"
echo 'DeskDrop autostart has been removed. Saved PIN, receiver URL, files, and login sessions were kept.'
