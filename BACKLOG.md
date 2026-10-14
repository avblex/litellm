# Backlog

## Нормализовать api_base для MCP-вызовов в Prometheus-метриках

`litellm_deployment_state` и `litellm_deployment_failure_responses` получают `api_base` из standard logging payload как есть. Для MCP-инструментов с URL-шаблонами (например, searxng) это полный URL запроса с query-строкой: `http://searxng:8080/search?q=site%3Aunsplash.com+...&format=json`. Каждая уникальная query - новая time series, из-за чего кардинальность раздувается, а дашборд показывает псевдо-деплойменты на каждый запрос

Починить на стороне прокси: нормализовать `api_base` (отбрасывать query/fragment) перед логированием в Prometheus. Дашборд пока обходится `label_replace` в запросах панелей "Deployment State per Endpoint" и "Provider Failures per Endpoint", но это костыль на чтении, запись надо чинить

Место в коде: `litellm/integrations/prometheus.py`, `_sanitize_prometheus_label_value` и путь standard logging payload -> лейблы деплоймента
