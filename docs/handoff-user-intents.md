# Handoff: пользовательские интенты (свои команды и фразы)

Статус: **проект/передаточный документ, реализация не начата**.  
Дата: 2026-11-21.  
Аудитория: агент, который будет реализовывать фичу, и ревьюер.

## 1. Что нужно сделать

Сейчас Юми понимает только фиксированный набор голосовых интентов из ONNX-модели
(`yumi/intents.py`, метки из `data/intents_labels.json`). Пользователь не может просто
добавить свою фразу/команду: для новой метки нужна дообученная модель. При этом в
`~/.config/yumi/actions.json` уже лежат «свои кнопки» с полями `phrases`, `keywords`,
`command`, `url`, и `yumi/nlu.py` умеет по ним искать совпадения — но этот слой зашит
вокруг кнопок, не имеет отдельного API и не покрывает сценарий «загрузил набор интентов
из файла».

Цель фичи: **дать пользователю возможность самому создавать, редактировать,
импортировать/экспортировать и тестировать собственные интенты/команды** поверх базовых,
из GTK-приложения и из веб-панели, без переобучения ONNX-модели.

Важное различие терминов, чтобы не сломать обратную совместимость:

| Термин | Что есть сейчас | Что добавляем |
|---|---|---|
| `intents` в настройках | ONNX-классификатор, enable/disable, порог, модель | **не трогаем**, не переименовываем |
| «свои интенты» / `user_intents` | фактически `actions.json` + `nlu.recognize()` | выделяем в отдельный слой со своим хранилищем и API |
| «кнопки» | `actions.json`, кольцо быстрых кнопок в оверлее | оставляем совместимыми, не ломаем |

## 2. Текущая архитектура (где что искать)

### Распознавание
- `yumi/intents.py` — `IntentEngine`: ONNX-модель, `predict(text, top_k=1)` →
  `Intent(label, score)`, `available()`, `labels()`. метки только из `labels.json`.
- `yumi/nlu.py` — `recognize(text, entries, ...)`: сопоставляет текст с записями
  (`phrases` точные, `keywords` partial) и возвращает `IntentResult(intent, payload, score, matched_text)`.
  scoring: точная фраза `1.0`, совпадение по словам `0.8`, partial keyword `0.6`.
  **Сейчас пропускает записи без `command` или `url`** — это нужно будет пересмотреть
  для новых типов действий.
- `yumi/brain.py` — `heard_text(text)`: сначала встроенные навыки (music, notes, time,
  weather, joke, params), потом `voice_intent(text)` → `nlu.recognize()` по
  `actions.json`, затем `intents.predict()` как fallback. Порядок важный: новые
  пользовательские интенты должны **дополнять** базовые, а не перехватывать их.
- `yumi/extras.py` — `actions_check()` следит за mtime `actions.json` и горячо
  перезагружает кнопки; `form_open()/form_save()` — GTK-редактор одной кнопки.

### Хранение и конфиг
- `yumi/config.py`:
  - `DEFAULT_SETTINGS` — все настройки, автоматически попадают в схему панели;
  - `ACTIONS_FILE = CONFIG_DIR / "actions.json"`, `load_actions()`, `save_actions()`;
  - строки `UI` ru/en.
- `USER_CONFIG_DIR` по умолчанию `~/.config/yumi` (или `YUMI_CONFIG_DIR`), Smoke-тесты
  используют временные каталоги через env.

### Веб-панель
- `yumi/ui/bridge.py` — `WebBridge`: единственный контракт HTTP ↔ GTK. Методы вызываются
  через `App._web_call` → `GLib.idle_add`.
- `yumi/ui/webpanel.py` — `_web_snapshot()`, `_web_apply_settings()`, `_clean_actions()`,
  `_web_actions_get()`, `_web_actions_put()`, `_web_config_save()`.
- `yumi/webpanel/server.py` — HTTP-роуты, CSRF, `/api/upload`, SSE, статика.
- `yumi/webpanel/catalog.py` — `PAGES`, `SECTIONS`, `KEY_SECTION`, `TYPES`, `CHOICES`,
  `RANGES`, `SECRET_KEYS`, `CONFIG_FILES` (редактор конфигов), `schema()`.
