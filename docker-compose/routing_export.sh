#!/bin/bash
# Сохраняет настройку fast/long с рабочего стенда в routing.dump.json (рядом со скриптом).
# PROXY_URL=http://localhost:4000 ADMIN_KEY=*** ./routing_export.sh
set -euo pipefail
: "${PROXY_URL:=http://localhost:4000}"
: "${ADMIN_KEY:?нужен ADMIN_KEY}"

models=$(curl -sf "$PROXY_URL/model/info" -H "Authorization: Bearer $ADMIN_KEY")
settings=$(curl -sf "$PROXY_URL/router/settings" -H "Authorization: Bearer $ADMIN_KEY")

jq -n --argjson models "$models" --argjson settings "$settings" '{
  models: [$models.data
           | map(select(.model_info.db_model == true))
           | unique_by(.model_info.id)[]
           | {model_name, litellm_params,
              model_info: {max_input_tokens: .model_info.max_input_tokens}}],
  router_settings: {
    enable_pre_call_checks: $settings.current_values.enable_pre_call_checks,
    context_window_fallbacks: $settings.current_values.context_window_fallbacks,
    model_group_alias: $settings.current_values.model_group_alias
  }
}' > "$(dirname "$0")/routing.dump.json"

echo "сохранено: $(dirname "$0")/routing.dump.json"
