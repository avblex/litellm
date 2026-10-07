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

# fix DB collation version mismatch

После смены образа БД (например, `postgres:16` на bookworm с glibc 2.36 ->
`postgres:16.14` на trixie с glibc 2.41) лог Postgres предупреждает на каждое
подключение: `database "..." has a collation version mismatch ... created using
collation version 2.36, but the operating system provides version 2.41`.
Правила сортировки даёт libc, Postgres запоминает её версию при initdb, а новые
индексы строятся по правилам текущей libc. Предупреждения появляются по каждой БД
(`litellm`, `postgres`, `template1`)

Лечение: перестроить индексы текущими правилами и обновить запомненную версию,
для каждой базы своей командой:

```bash
docker compose exec db psql -U litellm -d litellm -c 'REINDEX DATABASE litellm;' -c 'ALTER DATABASE litellm REFRESH COLLATION VERSION;'
docker compose exec db psql -U litellm -d postgres -c 'REINDEX DATABASE postgres;' -c 'ALTER DATABASE postgres REFRESH COLLATION VERSION;'
docker compose exec db psql -U litellm -d template1 -c 'REINDEX DATABASE template1;' -c 'ALTER DATABASE template1 REFRESH COLLATION VERSION;'
```

Альтернатива без REINDEX: остаться на старой libc, запинить
`image: postgres:16.14-bookworm`, тогда метаданные совпадут с библиотекой сами
