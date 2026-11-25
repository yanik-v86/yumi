# Задачи: пользовательские интенты (свои команды и фразы)

Статус: **реализовано полностью: T-01..T-08, T-10, T-11 и T-12; T-09 (P2, опционально) не реализован**.  
Дата: 2026-11-25 (уточнено: без GTK-редактора; реализовано 2026-11-25).  
Связанные документы: `docs/handoff-user-intents.md` (архитектура, контракты, риски),
`docs/plan-intents-action-log.md` и `docs/handoff-intents-action-log.md`
(отдельная задача: журнал действий интентов), а также
`docs/plan-internal-clock.md` / `docs/handoff-internal-clock.md`
(отдельная задача: внутренние часы Юми).

Правило проекта: см. `AGENTS.md` — каждая возможность обычно должна работать **и в GTK, и в веб-панели**.

## Решение по GTK (исключение из правила проекта)

Управление пользовательскими интентами делается **только в веб-панели и через ручное
редактирование `user_intents.json`**. Отдельный GTK-редактор не создаётся — это осознанное
решение владельца, а не пропуск.

- В GTK сохраняется только **исполнение** пользовательских интентов при распознавании фраз.
- Источник истины — один и тот же JSON-файл; панель — полноценный CRUD с валидацией,
  файл — офлайн/аварийный путь без запуска панели.
- Эквивалент в панели: список, создание, правка, удаление, импорт, экспорт и «Проверить фразу».
- Никаких скрытых GTK-форм, дублирующих логику валидации, не добавляем.

## Легенда

- Приоритет: P0 — блокирующий, P1 — важный, P2 — улучшение.
- Статус: T-01..T-08 `DONE`, T-09 `TODO` (P2, по решению владельца).
- Зависимости указаны в поле `Зависит от`.
- ID задач используются в коммитах: `feat(user-intents): T-01 ...`.

---

## Фаза 1 — ядро без UI

### T-01. Хранилище и схема пользовательских интентов (P0) — DONE

**Зависит от:** —  
**Файлы:** `yumi/config.py` (только путь `INTENTS_FILE`), `yumi/user_intents.py` (новый), `tests/test_user_intents.py` (новый).

**Что сделать:**
- Добавить `INTENTS_FILE = CONFIG_DIR / "user_intents.json"` рядом с `ACTIONS_FILE`.
  Переменной `USER_CONFIG_DIR` / `YUMI_CONFIG_DIR` в коде нет: конфиг — это
  `CONFIG_DIR = XDG_CONFIG_HOME/yumi` (`yumi/config.py:12-16`). Тесты используют временный
  `XDG_CONFIG_HOME` либо monkeypatch `config.CONFIG_DIR` и `user_intents.INTENTS_FILE`.
- Всю логику держать в `yumi/user_intents.py`: `load/save/validate/import_json/export_json`.
  `config.py` не может заниматься записью — только константой пути.
- Запись атомарная через `tmp` + `replace`, как в `config.save_actions()`
  (`yumi/config.py:374-382`). Блокировки в текущем `save_actions()` нет — не утверждать обратного.
- Схема: `{version: 1, revision: N, intents: [...]}`. `version` — версия формата,
  `revision` — счётчик для конфликтов при `PUT` из панели (см. T-06). Поля интента:
  `id`, `name`, `enabled`, `phrases`, `keywords`, `action{type,value}`, `speak`, `priority`,
  `requires_confirmation`, `created_at`, `updated_at`.
- `validate(payload)`: уникальные `id` (`[a-zA-Z0-9_-]{1,64}`), непустые `phrases` или
  `keywords`, разрешённые `action.type` (`command|url|say`), ограничения длин
  (≤50 фраз/ключевых слов, строка ≤200, `command` ≤1000), `url` только `http(s)://`.
- `requires_confirmation` по умолчанию: `true` для `command`, `false` для `url` и `say`.
  Для `say` реплика берётся из `speak`, а `action.value` — только если `speak` пуст.
