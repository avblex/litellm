# Бюджеты пользователей и команд (LiteLLM proxy)

Рабочая шпаргалка по тому, как устроены лимиты, где они хранятся, как сбрасываются и как чиниться. Собрана по итогам разбора инцидента с 429 `Budget has been exceeded! TeamMember=...`

## Три независимых слоя бюджета

Один запрос пользователя проверяется по нескольким слоям, каждый со своим лимитом, своим spend и своим сбросом. Блокирует любой, кто первым исчерпан

| Слой | Лимит хранится в | Spend хранится в | Проверка |
|---|---|---|---|
| Персональный юзер | `LiteLLM_UserTable.max_budget/budget_duration/budget_reset_at` (колонки таблицы, без ссылки на тиер) | `LiteLLM_UserTable.spend`, счётчик `spend:user:<id>` | `auth_checks.py`, ошибка `User=...` |
| Членство в команде | `LiteLLM_BudgetTable` (строка-тиер, ссылка `LiteLLM_TeamMembership.budget_id`) | `LiteLLM_TeamMembership.spend`, счётчик `spend:team_member:<user>:<team>` | `user_api_key_auth.py`, ошибка `TeamMember=<user>:<team>` |
| Ключ | `LiteLLM_VerificationToken.max_budget` | `LiteLLM_VerificationToken.spend`, счётчик `spend:key:<token>` | `auth_checks.py`, ошибка `Key=...` |

Важно: spend в слое членства персональный на участника, даже когда все членства ссылается на один тиер бюджета. Общий тиер = общий шаблон лимита, не общий кошелёк

Страница Users в Admin UI показывает только персональный слой. Бюджет членства виден на странице команды. Отсюда классическая путаница: у юзера $0 of $5, а запрос блокирует с 429, потому что исчерпан слой TeamMember

## Как устроен сброс (ResetBudgetJob)

`litellm/proxy/common_utils/reset_budget_job.py`, запускается APScheduler с интервалом `budget_interval`, если `general_settings.disable_reset_budget` не выставлен. На многоподовой установке за раз работает один под через Redis-лок

Выбор должников идёт по `budget_reset_at <= now`. NULL в `budget_reset_at` не устаревает никогда, поэтому бюджет без `budget_duration` не сбрасывается никогда. Это корень большинства "лимит завис навсегда"

Что делает джоба:

1. `reset_budget_for_litellm_users/keys/teams` - построчно обнуляет spend и двигает `budget_reset_at` у юзеров/ключей/команд с собственным `budget_duration`
2. `reset_budget_for_litellm_budget_table` - каскад по тиерам: для истёкших строк `LiteLLM_BudgetTable` в одной транзакции обнуляет spend всех членств, ключей, оргов, тегов, end users с этим `budget_id` и двигает `budget_reset_at` тиера
3. После коммита инвалидирует счётчики в Redis/in-memory (`spend:*`) и кэш `user_api_key_cache`, иначе авторизация будет читать старый spend до истечения TTL

Следующая граница сброса считается не "now + duration", а по календарной границе в настроенном поясе: `compute_budget_reset_at` -> `get_next_standardized_reset_time`, настройки `budget_reset_timezone` и `budget_reset_time` (по умолчанию полночь UTC). Для `1d` это всегда полночь

## Default User Settings (Admin UI -> Users -> Default User Settings)

Применяется только при создании пользователя (SSO-первый вход, `/user/new`, SCIM). Уже созданным юзерам ничего не меняется

- Max Budget / Reset Budget -> попадают в `LiteLLM_UserTable` как персональный лимит (первый слой)
- Default Teams с `$N max budget` -> юзер добавляется в команду с `max_budget_in_team`, и `_resolve_member_budget_id` (`litellm/proxy/management_helpers/utils.py`) создаёт под него НОВЫЙ тиер бюджета. В него пишутся только `max_budget` (и `allowed_models`), поле duration в этом пути не передаётся, поэтому такой тиер рождается без `budget_duration` и не сбрасывается никогда

Если `$N` в Default Teams НЕ задан, срабатывает ветка клонирования `_clone_team_default_budget_for_member`: берётся тиер из `LiteLLM_TeamTable.metadata.team_member_budget_id` (дефолтный бюджет участников команды, настраивается на странице команды через `team_member_budget`), копируются все непустые поля, включая `budget_duration`, и проставляется свежий `budget_reset_at`. Новичок получает свою копию лимита с корректным сбросом

Клонирование не сработает, если: в metadata команды нет `team_member_budget_id`, или дефолтный тиер пустой (все поля NULL -> клон тоже пустой, лимита нет)

`/team/member_update` делает clone-on-write: если членство ссылается на общий дефолтный тиер, правка одного участника сначала откопирует тиер, чтобы не задеть остальных. Поэтому со временем у команды появляются и общий тиер, и персональные клоны, это нормальное состояние

## Целевая конфигурация "5$ в день на каждого участника"