- `yumi/webui/static/js/pages/buttons.js` — готовый UX редактирования своих команд
  (список, форма, проверка, сохранение). Хороший шаблон для страницы интентов.
- `yumi/webui/static/js/api.js` — `api.request()`, `api.actionsGet/Put()`, `api.upload(file)`.
- `yumi/webui/static/js/app.js` — hash-роутер, ленивый импорт страниц, i18n.

### Тесты и документы
- `tests/test_webpanel.py` — поднимает реальный HTTP-сервер, проверяет схему, логин,
  cookie/CSRF, PATCH настроек, `/api/actions`, `/api/upload`, обход путей (path traversal).
- `tests/test_voice_intent.py`, `tests/test_nlu.py`, `tests/test_intents_cache.py` —
  профильные проверки.
- `tests/smoke_webpanel.sh`, `tests/smoke_voice_nlu.sh` — integration smoke-тесты.
- `docs/handoff-intents.md` — как устроен текущий ONNX-классификатор.
- `docs/handoff-web-panel.md` — контракт панели; **обязателен к прочтению** перед изменениями API.
- `AGENTS.md` — главное правило: любая возможность должна быть и в GTK, и в панели.

## 3. Предлагаемый слой пользовательских интентов

### 3.1 Хранилище

Новый файл: `USER_CONFIG_DIR / "user_intents.json"` (имя можно зафиксировать как
`INTENTS_FILE` в `yumi/config.py`). Придуман специально, чтобы:
- не смешиваться с ONNX-настройками `intents`;
- не ломать `actions.json` (кнопки остаются кнопками);
- дать отдельный API импорта/экспорта;
- хранить ошибки валидации отдельно, не ломая кнопки.

Формат (пример с версией):

```json
{
  "version": 1,
  "intents": [
    {
      "id": "lights_on",
      "name": "Свет в комнате",
      "enabled": true,
      "phrases": ["включи свет", "свет включи"],
      "keywords": ["свет", "лампа"],
      "action": {
        "type": "command",
        "value": "python3 /home/user/scripts/lights.py on"
      },
      "speak": "Включаю свет",
      "priority": 10,
      "requires_confirmation": false,
      "created_at": "2026-11-21T12:00:00Z",
      "updated_at": "2026-11-21T12:00:00Z"
    }
  ]
}
```

Поддерживаемые `action.type` (минимум):
- `command` — выполнить shell-команду (как сейчас `command` в `actions.json`);
- `url` — открыть URL (как сейчас `url`);
- `say` — просто ответить репликой (`speak` или `value`);
- `skill` — вызвать зарегистрированный внутренний/id навык (нужно явно описать whitelist).

Решение открытого вопроса: **рекомендуется начать с `command|url|say`**, `skill` добавить
вторым этапом, чтобы не допускать произвольный вызов Python.

Совместимость: при первом запуске можно предложить миграцию/импорт существующих
`actions.json` → `user_intents.json` (копирование, не удаление), чтобы пользователь
не терял свои кнопки. Авто-миграцию без спроса не делать.

### 3.2 Чистый модуль `yumi/user_intents.py`

Без GTK, без сетевых вызовов. Ответственности:
- `load(path) -> UserIntentsFile` / `save(path, data)` с атомарной записью и блокировкой (по образцу `config.save_actions()`);
- `validate(payload)` — схема, уникальность `id`, типы, nonempty phrases/keywords, длина строки,
  safety-проверки command/url;
- `recognize(text, intents, ...)` — переиспользовать `nlu.recognize()` после адаптации записей
  (или аккуратно расширить `nlu.recognize()` так, чтобы он не требовал `command`/`url`
  для `say`/`skill`);
- `to_nlu_entries(intents)` / `from_actions(actions)` — адаптеры;
- `import_json(text)` / `export_json(intents)` — валидация импорта целиком (fail-fast, без частичного применения).

### 3.3 Подключение в `Brain`

- `Brain.__init__`: загрузить `user_intents.json`, хранить кэш и mtime (как `extras.actions_check()`).
- `Brain.heard_text()`: после встроенных навыков, **до или сразу после**
  `voice_intent()` / fallback ONNX — вызвать `user_intents.recognize()`. Рекомендуемый
  приоритет: `built-in` → `user_intents` → `actions.json` → ONNX. Точный порядок зафиксировать
  в задаче T-05 и тестах.
