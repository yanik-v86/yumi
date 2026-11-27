# Handoff: общая система провайдеров нейронок

Статус: **проектная документация готова, реализация не начиналась**.  
Дата: 2026-11-27.  
Аудитория: агент(ы), которые будут реализовывать фичу, и ревьюер.  
Список задач: `docs/tasks-llm-providers.md` (P-01 … P-09, там же статусы и commit-id).  
Обязательно к прочтению: `AGENTS.md`, `docs/handoff-web-panel.md`.  
Смежные документы: `docs/tasks-agent-mcp.md`, `docs/handoff-agent-mcp.md` — их реестр провайдеров заменяется описанным здесь.

## 1. Что нужно сделать

Сейчас «мозги» Юми умеют два провайдера, зашитых прямо в `yumi/chat.py`: локальный native API и один OpenAI-совместимый облачный сервис с собственными ключами настроек. Нужно:

- вынести выбор диалекта и запросы в общий реестр `yumi/llm.py`, где провайдер — это **данные** (запись в настройках), а не ветка в коде;
- перенести существующий облачный провайдер в эту систему как обычную запись, а локальный Ollama — тоже в реестр;
- убрать из кода, UI, тестов и документации все упоминания старого бренда (кроме одноразового файла миграции);
- сделать создание/правку/удаление/проверку провайдеров **только в веб-панели (админке)**; в GTK оставить только переключение уже созданного провайдера и модели. Это явное исключение из главного правила `AGENTS.md`, зафиксированное владельцем;
- сохранить совместимость старых `settings.json` миграцией, не потеряв ключ.

**Не входит в задачу:** tool calling, агентный цикл и MCP (`docs/tasks-agent-mcp.md`). Они должны подключиться к готовому реестру, не создавая второй список провайдеров.

### Решения / допущения

| Вопрос | Решение плана |
|---|---|
| Где реестр | `yumi/llm.py`, чистый модуль без GTK и `webpanel` |
| Диалекты | `ollama` (native) и `openai` (OpenAI-совместимый) |
| Где список провайдеров | `DEFAULT_SETTINGS['llm_providers']` |
| Где ключи | отдельный `CONFIG_DIR/'llm_keys.json'`, `0600`, не в `settings.json` |
| Старый облачный провайдер | мигрирует в запись `cloud` типа `openai`; брендовых строк в коде не остаётся |
| Выбор модели | `chat_provider` = id записи; `chat_model` сбрасывается на `default_model` при выборе |
| Эмбеддинги | отдельный `embed_url`, не зависят от чат-провайдера |
| Интерфейс | CRUD и проверка — только страница панели `providers`; в GTK — только переключатели провайдера и модели; общий реестр и функция выбора |

Термины: **запись провайдера** — конфигурация подключения (id, имя, тип, адрес, модель по умолчанию); **диалект/kind** — адаптер протокола; **ключ** — секрет, хранится отдельно и в реестре не лежит.

---

## 2. Текущая архитектура (номера строк ориентировочные)

### Мозг и LLM

| Что | Где |
|---|---|
| Константы и брендовая ветка | `yumi/chat.py:22-24` (`DEFAULT_MODEL`, `DEFAULT_URL`, старая константа модели), `:36-43` (`_provider`, `_url`) |
| Проверка доступности | `yumi/chat.py:53-60` (для облачного провайдера всегда `True`, без сети) |
| Список моделей | `yumi/chat.py:69-111`: `/api/tags` против `/models` + Bearer; при пустом списке — брендовый fallback |
| Тела запросов | `yumi/chat.py:223-246`: `_ollama_chat` (`options`, `think`) и `_polza_chat` (`max_tokens`, Bearer) |
| Фильтр рассуждений | `yumi/chat.py:215-220` (`_strip_think`, баг: закрывающий тег тот же), `:249-292` (`_think_filter`) |
| Потоки | `yumi/chat.py:295-325` (NDJSON Ollama), `:328-360` (SSE облачного API) |
| Публичные вызовы | `yumi/chat.py:363-407` (`ask_stream`, `ask`), `:561-607` (`_one_shot`) |
| Промпты, шутки, погода | `yumi/chat.py:151-212`, `:410-436`, `:610-720`, `:824-1089` — трогать не нужно |
| Эмбеддинги | `yumi/memory.py:227-249`, `yumi/notes.py:249-269` — сейчас читают адрес локального провайдера |
| Кто вызывает LLM | `yumi/ui/senses.py:858-924` (голос), `yumi/ui/webpanel.py:958-1078` (веб-чат), `yumi/music.py:377-390`, `yumi/ui/senses.py:639-678` |
| Реактивный мозг | `yumi/brain.py:1626-1845` (`heard_text`), `:2457-2639` (ответы/стриминг) |

