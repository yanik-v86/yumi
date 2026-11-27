# Handoff: агент Юми с MCP-инструментами (голос + веб-панель)

Статус: **проектная документация готова, реализация не начиналась — ждёт подтверждения владельца**.  
Дата: 2026-11-22.  
Аудитория: агенты, которые будут реализовывать фичу, и ревьюер.  
Список задач: `docs/tasks-agent-mcp.md`.  
Переопределение: `docs/handoff-llm-providers.md` — общий реестр провайдеров (`yumi/llm.py`); раздел 3.1 ниже и реестр в T-01/T-03 считать заменёнными им.  
Обязательно к прочтению: `AGENTS.md`, `docs/handoff-web-panel.md`, `docs/handoff-user-intents.md`, `docs/handoff-speaker-dialogue.md`.

## 1. Что нужно сделать

Сейчас у Юми есть **реактивный** мозг (`brain.py`) и чат с LLM (`chat.py`), но нет агента,
который сам выбирает инструменты и выполняет действия. Нужно добавить слой `yumi/agent/`:

- цикл «восприятие → рассуждение → вызов инструмента → наблюдение → ответ»;
- вызов инструментов через LLM (сначала у Юми его нет — см. риск в §7);
- встроенные инструменты + MCP-серверы (`stdio` сейчас, HTTP/SSE — отдельная задача);
- два канала ввода/вывода: **веб-панель** и **голос** — одновременно;
- единая политика безопасности, подтверждения, лимиты и аудит.

### Решения владельца

| Вопрос | Решение |
|---|---|
| Что за агент | встроенный в Юми, с инструментами и MCP, доступен из панели и голосом |
| MCP-транспорт | `stdio` в этой задаче; `HTTP/SSE` — отдельная будущая задача, интерфейс заложить заранее |
| Модель | расширяемый реестр провайдеров/моделей; уже есть `ollama` и `polza.ai`; добавить свои OpenAI-совместимые |
| Каналы | панель + голос вместе |
| Безопасность | whitelist, `safe/confirm/deny`, подтверждения, песочница, лимиты, аудит; всё выключено по умолчанию |

Термины:

- **задача (Task)** — одно обращение к агенту с шагами и ответом;
- **шаг (Step)** — один вызов инструмента внутри задачи;
- **инструмент (Tool)** — встроенная функция или MCP tool с JSON-схемой;
- **политика** — решение `auto / confirm / deny` для конкретного вызова;
- **подтверждение** — однократное (`once`), отказ (`deny`) или постоянное (`always`, только из панели);
- **trust** — явное доверие к MCP-серверу, не то же самое, что `always` на инструмент.

---

## 2. Текущая архитектура (где что искать)

### Мозг и LLM

- `yumi/chat.py:20-22` — `DEFAULT_MODEL`, `DEFAULT_URL`, `POLZA_MODEL = 'deepseek/deepseek-v4-flash'`.
- `yumi/chat.py:34-42` — `_provider()` (`ollama` / `polza.ai`) и `_url()`.
- `yumi/chat.py:51-76` — `alive()`, `_get()`, `models()`; у Polza список моделей захардкожен.
- `yumi/chat.py:187-210` — `_ollama_chat()` и `_polza_chat()`, тесла ответа; `stream=True` → `urlopen`.
- `yumi/chat.py:213-325` — `_think_filter()`, стриминговые парсеры Ollama и Polza (SSE `data:`).
- `yumi/chat.py:327-371` — `ask_stream()` / `ask()`; пустой `polza_api_key` → сразу `''`.
- `yumi/config.py:42`, `:107-110` — `chat_provider`, `chat_model`, `ollama_url`, `polza_url`, `polza_api_key`.
- `yumi/brain.py` — реактивная маршрутизация; `heard_text()` ~`:1336-1478`; меню и диалоги подтверждений
  `intent_confirm` ~`:1295-1306`, `_voice_confirm_web()` ~`:1463-1475`.
- **Важно:** `chat.py` не поддерживает `tools`/`tool_calls`. Реестр `yumi/llm.py` должен добавить это,
  переиспользовав транспорт, а не дублируя его.

### Настройки, панель, мост