- `requires_confirmation` — переиспользовать существующий механизм подтверждения из
  `Brain.voice_intent()` (см. `confirm` в `actions.json`).
- `say` — вызывать существующий TTS-путь; `command` — существующий `os.system`/subprocess-путь;
  `url` — существующий `webbrowser.open`-путь. Не изобретать новые.
- Горячая перезагрузка `user_intents.json` по mtime, без перезапуска (важно для правки файла руками).

### 3.4 Настройки

Добавить в `DEFAULT_SETTINGS` (`yumi/config.py`):
- `user_intents = true` — включить слой пользовательских интентов;
- `user_intents_confirm = false` или использовать per-intent `requires_confirmation`;
- при необходимости `user_intents_file` — но лучше не давать пользователю менять путь через UI
  (безопасность), оставить только env для тестов.

Проверить `yumi/webpanel/catalog.py`: `TYPES`, `HINTS`, `KEY_SECTION`, `TITLES` — чтобы
ключи попали в схему с понятными заголовками ru/en. `tests/test_webpanel.py` автоматически
проверит, что каждый ключ `DEFAULT_SETTINGS` есть в схеме.

### 3.5 GTK-сторона

- `yumi/ui/app.py` (`PanelMixin` или отдельный mixin) — методы `user_intents_get/put/import/export/test`,
  вызываемые через `WebBridge`.
- `yumi/brain.py` — меню «Свои интенты» (аналог пункта «Свои кнопки»/`form_open` в `extras.py`):
  список, добавление, редактирование, удаление, тест фразы. Можно переиспользовать
  `extras.form_open()` как отправную точку, но лучше выделить отдельный редактор, чтобы
  не раздувать `extras.py`.
- Новые строки — только через `config.UI` (`{'ru': ..., 'en': ...}`).

### 3.6 Веб-панель

Новая страница `user-intents`:
- `yumi/webpanel/catalog.py`: `PAGES["user-intents"]` + `SECTIONS`/`KEY_SECTION` при нужде;
- `yumi/webui/static/js/pages/user-intents.js` с `render(view, ctx)`;
- lazy import в `yumi/webui/static/js/app.js`;
- UX копирует `buttons.js`: список карточек, форма, текстовые поля для фраз/keywords,
  выпадающий список `action.type`, кнопки «Проверить фразу» / «Импорт» / «Экспорт», статус включения.

`yumi/webui/static/js/api.js`:
- `api.userIntentsGet() / Put() / Import() / Export() / Test()`.

`yumi/ui/bridge.py` + `yumi/webpanel/server.py`:
- `GET /api/user-intents` — список + версия файла;
- `PUT /api/user-intents` — полная замена (как `/api/actions`), валидация на бэкенде;
- `POST /api/user-intents/import` — принимать `multipart/form-data` (файл) **или** JSON-тело, валидировать перед записью;
- `GET /api/user-intents/export` — вернуть `application/json` c `Content-Disposition: attachment`;
- `POST /api/user-intents/test` — `{text: "..."}` → `{matched: bool, intent?: {...}, score, source}`.

**Не использовать** общий путь `/api/upload` → импорт: он сохраняет произвольный файл в
`CACHE_DIR/uploads` и не проверяет схему. Импорт должен быть отдельным валидирующим роутом.

### 3.7 Безопасность

- Команды выполняются только пользователем, но **всё равно** значения `command` показывать
  в UI и логах как потенциально опасные; не выполнять автоматически при импорте.
- `url` — только `http://`/`https://` (или явно разрешить `file://`? рекомендуется нет).
- Ограничить длины: `phrases`/`keywords` ≤ 50 items, строка ≤ 200 chars, `command` ≤ 1000, `id` — `[a-zA-Z0-9_-]{1,64}`.
- CSRF: все POST/PUT идут через существующий механизм (cookie + `X-CSRF-Token`).
- `GET /api/user-intents/export` не должен отдавать токен или секреты; файл User Intents не содержит API-ключей.
- Аудит: логировать импорт/экспорт/изменение (без содержимого команд) в существующий audit log панели.