### Настройки, панель, мост

- `yumi/config.py:22-230` — `DEFAULT_SETTINGS`; LLM-ключи на `:47-51`, `:112-115`; пути — `:15-20`; загрузка — `:309-315` (`Store` — `:262-292`).
- `yumi/config.py:504-505`, `:620` — RU/EN подписи, включая брендовые.
- `yumi/webpanel/catalog.py:15-18` — `SECRET_KEYS`; `:21-62` — `PAGES`; `:106-154` — `KEY_SECTION`; `:157-186` — `CHOICES` (там `:177` — захардкоженный список провайдеров); `:230-260` — `TYPES`; `:593-637` — `_entry()`; `:640-661` — `schema()`; `:664-738` — `coerce()`, `redact()`, `validate_settings_patch()`.
- `yumi/webpanel/server.py:370-456` — таблица роутов; `:550-563` — `PATCH /api/settings`; `:896-907` — модели чата с хардкод-проверкой провайдера; `:361-368` — Origin/CSRF.
- `yumi/ui/bridge.py:17-18` — `_on()` → `App._web_call` → `GLib.idle_add`; `:188-197` — модели; `:364-365` — чат.
- `yumi/ui/webpanel.py:408-439` — `_web_snapshot()`; `:493-510` — статус моделей; `:512-575` — `_web_apply_settings()` ( `:557-563` — инвалидация при смене адреса/провайдера).
- `yumi/webui/static/js/api.js:88-197` — клиент; `:199` — `EVENTS`; `app.js:7-24` — ленивые страницы, `:305-320` — реакция на PATCH; `pages/settings.js:115-173` — карточка «Её мозги».
- Тесты: `tests/test_chat.py:187-243` (брендовый mock-сервер), `tests/test_webpanel.py:530`, `:800-815` (маскировка и модели), `tests/test_speaker_gate.py:31` (заглушки).

### Известные грабли (учти при рефакторинге)

1. Смена провайдера не сбрасывает `chat_model` — старое имя модели уезжает к новому провайдеру (`ui/webpanel.py:557-563` чистит только список).
2. `_strip_think()` ищет `<think>...<think>` вместо `<think>...</think>` (`chat.py:218-219`).
3. В `_one_shot()` у OpenAI-совместимого диалекта `max_tokens` лежит внутри `options`, а не на верхнем уровне (`chat.py:569-582`).
4. `alive()` для облачного провайдера всегда `True` (`chat.py:56-57`).
5. Веб-чат всегда вызывает `ask_stream()`, игнорируя `chat_stream` (`ui/webpanel.py:1016`) — не ломать и не «чинить» в этой задаче без отдельного решения.
6. `chat.py` не знает про `tools`/`tool_calls` — это отдельная задача агента.

**Запрещено:** импортировать GTK в `yumi/webpanel/` и в новый `llm.py`; хранить ключ в записи провайдера; логировать тела сообщений/ключи; отдавать ключ в `/api/status`, `/api/schema`, аудит или LLM-контекст.

---

## 3. Целевая архитектура

### 3.1 Новые модули

- `yumi/llm.py` — реестр + адаптеры, stdlib, без GTK. Владеет форматом записи, валидацией, построением HTTP-запросов, разбором NDJSON/SSE, переводами ошибок. Переиспользует логику `chat.py`, а не дублирует её; `chat.py` становится фасадом.
- `yumi/llm_keys.py` — хранилище секретов: `CONFIG_DIR/'llm_keys.json'`, `0600`, atomic write через `.tmp` + `os.replace()`, API `load()/get(id)/set(id, value)/delete(id)`.
- `yumi/llm_migrate.py` — одноразовая миграция; **единственный** файл со старыми именами ключей.

### 3.2 Формат записи провайдера

