# Маршрутизация fast/long по длине промпта

Клиенты пишут в одну модель (`qwen3.8-flash-fast`). Промпты длиннее порога LiteLLM
прозрачно переключает на `qwen3.8-flash-long`. Обе группы указывают на один vLLM
(`max_model_len` 240k), раздельные капы параллелизма защищают KV-бюджет движка.

Механика: `enable_pre_call_checks` считает токены промпта до отправки и отбраковывает
деплойменты с меньшим `max_input_tokens`, затем `context_window_fallbacks` переписывает
запрос на long-группу. При превышении 232k запрос получает 400 до отправки в vLLM.

## 1. Модели (через API, UI эти поля не показывает)

```bash
curl -X POST http://localhost:4000/model/new \
  -H "Authorization: Bearer $ADMIN_KEY" -H "Content-Type: application/json" \
  -d '{"model_name": "qwen3.8-flash-fast",
       "litellm_params": {"model": "openai/qwen3.8-flash", "api_base": "http://MGU4:8000/v1", "max_parallel_requests": 20},
       "model_info": {"max_input_tokens": 64000}}'

curl -X POST http://localhost:4000/model/new \
  -H "Authorization: Bearer $ADMIN_KEY" -H "Content-Type: application/json" \
  -d '{"model_name": "qwen3.8-flash-long",
       "litellm_params": {"model": "openai/qwen3.8-flash", "api_base": "http://MGU4:8000/v1", "max_parallel_requests": 5},
       "model_info": {"max_input_tokens": 232000}}'
```

Существующие модели правятся `POST /model/update` с `"id"` деплоймента (id виден в
`GET /model/settings` в `model_info.id`). `max_parallel_requests` создаёт семафор при
инициализации деплоймента, после update нужен рестарт прокси

## 2. Pre-call checks: только через config.yaml

`enable_pre_call_checks` отсутствует в `RUNTIME_UPDATABLE_ROUTER_SETTINGS`
(`litellm/constants.py`), поэтому из DB (UI, `/config/update`) он НЕ применяется к живому
роутеру, несмотря на True в `GET /router/settings` (тот показывает DB, а не роутер).
Только секция `router_settings` в config.yaml, она уходит в конструктор Router:

```yaml
router_settings:
  enable_pre_call_checks: true
```

## 3. Контекстный фоллбэк (пишется в DB и в живой роутер, рестарт не нужен)

```bash
curl -X POST http://localhost:4000/fallback \
  -H "Authorization: Bearer $ADMIN_KEY" -H "Content-Type: application/json" \
  -d '{"model": "qwen3.8-flash-fast", "fallback_models": ["qwen3.8-flash-long"], "fallback_type": "context_window"}'
```

Проверка: `GET /fallback/qwen3.8-flash-fast?fallback_type=context_window`

## 4. Точный счётчик токенов (hooks/custom_tokenizer_patch.py)

Без патча pre-call check считает токенизатором cl100k_base и завышает кириллицу ~в 2 раза
(реальные 80k -> насчитает 160k), из-за чего пороги не соответствуют токенам vLLM. Патч
подменяет `litellm.token_counter` на Qwen `tokenizer.json` (файл лежит рядом, truncation
из него вырезается, иначе оценка упирается в 2048). Монтируется в `/app` этим compose-файлом,
включается в config.yaml:

```yaml
litellm_settings:
  callbacks:
    - custom_tokenizer_patch._loader_instance
```

После включения `max_input_tokens` означают ровно то, что написано, в токенах vLLM.
Обновлять `tokenizer.json` нужно при смене модели на vLLM

## 5. Проверка

```bash
python3 -c "
import json
print(json.dumps({'model': 'qwen3.8-flash-fast',
                  'messages': [{'role': 'user', 'content': 'слово ' * 80000}],
                  'max_tokens': 16}))" > /tmp/req.json

curl -s http://localhost:4000/v1/chat/completions \
  -H "Authorization: Bearer $USER_KEY" -H "Content-Type: application/json" \
  -d @/tmp/req.json > /dev/null

grep -E "Max Input Tokens|Falling back|Selected deployment" litellm.log | tail -5
```

Ожидаем в логе: `Max Input Tokens=64000, Got=~80000`, `Falling back to model_group =
qwen3.8-flash-long`, `Selected deployment: {'model_name': 'qwen3.8-flash-long', ...}`.
В карточке лога Model ID должен совпасть с id long-деплоймента из шага 1 (поле Model
показывает backend-имя, оно у обеих групп общее). Короткий запрос должен оставаться на
fast без строк fallback

## 6. KV-бюджет vLLM

Расчёт от "GPU KV cache size" из логов старта vLLM (для MGU4 ~2.9M токенов):
`N_fast x (L_fast + A) + N_long x (L_long + A) <= B`, где A ~8k запас на генерацию.
При 20 коротких по 64k остаётся ~1.4M на длинные -> кап long 5. На vLLM стоит
`--max-num-seqs 25` (= 20 + 5), иначе своя очередь движка сломает расчёт капов