- `import_json(text)` — fail-fast: при ошибке существующий файл не трогается.
- `export_json(data)` — стабильный формат с отступом для ручного редактирования.

**Критерии приёмки:**
- Полный цикл save→load→export→import без потери данных, `revision` инкрементится.
- Некорректный JSON / дубли id / пустые фразы / `javascript:` URL отклоняются.
- Тесты не трогают домашний конфиг и не создают GTK-зависимостей.

---

### T-02. Адаптер распознавания для новых типов действий (P0) — DONE

**Зависит от:** T-01  
**Файлы:** `yumi/user_intents.py`, `yumi/nlu.py`, `tests/test_user_intents.py`, `tests/test_nlu.py`.

**Что сделать:**
- `to_nlu_entries(user_intents)` — преобразование в **плоский** формат, который уже понимает
  `nlu.recognize()`: `phrases`, `keywords`, `priority`, `speak`, `id`; для `command`/`url`
  пробрасываются одноимённые поля. Для `say` добавляется маркер `user_intent` — фиктивную
  команду в shell передавать нельзя.
- Аккуратно расширить фильтр в `nlu.recognize()` (`yumi/nlu.py:233`) с
  `command or url` до `command or url or user_intent`, и научить `_intent_name()`
  (`nlu.py:59`) понимать маркер. Старый контракт `match()` и все вызовы из
  `Brain.voice_intent()`/`addressing.py` остаются прежними. `yumi/intents.py` не трогаем:
  ONNX по-прежнему получает только записи из `actions.json`.
- `match(text, intents) -> IntentResult | None` уважает `enabled` и `priority`.
  Важно: в текущем коде `priority` — только разрешение ничьи после score
  (`nlu.py:251-259`, `tests/test_nlu.py:102`), а не абсолютный приоритет. Эту семантику
  зафиксировать тестом и не менять.
- Публичный `test_phrase(text)` для кнопки «Проверить фразу» — **без выполнения действия**.

**Критерии приёмки:**
- Точная фраза, keyword и fuzzy-совпадение дают 1.0 / 0.8 / 0.6.
- Отключённые интенты не матчатся; `say` матчится без фиктивной команды.
- Существующие `tests/test_nlu.py` зелёные без изменений в их ожиданиях.

---

### T-03. Миграция/импорт существующих actions.json (P1) — DONE

**Зависит от:** T-01  
**Файлы:** `yumi/user_intents.py`, `tests/test_user_intents.py`.

**Что сделать:**
- `from_actions(actions)` — конвертация записей кнопок (`label`/`label_ru` → `name`,
  `command`/`url`, `phrases`, `keywords`, `speak`, `priority`, `requires_confirmation`).
- Никакой авто-миграции при старте: только явный вызов из панели или из пользовательского
  скрипта. Оригинальный `actions.json` не удаляется и не перезаписывается.

**Критерии приёмки:**
- Все поля кнопок корректно маппятся; id дедуплицируются; повторный импорт не создаёт дубли.

---

## Фаза 2 — настройки и поведение Юми

### T-04. Настройки в DEFAULT_SETTINGS и каталоге панели (P0) — DONE

**Зависит от:** T-01  
**Файлы:** `yumi/config.py`, `yumi/webpanel/catalog.py`, `tests/test_webpanel.py`.

**Что сделать:**
- Добавить `user_intents: true` в `DEFAULT_SETTINGS`. Отдельного `user_intents_confirm` не нужно:
  подтверждение решается per-intent полем `requires_confirmation`.
- В `catalog.py`: `TITLES`, `HINTS`, `KEY_SECTION` — в существующую секцию `mind`
  (`catalog.py:80`, `:102-146`). Новая секция «Интенты» не заводится: для неё потребовалось бы
  править ещё `SECTIONS` и `SECTION_PAGE`.
- Новые строки ru/en добавляются только в `config.UI`, если они нужны в самой Юми.
- `_web_apply_settings()` отдельной ветки не требует: `Brain` читает флаг на каждую фразу.
  Если появится кэш настроек — инвалидировать его здесь же.