```json
{
  "llm_providers": [
    {"id": "local", "name": "Local Ollama", "kind": "ollama",
     "url": "http://127.0.0.1:11434",
     "default_model": "lakomoor/vikhr-llama-3.2-1b-instruct:1b", "enabled": true},
    {"id": "cloud", "name": "Cloud model", "kind": "openai",
     "url": "https://<user-endpoint>/v1",
     "default_model": "deepseek/deepseek-v4-flash", "enabled": true}
  ],
  "chat_provider": "local",
  "chat_model": "lakomoor/vikhr-llama-3.2-1b-instruct:1b",
  "embed_url": "http://127.0.0.1:11434"
}
```

Правила валидации (только в `llm.validate_record()`): `id` — `[a-z0-9_-]{1,32}`, уникален; `name` ≤ 60; `kind` ∈ `{'ollama','openai'}`; `url` — `http(s)://`, ≤ 400; `default_model` ≤ 200; `enabled` — bool; `models` (кэш) — ≤ 200 строк. Поле `api_key` в записи **запрещено**.

### 3.3 Настройки и схема панели

| Ключ | Тип | По умолчанию | Секция | Комментарий |
|---|---|---|---|---|
| `llm_providers` | list | `[local]` | `mind` | скрыть в общих настройках (`hidden: True`), CRUD на странице `providers` |
| `chat_provider` | select | `local` | `mind` | варианты — динамические id из реестра, подписи — `name` |
| `chat_model` | text/select | локальная модель | `mind` | остаётся; при выборе провайдера сбрасывается на его `default_model` |
| `embed_url` | text | `http://127.0.0.1:11434` | `mind` | только для `/api/embeddings` в `memory.py`/`notes.py` |
| `chat_think`, `chat_stream`, `chat_history_n`, `chat_memory` | как сейчас | как сейчас | `mind` | адаптер `ollama` применяет `think`; `openai` — нет |

`catalog.schema()` должна уметь получать текущие настройки, чтобы строить `CHOICES['chat_provider']` и `CHOICE_LABELS` по реестру (сигнатура `schema(settings=None)`, сервер передаёт снимок). `coerce('llm_providers', ...)` делегирует в `llm.normalize_list()` — валидация не дублируется. Старые ключи `polza_*` и `ollama_url` удаляются из `DEFAULT_SETTINGS`, `SECRET_KEYS`, `TYPES`, `TITLES`, `HINTS`, `KEY_SECTION`, `CHOICES`.

### 3.4 Хранилище ключей и маскирование

- Ключ отделён от настроек: `llm_keys.json` — объект `{provider_id: "secret"}`. Читать только в `llm.resolve()` перед запросом; в `settings` ключа нет.
- API отдаёт только булевы флаги: `has_key: true/false`. Пустая строка или маска в запросе на изменение = «оставить прежний ключ».
- `set_key()` создаёт директорию, пишет во временный файл, `chmod 0600`, `os.replace()`. Ошибки логируются без значения.
- Миграция переносит старый ключ в это хранилище **до** удаления легаси-полей из `settings.json`.

### 3.5 Публичный контракт `yumi/llm.py`

```python
providers(settings) -> list[dict]          # копии записей, без ключей
get(settings, id) -> dict | None
validate_record(record, existing_ids=()) -> dict   # ValueError при ошибке
normalize_list(value, settings=None) -> list[dict]
resolve(settings, id) -> {'url', 'key', 'kind', 'default_model'}
models(settings, id, timeout=4) -> {'provider', 'models', 'error'}
test(settings, id, timeout=4) -> {'ok', 'models', 'error'}
ask(settings, messages, *, provider=None, model=None, timeout=90, **opts) -> str
ask_stream(settings, messages, *, provider=None, model=None, timeout=90, **opts) -> iterator[str]
```

Требования: `models()`/`test()` не бросают исключения; текст ошибок общий; `ask_stream()` при пустом ключе сразу заканчивается; аргумент `tools=None` оставляем как заготовку под агент; в `ask/ask_stream` переиспользуется `<think>`-фильтр `chat.py`.

### 3.6 HTTP API и WebBridge