- `yumi/config.py:20-209` — `DEFAULT_SETTINGS`; `:211-219` — `TTS_PROFILE_*`; `:241-294` — `Store`/`load_settings`.
- `yumi/config.py:419-629` — `UI` со строками ru/en; `:632-635` — `tr()`.
- `yumi/webpanel/catalog.py` — `SECRET_KEYS`, `PAGES`, `SECTION_PAGE`, `SECTIONS`, `KEY_SECTION`,
  `TYPES`, `CHOICES`, `RANGES`, `TITLES`, `HINTS`, `CONFIG_FILES`; каждый новый ключ `DEFAULT_SETTINGS`
  обязан попасть в схему — это проверяет `tests/test_webpanel.py`.
- `yumi/ui/webpanel.py:291-395` — `_web_snapshot()`; `:397-442` — `_web_apply_settings()`; SSE-тик рядом.
- `yumi/ui/bridge.py:17-18` — `_on()` → `App._web_call` → `GLib.idle_add`; `:432-441` — `_ears_exclusive()`.
- `yumi/webpanel/server.py:371-418` — таблица роутов `: METHOD → handler`; CSRF и аудит в обработчиках.
- `yumi/webui/static/js/api.js` — объект `api` и `EVENTS`; `app.js` — ленивый импорт страниц из `PAGES`.
- Новая страница: запись в `catalog.PAGES` + `pages/agent.js::render(view, ctx)` + lazy import в `app.js`.
- Только `createElement`/`textContent`, никакого `innerHTML` с данными. Новые строки RU/EN.

### Голос, разрешения, состояние

- `yumi/ui/senses.py:236-274` — `followup_listen()`; `:357-380` — wake-цикл; voice-state рядом.
- `yumi/ears.py` — `wake()`, `listen()`, `mics()`, `stop()`, `mute()`, `unmute()`.
- `yumi/addressing.py` — `route(text, hints)` и `addressee(text, labels)`; агентный триггер проверять **до** `route()`.
- `yumi/permission.py` — `is_secret()`, `spoken_answer()`, `negative_wins()`, `normalize_target()`.
  Переиспользовать для подтверждений; не переписывать.
- `yumi/voice_state.py` — единый владелец микрофона; агент не создаёт второго слушателя.
- `yumi/tts.py::speak()` — Weg result в голос; `speaker_verify`/`speaker` гейт имеет приоритет над агентом.

**Запрещено:** импортировать GTK в `yumi/webpanel/` и в `yumi/agent/`;_log'ить ключи и аргументы с секретами;
передавать embedding'ы или биометрию в агентный контекст; запускать MCP-процессы до явного включения.

---

## 3. Контракты

### 3.1 Настройки (полный список — в tasks T-03)

| Ключ | Тип | По умолчанию | Смысл |
|---|---|---:|---|
| `agent_enabled` | bool | `false` | главный выключатель |
| `agent_voice` | bool | `true` | голосовой триггер |
| `agent_provider` | choice | `polza.ai` | провайдер рассуждений |
| `agent_model` | str | `''` | пусто → fallback провайдера |
| `agent_providers_custom` | list | `[]` | `{id, name, kind:'openai', url, models:[]}` без ключей |
| `agent_custom_keys` | dict | `{}` | ключи кастомных провайдеров → `SECRET_KEYS` |
| `agent_max_steps` | int | `8` | шагов на задачу |
| `agent_tool_timeout_s` | int | `20` | таймаут инструмента |
| `agent_max_tokens` | int | `4000` | токенов на задачу |
| `agent_confirm_timeout_s` | int | `15` | голосовое подтверждение |
| `agent_audit_n` | int | `200` | записей аудита в снимке |
| `agent_mcp_servers` | list | `[]` | конфиг MCP, все `enabled: false` |
| `agent_file_sandbox` | bool | `true` | файлы только в песочнице |
| `agent_allow_network` | bool | `false` | сеть запрещена |

`polza.ai` выбран по умолчанию, потому что локальная модель `lakomoor/vikhr-llama-3.2-1b-instruct:1b`
не гарантирует tool-calling. Пользователь может выбрать `ollama` вручную; тогда включается JSON-fallback.

### 3.2 Task и Step

```python
Task = {
    'id': int, 'origin': 'voice'|'panel'|'system', 'text': str,
    'created': float, 'status': 'queued'|'running'|'awaiting_confirmation'
                             |'done'|'failed'|'cancelled',
    'steps': [Step], 'answer': str,
}
Step = {
    'n': int, 'thought': str, 'tool': str|None, 'args': dict,
    'risk': 'safe'|'confirm'|'deny', 'result': str, 'error': str,
    'elapsed': float, 'ts': float, 'decision': 'auto'|'once'|'deny'|'always',
}
```

### 3.3 Инструмент

