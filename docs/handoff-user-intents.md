# Handoff: пользовательские интенты (свои команды и фразы)

Статус: **T-01..T-08 реализованы; T-09 (P2, опционально) не реализован**.  
Дата: 2026-11-25 (уточнено: без GTK-редактора; код 2026-11-25).  
Аудитория: агент, который будет реализовывать фичу, и ревьюер.

Следующие апгрейды описаны в двух **независимых** парах документов:

- [`plan-intents-action-log.md`](plan-intents-action-log.md) и
  [`handoff-intents-action-log.md`](handoff-intents-action-log.md) — журнал
  действий пользовательских интентов;
- [`plan-internal-clock.md`](plan-internal-clock.md) и
  [`handoff-internal-clock.md`](handoff-internal-clock.md) — внутренние часы
  Юми, общий механизм времени для интентов и других задач.

## 0. Решение по GTK

Управление пользовательскими интентами доступно **только в веб-панели и через ручное
редактирование `user-intents/<id>/intent.json`**. Отдельный GTK-редактор не делается —
осознанное исключение из общего правила `AGENTS.md` по решению владельца.

- В GTK остаётся только **исполнение** фраз, распознанных как пользовательский интент.
- Единый источник истины — каталог с одним JSON-файлом на правило; панель даёт полный CRUD
  с валидацией, файл даёт офлайн-путь без запуска панели.
- Дублирования валидации в GTK не допускается: никаких скрытых форм и вторых правил записи.

## 1. Что нужно сделать

Сейчас Юми распознаёт голосовые команды по правилам `yumi/nlu.py` поверх `actions.json`
(точная фраза `1.0`, keyword `0.8`, fuzzy `0.6`), а если правила не сработали —
ONNX-классификатором `yumi/intents.py` с метками из `labels.json` каталога модели
(`~/.local/share/yumi/intents`, `intents.py:21,52`; API — `.classify()`, `intents.py:123`).
Пользователь может добавить свои фразы в `actions.json`,
но у этого слоя нет версионирования, валидации импорта/экспорта и отдельного API.

Цель фичи: **дать пользователю создавать, редактировать, импортировать/экспортировать
и тестировать собственные интенты из веб-панели или вручную в JSON, без переобучения ONNX
и без GTK-редактора**.

| Термин | Что есть сейчас | Что добавляем |
|---|---|---|
| `intents` в настройках | ONNX-классификатор, enable/disable, порог, модель | **не трогаем**, не переименовываем |
| «свои интенты» / `user_intents` | `actions.json` + `nlu.recognize()` | отдельный слой со своим файлом, схемой и API |
| «кнопки» | `actions.json`, кольцо быстрых кнопок | оставляем совместимыми, не ломаем |
| GTK | исполнение голосовых команд | **без изменений в части CRUD** |

## 2. Текущая архитектура (где что искать)

### Распознавание
- `yumi/nlu.py` — `recognize(text, entries, ...)` → `IntentResult`. Скоринг: `1.0 / 0.8 / 0.6`
  (`nlu.py:33-35`). Фильтр `command or url` (`nlu.py:233`) — его нужно расширить маркером
  `user_intent` для `say`. `priority` сейчас только разрешает ничьи после score
  (`nlu.py:251-259`, `tests/test_nlu.py:102`), не абсолютный приоритет.
- `yumi/intents.py` — `classify(text, actions, min_prob=...)`, а не `predict()`; тоже фильтрует
  `command or url` (`intents.py:140`). **Не трогаем**: ONNX по-прежнему получает только
  записи `actions.json`.
- `yumi/brain.py` — `heard_text()` (`brain.py:1587-1796`). Реальный порядок:
  music-control → `voice_intent()` (actions.json + ONNX внутри `nlu.recognize()`) →
  ещё music-guess → notes/time/weather/joke/params/имя → addressing/fallback → chat.
  `voice_intent()` и его подтверждение — `brain.py:1934-1975`, `1883-1908`.
- `yumi/extras.py` — `actions_check()` (`extras.py:322-331`) следит за mtime `actions.json`;
  `form_open()/form_save()` — редактор именно кнопок, не интентов.
- `yumi/addressing.py:105` — `hints_from(actions)` берёт подсказки только из `actions.json`;
  фразы пользовательских интентов надо передавать туда же.