| Метод | Роут | WebBridge |
|---|---|---|
| GET | `/api/llm/providers` | `llm_providers()` |
| POST | `/api/llm/providers/check` | `llm_provider_check(record, key)` — проверка черновика формы, без записи |
| POST | `/api/llm/providers` | `llm_provider_save(record, key)` |
| PUT | `/api/llm/providers/<id>` | `llm_provider_save(record, key)` |
| DELETE | `/api/llm/providers/<id>` | `llm_provider_delete(id)` |
| POST | `/api/llm/providers/<id>/select` | `llm_provider_select(id)` |
| POST | `/api/llm/providers/<id>/test` | `llm_provider_test(id)` |
| POST | `/api/llm/providers/<id>/models/refresh` | `llm_models_refresh(id)` |

Все методы моста — через `_on()` → `App._web_call` → GTK-поток; сетевые проверки тяжёлые — в worker. Роуты мутаций получают Origin/CSRF автоматически (`server.py:364-368`); аудит пишет только `id` и результат. GTK использует только общую функцию выбора (`llm_provider_select`-эквивалент на уровне приложения), не CRUD-роуты. Существующие `/api/chat/models` и `/api/chat/models/refresh` остаются, но валидируют id по реестру, а не по списку из двух имен.

### 3.7 `/api/status` и SSE

```json
{
  "runtime": {
    "llm": {
      "providers": [
        {"id": "local", "name": "Local Ollama", "kind": "ollama", "active": true,
         "has_key": false, "models_count": 3, "error": null}
      ],
      "active_provider": "local",
      "active_model": "lakomoor/vikhr-llama-3.2-1b-instruct:1b"
    },
    "chat_models": ["..."], "chat_models_info": {"provider": "local", "models": [], "error": ""}
  }
}
```

Событие `llm` публикуется при создании/правке/удалении/выборе и несёт только безопасные поля; добавить в `EVENTS` (`api.js:199`) и обработчик в `app.js`.

---

## 4. Миграция

`yumi/llm_migrate.migrate(settings)` вызывается из `load_settings()` (`config.py:309-315`) до первого использования настроек.

1. Если есть старый облачный адрес/ключ — создать запись `cloud` (`kind: 'openai'`, `url` из старого адреса, `default_model` из прежней модели) и положить ключ в `llm_keys.json`.
2. Старый адрес локального API → `embed_url`; если записи `local` ещё нет — создать её с этим адресом.
3. Старое значение `chat_provider` перевести в новый id (`'ollama'` → `'local'`, старое облачное имя → `'cloud'`); `chat_model` оставить как есть.
4. Удалить легаси-ключи из settings **только после успешной записи ключей** и сохранить файл через `Store`.
5. Повторный вызов ничего не меняет (идемпотентность). При ошибке хранилища — общая запись в лог, старые поля остаются на месте.

```text
было: chat_provider=polza.ai, polza_url=https://.../v1, polza_api_key=SECRET,
      chat_model=deepseek/..., ollama_url=http://127.0.0.1:11434
стало: llm_providers=[local, cloud], chat_provider=cloud, chat_model=deepseek/...,
      embed_url=http://127.0.0.1:11434, llm_keys.json={'cloud': 'SECRET'}
```

**Единственное место со старыми именами** — таблица соответствий в `llm_migrate.py`. Планер-документы упоминают их исторически. В остальном коде, UI, README и тестах старого имени быть не должно.

---

## 5. Потоки

### 5.1 Добавление и проверка провайдера из панели

1. В модалке `provider-form` кнопка «Проверить» → `api.llmProviderCheck(record, key)` → `POST /api/llm/providers/check`: `llm.validate_record()` и `llm.test()` на отсоединённой копии настроек, таймаут 4 c. Ответ даёт статус доступности и список моделей, откуда выбирается модель по умолчанию; настройки, приватный ключ и SSE не меняются, модалка остаётся открытой.
2. `pages/providers.js` → `api.llmProviderSave(record, key)` → `POST /api/llm/providers` (или `PUT` для правки).
3. `server.py` → `WebBridge.llm_provider_save` → `App._web_*` в GTK-потоке: `llm.validate_record()`, `llm_keys.set()` (если key не пуст), сохранение настроек, публикация SSE `llm`.
4. Кнопка «Проверить» на карточке → `POST /api/llm/providers/<id>/test` → `llm.test()` c таймаутом 4 c; это `GET /models` или `/api/tags`, **не** chat-completion и не выполнение промпта.
5. Результат (количество моделей или общая ошибка) показывается в карточке; ключ в ответе не возвращается.

