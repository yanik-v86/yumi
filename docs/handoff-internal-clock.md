# Handoff: внутренние часы Юми

Статус: **реализовано**; контракт ниже описывает работающий код.

Дата: 2026-11-25.
Аудитория: агент, который будет реализовывать часы, и ревьюер.

План работ: [`plan-internal-clock.md`](plan-internal-clock.md) (C-01..C-08).
Смежная, **отдельная** задача: [`plan-intents-action-log.md`](plan-intents-action-log.md)
и [`handoff-intents-action-log.md`](handoff-intents-action-log.md) — журнал
действий интентов. Часы не являются частью этой задачи.

## 1. Роль и границы

Внутренние часы — общий сервис времени для всей Юми. Они дают другим
подсистемам возможность:

- запланировать задачу через `schedule()`;
- получить момент срабатывания через `register(kind, handler)`;
- отложить, пропустить или отменить задачу;
- пережить рестарт для задач с `persist=True`.

Часы **не знают**:

- что такое пользовательский интент, фраза, бабла, голос или подтверждение;
- что такое напоминание как бизнес-объект;
- ничего о HTTP, CSRF, сессиях и web-панели;
- ничего о GTK и виджетах.

Логику срабатывания пишет consumer в своём handler. Часы лишь вызывают его
вовремя и сообщают об ошибке через `on_error`.

## 2. Модули

| Модуль | Ответственность |
|---|---|
| `yumi/clock.py` | Ядро: задачи, реестр хендлеров, тик, отложки/пропуски, `snapshot()` |
| `yumi/clock_store.py` | Только персистентность: `clock-jobs.json`, валидация, `.tmp` + `replace` |

Оба модуля чистые: без GTK, без HTTP, без импорта `Brain`, без сети и без
обращения к `settings` напрямую. Настройки и зависимости передаются аргументами.

## 3. Модель job-а

```python
{
    "id": "water_42",              # [a-zA-Z0-9_-]{1,64}, уникальный
    "kind": "reminder",            # ключ реестра handler'ов
    "owner": "reminders",          # кто запланировал; часы не интерпретируют
    "due_at": 1764010000.0,        # epoch, абсолютное время срабатывания
    "every_s": 0,                  # 0 = одноразовая, иначе период ≥30
    "defer_until": 0.0,            # приоритетнее due_at
    "payload": {},                 # произвольные данные consumer'а
    "enabled": True,
    "persist": True,               # попадает в clock-jobs.json
    "last_fired_at": 0.0,
    "created_at": "2026-11-25T12:00:00Z",
}
```

`kind` и `owner` — разные вещи: `kind` выбирает handler, `owner` — просто
метка для диагностики. Часы не проверяют содержимое `payload`.

## 4. Публичный API

```python
class Clock:
    def __init__(self, *, store=None, missed_window_s=900): ...

    def register(self, kind: str, handler) -> None: ...
    def on_error(self, callback) -> None: ...

    def schedule(self, kind, *, in_s=None, due_at=None, every_s=0,
                 owner='', payload=None, persist=False, id=None) -> str: ...
    def cancel(self, job_id: str) -> bool: ...
    def defer(self, job_id: str, delay_s: int) -> bool: ...
    def skip(self, job_id: str) -> bool: ...
    def pause(self, job_id: str) -> bool: ...
    def resume(self, job_id: str) -> bool: ...

    def due(self, now_wall: float) -> list[dict]: ...
    def tick(self, now_wall: float, now_monotonic: float) -> list[dict]: ...
    def restore(self, jobs: list[dict]) -> None: ...
    def snapshot(self) -> dict: ...
```

- `in_s` и `due_at` взаимно исключаются; `in_s` нормализуется в абсолютный
  `due_at` в момент вызова. Для `every_s > 0` повтор считается от предыдущего
  `due_at`, а не от момента фактического вызова handler'а.
- `register()` с уже существующим `kind` заменяет handler — это позволяет
  подменять реализацию в тестах и при миграции потребителей.
