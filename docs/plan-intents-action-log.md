# План: журнал действий пользовательских интентов

Статус: **реализовано (L-01…L-06), ожидает ревью**.
Дата: 2026-11-25.  
Аудитория: агент, который будет реализовывать журнал, и ревьюер.

Связанные документы: [`handoff-intents-action-log.md`](handoff-intents-action-log.md)
(контракты), [`plan-internal-clock.md`](plan-internal-clock.md) и
[`handoff-internal-clock.md`](handoff-internal-clock.md) — **отдельная** задача
про внутренние часы, `docs/handoff-user-intents.md`,
`docs/tasks-user-intents.md`, `AGENTS.md`.

---

## 0. Что и зачем

У `#/user-intents` сегодня есть CRUD, импорт/экспорт, сухой `/test` и запуск
через `/run`. Но путь интента почти не наблюдаем: в лучшем случае одна строка
`_mind_log()` и одна строка аудита при изменении файла. Не видно:

- что именно совпало и с каким score;
- было ли подтверждение и кто его дал;
- что поставлено в очередь, чем закончилась команда, был ли таймаут;
- сколько занял запуск и какой ответ ушёл в баблу/голос.

Нужен отдельный структурированный JSONL-журнал с уровнями детализации,
управляемыми из веб-панели без перезапуска.

### Не цели этого этапа

- Не делать внутренние часы, планировщик и напоминания — это отдельная задача
  `plan-internal-clock.md`. Журнал не тикает и не планирует ничего.
- Не логировать текст команд и URL **никогда**; услышанную фразу и stdout —
  только при явном opt-in.
- Не добавлять новую страницу: блок «Журнал действий» живёт на
  `#/user-intents`. Счётчик страниц в `tests/test_webpanel.py` остаётся 16.
- Не делать GTK-просмотрщик: в GTK остаются только переключатель уровня
  (меню) и исполнение, просмотр — в панели. Это то же исключение, что и для
  `user-intents/<id>/intent.json`.

---

## 1. Состояние до старта

- Логи сегодня: `/tmp/yumi/mind.log` (`_mind_log`), `/tmp/yumi/app.log`,
  `/tmp/yumi/judge.log`, `STATE_DIR/web-audit.log`; `/api/logs` читает хвост
  до 512 КБ. Структурированного журнала действий нет.
- `logging`-модуль не используется; новый файл — самостоятельный канал,
  `_mind_log()` не заменяется.
- Путь: `config.STATE_DIR`; там же лежит `web-audit.log`.
- В рабочем дереве есть незакоммиченные правки `yumi/brain.py` и
  `yumi/ui/app.py`: `extra_env={'YUMI_INTENT_TEXT': heard}` передаётся через
  кортеж `('run_capture', …)` в `App.run_capture()`. Их сохраняем: это
  единственный надёжный источник услышанной фразы для журнала. Форму кортежа
  не меняем, `run_id` кладём внутрь уже существующего `options`.
- 4 провала в `tests/test_speaker_gate.py` — pre-existing, не регрессия.

---

## 2. Архитектура одним взглядом

```
голос / кнопка «Проверить»
        │
        ▼
brain.py: voice_user_intent → _voice_run → user_intent_answer
        │        intent_log.emit(...)     │
        └─────────────────────────────────┤
                                          ▼
                              yumi/intent_log.py
                              STATE_DIR/user-intents.log
                                          │
                     WebBridge → PanelMixin → /api/user-intents/log
                                          │
                                  SSE 'intents_log'
```

Журнал — чистый модуль без GTK, HTTP, сетевых вызовов и импорта `Brain`.

---

## 3. Задачи

Приоритеты: P0 — блокирующий, P1 — важный. Все задачи выполнены.
ID задач использовать в коммитах: `feat(intents-log): L-01 ...`.

| ID | Приоритет | Статус | Задача | Зависит от |
|----|-----------|--------|--------|------------|
| L-01 | P0 | готово | Настройки журнала в `DEFAULT_SETTINGS`, `catalog.py`, GTK-меню | — |
| L-02 | P0 | готово | `yumi/intent_log.py`: уровни, JSONL, redaction, ротация, чтение/очистка | L-01 |
| L-03 | P0 | готово | Инструментация `Brain`/`App`: `run_id` и события match/decision/start/result/error | L-02 |
| L-04 | P0 | готово | Панель: Bridge → роуты → `api.js` → блок на `#/user-intents`, SSE | L-03 |
| L-05 | P0 | готово | Тесты безопасности и smoke, проверка отсутствия утечек | L-04 |
| L-06 | P1 | готово | README (ru/en), handoff панели, финальная сверка | L-05 |

### L-01. Настройки и двуязычные строки (P0) — готово

**Файлы:** `yumi/config.py`, `yumi/webpanel/catalog.py`, `yumi/brain.py`
(`cycles`, `open_menu`), `tests/test_webpanel.py`.

