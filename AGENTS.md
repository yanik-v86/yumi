# AGENTS.md — Юми

Инструкции для AI-агента и разработчика, который работает над Юми: пиксельной
мотыльковой девушкой для Wayland-десктопа (Python + GTK) с браузерной панелью управления.

## Главное правило: изменение — и в Юми, и в веб-панели

**Любая новая возможность, настройка, действие или изменение поведения Юми должны
появляться в двух местах: в самой Юми (GTK-приложение) и в её веб-панели.** Панель —
это не отдельный проект и не «когда-нибудь потом», а второй полноценный пульт к той же
Юми. Если функция есть в приложении, но недоступна из браузера — изменение не считается
готовым.

Исключения — только то, что физически не имеет смысла в браузере (например, глобальный
хоткей, D-Bus-флаг запуска, перетаскивание окна). Такие случаи надо явно назвать в ответе
и, если возможно, дать в панели эквивалент (кнопку, настройку, статус).

Явное исключение, зафиксированное владельцем для провайдеров нейронок: в GTK доступны
только переключение провайдера и модели; создание, правка, удаление и проверка провайдеров
делаются только в веб-панели (`#/providers`). См. `docs/tasks-llm-providers.md` и
`docs/handoff-llm-providers.md`.

### Чек-лист для любой новой функции

1. **Настройка** — добавить ключ в `DEFAULT_SETTINGS` (`yumi/config.py`). Этого уже
   достаточно, чтобы ключ попал в схему панели; при желании уточнить в
   `yumi/webpanel/catalog.py`: `KEY_SECTION`, `TYPES`, `CHOICES`, `RANGES`,
   `SECRET_KEYS`, `TITLES`, `HINTS`.
2. **Живое применение** — если настройка что-то меняет на ходу, обработать её в
   `App._web_apply_settings` (`yumi/ui/webpanel.py`), чтобы панель и приложение
   применяли изменение одинаково.
3. **Действие/данные** — новый серверный вызов добавить методом в `WebBridge`
   (`yumi/ui/bridge.py`), затем роут в `yumi/webpanel/server.py` и вызов в
   `yumi/webui/static/js/api.js`.
4. **Страница** — новая страница: запись в `catalog.PAGES`, модуль
   `yumi/webui/static/js/pages/<id>.js` с `render(view, ctx)` и ленивый импорт в
   `app.js`. Если странице нужен новый вызов — см. пункт 3.
5. **Отображение** — если у функции есть состояние (включено/выключено, текущий трек,
   очередь, прогресс), добавить его в снимок `/api/status` и на нужную страницу панели.
6. **Тесты** — обновить `tests/test_webpanel.py` (он проверяет, что каждый ключ из
   `DEFAULT_SETTINGS` попал в схему) и профильные тесты в `tests/`.
7. **Документация** — обновить `README.ru.md` и `README.md`, а при существенных
   изменениях — `docs/handoff-web-panel.md`.

### Быстрая проверка

```bash
python3 tests/test_webpanel.py
python3 tests/test_user_intents.py
python3 tests/test_addressing.py
bash tests/smoke_user_intents.sh
python3 -m py_compile yumi/webpanel/*.py yumi/config.py yumi/brain.py yumi/ui/*.py yumi/user_intents.py
for f in yumi/webui/static/js/*.js yumi/webui/static/js/pages/*.js; do
  node --input-type=module --check < "$f" || echo "FAIL $f"
done
```

## Структура проекта

```
yumi/
  config.py          DEFAULT_SETTINGS, Store, пути
  user_intents.py    пользовательские фразы: схема, валидация, запись, match
  intents_bundle.py  ZIP-бандлы: манифест, SHA-256, Ed25519, безопасный импорт
  intents_remote.py  подписанный каталог официального репозитория и загрузка ZIP
  brain.py           поведение, меню, действия в мире
  memory.py          дневник (SQLite)
  chat.py            разговор с умом
  music.py           Jellyfin и локальные папки
  ears.py, oww_ear.py, stt_daemon.py, tts.py, voice.py
  ui/
    app.py           приложение, настройки, жизненный цикл
    main.py          точка входа
    overlay.py       окно и отрисовка
    painter.py       пиксельная графика
    senses.py        слух, VAD, реакции
    bridge.py        WebBridge — контракт между HTTP и приложением
    webpanel.py      PanelMixin: запуск панели, снимок, применение настроек
  webpanel/
    server.py        ThreadingHTTPServer, API, SSE, статика, аудит
    auth.py          токен, сессии, CSRF
    catalog.py       карта настроек, страниц и секций (без GTK)
  webui/
    index.html       оболочка SPA
    static/css/app.css
    static/js/{app,api,ui}.js
    static/js/pages/*.js       включая user-intents.js (свои фразы)
bin/yumi             запуск, флаги (включая --web)
tests/               pytest и интеграционные тесты
```

