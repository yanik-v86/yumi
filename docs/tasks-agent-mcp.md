# Задачи: агент Юми с MCP-инструментами (голос + веб-панель)

Статус: **НЕ НАЧАТО — ждёт подтверждения владельца**.  
Дата: 2026-11-22.  
Связанный документ: `docs/handoff-agent-mcp.md` (архитектура, контракты, риски).  
Указатель плана: `~/.opencode/plan/yumi-agent-mcp.md`.  
Переопределение: `docs/tasks-llm-providers.md` — общий реестр провайдеров; T-01 и блок провайдеров/ключей в T-03 ниже считать заменёнными этим планом (брендовых дефолтов и собственного списка провайдеров у агента не будет).  
Правило проекта: см. `AGENTS.md` — каждая возможность работает **и в GTK, и в веб-панели**.

## Решения владельца (зафиксированы)

1. Агент — **встроенный в Юми**, с циклом рассуждений и вызовом инструментов. Сейчас у Юми есть только реактивный `brain.py` и `chat.py` без tool-calling.
2. **MCP-транспорты**: `stdio` реализуется в этой задаче; `HTTP/SSE` — отдельная задача T-16, интерфейс закладывается заранее, чтобы дописывалось легко.
3. **Модель/провайдер**: добавить **механизм провайдеров и моделей**. Уже добавлены `ollama` и `polza.ai`; пользователь может добавить свои OpenAI-совместимые endpoint'ы. Агент выбирает провайдера/модель отдельно от обычного чата.
4. **Каналы**: веб-панель и голос — **одновременно**, не по очереди.
5. **Безопасность — приоритет**: whitelist инструментов, уровни `safe / confirm / deny`, подтверждения голосом и в панели, песочница, лимиты, аудит. Всё выключено по умолчанию.

## Легенда

- Приоритет: P0 — входит в Definition of Done, P1 — желательно, P2 — отдельная задача.
- Статус: `TODO` (все задачи до старта), затем `DONE` + commit-id в строке задачи.
- ID задач используются в коммитах: `feat(agent): T-01 ...`.
- Зависимости указаны в поле `Зависит от`.

---

## Фаза 1 — фундамент: провайдеры, модели, настройки

### T-01. Реестр провайдеров и моделей (P0)

**Статус:** TODO.  
**Зависит от:** —  
**Файлы:** `yumi/llm.py` (новый, чистый, без GTK), `yumi/config.py`, `tests/test_llm.py` (новый).

**Что сделать:**
- Не переписывать `chat.py` целиком. Добавить слой `yumi/llm.py`, который переиспользует уже существующую «трубу» `chat.py` (`_url`, `_get`, `_post`, `_provider`, `POLZA_MODEL`, `DEFAULT_MODEL`) и расширяет её.
- Встроенные провайдеры: `ollama` (`chat.ollama_url`, `/api/tags`, `/api/chat`) и `polza.ai` (`polza_url`, `/chat/completions`, ключ `polza_api_key`). Сохранить их текущее поведение.
- Пользовательские провайдеры через `DEFAULT_SETTINGS['agent_providers_custom']`: записи `{id, name, kind: 'openai', url, models: []}`. Ключи хранятся отдельно в `agent_custom_keys` (см. T-03) и маскируются.
- Публичный контракт: `providers() -> list[{id, name, builtin}]`, `models(provider) -> list[str]`, `resolve(settings, kind='agent') -> (provider, model, url, key)`, `alive(provider, settings) -> bool`.
- Проверка доступности провайдера — дешёвая, с таймаутом; отсутствие сети/ключа не должно ронять приложение.

**Критерии приёмки:**
- `models('ollama')` и `models('polza.ai')` совпадают с текущим поведением `chat.models()`.
- Добавление кастомного OpenAI-совместимого провайдера через settings даёт его в `providers()` без правки кода.
- Ни один ключ/токен не попадает в логи и в ответ API.

---

### T-02. LLM-клиент с вызовом инструментов (P0)

**Статус:** TODO.  
**Зависит от:** T-01  
**Файлы:** `yumi/llm.py`, `tests/test_llm.py`.

