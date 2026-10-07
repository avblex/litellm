# patch enterprise лицензии

`patch.py` правит исходники litellm внутри образа прямо при старте контейнера
(подключается через `docker-compose.override.yml` и `entrypoint.sh`):

- `litellm/proxy/auth/litellm_license.py` — `is_premium()` всегда возвращает `True`, проверка лицензии отключена
- `litellm/proxy/management_endpoints/ui_sso.py` — лимит SSO на free-тарифе поднят с 5 до 50 пользователей

Патч идемпотентен: повторный запуск пропускает уже исправленные файлы. Работает и со стоковым образом из registry, и с собранным локально, без пересборки

# nginx - для запуска https

# метрики Prometheus

Порт 4000 отдаёт `/metrics` только с валидным ключом; для скрейпинга поднят
отдельный процесс без авторизации на 4001 (`--prometheus_metrics_port` в
`command:`). Подключение Prometheus, настройка дашборда Grafana и диагностика
пустых панелей: [readme_prometheus.md](readme_prometheus.md)

# миграция на новый хост

Инструкция в [readme_migration.md](readme_migration.md). Там же про совпадение
`LITELLM_SALT_KEY`/`MASTER_KEY`, восстановление дампа через `psql` и правку
зашифрованного `proxy_base_url` в SSO-конфиге. Образ БД пинить минорной версией
(`postgres:16.14`): дамп снятый pg_dump 16.14 не восстанавливается psql 16.9 из-за
`\restrict`/`\unrestrict`

# бюджеты пользователей и команд

Три слоя лимитов, сброс по `budget_duration`, типовые грабли — в
[../docs/budgets/README.md](../docs/budgets/README.md)

# fix DB verison
docker exec litellm-db psql -d litellm -U llmproxy -c "ALTER DATABASE litellm REFRESH COLLATION VERSION;"
