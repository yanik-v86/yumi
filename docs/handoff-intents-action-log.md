# Handoff: журнал действий пользовательских интентов

Статус: **проект согласован, этой работой код не менялся**.  
Дата: 2026-11-25.  
Аудитория: агент, который будет реализовывать журнал, и ревьюер.

План работ: [`plan-intents-action-log.md`](plan-intents-action-log.md) (L-01..L-06).
Смежная, **отдельная** задача: [`plan-internal-clock.md`](plan-internal-clock.md)
и [`handoff-internal-clock.md`](handoff-internal-clock.md) — внутренние часы
Юми. Журнал не планирует и не тикает; часы не пишут этот журнал.

## 1. Цели и границы

Дать видимость полного пути пользовательского интента:

> услышали → совпало → подтвердили → запустили → ответили / ошибка

Журнал нужен для диагностики «почему Юми не ответила» и «что именно
выполнилось», а не для истории команд как источника истины. Источник истины —
`user-intents/<id>/intent.json`, журнал — только наблюдаемый побочный канал.

В границах задачи:

- отдельный JSONL-файл в `STATE_DIR`;
- уровни детализации из веб-панели без перезапуска;
- чтение и очистка из `#/user-intents`;
- `run_id`, связывающий события одного запуска.

Вне границ:

- внутренние часы, планировщик, напоминания и отложенные задачи;
- новый `catalog.PAGES`-раздельный или GTK-просмотрщик;
- логирование команд и URL — они не попадают в файл никогда.

## 2. Настройки

| Ключ | Тип/значения | По умолчанию | Секция `catalog` | Назначение |
|---|---|---|---|---|
| `intents_log_level` | `off`, `error`, `result`, `action`, `match`, `trace` | `off` | `mind` | Порог; уровни кумулятивные |
| `intents_log_include_text` | bool | `false` | `mind` | Превью фразы и stdout (не команды/URL!) |
| `intents_log_max_chars` | int, 100–8000 | `200` | `mind` | Обрезка одного превью |
| `intents_log_max_lines` | int, 100–20000 | `2000` | `mind` | Сколько строк хранить и отдавать |

`DEFAULT_SETTINGS` в `yumi/config.py`; `CHOICES`, `TYPES`, `RANGES`,
`TITLES`, `HINTS`, `KEY_SECTION` — в `yumi/webpanel/catalog.py`. Секция `mind`
уже существует. `_web_apply_settings()` читает настройки на каждую запись;
при появлении кэша — сбросить его здесь же.

GTK-эквивалент: `Brain.cycles()` → `intents_log_level`, `open_menu('set_chat')`
→ строка «Журнал действий» (`config.UI`, ru/en). Просмотрщика в GTK нет — это
явное исключение, как и для редактора `user-intents/<id>/intent.json`.

## 3. Уровни и формат строки

Уровни кумулятивные: включённый уровень включает все предыдущие.

| Уровень | Что пишем |
|---|---|
| `off` | ничего; фатальные ошибки файла — в `app.log`, не сюда |
| `error` | `severity=error`: провал команды, таймаут, битая запись |
| `result` | `error` + финальный `status`, длина ответа, источник |
| `action` | `result` + старт/окончание действия и подтверждение |
| `match` | `action` + `intent_id`, `score`, `source`, winner |
| `trace` | `match` + кандидаты, каждый этап, пропуски слоёв |

`severity`: `error | warning | info | debug`. `stage` — один из `heard`,
`match`, `decision`, `skip`, `start`, `result`, `error`, `panel`.

Файл: `config.STATE_DIR / 'user-intents.log'`, JSONL, UTF-8, режим 0600.

```json
{
  "v": 1,
  "ts": 1764000000.123,
  "level": "action",
  "severity": "info",
  "stage": "start",
  "intent_id": "lights_on",
  "source": "voice|panel",
  "run_id": "b1f0…",
  "status": "ok|fail|skipped|cancelled",
  "action_type": "command|url|say",
  "action_sha": "sha256:…",
  "action_len": 123,
  "duration_ms": 41,
  "heard_text": null,
  "stdout_preview": null,
  "stdout_len": 0,
  "error": null,
  "details": {}
}
```

- `action.value` (текст команды или URL) не сохраняется **ни при каких**
  настройках; вместо него `action_sha` и `action_len`.
- `heard_text` и `stdout_preview` — `null` по умолчанию; заполняются только
  при `intents_log_include_text=true` и обрезаются до
  `intents_log_max_chars`. Это два разных поля, чтобы короткое превью фразы
  не смешивалось с выводом команды.
- `run_id` — `uuid.uuid4().hex[:8]`, один на запуск. Передаётся в `run`-dict
  и внутрь уже существующего `options` кортежа `('run_capture', …)`; форму
  кортежа не меняем.
- `source` — `voice` для услышанной фразы, `panel` для кнопки «Проверить».
  Если журнал вызовет другой consumer, он укажет своё имя.

## 4. Модуль `yumi/intent_log.py`

Чистый модуль: без GTK, HTTP, сети и импорта `Brain`.