**Что сделать:**
- Общий метод `chat(settings, messages, tools=None, stream=False, provider=None, model=None, timeout=...)`.
- Для `polza.ai` и кастомных OpenAI-провайдеров: поле `tools` в `/chat/completions`, разбор `choices[0].message.tool_calls`, повторный запрос с `role:'tool'` результатами.
- Для `ollama`: передача `tools` в `/api/chat`; **обязательная проверка на целевой машине**, поддерживает ли установленная модель tool-calling. При отсутствии поддержки — JSON-fallback: system-инструкция вернуть строго `{"tool": "...", "args": {...}}` и жёсткий парсер с отказом при мусоре.
- Сохранить `<think>`-фильтр из `chat.py` (реплики могут утекать Reasoning в ответ).
- Ограничение `max_tokens` / `num_predict`, таймаут, `_log()` только без тел сообщений.

**Критерии приёмки:**
- С поддельным HTTP-сервером: tool_calls разбираются, результат инструмента возвращается модели, цикл завершается текстом.
- JSON-fallback работает и не выполняет инструмент при невалидном JSON.
- Пустой ключ `polza_api_key` → мгновенный отказ без зависания (как сейчас в `chat.ask`).

---

### T-03. Настройки, секреты и схема панели (P0)

**Статус:** TODO.  
**Зависит от:** T-01  
**Файлы:** `yumi/config.py` (`DEFAULT_SETTINGS`, `SECRET_KEYS` через `catalog.py`, `UI` ru/en), `yumi/webpanel/catalog.py`, `tests/test_webpanel.py`.

**Что сделать:**
- Ключи (минимум):

| Ключ | Тип | По умолчанию | Смысл |
|---|---|---:|---|
| `agent_enabled` | bool | `false` | вся фича; при `false` — текущее поведение Юми |
| `agent_voice` | bool | `true` | голосовой триггер агента |
| `agent_provider` | choice | `polza.ai` | провайдер рассуждений; polza по умолчанию, т.к. локальная 1b-модель не гарантирует tool-calling |
| `agent_model` | str | `''` | пусто → fallback провайдера (`POLZA_MODEL` / `DEFAULT_MODEL`) |
| `agent_providers_custom` | list | `[]` | кастомные OpenAI-совместимые провайдеры (без ключей) |
| `agent_custom_keys` | dict | `{}` | ключи кастомных провайдеров → добавить в `SECRET_KEYS` |
| `agent_max_steps` | int | `8` | максимум шагов на задачу |
| `agent_tool_timeout_s` | int | `20` | таймаут одного инструмента |
| `agent_max_tokens` | int | `4000` | лимит токенов на задачу |
| `agent_confirm_timeout_s` | int | `15` | голосовое подтверждение; нет ответа → отказ |
| `agent_audit_n` | int | `200` | сколько записей аудита держать в снимке |
| `agent_mcp_servers` | list | `[]` | конфиг MCP-серверов (все `enabled: false`) |
| `agent_file_sandbox` | bool | `true` | файловые инструменты только в песочнице |
| `agent_allow_network` | bool | `false` | сетевые инструменты/серверы выключены |

- В `catalog.py`: `KEY_SECTION` → новая секция `agent`; `TYPES`, `CHOICES`, `RANGES`, `TITLES`, `HINTS` ru/en; `agent_custom_keys` — в `SECRET_KEYS`.
- `UI` ru/en: названия секций, кнопок, подсказок, фраз подтверждения и отказа.
- Обратная совместимость `settings.json`: новые ключи получают значения по умолчанию, старые файлы не мигрируются принудительно.

**Критерии приёмки:**
- `python3 tests/test_webpanel.py` зелёный: каждый ключ `DEFAULT_SETTINGS` попал в схему.
- `agent_custom_keys` и `polza_api_key` маскируются в API и редакторе конфигов.

---

## Фаза 2 — ядро агента и безопасность

### T-04. Типы, контекст, реестр инструментов (P0)

**Статус:** TODO.  
**Зависит от:** T-02  
**Файлы:** `yumi/agent/__init__.py`, `yumi/agent/types.py`, `yumi/agent/context.py`, `yumi/agent/registry.py`, `tests/test_agent_core.py` (новый).

**Что сделать:**
- `Task`: `{id, origin: 'voice'|'panel'|'system', text, created, status, steps, answer}`; statuses: `queued|running|awaiting_confirmation|done|failed|cancelled`.
- `Step`: `{n, thought, tool, args, risk, result, error, elapsed, ts, decision}`.
- `Tool`: `{name, description_ru, description_en, risk, input_schema, handler}`; имя MCP-инструмента — `mcp__<server_id>__<tool>`.
- `context.build(settings, memory, voice_state, ...)` — короткий снимок: дневник (`memory.recall()`), текущее состояние (`voice_state.snapshot()`), дата/время, язык, списки разрешённых инструментов. Без сырых embedding'ов и секретов.
- `registry`: `register(tool)`, `get(name)`, `list_tools()`, `openai_schemas()`. Не импортирует GTK и `webpanel`.