### Хранение и конфиг
- `yumi/config.py`: `CONFIG_DIR = XDG_CONFIG_HOME/yumi` (`config.py:12-16`),
  `ACTIONS_FILE`, `DEFAULT_SETTINGS`, `load_actions()`, `save_actions()`.
  `USER_CONFIG_DIR`/`YUMI_CONFIG_DIR` в коде **нет**; тесты меняют `config.CONFIG_DIR`
  или передают `config_dir=` в `Panel`.
- `config.save_actions()` (`config.py:374-382`) пишет через `tmp` + `replace`, но **без блокировки**.

### Веб-панель
- `yumi/ui/bridge.py` — `WebBridge`, единственный контракт HTTP ↔ GTK. `_on()` →
  `App._web_call` → `GLib.idle_add` (`bridge.py:17-18`).
- `yumi/ui/webpanel.py` — `PanelMixin`: `_web_snapshot()`, `_web_apply_settings()`,
  `_web_actions_get()`, `_clean_actions()`, `_web_config_save()`.
- `yumi/webpanel/server.py` — роуты, SSE, статика, аудит. CSRF и origin проверяются
  централизованно для `POST/PUT/PATCH/DELETE` (`server.py:364-368`), отдельно в роутах не пишем.
  `/api/upload` (`server.py:477`, `:703-720`) кладёт файл в `CACHE_DIR/uploads` без проверки схемы —
  для импорта интентов не годится.
- `yumi/webpanel/catalog.py` — `PAGES`, `SECTIONS`, `SECTION_PAGE`, `KEY_SECTION`,
  `TITLES`, `HINTS`, `TYPES`, `CHOICES`, `RANGES`, `SECRET_KEYS`, `CONFIG_FILES`, `schema()`
  (`catalog.py:574-595`). Каждый ключ `DEFAULT_SETTINGS` попадает в схему автоматически.
- `yumi/webui/static/js/api.js` — низкоуровневый `api.get/post/put/...`; готовых
  `actionsGet/Put` там нет, страницы вызывают `api.get/put('/api/actions')` напрямую.
- `yumi/webui/static/js/pages/buttons.js` — шаблон UX для своих команд; `app.js:7-22` —
  карта ленивых страниц, `app.js:558-561` — вызов `render(view, ctx)`.

### Тесты и документы
- `tests/test_webpanel.py` — настоящий HTTP-сервер, но с **stub `Bridge`** (`:31`): сквозного
  пути до `Brain` он не проверяет. Счётчик страниц зашит в `:367-370` (сейчас 15).
- `tests/test_nlu.py`, `tests/test_voice_intent.py`, `tests/test_intents.py` — профильные тесты.
  `tests/test_intents_cache.py`, `tests/smoke_webpanel.sh`, `tests/smoke_voice_nlu.sh` в репозитории
  отсутствуют; smoke для этой фичи создаётся заново.
- `docs/handoff-intents.md`, `docs/handoff-web-panel.md`, `AGENTS.md` — обязательный контекст.

## 3. Предлагаемый слой пользовательских интентов

### 3.1 Хранилище

Каталог `CONFIG_DIR / "user-intents"` (константа `INTENTS_DIR` в `config.py`). В нём
`index.json` (`version`, `revision`, порядок правил) и по папке на интент:
`user-intents/<id>/intent.json`. Папки развязывают правила и дают место для своих файлов:
команда интента запускается в папке правила, поэтому `action.value` может быть относительным
путем (`python3 lights.py on`). Старый `user_intents.json` (`INTENTS_FILE`) при первом чтении
раскладывается по папкам с сохранением `revision`, а копия остаётся в
`user_intents.json.migrated`.

Формат `index.json`:

```json
{"version": 1, "revision": 7, "order": ["lights_on", "news_today"]}
```

Формат `user-intents/lights_on/intent.json` (имя папки = `id`; при расхождении имя папки
побеждает, чтобы скопированный файл не занял чужой слот):

