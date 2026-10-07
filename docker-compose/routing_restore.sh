#!/bin/bash
# Восстанавливает настройку fast/long на новом стенде из routing.dump.json.
# enable_pre_call_checks применяется только из config.yaml (см. шаг 2 ROUTING.md),
# остальное уходит в живой роутер через API. Перед прогоном поправьте api_base в дампе
# PROXY_URL=http://localhost:4000 ADMIN_KEY=*** ./routing_restore.sh
set -euo pipefail
: "${PROXY_URL:=http://localhost:4000}"
: "${ADMIN_KEY:?нужен ADMIN_KEY}"
dump=$(dirname "$0")/routing.dump.json

jq -c '.models[]' "$dump" | while read -r model; do
  echo "-> /model/new: $(jq -r .model_name <<<"$model")"
  curl -sf -X POST "$PROXY_URL/model/new" \
    -H "Authorization: Bearer $ADMIN_KEY" -H "Content-Type: application/json" \
    -d "$model" > /dev/null
done

echo "-> /config/update: router_settings"
jq '{router_settings: .router_settings}' "$dump" | curl -sf -X POST "$PROXY_URL/config/update" \
  -H "Authorization: Bearer $ADMIN_KEY" -H "Content-Type: application/json" \
  -d @- > /dev/null

echo "готово; проверьте GET /router/settings и GET /model/info"