**Критерии приёмки:**
- Реестр отдаёт корректные JSON-схемы для LLM; коллизии имён отклоняются.
- Контекст не содержит ключей, токенов, embedding'ов, путей к секретным файлам.

---

### T-05. Политика и подтверждения (P0)

**Статус:** TODO.  
**Зависит от:** T-04  
**Файлы:** `yumi/agent/policy.py`, `yumi/permission.py` (переиспользовать, не переписывать), `tests/test_agent_policy.py` (новый).

**Что сделать:**
- Уровни риска: `safe` → `auto`, `confirm` → запрос, `deny` → отказ.
- По умолчанию `deny` для: shell, произвольных файлов, сети, отправки сообщений, изменения `agent_*` и секретных настроек, для всех MCP-инструментов до явного включения сервера пользователем.
- `confirm` для: запись в дневник от имени пользователя, изменение обычных настроек, запуск кнопок из `actions.json`, инструменты доверенного MCP-сервера.
- `safe`: музыка, чтение дневника/статуса, `ui.say`, таймеры, чтение whitelist настроек.
- Решения: `once`, `deny`, `always`. **`always` — только из панели и только для безопасных target**, по образцу `permission.py`; голосовое «всегда» не принимается. Доверие к MCP-серверу — отдельный явный toggle, а не «всегда» на инструмент.
- Отрицание сильнее согласия («да, нет» → `deny`), обход через `..`/symlink — как в `permission.is_secret()`.

**Критерии приёмки:**
- Для неизвестного инструмента решение `deny` без исключения.
- Голос не может выдать `always`; панель может, но не для секретных target.
- Секретные аргументы инструмента маскируются в логах и в снимке.

---

### T-06. Агентный цикл (P0)

**Статус:** TODO.  
**Зависит от:** T-02, T-04, T-05  
**Файлы:** `yumi/agent/core.py`, `yumi/agent/executor.py`, `tests/test_agent_loop.py` (новый).

**Что сделать:**
- Цикл: контекст → запрос к LLM с инструментами → валидация вызова → политика → (подтверждение) → выполнение → наблюдение → повтор до ответа или лимита.
- `executor.call(tool, args, decision)` — таймаут, перехват исключений, маскирование аргументов, результат всегда строка/JSON для модели.
- Запрет рекурсии: агент не может создать агента; вложенные задачи отклоняются.
- Один активный `Task` на приложение; новые задачи при занятом агенте → `queued` или вежливый отказ (решить в T-11).
- Все long-running вызовы — в отдельном потоке; в GTK-поток только публикация через `GLib.idle_add` на стороне `WebBridge`.

**Критерии приёмки:**
- С поддельной моделью и поддельным инструментом: 2 шага → финальный ответ, `steps` заполнены.
- Превышение `agent_max_steps` → `failed` с понятной причиной, без зависания.
- Отмена во время ожидания подтверждения переводит задачу в `cancelled`.

---

### T-07. Аудит и лимиты (P0)

**Статус:** TODO.  
**Зависит от:** T-06  
**Файлы:** `yumi/agent/audit.py`, `tests/test_agent_policy.py`.

**Что сделать:**
- Аудит: `{ts, task_id, origin, tool, args_masked, decision, result_status, elapsed}`; путь: `STATE_DIR / 'agent_audit.jsonl'`, append-only, ротация по `agent_audit_n`.
- Маскирование: ключи из `SECRET_KEYS`, пути из `permission.SECRET_PATHS`, значения api_key/token/password.
- Лимиты: шаги (T-06), таймаут инструмента, токены, подтверждение, размер ответа инструмента (например, 8 КБ в контекст), частота задач от голоса.
- Снимок для панели отдаёт только последние N записей без секретов.

**Критерии приёмки:**
- В логе и в `/api/agent/audit` нет ключей и содержимого приватных путей.
- Переполнение лимита не роняет приложение и пишет запись в аудит.

---

## Фаза 3 — инструменты и MCP

### T-08. Встроенные инструменты (P0)

**Статус:** TODO.  
**Зависит от:** T-04, T-05  
**Файлы:** `yumi/agent/tools/builtin.py` (или `yumi/agent/builtin.py`), `tests/test_agent_tools.py` (новый).