## Архитектурные правила

- `yumi/webpanel/*` **не импортирует GTK** и не трогает виджеты: HTTP-потоки общаются
  с приложением только через `WebBridge`, а мост перекладывает вызовы в GTK-поток
  через `GLib.idle_add` (`App._web_call`).
- Панель выключена по умолчанию (`web_panel = false`). Не открывать порт без явного
  включения пользователем.
- Ключи нейронок лежат только в `~/.config/yumi/llm_keys.json` (права `0600`), не в
  `settings.json`; они не попадают в API, аудит, логи и снимок. Пароли/ключ Jellyfin
  маскируются в API и редакторе конфигов; токен панели отдаётся только по POST + CSRF.
  Подробности — `docs/handoff-llm-providers.md`.
- Фронтенд не вставляет HTML из данных: только `createElement`/`textContent`.
- Новые строки интерфейса — на русском и английском (`{'ru': ..., 'en': ...}`).
- Код и docstring'и — в стиле окружающих файлов; не переписывать чужие модули без
  необходимости.

## Пользовательские интенты (свои фразы)

Источник истины — каталог `~/.config/yumi/user-intents/` (`config.INTENTS_DIR`): в нём
`index.json` (version, revision, порядок правил) и по папке на интент —
`user-intents/<id>/intent.json`. Рядом с `intent.json` можно держать свои файлы: команда
интента запускается в этой папке, поэтому хватает относительного пути
(`python3 lights.py on`). Агент должен создавать интенты через страницу панели
`user-intents` (`#/user-intents`) или её API. Отдельного GTK-редактора **нет** — это явное
исключение из главного правила: в GTK остаётся только исполнение фраз. Если панель
недоступна, допустимо править `intent.json` руками, увеличив `revision` в `index.json`.
Старый `user_intents.json` при первом чтении раскладывается по папкам, а его копия
остаётся в `user_intents.json.migrated`.

Минимальный файл `user-intents/lights_on/intent.json` (имя папки = `id`):

```json
{
  "id": "lights_on",
  "name": "Свет",
  "enabled": true,
  "phrases": ["включи свет", "lights on"],
  "keywords": ["свет", "лампа"],
  "action": {"type": "command", "value": "python3 lights.py on"},
  "speak": "Включаю свет",
  "capture": false,
  "voice_answer": true,
  "bubble_answer": true,
  "bubble_limit": 1000,
  "priority": 0,
  "requires_confirmation": true
}
```

Правила, которые нельзя обходить:

- Валидация только в `yumi/user_intents.py`; не дублировать её в GTK, панели или скриптах.
  `id` — уникальный `[a-zA-Z0-9_-]{1,64}`; нужны `phrases` и/или `keywords`; не более 50
  строк в списке, строка ≤200, `command` ≤1000, `url` — только `http(s)://`, `priority`
  −100..100 и только разрешает ничью после score.
- `action.type`: `command`, `url` или `say`. Подтверждение по умолчанию включено для
  `command` и выключено для `url`/`say`. Для `say` говорится `speak`, а `action.value`
  используется только если `speak` пуст.
- Чтобы ответ команды появился **в бабле и голосом**, ставь `"capture": true` только на
  `command` и пиши `{stdout}` в `speak` (например, `"speak": "Новости: {stdout}"`).
  Вывод команды подставляется в реплику; команда выполняется в фоне через
  `('run_capture', ...)` и возвращается в `Brain.user_intent_answer()` — не через
  прямой `tts`/`play_file` в самом скрипте. Без вывода Юми говорит, что ответа нет.