- `tick()` возвращает список fired/missed/error событий для диагностики;
  handler'ы вызываются внутри него, но их ошибки не пробрасываются наружу.
  Событие: `{id, kind, owner, status, due_at, at, monotonic}` (`error`
  добавляет поле `error`); `payload` в события не попадает.
- `on_error(callback)` получает `(job, exception)`, где `job` — копия задачи.
- `skip()` для повтора сдвигает ближайшее срабатывание на `every_s`; у
  одноразовой задачи повтора нет, поэтому она удаляется, как при `cancel()`.
- `Clock(store=None, missed_window_s=900, now_wall=None)`: `now_wall` —
  необязаемый источник epoch-секунд для `in_s` и `created_at` (по умолчанию
  `time.time`), что позволяет тестировать планирование с подставным временем.
- `schedule()` при занятом `id` бросает `JobExists`; неверные параметры —
  `InvalidJob`; повтор короче 30 с не допускается.
- `snapshot()` — безопасная копия без изменения состояния: `{enabled,
  now_wall, jobs_active, jobs_persisted, next_due_at, last_fired_at,
  last_error}`. `enabled` означает, что сервис времени присутствует в
  приложении; выключателя настроек у часов нет.

## 5. Время и тик

- `App.frame()` вызывает `Brain.update(now_monotonic)`.
- `Brain.update()` после `timer_update(now)` вызывает
  `self.clock.tick(time.time(), now_monotonic)`.
- `now_wall` (epoch) используется для `due_at`, `defer_until` и `missed_window_s`;
  `now_monotonic` — только для длительностей и диагностики.
- Новых `GLib.timeout_add` нет: часы тикают в уже существующем кадре.

Порядок обработки одного job-а в `tick()`:

1. взять задачи с `due_at <= now_wall` (с учётом `defer_until` и `enabled`);
2. пометить job как `fired` **до** вызова handler'а;
3. заранее вычислить следующий `due_at` для повторов;
4. вызвать handler; при исключении — вызвать `on_error` и продолжить;
5. если `now_wall - due_at > missed_window_s`, задачу не выполнять, а вернуть
  событие `missed`.

Идемпотентность: два тика с одним и тем же `now_wall` не вызывают handler
дважды. Одноразовая задача после срабатывания удаляется из активных.

## 6. Персистентность

Файл `STATE_DIR / 'clock-jobs.json'`:

```json
{
  "version": 1,
  "revision": 3,
  "jobs": [
    {
      "id": "water_42",
      "kind": "reminder",
      "owner": "reminders",
      "due_at": 1764010000.0,
      "every_s": 0,
      "defer_until": 0.0,
      "payload": {"note": "water"},
      "enabled": true,
      "persist": true,
      "last_fired_at": 0.0,
      "created_at": "2026-11-25T12:00:00Z"
    }
  ]
}
```

- В файл попадают только задачи с `persist=True`.
- Запись через `.tmp` в той же директории + `os.replace`; `revision`
  увеличивается при каждой успешной записи.
- `load()` при битом JSON возвращает пустой список и **не** перезаписывает файл.
- `restore()` восстанавливает активные задачи; просроченные попадают под
  missed-окно из §5.

## 7. Точки расширения для потребителей

Минимальный пример подключения новой задачи (без правки ядра):

```python
def on_water(job):
    ...  # бизнес-логика consumer'а, часы её не знают

clock.register('water', on_water)
clock.schedule('water', in_s=120, owner='health',
               payload={'cup': 1}, persist=True)
```

- Пользовательский интент может запланировать отложенное действие через
  `clock.schedule('intent_action', in_s=..., owner='intents', payload={...})`.
  Исполнение фразы при этом остаётся в `Brain` — часы лишь вызывают хендлер.
- Напоминания подключены как consumer: `yumi/extras.py` регистрирует `reminders_tick`
  и раз в минуту запускает команду одноимённого пользовательского интента в его
  папке (`run_in`). Часы не хранят `reminders.json` и не знают о команде; systemd
  таймер/сервис для этого удалён. Отключение интента останавливает проверку.