### 5.2 Выбор провайдера (GTK и панель одинаково)

`llm_provider_select(id)` → `settings['chat_provider'] = id`, `settings['chat_model'] = record['default_model']`, сброс `brain.chat_models`/`chat_models_provider`/`chat_models_error`, запрос `('chat_models',)`, SSE `llm` + обновление `chat_models`. В GTK тот же вызов делает переключатель «Провайдер мозгов»: меняется `cycleChoices['chat_provider']` и подписи в меню, модель берётся из обновлённого списка. Никаких пунктов «Добавить/Изменить/Удалить/Проверить» в GTK нет — они живут на странице `providers`. При отсутствии ключа или недоступном сервере GTK показывает общую реплику «провайдер не ответил» и подсказку, что настройка делается в панели (RU/EN из `config.UI`).

### 5.3 Обычный запрос к LLM

`brain.heard_text()`/`ui.webpanel._web_chat()` → `ui.senses.chat_ask()` → `chat.ask()/ask_stream()` → `llm.resolve(settings, provider)` → адаптер `kind` строит URL/headers/body и парсит поток → ответ возвращается в `Brain.replied()` или SSE веб-чата. Ни вызывающие, ни промпты не знают, какой провайдер выбран.

### 5.4 Эмбеддинги

`memory.Book._embed()` и `Notes._embed()` читают `settings['embed_url']` и шлют `POST {embed_url}/api/embeddings` с `embed_model`. При выбранном облачном чат-провайдере локальный Ollama для дневника остаётся обязательным; при недоступности — прежний `_hashvec()`-fallback на 300 с.

---

## 6. Изменения по файлам

| Файл | Что сделать |
|---|---|
| `yumi/llm.py` (новый) | реестр, адаптеры `ollama`/`openai`, валидация, `models/test/ask/ask_stream`, общие ошибки |
| `yumi/llm_keys.py` (новый) | файл ключей `0600`, atomic write, get/set/delete |
| `yumi/llm_migrate.py` (новый) | одноразовая миграция легаси-ключей |
| `yumi/chat.py` | фасад: убрать брендовые ветви и константы, вызовы в `llm.py`, починить `_strip_think`, оставить промпты/погоду |
| `yumi/config.py` | новые ключи, удаление старых, вызов миграции, RU/EN подписи |
| `yumi/memory.py`, `yumi/notes.py` | `embed_url` вместо адреса локального чат-провайдера |
| `yumi/webpanel/catalog.py` | страница `providers`, скрытые ключи, динамические choices, валидация через `llm` |
| `yumi/ui/webpanel.py` | снимок `runtime.llm`, живые эффекты, `_web_*` методы провайдеров |
| `yumi/ui/bridge.py` | 6 новых методов моста |
| `yumi/webpanel/server.py` | 7 новых роутов, CSRF/аудит, обобщение `/api/chat/models/refresh` |
| `yumi/webui/static/js/api.js`, `app.js`, `pages/providers.js`, `pages/settings.js` | клиент, SSE, страница, карточка настроек, триггеры refresh |
| `yumi/brain.py` | динамические варианты переключателей провайдера/модели, общие реплики параметров; **без** CRUD-меню |
| `tests/test_llm.py` (новый), `tests/test_chat.py`, `tests/test_webpanel.py`, `tests/test_speaker_gate.py` | адаптеры, миграция, ключи, API, схема, заглушки |
| `README.md`, `README.ru.md`, `AGENTS.md`, `docs/*.md` | удалить старое имя, описать провайдеры/ключи/страницу, поправить cross-links |

---

## 7. Риски и запреты

