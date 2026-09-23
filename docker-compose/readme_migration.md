# LiteLLM Proxy: миграция на новый хост

Инструкция по переносу LiteLLM Proxy (docker-compose + Postgres) на другой хост
без «призраков» старой конфигурации (редирект логина на старый домен и т.п.).

## Что переезжает само, а что надо править

Переезжают вместе с каталогом/образами без изменений: `config.yaml`,
docker-томы, вся база Postgres.

Значения старого хоста могут быть **зашифрованы в БД** и поэтому не находятся
ни одним `grep` по дампу или файлам. Ищем их по таблицам:

| Где | Таблица / поле | Что хранит |
|---|---|---|
| SSO-конфиг | `LiteLLM_SSOConfig.sso_settings` → `proxy_base_url` | базовый URL UI; подставляется во ВСЕ редиректы после логина (и локального, и SSO), перезаписывает env `PROXY_BASE_URL` при старте |
| Секреты провайдеров | `LiteLLM_CredentialsTable.credential_values` | api_key / api_base (шифрованные) |
| Конфиг из UI | `LiteLLM_Config.param_value` | general/litellm/router settings |
| UI-настройки | `LiteLLM_UISettings.ui_settings` | флаги интерфейса |

Шифрование привязано к `LITELLM_SALT_KEY` (при его отсутствии — к `MASTER_KEY`).
Если на новом хосте ключ другой, все зашифрованные поля становятся нечитаемыми:
разделы UI пустеют, SSO и credentials «исчезают» (это не порча данных, а
несовпадение ключа).

## Порядок миграции

### 1. Ключи шифрования совпадают

В `docker-compose.yml` / env на новом хосте должны стоять те же
`LITELLM_SALT_KEY` и `MASTER_KEY`, что на старом:

```bash
docker exec litellm sh -c 'env | grep -E "LITELLM_SALT_KEY|MASTER_KEY"'
```

Если ключа нет в compose (задан только в рантайме) — взять из живого процесса
старого хоста: `/proc/<pid>/environ`.

### 2. Поднять стек и восстановить базу

```bash
docker compose up -d
# pg_dump со старого хоста:
docker exec -i litellm-db pg_restore -U litellm -d litellm --clean --if-exists < litellm.dump
docker restart litellm
```

### 3. Поправить `proxy_base_url` в SSO-конфиге (главный пункт)

Поле зашифровано, менять «в лоб» строкой в дампе нельзя, а **удалять ключ из
JSON нельзя** — загрузчик падает на отсутствующем поле и весь раздел SSO в UI
становится пустым. Правильно: сгенерировать новый шифр штатной функцией
LiteLLM внутри контейнера (ключ возьмёт из окружения, шифр совпадёт) и
подставить в JSON.

**3.1. Шифр нового значения:**

```bash
docker exec -it litellm python3 -c "
from litellm.proxy.common_utils.encrypt_decrypt_utils import encrypt_value_helper
print('NEW:  ', encrypt_value_helper('http://192.168.75.16:4000'))
print('EMPTY:', encrypt_value_helper(''))"
```

> Если вывод `env | grep` в п.1 был пустой — передать ключ явно:
> `encrypt_value_helper('http://...', 'ВАШ_КЛЮЧ')`.

**3.2. Подставить в БД** (тип колонки уточнить:
`select data_type from information_schema.columns where table_name='LiteLLM_SSOConfig' and column_name='sso_settings';`):

jsonb:

```sql
update "LiteLLM_SSOConfig"
set sso_settings = jsonb_set(sso_settings, '{proxy_base_url}', '"БАЗА64_ИЗ_П_3_1"')
where id = 'sso_config';
```

json / text:

```sql
update "LiteLLM_SSOConfig"
set sso_settings = ((sso_settings::jsonb - 'proxy_base_url' ||
     jsonb_build_object('proxy_base_url', 'БАЗА64_ИЗ_П_3_1'))::text)
where id = 'sso_config';
```

Если колонка оказалась повреждена (например, после `sso_settings - 'proxy_base_url'`) —
восстановить дамп и выполнить второй вариант запроса (он пересобирает JSON целиком).

**Проще вариант:** пока раздел SSO читается, открыть в UI Settings → SSO,
стереть/поменять поле «Proxy Base URL» и сохранить — приложение перепишет
строку и зашифрует текущим ключом само.

```bash
docker restart litellm
```

### 4. Проверка

```bash
# 1) Редирект после локального логина:
curl -si -X POST http://НОВЫЙ_IP:4000/login -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"***"}' -o /dev/null -D- | grep -i location
# ожидается location: http://НОВЫЙ_IP:4000/ui?login=success (или ваш новый домен)

# 2) Раздел SSO в UI наполнен (значит шифры читаются текущим ключом)
# 3) Пробный вход через Keycloak
```

## Диагностика «редиректит на старый хост» (шпаргалка)

Код редиректа: `get_custom_url()` в `proxy/utils.py` →
приоритет `os.getenv("PROXY_BASE_URL")` → URL запроса (Host / X-Forwarded-Host).
Проблема в том, что SSO-конфиг из БД при старте поднимает `PROXY_BASE_URL`
в `os.environ` **поверх** env из compose — поэтому задал `PROXY_BASE_URL`
в docker, а редирект всё равно старый.

Признаки, что значение сидит в БД (зашифровано):

- чисто в `config.yaml`, `docker compose env`, `/proc/*/environ`;
- `grep usetech` по файлам и дампу ничего не даёт (в дампе только ciphertext);
- Location меняется на `https://...` даже при http-запросе без прокси;
- прямое обращение к внутреннему IP контейнера редиректит так же.

Быстрая проверка «база или нет»: `pg_dump` маленькой БД / обнуление
LiteLLM-таблиц — если после обнуления редирект стал правильным, источник
точно в БД, смотреть `LiteLLM_SSOConfig`.

## Полезные команды

```bash
# кто реально слушает порт:
ss -ltnp | grep 4000

# окружение живого процесса (PID1 может быть bash из entrypoint):
docker exec litellm sh -c 'tr "\0" "\n" < /proc/$(pgrep -f "litellm --config" | head -1)/environ'

# таблицы с переносимой конфигурацией:
docker exec litellm-db psql -U litellm -d litellm -c 'table "LiteLLM_SSOConfig";'
docker exec litellm-db psql -U litellm -d litellm -c "select param_name from \"LiteLLM_Config\";"
docker exec litellm-db psql -U litellm -d litellm -c 'table "LiteLLM_CredentialsTable";'
```