```python
Tool = {
    'name': str,                    # 'music.play' или 'mcp__files__read_file'
    'description_ru': str, 'description_en': str,
    'risk': 'safe'|'confirm'|'deny',
    'input_schema': {...},          # JSON Schema для LLM
    'handler': callable,            # (args: dict) -> str, без GTK
}
```

Режим пользователя хранится отдельно и может только **усилить** риск (не ослабить `deny` для
секретных/сетевых инструментов). Имя MCP-инструмента всегда префиксовано `mcp__<id>__`.

### 3.4 Политика

| Категория | Инструменты | Решение |
|---|---|---|
| `safe` | музыка, чтение дневника/статуса, `ui.say`, таймеры, чтение whitelist настроек | `auto` |
| `confirm` | запись в дневник, изменение обычных настроек, кнопки `actions.json`, инструменты доверенного MCP | запрос |
| `deny` | shell, произвольные файлы, сеть, отправка сообщений, `agent_*`/секретные настройки, все инструменты недоверенного/невключённого MCP | отказ |

Правила: голос не выдаёт `always`; «да и нет» → `deny`; `..` и symlink на секретный путь — `deny`;
доверие к MCP-серверу — отдельный toggle в конфиге, не результат голосового подтверждения.

### 3.5 MCP-конфиг

```json
{
  "id": "files", "name": "Local files", "transport": "stdio",
  "command": "python3", "args": ["-m", "mcp_files"],
  "env": {}, "enabled": false,
  "trust": "untrusted", "allowed_tools": []
}
```

По умолчанию серверы не запускаются. `tools/list` регистрирует только инструменты из `allowed_tools`.
`trust=untrusted` → `deny`, `trusted` → `confirm`. Процесс получает whitelist env, песочницу как `cwd`,
таймауты и принудительный `kill` по exceeded.

### 3.6 Аудит

Путь: `STATE_DIR / 'agent_audit.jsonl'`, append-only, ротация по `agent_audit_n`.

```json
{"ts": 1763820000.0, "task_id": 12, "origin": "voice", "tool": "mcp__files__read",
 "args_masked": {"path": "~/notes.txt"}, "decision": "once",
 "result_status": "ok", "elapsed": 0.31}
```

Никаких ключей, токенов, содержимого приватных файлов и embedding'ов.

### 3.7 Роуты и WebBridge

| Метод | Роут | WebBridge |
|---|---|---|
| GET | `/api/agent/status` | `agent_status()` |
| GET | `/api/agent/tools` | `agent_tools()` |
| POST | `/api/agent/tool` | `agent_tool_set(name, mode)` |
| GET | `/api/agent/providers` | `agent_providers()` |
| GET | `/api/agent/models?provider=` | `agent_models(provider)` |
| GET | `/api/agent/history` | `agent_history()` |
| GET | `/api/agent/audit` | `agent_audit()` |
| POST | `/api/agent/task` | `agent_submit_task(text, origin='panel')` |
| POST | `/api/agent/approve` | `agent_approve(task_id, step_id, decision)` |
| POST | `/api/agent/cancel` | `agent_cancel(task_id)` |
| POST | `/api/agent/mcp/refresh` | `agent_mcp_refresh()` |

CSRF на все POST, аудит вызовов, ответы без секретов. SSE-событие `agent`:
`{task_id, step, status, answer}` — только безопасные поля; `EVENTS` в `api.js` дополняется.

### 3.8 `/api/status`

```json
{
  "runtime": {
    "agent": {
      "enabled": true, "provider": "polza.ai", "model": "deepseek/deepseek-v4-flash",
      "active_task": {"id": 12, "status": "awaiting_confirmation"},
      "pending_confirmations": 1, "tools_count": 14,
      "mcp": [{"id": "files", "enabled": true, "connected": true, "tools": 3, "last_error": null}],
      "last_error": null
    }
  }
}
```

В `light=True` оставить `{enabled, active_task id, pending_confirmations}`.

---

## 4. Потоки (поведение)

### 4.1 Задача из панели

1. `pages/agent.js` → `api.agentSubmit(text)` → `POST /api/agent/task` → `WebBridge.agent_submit_task()`.
2. Через `_on()`/`GLib.idle_add` задача попадает в `agent.core` в GTK-потоке; тяжёлый цикл — в worker.
3. Каждый шаг публикует SSE `agent`; шаг с `risk=confirm` останавливается в `awaiting_confirmation`.
4. Пользователь жмёт «Разрешить / Отклонить» → `POST /api/agent/approve` → цикл продолжается или `deny`.
5. Ответ и шаги видны в панели; при включённом `tts` — озвучиваются.