```json
{
  "id": "lights_on",
  "name": "Свет в комнате",
  "enabled": true,
  "phrases": ["включи свет", "свет включи"],
  "keywords": ["свет", "лампа"],
  "action": {"type": "command", "value": "python3 lights.py on"},
  "speak": "Включаю свет",
  "capture": false,
  "voice_answer": true,
  "bubble_answer": true,
  "bubble_limit": 1000,
  "priority": 10,
  "requires_confirmation": true,
  "created_at": "2026-11-25T12:00:00Z",
  "updated_at": "2026-11-25T12:00:00Z"
}
```

Экспорт/импорт по-прежнему работают со всем документом
`{"version": 1, "revision": N, "intents": [...]}` — это переносимый бэкап, а не файл в каталоге.

- `version` — версия формата; `revision` — счётчик в `index.json` для оптимистичной проверки
  `PUT` (при расхождении `409`). Это разные поля, не путать.
- `action.type`: `command`, `url`, `say`. `skill` — только в T-09 и только по белому списку.
- `requires_confirmation` по умолчанию `true` для `command`, `false` для `url`/`say`.
- Для `say` говорится `speak`; `action.value` используется только если `speak` пуст.
- `capture: true` разрешён только для `command`: её stdout подставляется в `{stdout}` внутри
  `speak` (или приписывается к реплике без маркера) и уходит в обычный `say_text()`.
- `voice_answer` / `bubble_answer` — независимые переключатели ответа (по умолчанию оба `true`).
  `voice_text` / `bubble_text` задают свои шаблоны вместо общего `speak` (пусто — взять общий):
  `{stdout}` подставляет вывод, а без маркера отдельный шаблон используется дословно.
  `bubble_limit` — длина текста в бабле: по умолчанию `1000`, допустимо `100..4000`;
  голос получает полный ответ до `MAX_CAPTURED_ANSWER = 4000`. Отдельные шаблоны имеют смысл
  только при `capture: true`.
- `url` — только `http(s)://`. Ограничения: ≤50 фраз/keywords, строка ≤200, `command` ≤1000,
  `id` — `[a-zA-Z0-9_-]{1,64}`.

Совместимость: импорт из `actions.json` — явный (`from_actions`), без авто-замены и без удаления
оригинала.

### 3.2 Чистый модуль `yumi/user_intents.py`

Без GTK и без сетевых вызовов. Ответственности:

- `load/save` с атомарной записью каждого `intent.json` и `index.json` (`tmp` + `replace`,
  без мнимой блокировки); `load()` собирает документ из папок, подхватывает папки, добавленные
  руками, и игнорирует битые файлы; `mtime()` берёт самый свежий файл каталога;
  `root_dir()`/`intent_dir()` — единственные места, где id превращается в путь;
- `validate(payload)` — схема, уникальность id, длины, safety-проверки, нормализация полей
  ответа (`_limit()` клампит `bubble_limit`, отдельные шаблоны требуют `capture`);
- `to_nlu_entries(intents)` — плоские записи для `nlu.recognize()`: `phrases`, `keywords`,
  `priority`, `speak`, `id`, `capture`, `voice_answer`, `bubble_answer`, `bubble_limit`,
  `voice_text`, `bubble_text`; `command`/`url` — для одноимённых типов; маркер
  `user_intent` — для `say`, чтобы в shell не ушла фиктивная команда;
- `match(text, intents)` и `test_phrase(text)` (без выполнения);
- `from_actions(actions)` — конвертация кнопок;
- `import_json(text)` / `export_json(data)` — fail-fast импорт, стабильный экспорт.

`priority` остаётся тай-брейком после score, как в `nlu.py`; пользовательский интент не должен
перебивать точную фразу встроенного навыка просто потому, что число больше.

### 3.3 Подключение в `Brain`

- Загрузить каталог `user-intents`, кэш + `mtime`/`revision`, горячая перезагрузка как
  `extras.actions_check()` (`extras.py:322-331`), без перезапуска.
- Порядок в `heard_text()` — **не переставляем существующие блоки**:

  1. stop/подтверждение/заметка;
  2. music-control;
  3. `voice_intent()` → `actions.json` + ONNX fallback как раньше;
  4. notes / время / погода / шутка / параметры / имя;
  5. **пользовательские интенты** (`use_intents=False`, и `text`, и `alt`);
  6. addressing/fallback → чат.

  Так кастомные фразы не перехватывают встроенные навыки, не ломают кнопки и ONNX.
  Если фраза совпала и с кнопкой, и с пользовательским интентом, побеждает кнопка.