**Критерии приёмки:**
- `python3 tests/test_webpanel.py` проходит: каждый ключ `DEFAULT_SETTINGS` есть в схеме.
- Настройка отображается в панели с понятным названием и подсказкой на двух языках.

---

### T-05. Интеграция в Brain: порядок, выполнение, горячая перезагрузка (P0) — DONE

**Зависит от:** T-02, T-04  
**Файлы:** `yumi/brain.py`, `yumi/user_intents.py`, `tests/test_voice_intent.py`, `tests/test_user_intents.py`.

**Что сделать:**
- Загружать `user_intents.json`, кэшировать и обновлять по `mtime`/`revision`
  (по образцу `extras.actions_check()`, `yumi/extras.py:322-331`), без перезапуска.
- **Зафиксированный порядок в `heard_text()`** (по текущему коду,
  `yumi/brain.py:1659-1748`) — существующие блоки не переставляем:

  1. stop/ожидание подтверждения/заметка — как сейчас;
  2. встроенный music-control (`brain.py:1663-1672`) — как сейчас;
  3. `voice_intent()` = `actions.json` + ONNX fallback внутри `nlu.recognize()`
     (`brain.py:1673`, `nlu.py:238-249`) — как сейчас;
  4. notes / время / погода / шутка / параметры / имя (`brain.py:1686-1747`) — как сейчас;
  5. **новый слой пользовательских интентов** — сразу после п. 4, до `fallback`/chat;
  6. `addressing` + чат (`brain.py:1748+`) — как сейчас.

  Так пользовательский интент не перехватывает встроенные навыки и не ломает кнопки/ONNX.
  При конфликте с кнопкой из `actions.json` побеждает кнопка — это честно отражается в подсказке панели.
- Матчить через `nlu.recognize(text, to_nlu_entries(...), use_intents=False, min_confidence=line)`
  и по `text`, и по `alt`. ONNX внутри нового слоя отключён: он остаётся только в п. 3.
- Выполнение переиспользовать существующие пути: `command` → `('run', ...)`, `url` → `('url', ...)`,
  `say` → `say_text()`. `requires_confirmation` — через существующий
  `pending_permission`/`permissions` (`brain.py:1883-1908`). Никакого выполнения в `test_phrase()`.
- Уважать `user_intents = false` (слой полностью выключен).
- Передавать фразы пользовательских интентов в `addressing.hints_from()` вместе с
  `self.custom` (`yumi/addressing.py:105-115`), чтобы «уши» слышали их и в fallback-режиме.

**Критерии приёмки:**
- Новая фраза находится и выполняется без перезапуска Юми (моки TTS/команд в тестах).
- Встроенные навыки, кнопки и ONNX fallback ведут себя как раньше; приоритет зафиксирован тестом.
- При выключенной настройке пользовательские интенты игнорируются.
- Для `command` по умолчанию спрашивается подтверждение; для `say` конфликт `speak`/`value`
  решён в пользу `speak`.

---

## Фаза 3 — API и веб-панель

### T-06. WebBridge + HTTP-роуты (P0) — DONE

**Зависит от:** T-01, T-05  
**Файлы:** `yumi/ui/bridge.py`, `yumi/ui/webpanel.py`, `yumi/webpanel/server.py`, `tests/test_webpanel.py`.

**Что сделать:**
- Методы `WebBridge`: `user_intents_get/put/import/export/test` — все через `_on()`
  → `App._web_call` → `GLib.idle_add` (`bridge.py:17-18`).
- Методы `PanelMixin` в `yumi/ui/webpanel.py` с теми же именами; валидация — только в
  `user_intents.py`.
- Роуты в `server.py`:
  - `GET /api/user-intents` → `{version, revision, mtime, intents}`;
  - `PUT /api/user-intents` — полная замена, обязателен `revision`, при расхождении `409`;
  - `POST /api/user-intents/import` — multipart-файл **или** JSON-тело, валидация до записи;
  - `GET /api/user-intents/export` — `application/json` + `Content-Disposition: attachment`;
  - `POST /api/user-intents/test` → `{matched, intent, score, source}`.