### 4.2 Голос

1. `senses.py` получает распознанную фразу; до `addressing.route()` проверяется `agent.voice.trigger()`.
2. При совпадении — `agent_submit_task(text, origin='voice')` вместо обычного чата.
3. Для `confirm`-шага: TTS задаёт вопрос, `ears.listen()` слушает короткий ответ с таймаутом
   `agent_confirm_timeout_s`; «да/подтверди» → `once`, «нет/отмена» → `deny`, тишина → `deny`.
4. Результат озвучивается и дублируется в SSE/статус панели.

### 4.3 MCP

1. При старте/по кнопке менеджер читает `agent_mcp_servers`, запускает только `enabled: true`.
2. `initialize` → `notifications/initialized` → `tools/list` → фильтр `allowed_tools` → `registry.register()`.
3. LLM получает схемы через `registry.openai_schemas()`; вызов `mcp__id__tool` → `tools/call`.
4. `close()` шлёт `shutdown`/`exit`, при зависании — `kill`. Ошибка одного сервера не роняет остальные.

### 4.4 Псевдокод цикла (для T-06)

```python
def run_task(task, settings, model, registry, policy, audit):
    ctx = context.build(settings, task)
    for n in range(1, settings['agent_max_steps'] + 1):
        call = model.choose_tool(ctx, registry.openai_schemas())   # или JSON-fallback
        if call is None:
            task.answer = model.finish(ctx)
            return 'done'
        tool = registry.get(call['name'])
        decision = policy.decide(tool, call['args'], task.origin)
        if decision == 'deny':
            ctx.add_observation('denied', call['name'])
            continue
        if decision == 'confirm':
            decision = policy.ask(task, n, tool, call['args'])      # панель или голос
            if decision != 'once':
                ctx.add_observation('cancelled', call['name'])
                continue
        result = executor.call(tool, call['args'], timeout=settings['agent_tool_timeout_s'])
        audit.write(task, call, decision, result)
        ctx.add_observation(call['name'], result)
    return 'failed'   # лимит шагов
```

---

## 5. Изменения по файлам

| Файл | Что добавить |
|---|---|
| `yumi/llm.py` (новый) | реестр провайдеров, кастомные OpenAI endpoint'ы, `chat()` с `tools` + JSON-fallback |
| `yumi/agent/` (новый) | `types`, `context`, `registry`, `policy`, `core`, `executor`, `audit`, `voice`, `tools/builtin` |
| `yumi/agent/mcp/` (новый) | `base`, `stdio`, `manager`; `http.py` — заготовка под T-16 |
| `yumi/config.py` | новые ключи, `UI` ru/en, пути аудита/песочницы |
| `yumi/permission.py` | только переиспользовать (`is_secret`, `spoken_answer`, `negative_wins`) |
| `yumi/webpanel/catalog.py` | секция `agent`, схема, `SECRET_KEYS` для `agent_custom_keys`, страница |
| `yumi/ui/webpanel.py` | `runtime.agent`, live-apply выключения агента/МCP |
| `yumi/ui/bridge.py` | 11 методов из §3.7, всё через `_on()`; микрофон — `_ears_exclusive()` |
| `yumi/webpanel/server.py` | 11 роутов, CSRF, аудит без секретов |
| `yumi/webui/static/js/api.js`, `pages/agent.js`, `app.js` | клиент, SSE, страница, lazy import |
| `yumi/brain.py`, `yumi/ui/senses.py` | GTK-меню, голосовой триггер, подтверждения |
| `tests/test_agent_*.py`, `tests/test_webpanel.py` | цикл, политика, MCP, голос, API, схема |
| `README*.md`, `docs/handoff-web-panel.md`, этот файл | документация |

---

## 6. Риски и решения

| Риск | Смягчение |
|---|---|
| Локальная 1b-модель не умеет tool-calling | дефолт `polza.ai`; для `ollama` — JSON-fallback + проверка поддержки на целевой машине |
| Prompt injection от вывода MCP-инструмента | вывод инструмента — данные, не инструкции; лимит размера; `deny` по умолчанию; аудит |
| Утечка ключей в LLM/логи/панель | маскирование по `SECRET_KEYS` + `permission.SECRET_PATHS`; ключи не попадают в контекст |
| Голос случайно разрешил опасное действие | голос только `once/deny`; `always` — кликом; отрицание сильнее согласия; таймаут → `deny` |
| MCP-процесс завис/течёт ресурсами | таймауты, whitelist env, `cwd`-песочница, `kill`, лимит вывода |
| Агент вызвал агента | вложенные задачи запрещены на уровне executor |
| Гонка за микрофон | агент использует существующего владельца; `_ears_exclusive()`; стоп-слова приоритетнее |
| GTK-поток заблокирован | цикл и MCP — в worker; только `GLib.idle_add` для публикации |
| Старый `settings.json` | новые ключи дефолтными, миграция не требуется |
| Схема панели | `tests/test_webpanel.py` требует каждый ключ в `catalog.py` |

