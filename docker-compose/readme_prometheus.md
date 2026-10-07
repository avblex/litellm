# LiteLLM Proxy: метрики Prometheus и дашборд Grafana

Как устроен сбор метрик в этой установке (docker-compose, образ 1.102.0), как
подключить Prometheus и почему дашборд может быть пустым даже когда данные есть

## Два эндпоинта /metrics

- `:4000/metrics` - основной порт, требует авторизацию: любой валидный виртуальный
  ключ в `Authorization: Bearer ...`, роли не проверяются. Роль `internal_user`
  со своим ключом тоже сможет скрейпить глобальные метрики. Отключить проверку:
  `litellm_settings.require_auth_for_metrics_endpoint: false`
- `:4001/metrics` - отдельный процесс-сайдкар без авторизации вообще, для
  внутреннего скрейпинга Prometheus. Включается флагом `--prometheus_metrics_port`
  в `command:` сервиса (см. docker-compose.yml). В `command:` каждый флаг отдельным
  элементом списка: одной строкой `"--config=... --prometheus_metrics_port 4001"`
  не работает - click примет её целиком как путь конфига и упадёт с
  `Config file not found`

Сайдкар читает счётчики из `PROMETHEUS_MULTIPROC_DIR` (директорию создаёт сам CLI)
и агрегирует по всем воркерам. При старте в логе должна быть строка
`LiteLLM: Serving Prometheus metrics on 0.0.0.0:4001/metrics`. Порт опубликован
как `4001:4001`

Метрики создаются лениво: серии появляются в выводе только после первого реального
запроса через прокси. Проверка:

```bash
curl -s http://<host>:4001/metrics | grep -c litellm_
```

## Scrape-конфиг Prometheus

```yaml
  - job_name: 'litellm-proxy'
    metrics_path: '/metrics/'
    scrape_interval: 15s
    static_configs:
      - targets: ['192.168.75.16:4001']
        labels:
          hostname: 'litellm-int'
    relabel_configs:
      - source_labels: [hostname]
        target_label: instance
```

`relabel_configs` нужен, чтобы в лейбле `instance` было человекочитаемое имя хоста
вместо `ip:port`: Prometheus всегда проставляет `instance` равным адресу цели, а
произвольный лейбл из `static_configs` лежит рядом и панели дашборда не видит

## Дашборд Grafana (ID 24965) и грабли пустых панелей

Официальный дашборд LiteLLM строится на переменных `job` / `instance` / `model`.
Типичные причины, при которых данные в Prometheus есть, а панели пустые:

1. Переменные определены через `label_values(litellm_proxy_total_requests_metric_created, job)`.
   Серия `..._created` существует только в однопросовом режиме; сайдкар на 4001
   отдаёт метрики через `MultiProcessCollector`, у которого created-таймстампы
   выключены, поэтому переменные пустеют и все запросы панелей
   (`job=~"$job", instance=~"$instance"`) не матчат ничего. Лечится правкой
   переменных в Settings -> Variables на метрику без `_created`:
   `label_values(litellm_proxy_total_requests_metric_total, job)` (то же для `instance`)
2. Не выбрана переменная `datasource` вверху дашборда после импорта
3. `rate(...)` по данным, которые появились меньше часа назад - расширить диапазон времени
4. Версия дашборда не соответствует версии LiteLLM - сверить имена метрик с
   `curl -s http://<host>:4001/metrics | grep '^# TYPE'`

Стоимость (панели Spend) появляется только на запросах со стоимостью: для
эмбеддингов ответ провайдера должен нести `usage.prompt_tokens`, для TTS цена
считается по символам текста запроса через `input_cost_per_character` из `model_info`
в model_list (см. litellm_config.yaml.example)

## Порядок диагностики пустого дашборда

1. `curl -s http://<host>:4001/metrics | grep -c litellm_` после пробного запроса - источник жив?
2. `http://<prometheus>:9090/targets` - цель UP? `401` значит скрейпит 4000 без токена
3. `http://<prometheus>:9090/graph` - запрос `litellm_proxy_total_requests_metric_total` возвращает серии?
4. Панель -> Edit -> скопировать expr в Explore; пусто в Explore - расхождение имён/лейблов
   с шага выше, есть данные в Explore - переменные дашборда (datasource, job, instance)
