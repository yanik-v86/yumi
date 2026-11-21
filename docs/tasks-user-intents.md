# Задачи: пользовательские интенты (свои команды и фразы)

Статус: **список задач к реализации, код не изменён**.  
Дата: 2026-11-21.  
Связанный документ: `docs/handoff-user-intents.md` (архитектура, контракты, риски).  
Правило проекта: см. `AGENTS.md` — каждая возможность должна работать **и в GTK, и в веб-панели**.

## Легенда

- Приоритет: P0 — блокирующий, P1 — важный, P2 — улучшение.
- Статус: `TODO` (все задачи сейчас в этом состоянии).
- Зависимости указаны в поле `Зависит от`.
- ID задач используются в коммитах: `feat(user-intents): T-01 ...`.

---

## Фаза 1 — ядро без UI

### T-01. Хранилище и схема пользовательских интентов (P0)

**Зависит от:** —  
**Файлы:** `yumi/config.py` (новый `INTENTS_FILE`, load/save-хелперы), `yumi/user_intents.py` (новый), `tests/test_user_intents.py` (новый).

**Что сделать:**
- Добавить `INTENTS_FILE = USER_CONFIG_DIR / "user_intents.json"` рядом с `ACTIONS_FILE`.
- Реализовать `load/save` с атомарной записью (по образцу `config.save_actions()`) и поддержкой `YUMI_CONFIG_DIR` для тестов.
- Определить схему: `{version: 1, intents: [...]}`; поля `id`, `name`, `enabled`, `phrases`, `keywords`, `action{type,value}`, `speak`, `priority`, `requires_confirmation`, `created_at`, `updated_at`.
- `validate(payload)`: уникальные `id` (`[a-zA-Z0-9_-]{1,64}`), непустые `phrases` или `keywords`, разрешённые `action.type` (`command|url|say`), ограничения длин, `url` только `http(s)://`.
- `import_json(text)` — fail-fast: при ошибке не трогать существующий файл.
- `export_json(data)` — стабильный формат с indentation для ручного редактирования.

**Критерии приёмки:**
- Полный цикл save→load→export→import без потери данных.
- Некорректный JSON / дубли id / пустые фразы / `javascript:` URL отклоняются.
- Тесты используют временный `YUMI_CONFIG_DIR`, не трогают домашний конфиг.

---

### T-02. Адаптер распознавания для новых типов действий (P0)

**Зависит от:** T-01  
**Файлы:** `yumi/user_intents.py`, `yumi/nlu.py`, `tests/test_user_intents.py`, `tests/test_nlu.py`.

**Что сделать:**
- `to_nlu_entries(user_intents)` — преобразование в формат, понятный `nlu.recognize()`.
- Аккуратно снять ограничение `nlu.recognize()`, требующее `command` или `url`, не сломав вызовы из `Brain.voice_intent()` и `extras.py`. Для `say`/`skill` либо расширить `payload`, либо передавать валидную заглушку.
- `match(text, intents) -> IntentResult | None` с уважением `enabled` и `priority`.
- Публичный `test_phrase(text)` для кнопки «Проверить фразу» — **без выполнения действия**.

**Критерии приёмки:**
- Точная фраза, keyword и partial match дают ожидаемый score (1.0 / 0.8 / 0.6).
- Отключённые интенты не матчатся.
- Существующие `tests/test_nlu.py` зелёные без изменений в их ожиданиях.

---

### T-03. Миграция/импорт существующих actions.json (P1)

**Зависит от:** T-01  
**Файлы:** `yumi/user_intents.py`, `tests/test_user_intents.py`.

**Что сделать:**
- `from_actions(actions)` — конвертация записей кнопок в пользовательские интенты (`command`/`url`, `phrases`, `keywords`, `speak`, `priority`, `requires_confirmation`).
- Никакой авто-миграции при старте: только явный вызов из UI/API.
- Оригинальный `actions.json` не удаляется и не перезаписывается.

**Критерии приёмки:**
- Все существующие поля кнопок корректно маппятся; id дедуплицируются.
- Повторный импорт не создаёт дубликаты.

---

## Фаза 2 — настройки и поведение Юми

### T-04. Настройки в DEFAULT_SETTINGS и каталоге панели (P0)

**Зависит от:** T-01  
**Файлы:** `yumi/config.py`, `yumi/webpanel/catalog.py`, `tests/test_webpanel.py`.