**Что сделать:**

- Добавить в `DEFAULT_SETTINGS`:
  - `intents_log_level = 'off'` (`off|error|result|action|match|trace`);
  - `intents_log_include_text = False`;
  - `intents_log_max_chars = 200` (диапазон 100..8000);
  - `intents_log_max_lines = 2000` (диапазон 100..20000).
- В `catalog.py`: `CHOICES`, `TYPES`, `RANGES`, `TITLES`/`HINTS` ru/en,
  `KEY_SECTION` → существующая секция `mind`. Новую секцию не заводим.
- `_web_apply_settings()` отдельной ветки не требует: модуль читает настройки
  из переданного `settings` на каждую запись; если появится кэш — сбросить
  его здесь же.
- GTK-эквивалент: `Brain.cycles()` получает `intents_log_level`, в
  `open_menu('set_chat')` — строка «Журнал действий». Новые `config.UI` — ru/en.
  GTK-просмотрщика лога нет: просмотр в панели.

**Критерии приёмки:** `python3 tests/test_webpanel.py` проходит; тумблер/цикл
меняют одно и то же значение `settings.json`.

---

### L-02. Модуль журнала (P0) — готово

**Файлы:** `yumi/intent_log.py` (новый), `tests/test_intent_log.py` (новый).

**Что сделать:**

- `config.STATE_DIR / 'user-intents.log'`, JSONL, UTF-8, файл 0600.
- `emit(settings, stage, **fields)`: проверяет уровень по кумулятивной шкале,
  санитизирует поля, добавляет `v=1`, `ts`, `run_id`, `source`.
- Redaction: `action.value` (команда/URL) не пишется **никогда**; только
  `action_sha` и `action_len`. При `intents_log_include_text=true` — короткие
  превью услышанной фразы и stdout, обрезанные до `intents_log_max_chars`.
- Ротация по `intents_log_max_lines` через `.tmp` + `replace`, не чаще раза
  в N записей. `read(limit, intent, stage)` возвращает свежие строки сверху,
  `clear()` обнуляет файл.
- Никаких вызовов `Brain`/GTK/сети.

**Критерии приёмки:** при дефолтах в логе нет фразы, команды, URL и stdout;
`off` не создаёт записей; при 2500 событиях файл ≤ `max_lines`; фильтры
`read()` работают.

---

### L-03. Инструментация (P0) — готово

**Файлы:** `yumi/brain.py`, `yumi/ui/app.py`, `tests/test_voice_intent.py`.

**Что сделать:**

- `run_id = uuid.uuid4().hex[:8]` генерируется при совпадении; передаётся
  в `run`-dict и внутрь `options` кортежа `('run_capture', …)`. Форму кортежа
  не трогаем, `extra_env` сохраняем.
- Точки `emit()`:
  - `voice_user_intent()` — `heard`, `match`, `decision`/`skip` (уровни
    `trace`/`match`/`action`);
  - `_voice_run()` — `start` (action type, флаги ответа, `run_id`);
  - `user_intent_answer()` — `result` (`status`, длина ответа, лимит баблы);
  - `App.run_capture()` — `error` на timeout/OSError, без команды и stdout;
  - панель `_web_user_intents_run()` — `stage=panel` с тем же `run_id`.
- `_mind_log()` оставляем как есть: это отдельный канал.
- Завершение команды (`run_capture`) логируется один раз — в
  `user_intent_answer()`, чтобы не дублировать `result`.

**Критерии приёмки:** один запуск даёт цепочку `match → start → result` с
одинаковым `run_id`; timeout даёт `error` с длительностью; при дефолтах ни
один вызов не пишет текст; `tests/test_voice_intent.py` зелёный.

---

### L-04. Журнал в панели (P0) — готово

**Файлы:** `yumi/ui/bridge.py`, `yumi/ui/webpanel.py`,
`yumi/webpanel/server.py`, `yumi/webui/static/js/api.js`,
`yumi/webui/static/js/pages/user-intents.js`, `tests/test_webpanel.py`.

**Что сделать:**

- `WebBridge.intents_log_get(limit, intent, stage)` и
  `WebBridge.intents_log_clear()` → методы `PanelMixin` с теми же именами.
- `GET /api/user-intents/log` и `POST /api/user-intents/log/clear`; мутации под
  общим CSRF, аудит `Panel.audit(..., 'intents-log-clear', '')` без деталей.
- Блок «Журнал действий» на существующей странице: уровень через
  `ctx.applySettings`, таблица строк, фильтры по id/stage, «Обновить» и
  «Очистить». DOM только `createElement`/`textContent`.
- `runtime.user_intents.log` в `_web_snapshot()`: `level`, `path`,
  `last_event_at`, `errors`, `lines`.