---

## 7. Тесты

- `tests/test_llm.py`: провайдеры, модели, tool_calls, JSON-fallback, маскирование ключей.
- `tests/test_agent_core.py`: типы, контекст, реестр, коллизии имён.
- `tests/test_agent_policy.py`: `safe/confirm/deny`, голос vs панель, `always`, `..`/symlink, аудит.
- `tests/test_agent_loop.py`: два шага → ответ, лимит шагов, отмена, запрет рекурсии.
- `tests/test_agent_tools.py`: встроенные инструменты и невалидные аргументы.
- `tests/test_mcp_stdio.py`: поддельный MCP-сервер, `tools/list`, `tools/call`, зависание, env.
- `tests/test_agent_voice.py`: триггер, подтверждение/таймаут/отрицание, приоритет стоп-слов.
- `tests/test_webpanel.py`: схема, CSRF, роуты, `/api/status`, отсутствие секретов.

Команды проверки:

```bash
python3 tests/test_webpanel.py
pytest tests/ -q
python3 -m py_compile yumi/config.py yumi/llm.py yumi/brain.py \
  yumi/agent/*.py yumi/agent/mcp/*.py yumi/ui/*.py yumi/webpanel/*.py
for f in yumi/webui/static/js/*.js yumi/webui/static/js/pages/*.js; do
  node --input-type=module --check < "$f" || echo "FAIL $f"
done
```

---

## 8. Критерии приёмки

1. Задача из панели и голосом выполняется одним и тем же агентом; статус и история общие.
2. Выбор провайдера/модели агента независим от обычного чата; кастомный провайдер добавляется настройкой.
3. MCP stdio с тестовым сервером регистрирует инструменты только после явного включения и whitelist'а.
4. `confirm`-инструмент не выполняется без подтверждения; нет ответа голосом → отказ.
5. Голос не может выдать `always`; «да и нет» → отказ; секретный путь не разрешается.
6. В логах/API/панели/аудите нет ключей, токенов, embedding'ов и содержимого приватных файлов.
7. Лимиты шагов/токенов/таймаутов работают, задача отменяется, рекурсия невозможна.
8. При `agent_enabled=false` и без MCP-серверов поведение Юми совпадает с текущим.
9. Все проверки §7 зелёные; README (ru/en) и handoff обновлены.

---

## 9. Открытые детали (решить при реализации)

- Нужен ли отдельный системный промпт агента или переиспользовать `chat.system_prompt()` с доп. блоком про инструменты. Рекомендация: отдельный, в `agent/context.py`, чтобы не раздувать реплики Юми.
- Формат JSON-fallback для моделей без tool-calling: зафиксировать в `llm.py` и покрыть тестом до подключения Ollama.
- Политика для двух и более активных задач: очередь или отказ. Рекомендация: одна активная + `queued` от панели, вежливый отказ голосом.
- Куда писать `.jsonl` аудит — `STATE_DIR` (предпочтительно) или `CACHE_DIR`; ротация по числу записей, не по размеру файла.
- Точные триггеры RU/EN и структура голосового вопроса подтверждения — согласовать с текущими фразами `confirm_ask/confirm_yes/confirm_no`.
- Как показывать аргументы инструмента в карточке подтверждения: полные (но замаскированные) или только имя инструмента + краткое описание. Рекомендация: маскированные JSON, обрезанные до 500 символов.

---

## 10. Что сделать первому агенту (быстрый старт)

1. Прочитать `AGENTS.md`, `docs/tasks-agent-mcp.md`, этот файл.
2. Не трогать код, пока владелец не подтвердит старт.
3. После подтверждения — начать с T-01 (`yumi/llm.py`) и T-03 (настройки/схема), прогнать
   `python3 tests/test_webpanel.py` до перехода к ядру агента.
4. Обновлять статусы задач в `docs/tasks-agent-mcp.md` и оставлять commit-ид в строке задачи.
5. T-16 (HTTP/SSE) не реализовывать без отдельного решения владельца.