- Встроенные `Brain.timer`, `breaks` и hourly chimes подключаются адаптерами:
  хендлер просто вызывает уже существующую логику. В первой версии эти старые
  проверки всё ещё работают в кадре, и никакие job-ы для них не
  планируются — адаптеры готовы к миграции, но не удваивают срабатывания.
  Полный перенос — отдельный шаг, не блокирующий первую версию.
- `on_error` нужен для диагностики; формат ошибки определяет consumer, часы
  только передают `job_id`, `kind` и исключение.

## 8. Интеграция с приложением

- `Brain.__init__` (или `extras_init`) создаёт `self.clock`.
- `Brain.update(now_monotonic)` вызывает `self.clock.tick(time.time(), now_monotonic)`.
- `App.frame()` не знает о часах: он по-прежнему только передаёт время в `Brain`.
- `yumi/ui/bridge.py` и `yumi/ui/webpanel.py` нужны только для read-only статуса;
  мутирующих HTTP-вызовов у часов на этом этапе нет.
- В `yumi/webpanel/*` не импортируется GTK; всё через `WebBridge` → `GLib.idle_add`.

## 9. Статус в панели и GTK

- `_web_snapshot()` → `runtime.clock`: `now_wall`, `jobs_active`,
  `jobs_persisted`, `next_due_at`, `last_fired_at`, `last_error`.
- Read-only карточка «Внутренние часы» на существующем `#/dashboard`: без
  создания новых `catalog.PAGES`, lazy import'ов и новых страниц.
- GTK-эквивалент: строка в меню/цикле через `config.UI` (ru/en), например
  «Часы: N задач, next HH:MM». Никакого GTK-редактора: сервис внутренний.
- DOM только `createElement`/`textContent`, строки ru/en.

## 10. Безопасность и совместимость

- Часы не выполняют произвольные команды: handler регистрирует сам consumer.
- `payload` не логируется и не отдаётся в панель без явного решения consumer'а.
- Новых секретов и токенов нет; CSRF не затрагивается, потому что нет
  мутирующих HTTP-роутов.
- `settings.json` не меняется: новых ключей нет. Если позже появится
  `missed_window_s` как настройка, она получает default в `DEFAULT_SETTINGS`
  и зеркалится в GTK/панель по общему правилу `AGENTS.md`.
- Незакоммиченные правки с `YUMI_INTENT_TEXT` в `brain.py`/`app.py` сохраняем.

## 11. Тесты

- `tests/test_clock.py`: schedule/cancel/defer/skip/pause/resume, repeat,
  идемпотентность, missed-окно, изоляция ошибок, подставное время.
- `tests/test_clock_store.py`: roundtrip, `persist`-флаг, битый файл, revision.
- Интеграция: `Brain.update()` тикает часы без GTK.
- `tests/smoke_clock.sh`: `in_s=2` → два тика → один вызов → `defer`/`cancel`.
- `tests/test_webpanel.py`: `runtime.clock` в снимке, 16 страниц, read-only
  карточку; проверки CSRF и роутов не меняем.
- `py_compile` и `node --input-type=module --check` по списку из плана §5.

Известная база: 4 провала `tests/test_speaker_gate.py` существуют до этой
работы и не являются регрессией.

## 12. Риски

- Две системы времени (`Brain.timer` и часы) могут рассинхронизироваться:
  миграцию потребителей делать по одному, через адаптеры.
- Просроченные повторяющиеся задачи могут «выстрелить в прошлое»: проверять
  missed-окно до вызова handler'а.
- Исключение в handler'е может остановить кадр: ловить и отдавать в `on_error`.
- Персистентность может задержать GTK-поток: писать один небольшой файл,
  не чаще чем при реальном изменении job-ов.
- Путаница ролей: часы не должны разрастаться до «планировщика напоминаний»
  или «журнала интентов» — это отдельные задачи с своими документами.

---

Готовность считается по чек-листу из конца
[`plan-internal-clock.md`](plan-internal-clock.md): каждая задача C-01…C-08
имеет тест и отмечена в плане.