**Что сделать:**
- `music.play / pause / next` — через существующий `music.py`; `diary.read / write` — через `memory.py`; `timer.set / cancel`; `settings.get` (whitelist); `ui.say` (через существующий путь TTS); `system.status`.
- Каждый инструмент: ru/en описание, JSON-схема, уровень риска, handler без GTK.
- Запись в дневник и изменение настроек — `confirm`; остальное — `safe`.

**Критерии приёмки:**
- Вызов инструмента с неверными аргументами возвращает ошибку модели, а не exception в цикле.
- Инструмент не может прочитать ключ, даже если агент его попросил.

---

### T-09. MCP-транспорт stdio (P0)

**Статус:** TODO.  
**Зависит от:** T-04  
**Файлы:** `yumi/agent/mcp/__init__.py`, `base.py`, `stdio.py`, `tests/test_mcp_stdio.py` (новый).

**Что сделать:**
- `McpTransport` (abstract): `initialize()`, `list_tools() -> list[Tool]`, `call_tool(name, args) -> str`, `close()`, `healthy() -> bool`.
- `StdioTransport`: `subprocess.Popen(command + args, stdin=PIPE, stdout=PIPE, stderr=PIPE, cwd=песочница)`, JSON-RPC 2.0: `initialize`, `notifications/initialized`, `tools/list`, `tools/call`, `ping`; `shutdown`/`exit` при закрытии.
- Окружение дочернего процесса — **whitelist** (`PATH`, `HOME`, `LANG`, явные `env` из конфига), не полный `os.environ`. Таймауты на каждую операцию, `kill()` по превышению, stderr — в лог с маскированием.
- `HttpTransport` в `http.py` — только заготовка с интерфейсом и явным `NotImplementedError`; в реестр не попадает. Это T-16.

**Критерии приёмки:**
- С поддельным MCP-сервером на Python: `list_tools()` возвращает схемы, `call_tool()` — результат, `close()` завершает процесс.
- Зависший сервер не блокирует приложение дольше таймаута.
- Небезопасный env не наследуется.

---

### T-10. MCP-менеджер и безопасная авторегистрация (P0)

**Статус:** TODO.  
**Зависит от:** T-09, T-05, T-08  
**Файлы:** `yumi/agent/mcp/manager.py`, `tests/test_mcp_stdio.py`.

**Что сделать:**
- Читать `agent_mcp_servers`: `{id, name, transport: 'stdio', command, args: [], env: {}, enabled: false, trust: 'untrusted'|'trusted', allowed_tools: []}`.
- Запускать **только** `enabled: true`; запуск при старте приложения и по кнопке «Обновить инструменты» в панели.
- `tools/list` → авторегистрация в `registry` как `mcp__<id>__<tool>`; `allowed_tools` — whitelist, пусто = инструменты не доступны даже у доверенного сервера (явный выбор пользователя).
- `trust='untrusted'` → все его инструменты `deny`; `trusted` → `confirm`.
- Перезапуск сервера, отключение,的状态 в снимке: `{id, name, enabled, connected, tools, last_error}`.

**Критерии приёмки:**
- По умолчанию (`enabled: false`) ни один процесс не запускается.
- Отключение сервера убирает его инструменты из реестра и из схемы LLM.
- Ошибка одного сервера не мешает остальным.

---

## Фаза 4 — интеграция: панель, GTK, голос

### T-11. WebBridge, роуты и клиент API (P0)

**Статус:** TODO.  
**Зависит от:** T-06, T-07, T-10  
**Файлы:** `yumi/ui/bridge.py`, `yumi/webpanel/server.py`, `yumi/webui/static/js/api.js`, `tests/test_webpanel.py`.

**Что сделать:**
- `WebBridge`: `agent_submit_task(text, origin='panel')`, `agent_status()`, `agent_history()`, `agent_audit()`, `agent_tools()`, `agent_tool_set(name, mode)`, `agent_providers()`, `agent_models(provider)`, `agent_approve(task_id, step_id, decision)`, `agent_cancel(task_id)`, `agent_mcp_refresh()`. Все вызовы — через `App._web_call` → `GLib.idle_add`.
- Роуты (CSRF на все POST, аудит):