- Один общий тиер `team-<alias>-budget-<hex>`: `max_budget=5`, `budget_duration=1d`, на него ссылается `metadata.team_member_budget_id` команды
- Все членства висят на нём (или на его клонах с теми же значениями)
- Персональные `max_budget` у юзеров сняты, `$N` из Default Teams убран (саму команду оставить)
- Сброс: daily, полночь UTC, каскадом по всем членствам тиера

## Управление: эндпоинты

- `POST /budget/update` `{"budget_id": ..., "max_budget": 5, "budget_duration": "1d"}` - правит тиер; при выставлении duration пересчитывает `budget_reset_at`; явный `null` очищает поле. Один вызов чинит всех, кто на этом тиере
- `POST /budget/info` `{"budgets": [...]}` - текущие значения тиеров
- `GET /budget/list` - все тиеры
- `POST /budget/delete` `{"id": ...}` - удалить тиер, по одному id за вызов, только proxy_admin
- `POST /team/{team_id}/member/{user_id}/reset_spend` `{"reset_to": 0}` - единственный способ обнулить spend членства; инвалидирует счётчик и кэш сразу. `reset_to` <= текущего spend и <= max_budget
- `POST /key/{key}/reset_spend` - то же для ключа
- `POST /user/update` / `/user/bulk_update` - персональный слой: `{"max_budget": null, "budget_duration": null}` снимает лимит, `{"spend": 0}` обнуляет. Явный null очищает, отсутствующее поле не трогается. Сам себе internal_user менять max_budget/spend не может (403), нужен admin
- `POST /team/member_update` - бюджет одного участника (клон-он-райт)

## Диагностика: полезные SQL

```sql
-- слой членства команды: кто на каком тиере, сколько потрачено
SELECT tm.user_id, tm.spend, b.max_budget, b.budget_duration, b.budget_reset_at
  FROM "LiteLLM_TeamMembership" tm
  LEFT JOIN "LiteLLM_BudgetTable" b ON b.budget_id = tm.budget_id
 WHERE tm.team_id = '<team_id>';

-- персональный слой
SELECT user_id, max_budget, budget_duration, budget_reset_at, spend
  FROM "LiteLLM_UserTable";

-- ссылка на дефолтный бюджет участников команды
SELECT metadata -> 'team_member_budget_id'
  FROM "LiteLLM_TeamTable" WHERE team_id = '<team_id>';

-- сироты: тиеры без ни на кого не ссылающихся (удалить через /budget/delete)
SELECT b.budget_id FROM "LiteLLM_BudgetTable" b
 WHERE NOT EXISTS (SELECT 1 FROM "LiteLLM_TeamMembership"     x WHERE x.budget_id = b.budget_id)
   AND NOT EXISTS (SELECT 1 FROM "LiteLLM_VerificationToken"  x WHERE x.budget_id = b.budget_id)
   AND NOT EXISTS (SELECT 1 FROM "LiteLLM_EndUserTable"       x WHERE x.budget_id = b.budget_id)
   AND NOT EXISTS (SELECT 1 FROM "LiteLLM_TagTable"           x WHERE x.budget_id = b.budget_id)
   AND NOT EXISTS (SELECT 1 FROM "LiteLLM_OrganizationTable"  x WHERE x.budget_id = b.budget_id)
   AND NOT EXISTS (SELECT 1 FROM "LiteLLM_ProjectTable"       x WHERE x.budget_id = b.budget_id);
```

Перепривязка членств на общий тиер (NULL-safe, чинит и NULL, и старые тиеры):

```sql
UPDATE "LiteLLM_TeamMembership"
   SET budget_id = '<общий_budget_id>'
 WHERE team_id = '<team_id>'
   AND budget_id IS DISTINCT FROM '<общий_budget_id>';
```

`IS DISTINCT FROM` вместо `<>` потому, что `NULL <> 'x'` даёт NULL и строки с NULL не обновятся

## Типичные грабли

- 429 `TeamMember=...` при $0 в UI пользователя: блокирует слой членства, смотреть `LiteLLM_TeamMembership`, а не страницу Users
- Тиер без `budget_duration` не сбрасывается никогда (`budget_reset_at IS NULL` не устаревает). Spend копится вечно, блокировка навсегда
- Дефолты Default User Settings применяются только при создании. Правка конфига не меняет существующих юзеров, их чинить `/user/bulk_update`
- `$N` в Default Teams создаёт тиер без duration, даже если дефолт команды настроен правильно (явный лимит имеет приоритет над клонированием). Хотите наследование duration - уберите `$N` из Default Teams
- `max_budget: null` в `/budget/update` на дефолтном тиере команды делает будущие клоны пустыми (копируются только непустые поля) - новички получат лимит "без лимита"
- Spend в ошибке чуть больше лимита (5.0013 при $5) - норма: проверка идёт до запроса, стоимость пишется после, последний пропущенный запрос перекрывает лимит
- `total_spend` в `LiteLLM_TeamMembership` - накопленная история за всё время, на лимиты не влияет
- Ручной сброс без `budget_duration` - временная мера, лимит вернётся сразу как только spend снова дорастёт до max_budget