**Что сделать:**
- Добавить `user_intents: true` в `DEFAULT_SETTINGS`.
- При желании `user_intents_confirm: false` (per-intent `requires_confirmation` всё равно имеет приоритет).
- В `catalog.py`: `TITLES`, `HINTS`, `KEY_SECTION` (секция «Голос»/«Интенты»), при необходимости `TYPES`/`CHOICES`.
- Новые строки ru/en в `config.UI`.

**Критерии приёмки:**
- `python3 tests/test_webpanel.py` проходит: каждый ключ `DEFAULT_SETTINGS` есть в схеме.
- Настройка отображается в панели с понятным названием и подсказкой на двух языках.

---

### T-05. Интеграция в Brain: приоритет, выполнение, горячая перезагрузка (P0)

**Зависит от:** T-02, T-04  
**Файлы:** `yumi/brain.py`, `yumi/extras.py` (только если переиспользуем механизм горячей перезагрузки), `tests/test_voice_intent.py`, `tests/test_user_intents.py`.

**Что сделать:**
- Загружать `user_intents.json` в `Brain.__init__`, кэшировать и обновлять по mtime (как `extras.actions_check()`).
- В `heard_text()` вызывать сопоставление пользовательских интентов **после built-in навыков** и перед/сразу после `voice_intent()` + ONNX fallback. Зафиксировать порядок: `built-in → user_intents → actions.json → ONNX`.
- Выполнение действий переиспользовать существующие пути: `command` (subprocess/shell), `url` (webbrowser), `say` (TTS). Не выполнять действие в `test_phrase()`.
- `requires_confirmation` — через существующий механизм подтверждения.
- Уважать `user_intents = false` (тогда слой полностью выключен).

**Критерии приёмки:**
- Новая фраза находится и выполняется без перезапуска Юми (мок TTS/команд в тестах).
- Пользовательский интент **не перехватывает** встроенные навыки (music/notes/time/weather/joke/params).
- При выключенной настройке пользовательские интенты игнорируются.
- ONNX fallback работает как раньше.

---

## Фаза 3 — API и веб-панель

### T-06. WebBridge + HTTP-роуты (P0)

**Зависит от:** T-01, T-05  
**Файлы:** `yumi/ui/bridge.py`, `yumi/ui/webpanel.py`, `yumi/webpanel/server.py`, `tests/test_webpanel.py`.

**Что сделать:**
- Методы `WebBridge`: `user_intents_get/put/import/export/test`.
- Методы `PanelMixin`: `user_intents_get()` (list + version + mtime), `user_intents_put(payload)`, `user_intents_import(payload)`, `user_intents_export()`, `user_intents_test(text)`. Все вызовы — через `App._web_call` → `GLib.idle_add`.
- Роуты в `server.py`:
  - `GET /api/user-intents`
  - `PUT /api/user-intents`
  - `POST /api/user-intents/import` (multipart-файл **или** JSON-тело)
  - `GET /api/user-intents/export` (attachment, `application/json`)
  - `POST /api/user-intents/test` (`{text}` → `{matched, intent, score, source}`)
- CSRF на всех POST/PUT, аудит изменений (без содержимого команд в логах).
- **Не использовать** `/api/upload` как импорт: там нет валидации схемы.

**Критерии приёмки:**
- `tests/test_webpanel.py`: авторизованный GET/PUT/import/export/test работает.
- Без CSRF-токена POST/PUT → 403.
- Invalid import → 400 и файл не изменён.
- Export отдаёт корректные `Content-Type`/`Content-Disposition`.

---

### T-07. GTK-редактор пользовательских интентов (P0)

**Зависит от:** T-05, T-06  
**Файлы:** `yumi/brain.py` (меню), `yumi/extras.py` или новый `yumi/ui/user_intents_dialog.py`, `yumi/config.py` (строки UI).

**Что сделать:**
- Пункт меню «Свои интенты» рядом с «Свои кнопки».
- Диалог: список карточек, добавление/редактирование/удаление, поля name/phrases/keywords/action/speak/priority/confirmation, кнопка «Проверить фразу».
- Импорт/экспорт файла через GTK-диалог выбора файла (вызывает те же bridge-методы).
- После сохранения — немедленное обновление кэша в `Brain` (mtime или прямой вызов).

**Критерии приёмки:**
- Из GTK можно создать, изменить, удалить, импортировать, экспортировать и протестировать интент.
- Изменения сразу видны в панели и наоборот (общее хранилище).
- Все новые строки — `config.UI` ru/en.

---

### T-08. Страница веб-панели и JS API-клиент (P0)