- `requires_confirmation` — через существующий `pending_permission`/`permissions`
  (`brain.py:1883-1908`); target для `say` — текст реплики.
- `command` → `('run', ...)`, `url` → `('url', ...)`, `say` → `say_text()`.
- `capture` → `('run_capture', command, intent_id, speak, options)`: пятый элемент несёт
  `voice`, `bubble`, `bubble_limit`, `voice_text`, `bubble_text` из записи. GTK-поток
  запускает команду в daemon-потоке (`App.run_capture`), ждёт stdout и через `GLib.idle_add`
  вызывает `Brain.user_intent_answer(output, intent_id, speak, failed, options)`. Она рендерит
  голос и баблу раздельно: `voice_text`/`bubble_text` заменяют общий `speak`, бабла обрезается
  по `bubble_limit`, голос — по `MAX_CAPTURED_ANSWER`. `\n` в выводе схлопываются в пробелы.
  При `bubble=False` скрытый бабл с пустым текстом держит id звука, пока TTS не зазвучит;
  `bubble_ops()` его не рисует, и панель не видит текст.
- Флаг `user_intents = false` выключает слой полностью.
- Фразы пользовательских интентов добавить в `addressing.hints_from()` вместе с `self.custom`.

### 3.4 Настройки

В `DEFAULT_SETTINGS`: только `user_intents = true`. `user_intents_confirm` не добавляем —
подтверждение per-intent важнее.

В `catalog.py`: `TITLES`, `HINTS`, `KEY_SECTION` → существующая секция `mind`. Новая секция
не заводится: без `SECTIONS`/`SECTION_PAGE` она не появится. `_web_apply_settings()` отдельной
ветки не требует — флаг читается на каждую фразу.

### 3.5 GTK-сторона

**Отдельного GTK-редактора нет.** В `brain.py` не добавляется пункт меню «Свои интенты»;
`extras.form_open()` остаётся редактором кнопок. Пользователь правит `intent.json`
вручную или пользуется панелью; исполнение фраз работает одинаково в обоих случаях.
Простые команды уходят в `('run_in', command, cwd)`, команды с `capture` несут `cwd`
седьмым элементом `('run_capture', ...)`: оба запускаются в папке правила.

### 3.6 Веб-панель

Новая страница `user-intents` (`catalog.PAGES`, lazy import в `app.js`, `render(view, ctx)`):
список карточек, форма, textarea фраз, select `action.type`, кнопки «Проверить» / «Импорт» /
«Экспорт», тумблеры `enabled`, `requires_confirmation` и `capture` (только для `command`),
поля ответа «Озвучивать отдельно» / «Пузыть отдельно», «Голосовая реплика» / «Реплика в бабле»
и «Лимит бабла» (показываются только при `capture`), скрытое поле `revision`.
Подсказка у `speak` объясняет `{stdout}`. Карточка показывает статус ответа и лимит. Кнопка «Проверить»
вызывает `/run` (нашла фразу — запустила с репликой/голосом/командой); блок «Совпадение?»
вызывает `/test` и ничего не исполняет. UX и DOM-безопасность — по образцу `buttons.js`: только
`createElement`/`textContent`.

`api.js`: `userIntentsGet/Put/Import/Export/Test/Run`.

`bridge.py` + `webpanel.py` + `server.py`:

- `GET /api/user-intents` — `{version, revision, mtime, intents}`;
- `PUT /api/user-intents` — полная замена, обязателен `revision`, конфликт → `409`;
- `POST /api/user-intents/import` — multipart-файл **или** JSON-тело, валидация до записи;
- `GET /api/user-intents/export` — `application/json` + `Content-Disposition: attachment`;
- `POST /api/user-intents/test` — `{text}` → `{matched, intent, score, source}`, без выполнения;
- `POST /api/user-intents/run` — `{text}` → `{matched, ran, intent, score, source}`; через
  `WebBridge.user_intents_run()` → `PanelMixin._web_user_intents_run()` (GTK-поток) вызывает
  `Brain.voice_user_intent()`, то есть кнопка «Проверить» на карточке равна услышанной фразе.