- CSRF/origin уже проверяются централизованно для всех `POST/PUT/PATCH/DELETE`
  (`server.py:364-368`) — отдельной проверки в роутах не добавляем. Аудит изменений ведём
  без содержимого команд.
- **Не использовать** `/api/upload` как импорт: он сохраняет файл в `CACHE_DIR/uploads`
  без проверки схемы (`server.py:703-720`).
- В `tests/test_webpanel.py` расширить stub `Bridge` новыми методами — сейчас он не знает
  пользовательских интентов.

**Критерии приёмки:**
- Авторизованные GET/PUT/import/export/test работают; без CSRF → 403.
- Invalid import → 400 и файл не изменён; конфликт `revision` → 409.
- Export отдаёт корректные `Content-Type`/`Content-Disposition`.
- `test` ничего не выполняет и не меняет файл.

---

### T-07. Страница веб-панели и JS API-клиент (P0) — DONE

**Зависит от:** T-06, T-04  
**Файлы:** `yumi/webpanel/catalog.py`, `yumi/webui/static/js/api.js`,
`yumi/webui/static/js/pages/user-intents.js` (новый), `yumi/webui/static/js/app.js`,
`tests/test_webpanel.py`, CSS — при нужде.

**Что сделать:**
- `PAGES["user-intents"]` с заголовками ru/en и иконкой рядом с `buttons`.
  Отдельный раздел настроек не нужен: тумблер `user_intents` живёт в Settings → Mind.
- `api.userIntentsGet/Put/Import/Export/Test()` в `api.js` (сейчас там нет даже
  `actionsGet/Put` — страницы вызывают `api.get/put('/api/actions')` напрямую).
- `pages/user-intents.js` с `render(view, ctx)`: список карточек, форма, textarea фраз,
  `select` для `action.type`, кнопки «Проверить», «Импорт», «Экспорт», тумблер `enabled`,
  скрытое поле `revision`.
- DOM только через `createElement`/`textContent`, как в `pages/buttons.js`; никакого
  `innerHTML` с данными. Lazy import в `app.js` (карта `PAGES` в `app.js:7-22`).
- Обновить жёсткую проверку в `tests/test_webpanel.py:367-370`: страниц станет 16,
  в множество id добавится `user-intents`.

**Критерии приёмки:**
- Страница открывается по `#/user-intents`, работает на ru/en.
- CRUD + import/export + test фразы идут через API; `node --input-type=module --check` зелёный.

---

## Фаза 4 — завершение

### T-08. Тесты, smoke, документация (P0) — DONE

**Зависит от:** T-01..T-07  
**Файлы:** `tests/smoke_user_intents.sh` (новый; готовых smoke-скриптов в репозитории нет),
`README.ru.md`, `README.md`, `docs/handoff-web-panel.md`, `docs/handoff-user-intents.md`.

**Что сделать:**
- Smoke-сценарий без GTK: создать интент через API → поправить `user_intents.json` руками →
  убедиться, что `Brain` подхватил его по mtime → test phrase → export → import → delete.
- Обновить README (ru/en): как создавать интенты в панели и вручную в файле, формат JSON,
  импорт/экспорт, что это правила `nlu`, а не дообучение ONNX, и что GTK-редактора нет.
- В `docs/handoff-web-panel.md` дописать новые роуты и страницу (сейчас там 15 страниц).
- Отметить завершённые пункты в `docs/handoff-user-intents.md`.

**Критерии приёмки:**
- Весь набор зелёный:

```bash
python3 tests/test_webpanel.py
python3 tests/test_voice_intent.py
python3 tests/test_nlu.py
python3 tests/test_user_intents.py
python3 -m py_compile yumi/webpanel/*.py yumi/config.py yumi/brain.py yumi/ui/*.py yumi/user_intents.py
for f in yumi/webui/static/js/*.js yumi/webui/static/js/pages/*.js; do
  node --input-type=module --check < "$f" || echo "FAIL $f"
done
pytest tests/ -q
```

