# patch enterprise лицензии

`patch.py` правит исходники litellm внутри образа прямо при старте контейнера
(подключается через `docker-compose.override.yml` и `entrypoint.sh`):

- `litellm/proxy/auth/litellm_license.py` — `is_premium()` всегда возвращает `True`, проверка лицензии отключена
- `litellm/proxy/management_endpoints/ui_sso.py` — лимит SSO на free-тарифе поднят с 5 до 50 пользователей

Патч идемпотентен: повторный запуск пропускает уже исправленные файлы. Работает и со стоковым образом из registry, и с собранным локально, без пересборки

# nginx - для запуска https 

# fix DB verison
docker exec litellm-db psql -d litellm -U llmproxy -c "ALTER DATABASE litellm REFRESH COLLATION VERSION;"
