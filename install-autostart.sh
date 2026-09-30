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
    if [[ ! -f "$env_file" ]]; then
      read -r -p '为接收端设置固定 PIN（直接回车会生成一个随机 PIN）：' pin
      if [[ -z "$pin" ]]; then
        pin=$(od -An -N4 -tu4 /dev/urandom | tr -d ' ')
        pin=$((pin % 900000 + 100000))
      fi
      if [[ ! "$pin" =~ ^[0-9]{4,12}$ ]]; then
        echo 'PIN 必须是 4–12 位数字。' >&2
        exit 1
      fi
      printf 'export TRANSFER_PIN=%q\n' "$pin" > "$env_file"
      chmod 600 "$env_file"
      echo "接收 PIN：$pin（已保存到 $env_file）"
    else
      # shellcheck disable=SC1090
      source "$env_file"
      echo "接收 PIN：${TRANSFER_PIN:-（配置文件中没有 PIN）}"
    fi

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
    "$project_dir/send-to-deskdrop.sh" --configure
    autostart_dir="${XDG_CONFIG_HOME:-$HOME/.config}/autostart"
    mkdir -p "$autostart_dir"
    sender_arg=$(desktop_escape "$project_dir/send-to-deskdrop.sh")
    cat > "$autostart_dir/deskdrop-sender.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=DeskDrop Sender
Comment=Open the configured DeskDrop receiver after login
Exec=/bin/bash $sender_arg --no-prompt
Terminal=false
X-GNOME-Autostart-enabled=true
EOF
    echo '发送端已配置为登录后自动打开接收页面。'
    ;;
  *)
    echo 'Usage: install-autostart.sh receiver|sender' >&2
    exit 2
    ;;
esac
