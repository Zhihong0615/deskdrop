#!/usr/bin/env bash
set -euo pipefail

config_dir="${XDG_CONFIG_HOME:-$HOME/.config}/deskdrop"
url_file="$config_dir/receiver.url"
configure=0
allow_prompt=1
for arg in "$@"; do
  [[ "$arg" == '--configure' ]] && configure=1
  [[ "$arg" == '--no-prompt' ]] && allow_prompt=0
done

prompt_for_url() {
  local current="${1:-}" value
  if command -v zenity >/dev/null 2>&1 && [[ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]]; then
    value=$(zenity --entry --title='DeskDrop 接收端' --text='输入工位电脑显示的局域网地址：' --entry-text="$current") || exit 0
  else
    read -r -p '输入工位电脑显示的局域网地址（例如 http://deskpc.local:8787）：' value
  fi
  value=${value%/}
  if [[ ! "$value" =~ ^http://[a-zA-Z0-9.-]+(:[0-9]{1,5})?$ ]]; then
    echo '地址格式不正确。请输入类似 http://192.168.1.20:8787 的局域网地址。' >&2
    exit 1
  fi
  mkdir -p "$config_dir"
  printf '%s\n' "$value" > "$url_file"
  chmod 600 "$url_file"
  printf '已保存接收地址：%s\n' "$value"
}

current_url=''
[[ -f "$url_file" ]] && current_url=$(head -n 1 "$url_file")
if (( configure )) || [[ -z "$current_url" ]]; then
  if (( ! allow_prompt )); then
    echo 'DeskDrop 接收地址尚未配置。先运行 Configure DeskDrop Sender.desktop。' >&2
    exit 1
  fi
  prompt_for_url "$current_url"
  current_url=$(head -n 1 "$url_file")
fi

if command -v xdg-open >/dev/null 2>&1; then
  xdg-open "$current_url" >/dev/null 2>&1 &
else
  echo "请在浏览器打开：$current_url"
fi