CSRF/origin проверяются общим кодом сервера (`server.py:364-368`). `/api/upload` не использовать.
В `tests/test_webpanel.py` обновить stub `Bridge` и жёсткое ожидание 16 страниц.

### 3.7 Журнал действий

Отдельная задача описана в `docs/plan-intents-action-log.md` и
`docs/handoff-intents-action-log.md`; модуль `yumi/intent_log.py` пишет приватный
`STATE_DIR/user-intents.log` (JSONL, `0600`) и ничего не знает о GTK/HTTP. Уровни
`off|error|result|action|match|trace` кумулятивные, по умолчанию `off`. `Brain` отдаёт
однаковый `run_id` (`uuid4().hex[:8]`) в `heard` → `match` → `decision`/`skip` → `start`
→ `result`, а `App.run_capture()` добавляет `error` при провале команды. Неизменённый канал
`extra_env={'YUMI_INTENT_TEXT': heard}` и форма кортежа `('run_capture', …)` остались прежними:
`run_id`, `source` и `started_at` живут внутри пятого элемента `options`. Панель получает
`GET /api/user-intents/log` и `POST /api/user-intents/log/clear` (CSRF + аудит
`intents-log-clear`), показывает блок на `#/user-intents` и вкладку `#/logs` с `name=intents`;
новые строки приходят SSE-событием `intents_log`. Команда и URL заменяются `action_sha`/
`action_len`, фраза и stdout — отдельные поля только при `intents_log_include_text`.

### 3.8 Безопасность

- Команды остаются действиями самого пользователя, но значения `command` не пишутся в аудит
  и не показываются как обычный текст без явного намерения.
- Импорт не выполняет команды; подтверждение по умолчанию для `command` снижает риск.
- Captured-команда выполняется тем же пользовательским кодом, что и обычная; её stdout
  становится репликой Юми, но stderr и сам текст команды в логи/аудит не идут. Лимит ответа —
  `MAX_CAPTURED_ANSWER`, таймаут потока — 30 с.
- `url` — только `http(s)://`, `file://` не разрешаем.
- Ограничения длин — см. §3.1.
- Аудит импорта/экспорта/изменений — без содержимого команд.
- Экспорт не содержит секретов и токена панели.
- `revision` защищает от потери правки при одновременной работе панели и ручного файла.

## 4. План работ

Подробный список: `docs/tasks-user-intents.md`. Кратко:

1. T-01..T-03 — хранилище, схема, валидация, адаптер, импорт из `actions.json`.
2. T-04 — `user_intents` в настройках и каталоге.
3. T-05 — `Brain`, фиксированный порядок, выполнение, горячая перезагрузка.
4. T-06 — WebBridge + роуты + `revision`/409 + тесты панели.
5. T-07 — страница панели + `api.js` + i18n.
6. T-08 — smoke-тест, документация, финальная проверка.
7. T-09 — опционально: `skill` и дообучение из панели.

GTK-этапа нет.

## 5. Тесты (обязательный минимум)

- `tests/test_user_intents.py` (новый): load/save/validate, полный цикл import/export,
  `revision`, scoring `1.0/0.8/0.6`, `enabled`, `priority` как тай-брейк, горячая перезагрузка;
  дефолты и клампинг `bubble_limit`, отказ отдельных шаблонов без `capture`.
- `tests/test_webpanel.py`: новые роуты, CSRF, схема, `revision`→409, invalid import→400,
  заголовки export, `/test` и `/run`, roundtrip новых полей ответа; обновить stub `Bridge`
  и ожидание 16 страниц.
- `tests/test_voice_intent.py` / `tests/test_nlu.py`: базовые кнопки и ONNX не сломаны; отдельно
  проверяется `run_capture` → `user_intent_answer()` с пятым `options`: бабла + `voice`-запрос,
  подтверждение, голос без баблы (скрытый бабл), бабла без голоса, отдельные шаблоны и лимит.
- `tests/smoke_user_intents.sh` (новый): API → ручная правка JSON → `Brain` видит →
  test phrase → `/run` через HTTP → export → import → delete. Без GTK.

Быстрая проверка из `AGENTS.md` дополнена `test_user_intents.py` и `py_compile user_intents.py`.

### Тик напоминаний на внутренних часах