**Зависит от:** T-06, T-04  
**Файлы:** `yumi/webpanel/catalog.py`, `yumi/webui/static/js/api.js`, `yumi/webui/static/js/pages/user-intents.js` (new), `yumi/webui/static/js/app.js`, `yumi/webui/static/css/app.css` (при нужде).

**Что сделать:**
- `PAGES["user-intents"]` с заголовками ru/en и иконкой.
- `api.userIntentsGet/Put/Import/Export/Test()` в `api.js`.
- `pages/user-intents.js` с `render(view, ctx)`: список, форма, textarea фраз, select `action.type`, кнопки «Проверить», «Импорт», «Экспорт», тумблер enabled.
- UX и безопасность DOM — по образцу `pages/buttons.js`: только `createElement`/`textContent`, никакого `innerHTML` с данными.
- Lazy import в `app.js`.
- Переключатель настройки `user_intents` — через общую схему настроек (страница Settings), отдельный UI не нужен.

**Критерии приёмки:**
- Страница открывается по hash `#/user-intents`, работает на ru/en.
- CRUD + import/export + test фразы работают через API.
- `node --input-type=module --check < file.js` проходит для всех JS.

---

## Фаза 4 — завершение

### T-09. Тесты, smoke, документация (P0)

**Зависит от:** T-01..T-08  
**Файлы:** `tests/smoke_webpanel.sh` (или новый `tests/smoke_user_intents.sh`), `README.ru.md`, `README.md`, `docs/handoff-web-panel.md`, `docs/handoff-user-intents.md`.

**Что сделать:**
- Добавить smoke-сценарий: создать интент через API → проверить, что `Brain` видит его → test phrase → export → import → delete.
- Обновить README (ru/en): как создавать свои интенты, формат файла, импорт/экспорт, что это не ONNX.
- В `docs/handoff-web-panel.md` дописать новые роуты и страницу.
- Отметить завершённые пункты в `docs/handoff-user-intents.md` (Definition of done).

**Критерии приёмки:**
- Весь набор зелёный:

```bash
python3 tests/test_webpanel.py
python3 tests/test_voice_intent.py
python3 tests/test_nlu.py
python3 -m py_compile yumi/webpanel/*.py yumi/config.py yumi/brain.py yumi/ui/*.py
for f in yumi/webui/static/js/*.js yumi/webui/static/js/pages/*.js; do
  node --input-type=module --check < "$f" || echo "FAIL $f"
done
pytest tests/ -q
```

---

### T-10 (P2, опционально). Действие типа `skill` и ONNX-дообучение из UI

**Зависит от:** T-05, T-09  
**Файлы:** `yumi/user_intents.py`, `yumi/brain.py`, `tools/intents_train.py`, UI-формы.

**Что сделать:**
- Белый список внутренних навыков (`id` существующих методов `Brain`) для `action.type = "skill"`.
- Кнопка «Обучить классификатор на моих фразах» (добавляет intents в `data/intents-corpus.json` и запускает `tools/intents_train.py`). Осторожно: операция долгая, только по явному действию пользователя.

**Критерии приёмки:**
- `skill` не может вызвать произвольный Python.
- Обучение не блокирует GTK-поток (отдельный поток/процесс + статус в панели).

---

## Итоговый Definition of Done (для всех агентов)

- [ ] T-01 — T-09 выполнены (T-10 по решению владельца).
- [ ] Пользователь может создавать/редактировать/удалять/импортировать/экспортировать/тестировать интенты из GTK **и** из веб-панели.
- [ ] Кастомные интенты не требуют переобучения ONNX и работают без перезапуска.
- [ ] Базовые intents и навыки не сломаны, приоритет зафиксирован тестами.
- [ ] Секреты/токен не утекают; CSRF/аудит на месте.
- [ ] README (ru/en) и handoff обновлены.
- [ ] Все проверки из T-09 зелёные.

## Порядок передачи между агентами

1. Агент A: T-01 → T-02 → T-03 (ядро + тесты). Отчитаться результатами `pytest tests/test_user_intents.py tests/test_nlu.py`.
2. Агент B: T-04 → T-05 (настройки + Brain). Проверить `tests/test_voice_intent.py`.
3. Агент C: T-06 → T-08 (API + панель). Проверить `tests/test_webpanel.py` и JS syntax check.
4. Агент D: T-07 (GTK) — можно параллельно с C, но после T-05/T-06.
5. Агент E: T-09 (финальные тесты/доки) — после всех.

При передаче всегда обновляйте статусы задач в этом файле и оставляйте коммит-ид в строке задачи.