Фактический прогон: профильные тесты, `py_compile`, JS syntax check и
`tests/smoke_user_intents.sh` зелёные. Полный `pytest tests/ -q` дал 60 passed,
1 skipped и 4 провала в `tests/test_speaker_gate.py`; те же 4 провала
воспроизводятся на этой ветке **до** изменений пользовательских интентов и к фиче
отношения не имеют.

---

### T-09 (P2, опционально). Действие `skill` и ONNX-дообучение из панели

**Зависит от:** T-05, T-08  
**Файлы:** `yumi/user_intents.py`, `yumi/brain.py`, `tools/intents_train.py`, веб-страница/API.

**Что сделать:**
- Белый список внутренних навыков (id существующих методов `Brain`) для `action.type = "skill"`.
- Кнопка «Обучить классификатор на моих фразах» **только в веб-панели**. Адаптер должен
  превращать интенты в формат corpus (`label`, `phrases`): `intents_train.py` читает
  `--corpus` и `--actions` (`tools/intents_train.py:304-305,45`), а поле `name` не равно `label`.
  Запуск — отдельным процессом/потоком, статус виден в панели; GTK-поток не блокируется.

**Критерии приёмки:**
- `skill` не может вызвать произвольный Python.
- Обучение не блокирует приложение и запускается только явным действием пользователя.

---

### T-10 (P0). Ответ пользовательского интента в бабле и голосом — DONE

**Зависит от:** T-01, T-02, T-05, T-07  
**Файлы:** `yumi/user_intents.py`, `yumi/brain.py`, `yumi/ui/app.py`,
`yumi/webui/static/js/pages/user-intents.js`, `tests/test_user_intents.py`,
`tests/test_voice_intent.py`, `tests/test_webpanel.py`.

**Что сделать:**
- Добавить `capture` в схему (только для `command`) и в `to_nlu_entries()`/`public()`.
- Вместо `('run', ...)` создавать `('run_capture', command, intent_id, speak)` и не говорить
  шаблон с литеральным `{stdout}` до получения вывода.
- `App.run_capture()`: фоновый поток, `sh -c`, stdout, таймаут 30 с, возврат через
  `GLib.idle_add` → `Brain.user_intent_answer()` → обычный `say_text()` (бабла + голос).
- В панели — тумблер «Использовать вывод команды», подсказка про `{stdout}`, бейдж в карточке
  (дополнительные поля ответа появились в T-12).

**Критерии приёмки:**
- Вывод команды виден в бабле и озвучивается; пустой вывод даёт реплику «ответа нет».
- Подтверждение работает и для captured-команды; тест фразы по-прежнему ничего не запускает.

---

### T-11 (P0). Запуск интента кнопкой «Проверить» в панели — DONE

**Зависит от:** T-05, T-06, T-07, T-10  
**Файлы:** `yumi/ui/bridge.py`, `yumi/ui/webpanel.py`, `yumi/webpanel/server.py`,
`yumi/webui/static/js/api.js`, `yumi/webui/static/js/pages/user-intents.js`, тесты, доки.

**Что сделать:**
- Новый `POST /api/user-intents/run` (CSRF обязателен) и `WebBridge.user_intents_run()`.
- `PanelMixin._web_user_intents_run()` на GTK-потоке: свежий mtime, тот же порог уверенности,
  поиск по фразам и вызов `Brain.voice_user_intent()` — без отдельного «теневого» исполнения.
- Кнопка карточки «Проверить» вызывает `/run`; блок «Совпадение?» остаётся сухим `/test`.

**Критерии приёмки:**
- После клика найденный интент даёт баблу, голос и обычное действие (включая `capture`).
- Несовпадение и выключенный слой возвращают `ran: false` без побочных эффектов.

---