| Риск | Смягчение |
|---|---|
| Старый `settings.json` с ключом | миграция до удаления полей, идемпотентность, откат при ошибке записи |
| Утечка ключа в панель/логи | отдельный файл `0600`, только `has_key` наружу, аудит по id, маска при редактировании |
| Динамический список в `CHOICES` | `schema(settings=None)`; сервер передаёт текущие настройки; панель не падает при пустом реестре |
| Гонка смены провайдера и ответа моделей | уже есть защита от устаревшего ответа в `brain.chat_models_loaded` и `_web_chat_models_loaded` — сохранить |
| Блокировка GTK-потока сетевым тестом | проверка/обновление моделей в worker, публикация через `_on()`/`GLib.idle_add` |
| Удаление активного/последнего провайдера | запретить, предложить сначала выбрать другой |
| Два разных реестра (здесь и в agent-mcp) | агент использует `yumi/llm.py`; в документах T-01/T-03 переопределены |
| Требование «ноль упоминаний бренда» | оставить только таблицу легаси-имен в `llm_migrate.py`; при строгом требовании убрать миграцию и предупредить владельца о потере совместимости |

**Не делать:** создавать второй конфиг провайдеров; держать api_key в `settings.json` или в записи; логировать тела запросов; добавлять брендовые ветки «на всякий случай»; **добавлять создание/правку/удаление/проверку провайдеров или поля ключа в GTK** (это только админка); менять промпты/погоду/агентный цикл в этой задаче; трогать `tools`/`tool_calls` без отдельного решения.

---

## 8. Тесты

`tests/test_llm.py` (новый): оба диалекта на поддельном HTTP-сервере (`/api/tags`, `/api/chat`, `/models`, `/chat/completions`), Bearer, NDJSON и SSE, пустой ключ, таймаут, невалидная запись, уникальность id, миграция, режим файла ключей, отсутствие ключа в логах.

Обновить: `tests/test_chat.py` (generic-провайдеры вместо брендового mock), `tests/test_webpanel.py` (схема, CRUD/CSRF, `/api/status`, отсутствие секретов), `tests/test_speaker_gate.py` (новые заглушки).

Команды:

```bash
python3 tests/test_llm.py
python3 tests/test_webpanel.py
python3 tests/test_user_intents.py
python3 tests/test_addressing.py
bash tests/smoke_user_intents.sh
pytest tests/ -q
python3 -m py_compile yumi/*.py yumi/ui/*.py yumi/webpanel/*.py
for f in yumi/webui/static/js/*.js yumi/webui/static/js/pages/*.js; do
  node --input-type=module --check < "$f" || echo "FAIL $f"
done
rg -in --glob '!**/__pycache__/**' --glob '!.git/**' 'polza' .
```

Последняя команда должна выдавать строки только в `yumi/llm_migrate.py`, `docs/tasks-llm-providers.md`, `docs/handoff-llm-providers.md`.

---

## 9. Критерии приёмки

1. Провайдеры создаются/правятся/удаляются/проверяются **только в веб-панели**; в GTK доступны только переключение провайдера и модели. Состояние общее, расхождений нет.
2. Новый OpenAI-совместимый провайдер добавляется настройкой без правки кода; `ollama` работает через тот же реестр.
3. Старые `settings.json` мигрируют с сохранением ключа; легаси-поля исчезают; `settings.json` не ломается при ошибке миграции.
4. Ключ хранится отдельно (`0600`) и не попадает в API, схему, снимок, логи, аудит или контекст LLM.
5. Смена провайдера в любой точке сбрасывает модель на `default_model` и обновляет список моделей.
6. Эмбеддинги используют `embed_url` и не зависят от активного чат-провайдера.
7. Все проверки §8 зелёные; README ru/en и handoff'ы обновлены; `rg` показывает только разрешённые файлы.

---

## 10. Быстрый старт для первого агента

1. Прочитать `AGENTS.md`, `docs/tasks-llm-providers.md`, этот файл; дождаться подтверждения владельца (в плане есть решения, которые стоит зафиксировать).
2. Начать с P-01 (`yumi/llm.py`, `llm_keys.py`, `tests/test_llm.py`) → P-02 (`chat.py`) → P-03 (настройки, миграция, `catalog.py`). Прогнать `tests/test_llm.py` и `tests/test_webpanel.py` до перехода к API.
3. Затем P-04/P-05 (мост, роуты, страница); P-06 (GTK) — только переключатели, никаких CRUD-диалогов.
4. В P-07 вычистить старое имя везде, кроме `llm_migrate.py` и этих двух документов, и проверить исключение для GTK в `AGENTS.md`; в P-08 прогнать все проверки.
5. Обновлять статусы и commit-id в `docs/tasks-llm-providers.md`; P-09 — передача ревьюеру.
