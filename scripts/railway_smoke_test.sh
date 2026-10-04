#!/usr/bin/env bash
set -Eeuo pipefail

# Full post-deploy smoke test for the Xiantu AI Railway service.
# It creates a temporary smoke-test account by default, exercises the authenticated
# API surface, deletes the temporary product, and leaves one generation record when
# generation is enabled. Set SMOKE_SKIP_GENERATION=true to avoid Qwen/API cost.
BASE_URL="${1:-${RAILWAY_URL:-}}"
TIMEOUT="${SMOKE_TIMEOUT_SECONDS:-30}"
AUTH_MODE="${SMOKE_AUTH_MODE:-register}"
EMAIL="${SMOKE_EMAIL:-smoke-$(date +%s)-$RANDOM@example.invalid}"
PASSWORD="${SMOKE_PASSWORD:-SmokeTest-$(date +%s)-$RANDOM}"
DISPLAY_NAME="${SMOKE_DISPLAY_NAME:-Railway Smoke Test}"
SKIP_GENERATION="${SMOKE_SKIP_GENERATION:-false}"
TMP_DIR="$(mktemp -d)"
TOKEN=""
PRODUCT_ID=""
GENERATION_ID=""

cleanup() { rm -rf "$TMP_DIR"; }
trap cleanup EXIT

if [[ -z "$BASE_URL" ]]; then
  echo "用法: $0 https://你的-app.up.railway.app" >&2
  echo "也可以设置 RAILWAY_URL 环境变量。" >&2
  exit 2
fi
BASE_URL="${BASE_URL%/}"

fail() { echo "Smoke test failed: $*" >&2; exit 1; }

request() {
  local method="$1" path="$2" body="${3:-}"
  local response_file="$TMP_DIR/response.json"
  local status
  local -a args=(--silent --show-error --location --max-time "$TIMEOUT" -X "$method" -H 'Accept: application/json')
  [[ -n "$TOKEN" ]] && args+=(-H "Authorization: Bearer $TOKEN")
  if [[ -n "$body" ]]; then
    args+=(-H 'Content-Type: application/json' --data "$body")
  fi
  status="$(curl "${args[@]}" -o "$response_file" -w '%{http_code}' "$BASE_URL$path")" || fail "$method $path: network error"
  cp "$response_file" "$TMP_DIR/last.json"
  if [[ "$status" -lt 200 || "$status" -ge 300 ]]; then
    echo "--- $method $path returned HTTP $status ---" >&2
    cat "$response_file" >&2 || true
    fail "$method $path"
  fi
}

json_value() {
  local expression="$1"
  python3 - "$TMP_DIR/last.json" "$expression" <<'PY'
import json
import sys
path, expression = sys.argv[1:]
with open(path, encoding="utf-8") as handle:
    value = json.load(handle)
for part in expression.split('.'):
    if isinstance(value, list):
        value = value[int(part)]
    else:
        value = value.get(part)
print("" if value is None else value)
PY
}

json_length() {
  local expression="$1"
  python3 - "$TMP_DIR/last.json" "$expression" <<'PY'
import json
import sys
path, expression = sys.argv[1:]
with open(path, encoding="utf-8") as handle:
    value = json.load(handle)
for part in expression.split('.'):
    value = value[int(part)] if isinstance(value, list) else value.get(part)
if not isinstance(value, list):
    raise SystemExit(f"{expression} is not a JSON array")
print(len(value))
PY
}

assert_status() {
  local expected="$1" actual
  actual="$(json_value status)"
  [[ "$actual" == "$expected" ]] || fail "expected status=$expected, got status=$actual"
}

make_json() {
  python3 - "$@" <<'PY'
import json
import sys
print(json.dumps(dict(zip(sys.argv[1::2], sys.argv[2::2])), ensure_ascii=False))
PY
}

printf 'Railway smoke test: %s\n' "$BASE_URL"

request GET /readyz
assert_status ready
echo '✓ /readyz'