| Метод | Роут | Назначение |
|---|---|---|
| GET | `/api/agent/status` | активная задача, ожидающие подтверждения, MCP, последняя ошибка |
| GET | `/api/agent/tools` | инструменты, риск, режим `auto/confirm/deny` |
| POST | `/api/agent/tool` | `{name, mode}` — режим инструмента |
| GET | `/api/agent/providers` | список провайдеров |
| GET | `/api/agent/models?provider=` | модели провайдера |
| GET | `/api/agent/history` | последние задачи |
| GET | `/api/agent/audit` | последние записи аудита |
| POST | `/api/agent/task` | `{text, origin: 'panel'}` |
| POST | `/api/agent/approve` | `{task_id, step_id, decision}` |
| POST | `/api/agent/cancel` | `{task_id}` |
| POST | `/api/agent/mcp/refresh` | перечитать `tools/list` |

- `api.js`: `agentStatus/Tools/ToolSet/Providers/Models/History/Audit/Submit/Approve/Cancel/McpRefresh`; добавить `'agent'` в `EVENTS`.
- Никакого HTML из данных: только `createElement`/`textContent`.

**Критерии приёмки:**
- Авторизованный GET/POST работают; без CSRF → 403.
- `yumi/webpanel/*` не импортирует GTK; все GTK-вызовы идут через мост.

---

### T-12. Страница панели, SSE и `/api/status` (P0)

**Статус:** TODO.  
**Зависит от:** T-11  
**Файлы:** `catalog.py` (`PAGES`, `SECTION_PAGE`, `SECTIONS`), `app.js`, `yumi/webui/static/js/pages/agent.js` (новый), `yumi/ui/webpanel.py`, `tests/test_webpanel.py`.

**Что сделать:**
- `catalog.PAGES`: страница `agent` — «Агент / Agent», иконка из уже существующего набора.
- `pages/agent.js :: render(view, ctx)`:
  - поле задачи и кнопка «Отправить»;
  - живой лог шагов через SSE `agent` (`{task_id, step, status, answer}`);
  - карточка подтверждения: «Разрешить / Всегда / Отклонить» + текст инструмента и аргументы (маскированные);
  - сетка инструментов с бейджами `safe / confirm / deny` и переключателем режима;
  - список MCP-серверов: включён/подключён/инструменты/ошибка, кнопка «Обновить инструменты»;
  - выбор провайдера и модели для агента;
  - вкладки «История» и «Аудит»;
  - строки RU/EN через локальную `say(ru, en)`.
- `_web_snapshot()`: `runtime.agent = {enabled, provider, model, active_task, pending_confirmations, tools_count, mcp: [...], last_error}`; в `light=True` оставить только минимум.
- SSE-событие `agent` нести только безопасные поля.

**Критерии приёмки:**
- Страница открывается, обновляется в реальном времени, подтверждение из панели снимает ожидание задачи.
- `node --input-type=module --check` проходит для всех JS.

---

### T-13. GTK-эквивалент (P0)

**Статус:** TODO.  
**Зависит от:** T-06, T-11, T-03  
**Файлы:** `yumi/brain.py` (меню), `yumi/config.py` (`UI`), `yumi/ui/app.py` (при нужде).

**Что сделать:**
- Пункты меню «Агент» рядом с «Её мозги»: «Задать задачу», «Статус агента», «Инструменты и разрешения», «История агента».
- Простой диалог задачи (ввод + результат), список инструментов с режимами, список MCP-серверов, история.
- Подтверждение — в том же стиле, что существующие `confirm_ask / confirm_yes / confirm_no` (RU/EN), плюс «Всегда» только для безопасных случаев.
- Вызовы идут в те же методы приложения, что и панель (общее состояние), без прямой работы с MCP/LLM из GTK-потока.

**Критерии приёмки:**
- Задача, данная в GTK, видна в панели и наоборот; режим инструмента, изменённый в GTK, виден в панели.

---

### T-14. Голосовой канал (P0)

**Статус:** TODO.  
**Зависит от:** T-06, T-13, T-05  
**Файлы:** `yumi/ui/senses.py`, `yumi/brain.py`, `yumi/agent/voice.py` (новый), `tests/test_agent_voice.py` (новый).

**Что сделать:**
- Триггер (RU: «Юми, сделай / запусти / найди», EN: «Yumi, do / run / find») проверять **до** обычной маршрутизации `addressing.route()`: при `agent_enabled` и `agent_voice` фраза уходит агенту с `origin='voice'`.
- Результат озвучивается через `tts.py` и одновременно появляется в панели.
- Подтверждение голосом: «Юми, подтверди / да» → `once`, «отмена / нет» → `deny`; таймаут `agent_confirm_timeout_s` → `deny`. Голосовое «всегда» отвергается с репликой «Навсегда — только кликом».
- Не путать с wake-word и `speaker` гейтом: стоп-слова и speaker-логика остаются приоритетными.
- Микрофон — только через существующий владелец `_ears_exclusive()` / wake-цикл, без второго слушателя.

