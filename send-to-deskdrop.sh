#!/usr/bin/env bash
set -euo pipefail
script_dir="$(cd "$(dirname "$0")" && pwd -P)"
exec "$script_dir/deskdrop-client.py" "$@"