request GET /api/health
assert_status ok
echo "✓ /api/health (qwen_configured=$(json_value qwen_configured))"

if [[ "$AUTH_MODE" == "login" ]]; then
  [[ -n "${SMOKE_EMAIL:-}" && -n "${SMOKE_PASSWORD:-}" ]] || fail 'SMOKE_AUTH_MODE=login requires SMOKE_EMAIL and SMOKE_PASSWORD'
  auth_body="$(make_json email "$EMAIL" password "$PASSWORD")"
  request POST /api/auth/login "$auth_body"
else
  auth_body="$(make_json email "$EMAIL" password "$PASSWORD" display_name "$DISPLAY_NAME")"
  request POST /api/auth/register "$auth_body"
fi
TOKEN="$(json_value access_token)"
[[ -n "$TOKEN" ]] || fail 'authentication response did not contain access_token'
echo "✓ authentication ($AUTH_MODE)"

request GET /api/auth/me
[[ "$(json_value email)" == "$EMAIL" ]] || fail '/api/auth/me returned a different account'
echo '✓ /api/auth/me'

product_name="Railway Smoke $RANDOM"
product_body="$(python3 - "$product_name" <<'PY'
import json
import sys
print(json.dumps({"name": sys.argv[1], "origin": "Smoke Test Farm", "spec": "1kg", "tags": ["测试", "新鲜"], "image_url": None}, ensure_ascii=False))
PY
)"
request POST /api/products "$product_body"
PRODUCT_ID="$(json_value id)"
[[ -n "$PRODUCT_ID" ]] || fail 'product response did not contain id'
echo '✓ create product'

query="$(python3 - "$product_name" <<'PY'
from urllib.parse import quote
import sys
print(quote(sys.argv[1]))
PY
)"
request GET "/api/products?q=$query"
[[ "$(json_length items)" -ge 1 ]] || fail 'created product not found in product list'
echo '✓ list/search products'

update_body='{"tags":["测试","已更新"]}'
request PUT "/api/products/$PRODUCT_ID" "$update_body"
[[ "$(json_value id)" == "$PRODUCT_ID" ]] || fail 'updated product id mismatch'
echo '✓ update product'

request GET /api/templates
[[ "$(json_length items)" -ge 1 ]] || fail 'template library is empty'
echo '✓ templates'

request GET /api/help?q=%E5%8D%83%E9%97%AE
[[ "$(json_length items)" -ge 1 ]] || fail 'help center search returned no Qwen article'
echo '✓ help center search'

if [[ "$SKIP_GENERATION" == "true" ]]; then
  echo '· generation skipped (SMOKE_SKIP_GENERATION=true)'
else
  generation_body="$(python3 - "$PRODUCT_ID" <<'PY'
import json
import sys
print(json.dumps({"product_id": sys.argv[1], "usage": "hero", "style": "natural"}))
PY
)"
  request POST /api/generations "$generation_body"
  [[ "$(json_value status)" == "completed" ]] || fail 'generation did not complete'
  [[ "$(json_value assets.0.image)" == http* ]] || fail 'generation did not return an image URL'
  GENERATION_ID="$(json_value id)"
  echo "✓ generation ($GENERATION_ID)"

  request GET /api/generations
  [[ "$(json_value total)" == '' || "$(json_value items.0.id)" == "$GENERATION_ID" ]] || true
  [[ "$(json_value items.0.id)" == "$GENERATION_ID" ]] || fail 'new generation not found in history'
  echo '✓ generation history'

  request GET /api/assets
  [[ "$(json_length items)" -ge 5 ]] || fail 'generated assets not found in library'
  echo '✓ asset library'
fi

request DELETE "/api/products/$PRODUCT_ID"
[[ "$(json_value deleted)" == "True" || "$(json_value deleted)" == "true" ]] || fail 'product deletion was not confirmed'
echo '✓ delete smoke product'

echo 'Railway smoke test passed.'
if [[ -n "$GENERATION_ID" ]]; then
  echo "Note: generation $GENERATION_ID remains as a smoke-test history record."
fi