- `voice_answer` и `bubble_answer` включают голос и баблу **независимо** (по умолчанию оба
  `true`). `voice_text` и `bubble_text` задают свои шаблоны вместо общего `speak`; пустое поле
  означает «взять общий». В отдельном шаблоне `{stdout}` подставляет вывод, а без него строка
  говорится дословно и не приписывает длинный вывод (короткое объявление голосом).
  `bubble_limit` — длина текста в бабле, по умолчанию `1000`, допустимо `100..4000`; голос
  получает полный ответ (жёсткий потолок `MAX_CAPTURED_ANSWER = 4000`). Для новостей удобно
  коротким `voice_text` объявить ответ,
  а полный `{stdout}` оставить только в бабле.
- Пользовательские интенты проверяются **после** встроенных навыков и кнопок
  `actions.json`, поэтому кнопка выигрывает спор за ту же фразу. Это обычные правила
  `nlu`, а не дообучение ONNX: новая фраза подхватывается по mtime без перезапуска.
- Правка `intent.json` вручную увеличивает `revision` в `index.json`. Запись из панели
  (`PUT /api/user-intents`) обязана прислать текущий `revision`; при расхождении сервер
  отдаёт `409`, а не перезаписывает чужую правку.
- Импорт/экспорт — **только ZIP**: `POST /api/user-intents/import.zip` (multipart) и
  `GET /api/user-intents/export.zip`, не `/api/upload` и не старый JSON. В архиве лежат
  `manifest.json` с SHA-256 всех файлов, `intents/index.json`, `intents/<id>/intent.json`
  и все остальные файлы папки правила (с правами доступа). Валидация архива — в
  `yumi/intents_bundle.py`, не дублировать её в панели. Импорт заменяет хранилище, но не
  исполняет команды.
- Официальный репозиторий на будущее: `GET /api/user-intents/remote` читает подписанный
  `index.json` с `user_intents_repo_url`, `POST /api/user-intents/remote/install` ставит
  один набор **merge-ом**, не удаляя свои правила. Каталог и ZIP проверяются подписью
  Ed25519 (`user_intents_trusted_keys`, опциональный `cryptography`) и SHA-256; по умолчанию
  подпись обязательна только для удалённых данных. Локальные ZIP без подписи допустимы.
  Переключатель `user_intents_require_signature` продублирован в GTK-меню «Веб-панель»,
  оттуда же есть переход на `#/user-intents`; адрес репозитория и ключи — длинный текст,
  их редактирует только панель (явное исключение, как адреса Jellyfin).
  `POST /api/user-intents/test` показывает совпадение и ничего не выполняет;
  `POST /api/user-intents/run` находит фразу и запускает интент через тот же `Brain`, что и
  услышанная речь (бабла, голос, команда). Кнопка «Проверить» на карточке страницы
  `user-intents` использует именно `run`; отдельная проверка совпадения остаётся без запуска.
  Аудит изменений не содержит текста команд.

Интент `reminders_tick` (`python3 reminders.py --tick`) — тик напоминаний через
внутренние часы Юми (`yumi/extras.py`, задача раз в минуту), systemd-таймер для
этого не нужен. Команда и `enabled` правятся на странице `user-intents`, статус
задачи виден в `runtime.clock` и в GTK-меню.

Ключевые файлы: `yumi/user_intents.py` (валидация правил), `yumi/intents_bundle.py`
(ZIP, манифест, подпись), `yumi/intents_remote.py` (каталог и загрузка),
`yumi/brain.py` (`voice_user_intent()`), `yumi/ui/webpanel.py` (`_web_user_intents_*`),
`yumi/webpanel/server.py` (роуты), `yumi/webui/static/js/pages/user-intents.js`.
Подробности — `docs/handoff-user-intents.md`.

## Тесты

```bash
pytest tests/ -q
```

`tests/test_webpanel.py` поднимает настоящий HTTP-сервер и проверяет схему настроек,
вход по токену, cookie/CSRF, лимит попыток, PATCH настроек, ротацию ссылки, статику и
защиту от path traversal. Тест должен оставаться зелёным после каждого изменения.

## Чего не делать

- Не добавлять функцию только в GTK или только в панель, если она должна быть в обоих.
- Не создавать GTK-редактор `user-intents/<id>/intent.json`: свои фразы правятся в панели
  или в файле.
- Не импортировать GTK в `yumi/webpanel/` и не обращаться к виджетам из HTTP-потока.
- Не отдавать секреты и токен панели в открытом виде.
- Не ломать обратную совместимость `settings.json` без миграции/значения по умолчанию.