Интент `reminders_tick` с командой `python3 reminders.py --tick` — не голосовая
фраза, а задача внутренних часов: `Extras.extras_init()` регистрирует хендлер
`reminders_tick` и планирует повтор раз в минуту (`in_s=60`, `every_s=60`,
`persist=False`). Хендлер читает текущий список интентов через
`user_intents_check()`, берёт команду из `action.value` и кладёт в очередь
`('run_in', command, cwd)` — скрипт запускается в папке интента, где лежит его
`reminders.py`, и сам озвучивает/показывает сработавшие напоминания. Скрипт не
дублируется в ядре: состояние остаётся в `~/.local/state/yumi/reminders.json`,
настройки — в `~/.config/yumi/reminders.json`. Systemd-юниты
`yumi-reminders.service`/`.timer` удалены; если Юми не запущена, тика нет.
Правка команды или `enabled` в панели (`#/user-intents`) применяется без рестарта;
статус задачи виден в `runtime.clock` и в GTK-меню.

## 6. Риски и открытые вопросы

1. **Путь хранилища.** Зафиксирован: `CONFIG_DIR / user-intents`, env `XDG_CONFIG_HOME`.
   `YUMI_CONFIG_DIR` не добавляем без реальной потребности. Старый `user_intents.json`
   мигрирует один раз, рядом с ним остаётся копия `.migrated`.
2. **Порядок.** Зафиксирован в §3.3: не переставляем встроенные навыки, ONNX остаётся внутри
   `voice_intent()`. Пользовательские интенты идут после встроенных и после кнопок.
3. **`nlu.recognize()` фильтр.** Расширяем только его и `_intent_name()`; `intents.py` не трогаем.
4. **`priority`.** Остаётся тай-брейком после score, как в текущем коде.
5. **`skill`.** Отложен до T-09; белый список методов `Brain`, никакого произвольного Python.
6. **ONNX fallback.** Кастомные фразы работают через `nlu`, не через модель; прямо написать в UI/доке.
7. **Конкурентность.** Решена через `revision` + `409` вместо обещаемой блокировки файла.
8. **Конфиг-редактор.** `user-intents/*/intent.json` **не** добавляется в `catalog.CONFIG_FILES`:
   только валидирующий API и ручная правка с полной схемой.
9. **Обучение.** `tools/intents_train.py` читает `--corpus` и `--actions`; для T-09 нужен
   адаптер `name` → `label`, иначе новые метки не появятся.

## 7. Definition of done

- [x] Пользователь может создать/удалить/изменить свой интент **из панели** и **вручную в JSON**.
- [x] GTK-редактор не добавлен; исполнение фраз в GTK работает как раньше + новый слой.
- [x] Есть импорт/экспорт JSON через панель с валидацией и защитой от конфликта правок.
- [x] Тест фразы показывает совпадение без выполнения действия.
- [x] Кнопка «Проверить» в панели запускает найденный интент со всеми обычными эффектами.
- [x] Ответ `capture`-интента появляется в бабле и озвучивается обычным путём `say_text()`.
- [x] Голос и бабла переключаются независимо, имеют свои шаблоны и лимит баблы по умолчанию.
- [x] Кастомные интенты работают без перезапуска и без переобучения ONNX.
- [x] Базовые навыки, кнопки и ONNX не сломаны; порядок зафиксирован тестами.
- [x] Новые настройки и страница отражены в `catalog.py`, `api.js` и счётчике страниц теста.
- [x] `tests/test_webpanel.py`, `test_user_intents.py`, `py_compile`, JS syntax check — зелёные.
- [x] `tests/smoke_user_intents.sh`: API → ручная правка JSON → горячая перезагрузка Brain →
      test phrase → export/import → delete, без GTK-окна.
- [x] Обновлены `README.ru.md`, `README.md`, `docs/handoff-web-panel.md`.

Полный `pytest tests/ -q`: 60 passed, 1 skipped, 4 failure в `tests/test_speaker_gate.py`.
Эти же 4 провала воспроизводятся на ветке до изменений пользовательских интентов — это
pre-existing состояние тестов спикера, а не регрессия фичи. Профильные тесты
(`test_user_intents.py`, `test_nlu.py`, `test_voice_intent.py`, `test_webpanel.py`,
`test_addressing.py`), `py_compile`, JS syntax check и smoke зелёные.