## 4. План работ (высокий уровень)

Подробный список задач: `docs/tasks-user-intents.md`. Кратко:

1. T-01..T-03 — хранилище/валидация/модуль + тесты (без UI).
2. T-04 — настройки в `DEFAULT_SETTINGS` + каталог.
3. T-05 — интеграция в `Brain` + горячая перезагрузка + тесты.
4. T-06 — WebBridge + серверные роуты + CSRF/аудит + тесты.
5. T-07 — GTK-редактор/меню.
6. T-08 — страница панели + API-клиент + i18n.
7. T-09 — документация, smoke-тесты, финальная проверка.

## 5. Тесты (обязательный минимум)

Добавить/обновить:
- `tests/test_user_intents.py` (новый): load/save, validate, полный цикл import/export,
  recognize (точная фраза/keyword/partial), приоритет, горячая перезагрузка по mtime.
- `tests/test_webpanel.py`: новые роуты, CSRF на POST/PUT, схема настроек, заголовки export,
  отклонение невалидного импорта, эндпоинт проверки фразы.
- `tests/test_voice_intent.py` / `tests/test_nlu.py`: убедиться, что добавление
  пользовательского интента не ломает базовые и ONNX fallback.
- smoke: `tests/smoke_webpanel.sh` (или новый `smoke_user_intents.sh`) —
  создать intent через API, проверить, что `Brain` его видит.

Быстрая проверка (из `AGENTS.md`):

```bash
python3 tests/test_webpanel.py
python3 -m py_compile yumi/webpanel/*.py yumi/config.py yumi/brain.py yumi/ui/*.py
for f in yumi/webui/static/js/*.js yumi/webui/static/js/pages/*.js; do
  node --input-type=module --check < "$f" || echo "FAIL $f"
done
pytest tests/ -q
```

## 6. Риски и открытые вопросы

1. **Имя хранилища и миграция.** `user_intents.json` vs переиспользовать `actions.json`.
   Рекомендация: отдельный файл + необязательный импорт из `actions.json`, без авто-замены.
2. **Приоритет.** Built-in навыки сейчас выполняются раньше `voice_intent()`. Нужно решить,
   может ли пользовательский интент переопределить, например, «включи музыку».
   Рекомендация: **нет**, чтобы не сломать базовые сценарии; пользовательские интенты
   идут после built-in.
3. **`nlu.recognize()` фильтр.** Он требует `command` или `url`; для `say`/`skill` нужно
   либо расширить `IntentResult.payload`, либо передавать записи с фиктивным action.
   Рекомендация: адаптировать `nlu.recognize()` так, чтобы он принимал `action.type`
   без слома старых вызовов.
4. **`skill` action.** Список допустимых id навыков и способ вызова. Рекомендация:
   отложить до T-10 или ограничить существующими именами методов в `Brain`.
5. **ONNX fallback.** Пользовательские интенты не обучают модель; нужно явно написать
   в UI/доке, что кастомные фразы работают через `nlu`, а не через ONNX.
6. **Конкурентность.** Одновременная запись из панели и GTK. Использовать атомарную
   запись + проверку mtime (последняя запись побеждает) либо оптимистичную блокировку
   через поле `version`.
7. **Конфиг-редактор.** Стоит ли добавить `user_intents.json` в `catalog.CONFIG_FILES`?
   Рекомендация: **нет**, только через новый валидирующий API, чтобы не обойти проверки.

## 7. Definition of done

- [ ] Пользователь может создать/удалить/изменить свой интент из GTK и из панели.
- [ ] Есть импорт/экспорт JSON через панель с валидацией.
- [ ] Тест фразы показывает, что распозналось, без выполнения действия.
- [ ] Кастомные интенты работают без перезапуска и без переобучения ONNX.
- [ ] Базовые intents/навыки не сломаны; приоритет зафиксирован тестами.
- [ ] Новые настройки и страница панели отражены в `catalog.py` и `api.js`.
- [ ] `tests/test_webpanel.py`, `test_user_intents.py`, `py_compile`, JS syntax check — зелёные.
- [ ] Обновлены `README.ru.md`, `README.md`, `docs/handoff-web-panel.md`.