### T-12 (P0). Раздельные голос/бабла и лимит текста в бабле — DONE

**Зависит от:** T-10, T-11  
**Файлы:** `yumi/user_intents.py`, `yumi/brain.py`, `yumi/ui/app.py`,
`yumi/webui/static/js/pages/user-intents.js`, тесты, доки, живой `user_intents.json`.

**Что сделать:**
- Новые поля интента: `voice_answer`, `bubble_answer` (по умолчанию `true`), `voice_text`,
  `bubble_text` (свои шаблоны: `{stdout}` подставляет вывод, без маркера — дословно;
  пусто — общий `speak`), `bubble_limit`
  (по умолчанию `1000`, диапазон `100..4000`). Отдельные шаблоны требуют `capture`.
- `Brain._voice_run()` кладёт пятый аргумент `options` в `('run_capture', ...)`;
  `App.run_capture()` передаёт его в `Brain.user_intent_answer()`.
- `say_text(..., bubble=False)` создаёт скрытый бабл с пустым текстом, чтобы звук имел id
  и `_voice_pump()` не терял его; `bubble_ops()` скрытый бабл не рисует.
- `user_intent_answer()` рендерит голос и баблу раздельно: голос получает полный ответ
  (жёсткий потолок `MAX_CAPTURED_ANSWER`), бабла обрезается по `bubble_limit`. Разные строки
  идут через `spoken=`, чтобы одна озвучка была привязана к одному видимому баблу.
- Панель: переключатели, два поля шаблонов, числовое поле лимита и бейджи/подсказка в карточке.
- Живой интент новостей: короткий `voice_text`, полный `{stdout}` в бабле, `revision` увеличен.

**Критерии приёмки:**
- Голос можно выключить при включённой бабле и наоборот; при двух выключенных переключателях
  команда выполняется молча.
- Длинный новостной ответ в бабле укладывается в 1000 символов по умолчанию, а голос не
  обрывается раньше жёсткого потолка 4000.
- Отдельные шаблоны и кастомный лимит проходят roundtrip через API и выживают без перезапуска.

---

## Итоговый Definition of Done (для всех агентов)

- [x] T-01 — T-08, T-10, T-11 и T-12 выполнены (T-09 — по решению владельца).
- [x] Пользователь может создавать/редактировать/удалять/импортировать/экспортировать/
      тестировать интенты **из веб-панели** и **вручную в `user_intents.json`**. GTK-редактора нет.
- [x] Кастомные интенты не требуют переобучения ONNX и работают без перезапуска.
- [x] Ответ captured-интента показывается в бабле и звучит как обычная реплика Юми.
- [x] Кнопка «Проверить» запускает найденный интент через HTTP + Bridge + Brain.
- [x] Голос и бабла captured-ответа управляются независимо, с отдельными шаблонами и лимитом.
- [x] Встроенные навыки, кнопки `actions.json` и ONNX fallback не сломаны; порядок зафиксирован тестами.
- [x] Секреты/токен не утекают; CSRF, аудит и проверка `revision` на месте.
- [x] README (ru/en) и оба handoff обновлены; счётчик страниц в тесте панели обновлён.
- [x] Профильные проверки из T-08 зелёные; 4 провала полного `pytest` в `test_speaker_gate.py`
      зафиксированы как pre-existing и не вызваны этой фичей.

## Порядок передачи между агентами

1. Агент A: T-01 → T-02 → T-03 (ядро + тесты). Отчитаться `pytest tests/test_user_intents.py tests/test_nlu.py`.
2. Агент B: T-04 → T-05 (настройки + Brain). Проверить `tests/test_voice_intent.py`.
3. Агент C: T-06 → T-07 (API + панель). Проверить `tests/test_webpanel.py` и JS syntax check.
4. Агент D: T-08 (финальные тесты/доки/smoke) — после всех.
5. GTK-агента нет: по решению владельца редактор в GTK не делается.

При передаче всегда обновляйте статусы задач в этом файле и оставляйте коммит-ид в строке задачи.
