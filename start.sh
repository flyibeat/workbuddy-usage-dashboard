#!/usr/bin/env sh
# ============================================================
#  WorkBuddy Token Usage Dashboard - macOS / Linux launcher
#
#  用法：
#      ./start.sh
#      ./start.sh --port 8800 --open
#      ./start.sh --rebuild          忽略缓存全量重扫
#
#  首次使用可能需要： chmod +x start.sh
# ============================================================
set -e
cd "$(dirname "$0")"

if command -v python3 >/dev/null 2>&1; then
  PY=python3
elif command -v python >/dev/null 2>&1; then
  PY=python
else
  echo "[x] 找不到 Python。请先安装 Python 3.8+。" >&2
  exit 1
fi

exec "$PY" usage_server.py "$@"