**Критерии приёмки:**
- «Юми, включи музыку» → агент → инструмент `music.play` → реплика + запись в аудит.
- Нет ответа на вопрос подтверждения → инструмент не выполнен.
- При `agent_enabled=false` голосовое поведение совпадает с текущим.

---

## Фаза 5 — завершение

### T-15. Тесты и документация (P0)

**Статус:** TODO.  
**Зависит от:** T-01 — T-14  
**Файлы:** `tests/test_agent_*.py`, `tests/test_webpanel.py`, `README.ru.md`, `README.md`, `docs/handoff-web-panel.md`, `docs/handoff-agent-mcp.md`, этот файл.

**Что сделать:**
- Обновить статусы и оставить commit-id в строках задач.
- README (ru/en): что такое агент, как включить, как выбрать модель, как добавить провайдер/MCP-сервер, правила подтверждений и аудит.
- `docs/handoff-web-panel.md`: новые роуты, SSE-событие, поля `/api/status`, страница.
- Прогнать все проверки:

```bash
python3 tests/test_webpanel.py
pytest tests/ -q
python3 -m py_compile yumi/config.py yumi/llm.py yumi/brain.py \
  yumi/agent/*.py yumi/agent/mcp/*.py yumi/ui/*.py yumi/webpanel/*.py
for f in yumi/webui/static/js/*.js yumi/webui/static/js/pages/*.js; do
  node --input-type=module --check < "$f" || echo "FAIL $f"
done
```

- Ручный smoke: агент из панели и голосом, подтверждение/отклонение, MCP stdio с тестовым сервером, работа без сети.

**Критерии приёмки:**
- Все проверки зелёные; ручные сценарии пройдены; документация обновлена.

---

### T-16. MCP HTTP/SSE-транспорт (P2, отдельная задача)

**Статус:** TODO — **не входит в этот DoD**.  
**Зависит от:** T-09, T-10  
**Файлы:** `yumi/agent/mcp/http.py`, `tests/test_mcp_http.py`.

**Что сделать:**
- Реализовать уже заложенный `McpTransport` для HTTP/SSE: `GET /sse`, `POST /message`, сессия, reconnect, таймауты.
- Включение — только явным конфигом `transport: 'http'`, по умолчанию выключен; белый список хостов, TLS обязателен для удалённых.
- Отдельный документ/задача, чтобы не раздувать текущую реализацию.

---

## Итоговый Definition of Done

- [ ] T-01 — T-15 выполнены (T-16 остаётся отдельной задачей).
- [ ] Агент доступен **и в GTK, и в веб-панели, и голосом**; состояние синхронизировано.
- [ ] Провайдеры/модели расширяемы через настройки; выбор агента независим от обычного чата.
- [ ] MCP stdio работает; HTTP/SSE имеет готовый интерфейс под будущую реализацию.
- [ ] По умолчанию всё выключено: `agent_enabled=false`, MCP-серверы `enabled=false`, сеть запрещена.
- [ ] Голос не может выдать постоянное разрешение; отрицание сильнее согласия.
- [ ] Секреты и приватные пути не утекают в LLM, логи, API, панель и аудит.
- [ ] Есть лимиты шагов/токенов/таймаутов, аудит и отмена задачи.
- [ ] Тесты и все проверки из T-15 зелёные; README и handoff обновлены.

## Порядок передачи между агентами

1. Агент A: T-01 → T-02 → T-03 (`yumi/llm.py`, настройки, схема). Отчитаться `tests/test_llm.py` + `tests/test_webpanel.py`.
2. Агент B: T-04 → T-05 → T-06 → T-07 (ядро, политика, цикл, аудит). Отчитаться `tests/test_agent_*.py`.
3. Агент C: T-08 → T-09 → T-10 (инструменты, MCP stdio, менеджер). Можно начинать после T-04/T-05, параллельно с A.
4. Агент D: T-11 → T-12 (мост, роуты, страница, SSE) после T-06/T-07/T-10.
5. Агент E: T-13 (GTK) после T-11/T-03; T-14 (голос) после T-13. Можно дробить.
6. Агент F: T-15 (финальные тесты/доки) после всех. T-16 — по отдельному решению владельца.

При передаче всегда обновляйте статусы задач в этом файле и оставляйте commit-ид в строке задачи.
