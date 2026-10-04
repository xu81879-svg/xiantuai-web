#!/usr/bin/env bash
set -Eeuo pipefail

BASE_URL="${1:-${RAILWAY_URL:-}}"
TIMEOUT="${HEALTHCHECK_TIMEOUT_SECONDS:-15}"

if [[ -z "$BASE_URL" ]]; then
  echo "用法: $0 https://你的-app.up.railway.app" >&2
  echo "也可以设置 RAILWAY_URL 环境变量。" >&2
  exit 2
fi
BASE_URL="${BASE_URL%/}"

check_json() {
  local path="$1"
  local expected="$2"
  local body
  body="$(curl --fail --silent --show-error --location --max-time "$TIMEOUT" \
    --header 'Accept: application/json' "$BASE_URL$path")"
  python3 - "$path" "$expected" "$body" <<'PY'
import json
import sys
path, expected, body = sys.argv[1:]
try:
    payload = json.loads(body)
except json.JSONDecodeError as exc:
    raise SystemExit(f"{path}: 非 JSON 响应: {exc}")
if payload.get("status") != expected:
    raise SystemExit(f"{path}: status={payload.get('status')!r}，期望 {expected!r}")
print(f"{path}: ok ({expected})")
PY
}

check_json "/api/health" "ok"
check_json "/readyz" "ready"
echo "Railway health check passed: $BASE_URL"
