#!/usr/bin/env bash
set -euo pipefail

project_dir=$(cd "$(dirname "$0")" && pwd)
mode="${1:-}"
config_dir="${XDG_CONFIG_HOME:-$HOME/.config}/deskdrop"
mkdir -p "$config_dir"

desktop_escape() {
  local value=$1
  value=${value//\\/\\\\}
  value=${value//\"/\\\"}
  value=${value//%/%%}
  printf '"%s"' "$value"
}

case "$mode" in
  receiver)
    if ! command -v systemctl >/dev/null 2>&1 || ! systemctl --user show-environment >/dev/null 2>&1; then
      echo 'This Linux session does not provide systemd user services.' >&2
      exit 1
    fi
    env_file="$config_dir/receiver.env"
    touch "$env_file"
    chmod 600 "$env_file"

    bin_dir="${XDG_BIN_HOME:-$HOME/.local/bin}"
    unit_dir="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
    mkdir -p "$bin_dir" "$unit_dir"
    wrapper="$bin_dir/deskdrop-service-start"
    printf '#!/usr/bin/env bash\nset -euo pipefail\ncd %q\nexec /bin/bash %q --no-browser\n' \
      "$project_dir" "$project_dir/start-deskdrop.sh" > "$wrapper"
    chmod 700 "$wrapper"
    wrapper_arg=$(desktop_escape "$wrapper")
    cat > "$unit_dir/deskdrop.service" <<EOF
[Unit]
Description=DeskDrop local file receiver
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/bin/bash $wrapper_arg
Restart=on-failure
RestartSec=3

[Install]
WantedBy=default.target
EOF
    systemctl --user daemon-reload
    systemctl --user enable --now deskdrop.service
    echo '接收端已加入登录自启并已启动。'
    echo "局域网地址：http://$(hostname -s).local:8787（若 mDNS 不可用，请运行 hostname -I 查看 IP）"
    echo '查看服务状态：systemctl --user status deskdrop.service'
    echo '查看地址和日志：journalctl --user -u deskdrop.service -n 30 --no-pager'
    ;;
  sender)
    autostart_dir="${XDG_CONFIG_HOME:-$HOME/.config}/autostart"
    mkdir -p "$autostart_dir"
    sender_arg=$(desktop_escape "$project_dir/send-to-deskdrop.sh")
    cat > "$autostart_dir/deskdrop-sender.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=DeskDrop Sender
Comment=Open the native DeskDrop chat room after login
Exec=/bin/bash $sender_arg --no-prompt
Terminal=false
X-GNOME-Autostart-enabled=true
EOF
    echo 'DeskDrop 聊天客户端已配置为登录后自动打开。'
    ;;
  *)
    echo 'Usage: install-autostart.sh receiver|sender' >&2
    exit 2
    ;;
esac
