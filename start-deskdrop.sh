#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

config_env="${XDG_CONFIG_HOME:-$HOME/.config}/deskdrop/receiver.env"
if [[ -f "$config_env" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$config_env"
  set +a
fi

open_browser=1
for arg in "$@"; do
  [[ "$arg" == '--no-browser' ]] && open_browser=0
done

is_supported_node() {
  command -v "$1" >/dev/null 2>&1 || return 1
  local version major
  version=$("$1" --version 2>/dev/null | sed 's/^v//') || return 1
  major=${version%%.*}
  [[ "$major" =~ ^[0-9]+$ ]] && (( major >= 18 ))
}

node_cmd=""
if is_supported_node node; then
  node_cmd="$(command -v node)"
else
  cache_dir="${XDG_CACHE_HOME:-$HOME/.cache}/deskdrop/runtime"
  portable_node="$cache_dir/node"
  if [[ -x "$portable_node" ]]; then
    node_cmd="$portable_node"
  else
    echo 'Preparing DeskDrop for first use (downloading the portable Node.js runtime)...'
    command -v curl >/dev/null 2>&1 || { echo 'curl is required for first-time setup.' >&2; exit 1; }
    os_name=$(uname -s)
    case "$os_name" in
      Linux) platform=linux ;;
      Darwin) platform=darwin ;;
      *) echo "Unsupported operating system: $os_name" >&2; exit 1 ;;
    esac
    machine=$(uname -m)
    case "$machine" in
      x86_64|amd64) arch=x64 ;;
      aarch64|arm64) arch=arm64 ;;
      *) echo "Unsupported processor architecture: $machine" >&2; exit 1 ;;
    esac
    mkdir -p "$cache_dir"
    temp_dir=$(mktemp -d)
    trap 'rm -rf "$temp_dir"' EXIT
    curl -fsSL --max-time 30 https://nodejs.org/dist/index.json -o "$temp_dir/index.json"
    version=$(sed -n '/"lts":"[^"]*"/{s/.*"version":"\([^"]*\)".*/\1/p;q;}' "$temp_dir/index.json")
    [[ -n "$version" ]] || { echo 'Could not find a current Node.js LTS release.' >&2; exit 1; }
    archive="node-$version-$platform-$arch.tar.xz"
    curl -fL --retry 2 --connect-timeout 15 "https://nodejs.org/dist/$version/$archive" -o "$temp_dir/$archive"
    tar -xJf "$temp_dir/$archive" -C "$temp_dir"
    cp "$temp_dir/node-$version-$platform-$arch/bin/node" "$portable_node"
    chmod +x "$portable_node"
    node_cmd="$portable_node"
    rm -rf "$temp_dir"
    trap - EXIT
    echo 'Runtime ready.'
  fi
fi

if (( open_browser )); then
  echo 'Opening DeskDrop in your browser. Keep this window open while receiving files.'
  (
    sleep 2
    case "$(uname -s)" in
      Darwin) open http://localhost:8787 >/dev/null 2>&1 || true ;;
      Linux) xdg-open http://localhost:8787 >/dev/null 2>&1 || true ;;
    esac
  ) &
else
  export DESKDROP_SERVICE=1
fi
"$node_cmd" server.js