```python
emit(settings, stage, **fields) -> None
read(limit=None, intent=None, stage=None) -> list[dict]
clear() -> None
```

- `emit()` сначала проверяет уровень, затем санитизирует поля, добавляет
  `v`, `ts`, `run_id`, `source` и пишет одну строку.
- Ротация по `intents_log_max_lines`: временный файл + `os.replace`, не чаще
  раза в N записей, чтобы не блокировать GTK-поток.
- `read()` возвращает свежие строки сверху, фильтрует по `intent` (id) и
  `stage`. `clear()` обнуляет файл и пишет аудит только на уровне сервера.
- `_mind_log()` в `brain.py` оставляем: это отдельный канал, а не замена.

## 5. Точки вызова

| Место | `stage` | Уровень | Что важно |
|---|---|---|---|
| `Brain.voice_user_intent()` | `heard`, `match` | `trace`, `match` | id, score, winner; без текста |
| подтверждение | `decision`, `skip` | `action`, `trace` | кто разрешил/отклонил |
| `Brain._voice_run()` | `start` | `action` | action type, флаги ответа, `run_id` |
| `App.run_capture()` | `error` | `error` | timeout/OSError, длительность |
| `Brain.user_intent_answer()` | `result` | `result` | status, длина ответа, лимит баблы |
| `PanelMixin._web_user_intents_run()` | `panel` | `action` | тот же `run_id`, что у действия |

Завершение `run_capture` логируется **один раз** — в
`user_intent_answer()`, чтобы не дублировать `result`.

Незакоммиченный канал `extra_env={'YUMI_INTENT_TEXT': heard}` сохраняем как
есть: при `intents_log_include_text=true` он даёт `heard_text`, а команда
по-прежнему остаётся скрытой.

## 6. HTTP, Bridge и панель

| Метод | Путь | Действие |
|---|---|---|
| GET | `/api/user-intents/log` | последние N строк, фильтры `limit`, `intent`, `stage` |
| POST | `/api/user-intents/log/clear` | очистить файл, CSRF, аудит без деталей |

`WebBridge.intents_log_get()` / `intents_log_clear()` → `_on()` →
`App._web_call` → `GLib.idle_add` → `PanelMixin` с теми же именами.
В `yumi/webpanel/*` GTK не импортируется.

`api.js`: `intentsLogGet()`, `intentsLogClear()`, `EVENTS.intents_log`.
`/api/logs` получает имя `intents` → тот же файл.

`pages/user-intents.js` — новый блок внутри существующей страницы:

- уровень — через `ctx.applySettings` (тот же ключ, что в Settings → Mind);
- таблица последних N строк;
- фильтры по `intent` и `stage`;
- кнопки «Обновить» и «Очистить»;
- автообновление по SSE `intents_log`, без polling-а.

DOM только через `createElement`/`textContent`, строки ru/en. Нового
`catalog.PAGES`-записи и lazy import'а нет; в `tests/test_webpanel.py`
остаётся 16 страниц.

`_web_snapshot()` → `runtime.user_intents.log`: `level`, `path`,
`last_event_at`, `errors`, `lines`. Событие публикуется только при появлении
новой строки, не в каждый `web_tick()`.

## 7. Безопасность

- Команда и URL не пишутся в журнал никогда: только `action_sha`, `action_len`.
- `heard_text` и `stdout_preview` — явный opt-in с предупреждением в UI и
  записью включения в аудит.
- Секреты из `SECRET_KEYS` и токен панели не	loggются и не отдаются в API.
- Чтение лога требует сессии; очистка — CSRF; аудит очистки не содержит
  содержимого строк.
- Файл 0600 в `STATE_DIR`, а не в публичной статике.

## 8. Тесты

- `tests/test_intent_log.py`: уровни, фильтры, маскировка, превью при opt-in,
  ротация, `run_id`, режим файла.
- `tests/test_webpanel.py`: схема новых ключей, 16 страниц, логин/CSRF,
  новые роуты, `runtime.user_intents.log`, SSE.
- `tests/test_voice_intent.py`: голосовой путь даёт цепочку событий и не
  ломает `extra_env`/`run_capture`.
- `tests/smoke_intents_log.sh`: `/run` → чтение лога → проверка отсутствия
  команды/фразы → opt-in → проверка превью → `clear`.

Полный список команд — в плане §5. Известная база: 4 провала
`tests/test_speaker_gate.py` существуют до этой работы и не являются регрессией.

## 9. Риски

- Дублирование `result` между `run_capture()` и `user_intent_answer()` —
  фиксируем одну точку.
- Утечка текста через `details`: санитизировать всё, что попадает в журнал.
- Блокировка GTK при ротации: делать её не на каждую запись.
- Путаница с внутренними часами: журнал не должен получать события таймера и
  не должен планировать задачи; это разные задачи и разные документы.
- Обратная совместимость `settings.json`: все ключи имеют значения по умолчанию из
  `DEFAULT_SETTINGS`, миграция не требуется.

---

Готовность считается по чек-листу из конца
[`plan-intents-action-log.md`](plan-intents-action-log.md): каждая задача
L-01…L-06 имеет тест и отмечена в плане.
