#!/usr/bin/env bash
set -Eeuo pipefail

# Check local Railway env files without printing secret values, and optionally
# check the deployed service's health and authenticated PayPal runtime status.
BASE_URL=""
ENV_FILE=""
TIMEOUT="${RAILWAY_ENV_CHECK_TIMEOUT_SECONDS:-20}"

usage() {
  cat <<'USAGE'
用法:
  ./scripts/check_railway_env.sh --file railway.env.example
  ./scripts/check_railway_env.sh --url https://your-app.up.railway.app
  ./scripts/check_railway_env.sh --file railway.env --url https://your-app.up.railway.app

本地文件检查不会输出任何 Secret 内容。线上 PayPal 配置检查需要通过环境变量提供
一个已有账户（不会自动注册、不会创建 PayPal 订单）：
  RAILWAY_CHECK_EMAIL='you@example.com' \
  RAILWAY_CHECK_PASSWORD='your-password' \
  ./scripts/check_railway_env.sh --url https://your-app.up.railway.app

也可以使用：
  RAILWAY_URL=https://your-app.up.railway.app ./scripts/check_railway_env.sh
USAGE
}

fail_count=0
warn_count=0
fail() { printf '✗ %s\n' "$*" >&2; fail_count=$((fail_count + 1)); }
pass() { printf '✓ %s\n' "$*"; }
warn() { printf '! %s\n' "$*"; warn_count=$((warn_count + 1)); }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --file) [[ $# -ge 2 ]] || { usage >&2; exit 2; }; ENV_FILE="$2"; shift 2 ;;
    --url) [[ $# -ge 2 ]] || { usage >&2; exit 2; }; BASE_URL="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *)
      if [[ -z "$BASE_URL" && "$1" == https://* ]]; then BASE_URL="$1"; shift
      else echo "未知参数: $1" >&2; usage >&2; exit 2; fi
      ;;
  esac
done
BASE_URL="${BASE_URL:-${RAILWAY_URL:-}}"
BASE_URL="${BASE_URL%/}"

if [[ -n "$ENV_FILE" ]]; then
  [[ -f "$ENV_FILE" ]] || { echo "环境变量文件不存在: $ENV_FILE" >&2; exit 2; }
  printf '%s\n' "--- 本地环境文件: $ENV_FILE ---"
  declare -A ENV_VALUES=()
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line#"${line%%[![:space:]]*}"}"
    [[ -z "$line" || "${line:0:1}" == '#' ]] && continue
    if [[ "$line" =~ ^([A-Za-z_][A-Za-z0-9_]*)[[:space:]]*=[[:space:]]*(.*)$ ]]; then
      key="${BASH_REMATCH[1]}"
      value="${BASH_REMATCH[2]}"
      value="${value%$'\r'}"
      value="${value#\"}"; value="${value%\"}"
      value="${value#'}"; value="${value%'}"
      ENV_VALUES["$key"]="$value"
    fi
  done < "$ENV_FILE"

  required=(
    ENVIRONMENT DEBUG DATABASE_URL PGSSLMODE JWT_SECRET JWT_EXPIRE_MINUTES
    AUTO_CREATE_SCHEMA SEED_DEMO_USER LOCAL_STORAGE_DIR CORS_ORIGINS
    SMTP_HOST SMTP_PORT SMTP_USERNAME SMTP_PASSWORD SMTP_FROM SMTP_STARTTLS SMTP_TIMEOUT_SECONDS
    QWEN_API_KEY QWEN_BASE_URL QWEN_IMAGE_BASE_URL QWEN_VISION_MODEL
    QWEN_IMAGE_MODEL QWEN_IMAGE_SIZE QWEN_TIMEOUT_SECONDS QWEN_MOCK_FALLBACK
    PAYPAL_BASE_URL PAYPAL_CLIENT_ID PAYPAL_CLIENT_SECRET PAYPAL_WEBHOOK_ID
    PAYPAL_CURRENCY PAYPAL_BRAND_NAME PUBLIC_APP_URL PAYPAL_MOCK_MODE PAYPAL_TIMEOUT_SECONDS
  )
  placeholders='请配置|请替换|你的 Railway|你的-app|<railway-domain>|example.com|your-|TODO|CHANGE_ME'
  for key in "${required[@]}"; do
    value="${ENV_VALUES[$key]-}"
    if [[ -z "$value" ]]; then fail "$key 未设置"; continue; fi
    if [[ "$value" =~ $placeholders ]]; then fail "$key 仍是占位值"; continue; fi
    pass "$key 已设置"
  done

  [[ -n "${ENV_VALUES[REDIS_URL]-}" ]] || warn 'REDIS_URL 未设置；认证和媒体限流仅在单进程内共享，多副本部署应配置 Redis'

  [[ "${ENV_VALUES[ENVIRONMENT]-}" == "production" ]] || fail "ENVIRONMENT 必须为 production"
  [[ "${ENV_VALUES[DEBUG]-}" == "false" ]] || fail "DEBUG 必须为 false"
  [[ "${ENV_VALUES[AUTO_CREATE_SCHEMA]-}" == "false" ]] || fail "AUTO_CREATE_SCHEMA 必须为 false"
  [[ "${ENV_VALUES[SEED_DEMO_USER]-}" == "false" ]] || fail "SEED_DEMO_USER 必须为 false"
  [[ "${ENV_VALUES[QWEN_MOCK_FALLBACK]-}" == "false" ]] || fail "QWEN_MOCK_FALLBACK 必须为 false"
  [[ "${ENV_VALUES[PAYPAL_MOCK_MODE]-}" == "false" ]] || fail "PAYPAL_MOCK_MODE 必须为 false"
  [[ "${ENV_VALUES[PAYPAL_BASE_URL]-}" == "https://api-m.paypal.com" ]] || fail "生产 PAYPAL_BASE_URL 必须为 https://api-m.paypal.com"
  [[ "${ENV_VALUES[SMTP_STARTTLS]-}" == "true" ]] || fail "SMTP_STARTTLS 必须为 true"
  [[ "${ENV_VALUES[PUBLIC_APP_URL]-}" == https://* ]] || fail "PUBLIC_APP_URL 必须是 HTTPS 地址"
  [[ "${ENV_VALUES[CORS_ORIGINS]-}" == https://* ]] || fail "CORS_ORIGINS 必须是 HTTPS 地址"
  [[ "${ENV_VALUES[JWT_SECRET]-}" != *'请替换'* && ${#ENV_VALUES[JWT_SECRET]} -ge 32 ]] || fail "JWT_SECRET 长度必须至少 32 位且不能是占位值"
  pass '生产安全开关和值校验完成'
fi

if [[ -n "$BASE_URL" ]]; then
  printf '%s\n' "--- 线上服务: $BASE_URL ---"
  [[ "$BASE_URL" == https://* ]] || fail '线上 BASE_URL 必须使用 HTTPS'
  TMP_DIR="$(mktemp -d)"
  trap 'rm -rf "$TMP_DIR"' EXIT
  get_json() {
    local path="$1" output="$TMP_DIR/response.json" status
    status="$(curl --silent --show-error --location --max-time "$TIMEOUT" -o "$output" -w '%{http_code}' -H 'Accept: application/json' "$BASE_URL$path")" || { fail "$path 网络请求失败"; return 1; }
    if [[ "$status" != 2* ]]; then fail "$path 返回 HTTP $status"; return 1; fi
    printf '%s\n' "$output"
  }
  check_status() {
    local path="$1" expected="$2" file
    file="$(get_json "$path")" || return
    python3 - "$file" "$path" "$expected" <<'PY' || { fail "$2 状态不是 $3"; return; }
import json, sys
with open(sys.argv[1], encoding='utf-8') as handle:
    payload = json.load(handle)
if payload.get('status') != sys.argv[3]:
    raise SystemExit(1)
PY
    pass "$path 返回 status=$expected"
  }
  check_storage_writable() {
    local file
    file="$(get_json '/api/health')" || return
    python3 - "$file" <<'PY' || { fail '/api/health storage_writable 不是 true'; return; }
import json, sys
with open(sys.argv[1], encoding='utf-8') as handle:
    payload = json.load(handle)
if payload.get('storage_writable') is not True:
    raise SystemExit(1)
PY
    pass '/api/health storage_writable=true'
  }
  check_status '/api/health' 'ok'
  check_storage_writable
  check_status '/readyz' 'ready'

  email="${RAILWAY_CHECK_EMAIL:-}"
  password="${RAILWAY_CHECK_PASSWORD:-}"
  if [[ -z "$email" || -z "$password" ]]; then
    warn '未提供 RAILWAY_CHECK_EMAIL/RAILWAY_CHECK_PASSWORD，跳过需登录的 PayPal 配置检查'
  else
    auth_file="$TMP_DIR/auth.json"
    auth_status="$(curl --silent --show-error --location --max-time "$TIMEOUT" -o "$auth_file" -w '%{http_code}' \
      -H 'Accept: application/json' -H 'Content-Type: application/json' \
      --data "$(python3 - "$email" "$password" <<'PY'
import json, sys
print(json.dumps({'email': sys.argv[1], 'password': sys.argv[2]}))
PY
)" "$BASE_URL/api/auth/login")" || { fail '线上登录请求失败'; auth_status=000; }
    if [[ "$auth_status" != 2* ]]; then
      fail "线上登录返回 HTTP $auth_status（不会输出密码或响应内容）"
    else
      token="$(python3 - "$auth_file" <<'PY'
import json, sys
with open(sys.argv[1], encoding='utf-8') as handle:
    print(json.load(handle).get('access_token', ''))
PY
)"
      if [[ -z "$token" ]]; then fail '登录响应未包含 access_token'; else
        config_file="$TMP_DIR/paypal.json"
        config_status="$(curl --silent --show-error --location --max-time "$TIMEOUT" -o "$config_file" -w '%{http_code}' \
          -H 'Accept: application/json' -H "Authorization: Bearer $token" "$BASE_URL/api/billing/paypal/config")"
        if [[ "$config_status" != 2* ]]; then
          fail "PayPal 配置接口返回 HTTP $config_status"
        else
          runtime="$(python3 - "$config_file" <<'PY'
import json, sys
with open(sys.argv[1], encoding='utf-8') as handle:
    config = json.load(handle)
print(f"{str(config.get('enabled', False)).lower()} {config.get('mode', '')}")
PY
)"
          if [[ "$runtime" == "true live" ]]; then pass '线上 PayPal runtime config 为 Live 且 enabled=true'; else fail '线上 PayPal runtime config 不是可用的 Live 模式（请检查 Client ID/Secret/Base URL）'; fi
        fi
      fi
    fi
  fi
fi

if [[ -z "$ENV_FILE" && -z "$BASE_URL" ]]; then usage >&2; exit 2; fi
printf '\n检查完成：%d 个错误，%d 个提示\n' "$fail_count" "$warn_count"
if (( fail_count > 0 )); then exit 1; fi