- Новое SSE-событие `intents_log` в `api.js:EVENTS`; публиковать только при
  появлении строки, не в каждый `web_tick()`.
- `/api/logs` получает имя `intents` → тот же файл.

**Критерии приёмки:** чтение требует сессии; очистка без CSRF → 403; страница
работает на ru/en; счётчик страниц остаётся 16.

---

### L-05. Безопасность и smoke (P0) — готово

**Файлы:** `tests/test_intent_log.py`, `tests/test_webpanel.py`,
`tests/smoke_intents_log.sh` (новый).

**Что сделать:**

- Тесты: маскировка при дефолтах и при `include_text=true`, filesystem mode
  0600, ротация, `run_id`, отсутствие токена/секретов, CSRF на clear.
- Smoke без GTK: создать интент → `/run` → прочитать журнал → проверить,
  что команда/фраза не попали в лог; включить `include_text` → повторить →
  убедиться, что превью есть, а команда/URL отсутствуют; `clear`.

**Критерии приёмки:** smoke зелёный; в логе нет `action.value` ни при каких
настройках.

---

### L-06. Документация (P1) — готово

**Файлы:** `README.ru.md`, `README.md`, `docs/handoff-web-panel.md`,
`docs/handoff-user-intents.md`, `docs/tasks-user-intents.md`.

**Что сделать:**

- README (ru/en): уровни журнала, путь файла, как включить превью текста,
  где читать/очищать, что часы/напоминания — другая задача.
- В handoff панели: новые роуты, SSE `intents_log`, поле снимка, исключение
  по GTK-просмотрщику.
- В handoff/tasks интентов: ссылки на эту пару документов.

**Критерии приёмки:** документы не смешивают журнал и внутренние часы.

---

## 4. Порядок передачи между агентами

1. **Агент A:** L-01 → L-02 (настройки и ядро журнала). Проверить
   `test_webpanel.py`, `test_intent_log.py`.
2. **Агент B:** L-03 (инструментация). Обязательно сверить незакоммиченный
   diff `extra_env`; проверить `test_voice_intent.py`.
3. **Агент C:** L-04 (панель) параллельно с B, если контракты из handoff
   зафиксированы; проверить `test_webpanel.py`, JS syntax check.
4. **Агент D:** L-05 → L-06 после всех.

При передаче обновлять статусы задач в этом файле и оставлять commit-id.

---

## 5. Тесты и быстрая проверка

```bash
python3 tests/test_webpanel.py
python3 tests/test_user_intents.py
python3 tests/test_voice_intent.py
python3 tests/test_intent_log.py
python3 tests/test_addressing.py
bash tests/smoke_user_intents.sh
bash tests/smoke_intents_log.sh
python3 -m py_compile yumi/webpanel/*.py yumi/config.py yumi/brain.py \
  yumi/ui/*.py yumi/user_intents.py yumi/intent_log.py
for f in yumi/webui/static/js/*.js yumi/webui/static/js/pages/*.js; do
  node --input-type=module --check < "$f" || echo "FAIL $f"
done
pytest tests/ -q
```

---

## 6. Definition of Done

- [ ] Уровни редактируются из панели и живо применяются; `off` ничего не пишет.
- [ ] Один запуск интента имеет сквозной `run_id` и цепочку
      `match/decision/start/result` (при достаточно подробном уровне).
- [ ] По умолчанию в логе нет текста фразы, stdout, команд и URL; команда/URL
      не пишутся никогда.
- [ ] Журнал читается и очищается из панели; имя `intents` есть в `/api/logs`.
- [ ] SSE `intents_log` обновляет таблицу без polling-а; 16 страниц не изменилось.
- [ ] GTK имеет переключатель уровня, но не имеет просмотрщика — исключение
      явно названо.
- [ ] README (ru/en) и handoff'ы обновлены; тесты из §5 зелёные.
- [ ] Ни в одном документе журнал не смешан с внутренними часами.

---

## 7. Открытые вопросы (решить до L-03)

1. **Уровень по умолчанию.** Предложено `off`, чтобы не включать запись без
   явного желания. Если владелец хочет видеть результаты сразу — заменить на
   `result`, контракт события от этого не меняется.
2. **Имена уровней.** `off|error|result|action|match|trace`; альтернатива —
   классические `ERROR/WARN/INFO/DEBUG`. Меняется только список в
   `intent_log.py` и `catalog.CHOICES`.
3. **Формат previews.** Ограничить фразу и stdout одним полем `text` или
   разделить на `heard_text`/`stdout_preview`? Рекомендуется разделить.
4. **Имя SSE-события.** `intents_log`, чтобы не конфликтовать с возможными
   будущими событиями часов.
5. **Ротация.** По числу строк (`max_lines`) или по размеру файла?
   Рекомендуется по числу строк, как проще тестировать.
