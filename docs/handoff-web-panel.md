# Веб-панель Юми — передача проекта

Документ для следующего агента или человека, который продолжит работу над браузерной
панелью. Здесь описано, что уже сделано, как это устроено, где лежит, чего трогать нельзя
и что осталось.

Панель **выключена по умолчанию**: пока её не включат в настройках самой Юми, ни один порт
не открывается. Включение — Настройки → Веб-панель → «Панель в браузере» (или флаг
`yumi --web`). После включения Юми печатает в stderr ссылку с токеном:

```
yumi: browser panel at http://127.0.0.1:8765/?t=…
```

Ссылка одноразовая по смыслу: токен в URL обменивается на подписанную HttpOnly-сессию,
после чего токен в адресной строке больше не нужен. Токен можно сменить на странице
«Безопасность»; живые сессии при этом не рвутся (меняется только токен, не секрет подписи).

---

## 1. Структура кода

```
yumi/
  webpanel/
    __init__.py        публичный экспорт Panel
    auth.py            токен, подписанные сессии, CSRF, лимит попыток
    catalog.py         карта всех настроек, страниц, секций, конфигов, масок
    server.py          ThreadingHTTPServer, роуты API, SSE, статика, аудит
  webui/
    index.html         оболочка SPA + оверлей входа + баннер разрешения
    static/
      css/app.css      вся пиксельная тема и компоненты
      img/icon.png     иконка панели (фавикон, вход, бренд, герой обзора)
      js/app.js        сессия, навигация, hash-роутер, живой статус, топбар, баннер
      js/api.js        единственное место, где ходят HTTP и SSE
      js/ui.js         DOM-хелперы, иконки, тосты, модалки, контролы настроек
      js/pages/*.js    14 страниц (добавилась doctor.js)
bin/yumi               флаги --web и --doctor
yumi/ui/app.py         жизненный цикл панели, ревизия и журнал чата
yumi/ui/bridge.py      WebBridge — контракт HTTP ↔ приложение
yumi/config.py         настройки web_panel_*, бэкап сломанного settings.json
yumi/brain.py          пункты меню, голосовые команды и разрешения
yumi/doctor.py         один отчёт самопроверки для CLI и панели (без GTK)
yumi/models.py         явные SHA-256 отпечатки моделей, кэш для статуса
yumi/permission.py     правила ALLOW/ALWAYS/DENY, безопасные пути
yumi/voice_state.py    единое состояние микрофона (владелец, поколение)
yumi/nlu.py            распознавание фраз: IntentResult, recognize(), match()
yumi/entities.py       общие сущности фразы: громкость, время, дата
yumi/memory.py         хелперы дневника для страницы «Память»
yumi/notes.py          заметки: sqlite + векторы, голосовые команды, страница «Заметки»
tests/test_webpanel.py интеграционный тест API и безопасности
tests/test_notes.py    тест книжки заметок и разбора голосовых фраз
tests/test_doctor.py   мок-тест отчёта врача и CLI
tests/test_models.py   запись/сравнение хэшей моделей
tests/test_permission.py   отказы сильнее согласий, секреты не запоминаются
tests/test_voice_state.py  переходы состояния микрофона
tests/test_config_backup.py сломанный settings.json → .bad
```

Ключевое правило: `yumi/webpanel/*` **не импортирует GTK**. HTTP-потоки не трогают
виджеты напрямую. Мост `WebBridge` в `yumi/ui/bridge.py` перекладывает каждый вызов в
GTK-поток через `GLib.idle_add` (`_on`) и возвращает результат в HTTP-поток.

```
браузер
  │  HTTP + SSE
  ▼
ThreadingHTTPServer (webpanel.server)
  │  Panel.bridge.<method>(...)
  ▼
WebBridge (yumi.ui.bridge)  ── GLib.idle_add ──▶  App / Brain / Memory
```

---

## 2. Страницы сайта

Навигация задаётся в `catalog.PAGES`, а не в HTML. Порядок страниц — это и есть
предлагаемая структура сайта.

| id | русский заголовок | что делает |
|----|-------------------|------------|
| `dashboard` | Обзор | портрет, реплика, режим, аптайм, таймер, музыка, очередь файлов, быстрые действия |
| `chat` | Разговор | чат с умом, история с ревизией и SSE-операциями Insert/Update/Remove/Clear, «сказать в мир», быстрый старт, живая реплика |
| `notes` | Заметки | поиск по заметкам, создание и правка, удаление, очистка, запись голосом через `/api/voice/listen` |
| `files` | Файлы | очередь обработки, drag-and-drop загрузка, недавние, полка, открыть, конвертировать, сжать |
| `music` | Музыка | текущий трек, play/pause/next/stop/продолжи, громкость, поиск по Jellyfin/папкам |
| `voice` | Ушки и голос | карточки «Активация», «Судья фраз», «Голос»: выбор движка, состояние «доступно/нет», проверка имени и фразы вживую, прослушивание TTS; ниже — «закрыть ушки», выбор микрофона, живое состояние микрофона с кнопками Пауза/Продолжить/Освободить и остальные настройки ушек/звука; голосовые профили: явный выбор профиля, поля «Старое имя» / «Новое имя», результат «Проверить голос» сохраняется при обновлении статуса, переименование подтверждает «было → стало», удаление профиля спрашивает подтверждение в модалке |
| `doctor` | Диагностика | один отчёт: движки, микрофоны, модели, имя, TTS и STT; быстрый запуск без микрофона, запись и проверку хэшей моделей, копирование отчёта. То же, что `yumi --doctor` |
| `buttons` | Кнопки | кольцо, порядок, выключенные кнопки, свои команды, добавление и редактирование; карточка ожидающего разрешения Разово/Всегда/Запретить |
| `appearance` | Внешний вид | текущая палитра, пипетка, пересборка цветов, наряд, масштаб, другой экран, JSON палитры |
| `settings` | Настройки | все ключи `settings.json`, сгруппированные по секциям, поиск, сброс, живое применение |
| `memory` | Память | поиск по дневнику, лимит, строки, удаление 18+ и всей памяти |
| `configs` | Конфиги | список JSON-файлов, просмотр и редактирование с бэкапами; токен только для чтения |
| `security` | Безопасность | адрес, токен, сессии, ротация ссылки, настройки доступа, список и сброс сохранённых разрешений, журнал |
| `logs` | Журналы | лог Юми, лог ушек, журнал решений, журнал панели, скачивание |

Страница — это модуль `export function render(view, ctx)`, который наполняет `view` и
возвращает функцию очистки. `ctx` даёт:

```js
ctx.status          // последний снимок
ctx.schema          // карта настроек из /api/schema
ctx.lang            // 'ru' | 'en'
ctx.applySettings(patch, opts)
ctx.refreshStatus()
ctx.onStatus(fn)    // подписка на живой статус, возвращает отписку
ctx.onEvent(name, fn)
ctx.navigate(id)
```

Роутер в `app.js` лениво импортирует модуль страницы по hash (`#/chat`), кэширует его и
зовёт `render`. Ошибка страницы показывается в её контейнере, оболочка не ломается.

В шапке живут быстрые чипы: **Ушки** (включает и выключает `wake_ears` — тот же
переключатель, что на кольце и в главном меню Юми), DND, показать/спрятать, таймер и
«не прятаться». Чип ушек горит акцентом, когда имя «Юми» слушается.

---

## 3. API

Все ответы — JSON `{ok: true, …}` либо `{ok: false, error: "…"}`. Мутации требуют
заголовок `X-Yumi-CSRF`, совпадающий с читаемой cookie `yumi_csrf`.

Публичное (без сессии):

- `GET /` , `GET /index.html` — оболочка SPA
- `GET /static/…` — CSS/JS
- `GET /art/…`, `GET /favicon.ico` — спрайты и иконка; иконка берётся из
  `webui/static/img/icon.png`, затем из `data/` или темы иконок установленной Юми
- `GET /api/session` — `{authed, csrf?, panel, version, remote}`
- `POST /api/login` — `{token}` или полная ссылка; ставит cookie

С сессией:

| метод | путь | назначение |
|-------|------|-----------|
| POST | `/api/logout` | погасить cookie |
| GET | `/api/status` | полный снимок мира |
| GET | `/api/schema` | карта настроек и страниц |
| GET | `/api/settings` | маскированные значения |
| PATCH | `/api/settings` | `{patch:{key:value}}`, живое применение |
| POST | `/api/settings/reset` | `{key}` или `{all:true}` |
| GET | `/api/configs` | список JSON-файлов |
| GET/PUT | `/api/config/<name>` | чтение/запись с бэкапом |
| GET/PUT | `/api/actions` | свои кнопки; PUT сохраняет и поля `id`, `priority`, `requires_confirmation`, `entities` |
| POST | `/api/actions/<i>/run` | нажать свою кнопку |
| POST | `/api/nlu/confirm` | `{ok:true|false}` — старый ответ да/нет на отложенную команду (совместимость) |
| POST | `/api/doctor` | `{sections?, text?}` — полный отчёт самопроверки; публикует SSE `doctor` |
| GET | `/api/models` | кэшированная проверка моделей (без хэширования) |
| POST | `/api/models/verify`, `/api/models/record` | `{names?}` — явная проверка / запись SHA-256 |
| GET | `/api/permissions` | сохранённые правила allow/deny |
| POST | `/api/permissions/answer` | `{decision: once|always|deny}` — ответить на ожидающее разрешение; `always` только кликом |
| POST | `/api/permissions/clear` | стереть все сохранённые правила |
| POST | `/api/state/<action>` | toggle/show/hide/home/monitor/pipette/recent/shelf/sleep |
| GET | `/api/files/recent`, `/api/files/shelf` | списки файлов |
| POST | `/api/files/shelf` | `{path, add}` |
| POST | `/api/files/open` | открыть файл системно |
| POST | `/api/files/job` | `{op, path, arg}` — convert/compress |
| POST | `/api/files/jobs/cancel` | очистить очередь |
| POST | `/api/upload?name=…` | сырое тело файла |
| GET | `/api/file/preview?path=…` | превью изображения |
| GET/POST | `/api/timer` | состояние / `{action, seconds}` |
| POST | `/api/ask` | короткий вопрос уму |
| GET | `/api/chat/history` | `{ok, messages, rev}` — старый массив `messages` сохранён, добавилась ревизия |
| POST | `/api/chat` | `{text}` → `{reply, history, rev, ops}`; insert-опубликуется и в SSE, и в ответе |
| GET | `/api/chat/ops?since=<rev>` | журнал операций после ревизии, для догоняющей вкладки |
| POST | `/api/chat/message/update`, `/api/chat/message/remove` | `{id, text?}` / `{id}` — операции update / remove |
| DELETE | `/api/chat/history` | `{cleared, rev, ops:[clear]}` — чистит и публикует clear |
| GET | `/api/memory` | `?q=&limit=` |
| POST | `/api/memory/clear` | `{tag}` (`all`, `sassy`) |
| GET | `/api/notes` | `?q=&limit=` — список или поиск по заметкам |
| POST | `/api/notes` | `{text, title?}` — новая заметка |
| GET/PATCH/DELETE | `/api/notes/<id>` | одна заметка, правка, удаление |
| POST | `/api/notes/clear` | `{all:true}` — стереть всю книжку |
| GET | `/api/music` | текущий трек, громкость и `resumable` (есть что продолжить после «стоп») |
| GET | `/api/music/search` | `?kind=&q=` |
| POST | `/api/music/play`, `/api/music/control` | play/pause/next/stop/resume/volume |
| GET | `/api/voice/engines` | наличие oww/vosk/whisper/nemotron/TTS, список голосов и моделей |
| GET | `/api/voice/mics` | свежий список микрофонов звуковой системы (заодно обновляет меню ушек) |
| GET | `/api/voice/state` | одно состояние микрофона: state/owner/generation/reason/wake_enabled/transitions |
| POST | `/api/voice/pause`, `/api/voice/resume`, `/api/voice/release` | забрать микрофон у wake-цикла, вернуть его, полностью отпустить |
| POST | `/api/voice/listen` | `{seconds?, engine?}` — записать фразу выбранным судьёй |
| POST | `/api/voice/test-wake` | `{seconds?, ear?}` — проверить имя выбранным ухом |
| POST | `/api/voice/test` | `{text?, lang?}` — синхронизировать профиль и озвучить пробу текущим голосом |
| POST | `/api/voice/stop`, `/api/voice/speak` | остановить запись/озвучку, сказать текст |
| GET | `/api/speaker` | `{speaker: {enabled, profiles, participants, current, last_event, policy, model}}` — только ids/метки, без векторов |
| POST | `/api/speaker/enroll`, `/api/speaker/test` | записать / проверить голос через демона ушей (микрофон берётся через `_ears_exclusive()`) |
| POST | `/api/speaker/rename`, `/api/speaker/delete` | `{id, label}` / `{id}` — переименовать или удалить профиль |
| POST | `/api/speaker/clear` | очистить участников текущего диалога, профили не трогать |
| GET | `/api/security` | адрес, токен (маска), сессии |
| POST | `/api/security/rotate` | новая ссылка |
| POST | `/api/security/link` | показать ссылку с токеном (только POST + CSRF) |
| GET | `/api/audit` | хвост журнала панели |
| GET | `/api/logs?source=&lines=` | логи |
| GET | `/api/events` | SSE: hello/status/bubble/settings/files/jobs/actions/chat/notes/server/doctor |
| GET | `/api/tools/time|weather|joke|params` | мелкие инструменты |

Важно: `/api/security/link` намеренно **не** отдаёт токен по GET, чтобы он не попал в
историю, referer или кэш. Фронтенд показывает его только после явного нажатия.

Голосовые команды в снимке: `runtime.nlu` — `{last_intent, last_confidence, confirm,
pending_permission}`. `confirm: true` (совместимость) или непустой `pending_permission`
означают, что Юми ждёт ответа на «Запустить?»; страница «Кнопки» показывает Разово/Всегда/
Запретить и вызывает `/api/permissions/answer`, а оболочка дополнительно показывает баннер
на любой странице. `pending_permission` содержит только id, цель, текст, options и secret —
не сырое действие и не слоты. Настройка `nlu_confidence`
(тип `range`, 0.5–1.0, шаг 0.05, по умолчанию 0.6) живёт в секции `mind` и применяется
на каждой фразе без перезапуска. Новые поля кнопки (`id`, `priority`,
`requires_confirmation`, `entities`) проходят через `_clean_actions()` в `ui/webpanel.py` —
он же используется и при записи `actions.json` из конфигов, и при PUT `/api/actions`.

Ещё три поля снимка: `runtime.voice_state` (состояние микрофона), `runtime.models_check`
(кэш явной проверки моделей, без хэширования на тике) и `runtime.doctor` (только короткое
саммари последнего запуска). Полный отчёт живёт в ответе `POST /api/doctor` и в SSE
`doctor`, в снимок не попадает.

`runtime.speaker` — состояние голосовых профилей: `enabled`, `profiles` (`id`, `label`),
`participants`, `current` (`id`, `label`, `status`, `score`), `last_event`, `policy`,
`model` (`ready`, `name`, `error`). Сюда никогда не попадают embedding'ы, пути к модели
и секреты. Четыре настройки — `speaker_verify`, `speaker_threshold`, `speaker_min_ms`,
`speaker_join_policy` — живут в секции `ears` и применяются без перезапуска; выключение
фичи очищает участников и кэш узнавания, но не удаляет профили. `speakers.json`
**не** входит в `CONFIG_FILES`: биометрию нельзя редактировать как обычный JSON через
панель.

Состояние микрофона включает `awaiting_followup` (владелец `conversation`): она ответила
и ждёт реплику без wake-word. Рядом лежат `runtime.conversation` (снимок
`{active, source, since, until, remaining, last_at, exchanges, timeout,
waiting_answer, reason, id}`) и `runtime.conversation_active`. Четыре настройки
автодиалога — `conversation_mode`, `conversation_timeout_s`,
`conversation_gap_reset_min`, `conversation_history_n` — живут в отдельной секции
`dialogue` на странице `settings` (`/#/settings`): тумблер и все параметры диалога
только там. Выключение режима или wake-word закрывает диалог сразу, а
`conversation_timeout_s` применяется на ходу. Живой индикатор находится на странице
`chat` (`/#/chat`), ещё один — на `dashboard` и `voice`. Отдельного
API-вызова или SSE-события для диалога нет: панель читает тот же снимок статуса,
что и GTK. История чата хранится как `{messages, rev, ops}`; `rev`
растёт на каждую операцию, SSE `chat` несёт `{rev, ops:[insert|update|remove|clear]}`,
а `pages/chat.js` применяет журнал по ревизиям и перезагружает всю историю при пропуске.

`WebBridge` (см. `yumi/ui/bridge.py`) — контракт между HTTP и приложением:
`snapshot, configs, config_get, config_save, actions_get, actions_save, action_run,
confirm_action, apply_settings, doctor, models_verify_cached, models_verify, models_record,
state_action, files_recent, files_shelf, shelf_change, files_open,
job_add, jobs_cancel, timer_get, timer, ask, chat, chat_history, chat_state, chat_ops,
chat_message_update, chat_message_remove, chat_clear,
voice_state, voice_pause, voice_resume, voice_release,
permission_answer, permissions_list, permissions_clear,
memory_recent, memory_search, memory_clear, notes_list, notes_search, notes_get,
notes_add, notes_update, notes_delete, notes_clear, music_status, music_search,
music_play, music_control, voice_listen(seconds, engine), voice_stop, voice_speak,
voice_engines, voice_mics, voice_test_wake(seconds, ear), voice_test(text, lang),
speaker_status, speaker_enroll, speaker_test, speaker_rename(id, label),
speaker_delete(id), speaker_clear_participants,
tools_*, logs`.

Проверки слуха и голоса (`voice_listen`, `voice_test_wake`, `/api/speaker/test`) на время
записи ставят фоновый wake-цикл на паузу и всегда возобновляют его. `wake_pause()` не
оставляет устаревший поток в `wake_thread`, а `wake_resume()` запускает свежий цикл даже
после медленного выхода старого (защита поколением в `senses.py`), поэтому имя «Юми»
продолжает будить после любого теста. `voice_test` синхронизирует профиль TTS с
`tts.json`, при необходимости перезапускает демон и проигрывает полученный WAV через
`SensesMixin.play_voice_file`. `/api/speaker/test` пишет аудит `speaker-test`.

---

## 4. Как добавить настройку

1. Добавить ключ в `config.DEFAULT_SETTINGS` (это единственный обязательный шаг).
2. При желании уточнить в `yumi/webpanel/catalog.py`:
   - `KEY_SECTION` — на какую страницу/секцию попадёт;
   - `TYPES` — `switch`, `select`, `range`, `number`, `text`, `password`, `path`, `list`;
   - `CHOICES` / `CHOICE_LABELS` — варианты списка;
   - `RANGES` — границы и шаг;
   - `SECRET_KEYS` — если значение нельзя отдавать в браузер;
   - `TITLES` / `HINTS` — подписи (ru/en).
3. Если ключ требует действия в живом приложении, добавить его обработку в
   `App._web_apply_settings` (`yumi/ui/webpanel.py`) и в `App.handle_requests`
   (`yumi/ui/app.py`) для изменений из GTK.
4. Прогнать `python3 tests/test_webpanel.py` — тест проверяет, что каждый ключ из
   `DEFAULT_SETTINGS` попал в схему.

Фронтенд сам рисует контрол по `type`; отдельный код страницы нужен только для
нестандартного поведения.

## 5. Как добавить страницу

1. Добавить запись в `catalog.PAGES` (id, icon, title, hint).
2. Создать `yumi/webui/static/js/pages/<id>.js` с `render(view, ctx)`.
3. Добавить ленивый импорт в объект `PAGES` в `app.js`.
4. Если странице нужен новый серверный вызов — добавить роут в `server.py` и метод
   `WebBridge`, затем тест.

---

## 6. Безопасность

- Слушает `127.0.0.1` по умолчанию. `0.0.0.0` — осознанное решение пользователя,
  подсказка в интерфейсе предупреждает про LAN и файрвол.
- Токен: 32 случайных байта, url-safe base64. Хранится в
  `~/.config/yumi/webpanel.json` вместе с секретом подписи; файл создаётся с `0600`.
- Сессия: cookie `yumi_web` = `<expiry>.<HMAC-SHA256>`, `HttpOnly`, `SameSite=Strict`,
  срок из `web_panel_session_hours` (по умолчанию 168 часов). Секрет подписи при
  ротации токена не меняется, поэтому открытая вкладка не выкидывается.
- CSRF: cookie `yumi_csrf` читается JS, значение обязано прийти в `X-Yumi-CSRF`.
  Сравнение — `hmac.compare_digest`.
- Проверка `Host` (защита от DNS rebinding) и `Origin` для всех мутаций.
- Лимит входа: 10 неудач с одного IP за 60 секунд → 429.
- Заголовки: `Content-Security-Policy` без внешних источников, `X-Frame-Options: DENY`,
  `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `Cache-Control: no-store`.
- Статика отдаётся через `_safe_join`; выход за пределы `yumi/webui` и спрайтов невозможен.
- Секреты (`polza_api_key`, пароли/ключ Jellyfin) маскируются в API и в редакторе конфигов.
- Превью и открытие файлов разрешены только для недавних, полки и собственных загрузок
  панели: подставленный в `?path=` посторонний путь получает 403.
- `webpanel.json` нельзя сохранить через API: токен меняется только на странице
  «Безопасность» (POST + CSRF).
- Разрешение «всегда» принимается только кликом и только для безопасной цели: голосом
  доступны «разово» и «запретить», а путь с ключом/паролем не запоминается вовсе. Отказ
  сильнее согласия, закрытие всплывашки — отказ. В снимок попадает только публичная часть
  вопроса, без action/слотов.
- Аудит: `~/.local/state/yumi/web-audit.log`, JSON-строки, все мутации и входы.
- Фронтенд нигде не вставляет HTML из данных: только `createElement`/`textContent`.

Остаточные риски, о которых стоит помнить:

- `/art/…` отдаётся без сессии (картинки не секретны, но это стоит знать).
- При `web_panel_host = 0.0.0.0` трафик идёт по HTTP без TLS. Для LAN это приемлемо
  только в доверенной сети; для интернета нужен reverse proxy с HTTPS.
- Токен в ссылке всё же попадает в историю браузера и может попасть в лог прокси.
  После входа его можно сменить на странице «Безопасность».

---

## 7. Данные, бэкапы, журналы

- Настройки: `~/.config/yumi/settings.json`. Сломанный JSON откладывается в
  `settings.json.bad` и не перезаписывается (как это уже делал `load_actions`).
- Доступ к панели: `~/.config/yumi/webpanel.json` (`0600`).
- Разрешения: `~/.config/yumi/permissions.json` — списки `allow` / `deny` для «всегда».
- Отпечатки моделей: `~/.config/yumi/model_hashes.json`, создаются только кнопкой
  «Запомнить хэши»; старые файлы без хэшей читаются как `unknown`.
- Бэкапы конфигов: `~/.config/yumi/backups/<name>-<timestamp>.json`, не больше 20 на файл.
- Состояние: `~/.local/state/yumi/state.json`.
- Чат панели: `~/.local/state/yumi/web-chat.json` (`0600`) — `{messages, rev, ops}`. Старые
  файлы-массивы читаются и получают id сообщений без потери истории.
- Дневник: `~/.local/state/yumi/yumi.db`.
- Аудит панели: `~/.local/state/yumi/web-audit.log`.
- Лог приложения: `~/.local/state/yumi/yumi.log`.

Запись конфига из панели всегда сначала делает бэкап, затем валидирует данные и лишь
потом сохраняет. Для `settings` дополнительно применяется `catalog.validate_settings_patch`.

---

## 8. Тесты и проверка

```bash
cd /home/nikolas/Projects/yumi

python3 tests/test_webpanel.py
python3 tests/test_doctor.py
python3 tests/test_models.py
python3 tests/test_permission.py
python3 tests/test_voice_state.py
python3 tests/test_config_backup.py
python3 tests/test_memory_jokes.py
python3 tests/test_chat.py
python3 tests/test_phrases.py
python3 tests/test_library.py
python3 tests/test_music_text.py
python3 tests/test_nlu.py
python3 tests/test_arbiter.py
python3 tests/test_tts.py
python3 tests/test_voice_intent.py

# или все standalone-скрипты сразу (старые тесты зовут sys.exit(0),
# поэтому pytest пока падает на этапе сбора — это не регрессия панели):
for f in tests/test_*.py; do python3 "$f" || echo "FAIL $f"; done

python3 -m py_compile yumi/webpanel/*.py yumi/ui/*.py yumi/config.py yumi/brain.py \
  yumi/doctor.py yumi/models.py yumi/permission.py yumi/voice_state.py \
  yumi/ears.py yumi/stt_daemon.py yumi/memory.py yumi/notes.py
for f in yumi/webui/static/js/*.js yumi/webui/static/js/pages/*.js; do
  node --input-type=module --check < "$f" || echo "FAIL $f"
done
bash -n bin/yumi
```

`tests/test_webpanel.py` поднимает настоящий сервер на свободном порту и проверяет:
покрытие схемы (14 страниц), вход по токену, cookie и CSRF, лимит попыток, logout,
PATCH настроек, ссылку и ротацию, статику и защиту от path traversal, а также новые
роуты диагностики, моделей, разрешений, состояния микрофона и журнала чата (включая
отказ без CSRF). Отдельные скрипты проверяют чистую логику без GTK: врача с моками
ушек/голоса, хэши моделей, правила разрешений, машину состояния микрофона и бэкап
сломанного `settings.json`.

Визуальная проверка без GTK: можно поднять `Panel` с заглушкой-мостом (см. пример в
истории работы) и обойти все `#/…` в браузере. При этом надо помнить, что заглушка
возвращает пустые списки, поэтому пустые состояния — нормальный результат.

---

## 9. Что осталось / идеи

- Проверить панель на живом GTK-запуске: вход, все страницы, drag-and-drop, голос,
  музыку и редактор конфигов. Заглушка этого не покрывает.
- Добавить в `tests/` тест на `/api/config/<name>` с реальным временным каталогом и
  бэкапами (сейчас покрыт только HTTP-слой).
- Экспорт/импорт настроек одним файлом (сейчас есть только JSON-редактор).
- Мобильная вёрстка проверена только по CSS (два breakpoint'а, выезжающий сайдбар);
  стоит посмотреть на реальном телефоне.
- При желании — HTTPS из коробки (поле `ssl` уже импортировано в `server.py` как задел).
- Оверлей входа локализуется до входа по `navigator.language` (русский/английский),
  а после входа язык берётся из `ui_lang` и переключается вживую вместе с оболочкой.
- Покрыть страницу «Журналы» живыми данными на демо-стенде (сейчас она пустая, потому
  что заглушка не отдаёт лог).

---

## 10. Статус

Готово и проверено: сервер, авторизация, CSRF, схема настроек, все 14 страниц
(включая «Заметки» с поиском и записью голосом и новую «Диагностику»),
пиксельная тема с двумя breakpoint'ами, живые события, бэкапы, аудит, флаги `--web` и
`--doctor`, интеграционные тесты. Добавлены: единый doctor,
явное состояние микрофона, ALLOW/ALWAYS/DENY с «отказ сильнее согласия», вердикт пробуждения,
проверка целостности моделей, журнал операций чата с ревизией и бэкап сломанного
`settings.json`. Дополнительно проверено в headless-Chromium: все страницы
отрисовываются без исключений и неудачных запросов, переключение языка перестраивает
оболочку и текущую страницу, PATCH настроек, чат, память и выдача ссылки работают.

Страница «Ушки и голос» получила три карточки выбора и живые проверки: активация
(openWakeWord/vosk), судья фраз (whisper/nemotron) и голос Silero с прослушиванием.
Подробности и оставшаяся живая приёмка — в `docs/handoff-voice-controls.md`.

Всё это лежит в репозитории. Перед передачей стоит прогнать тесты ещё раз и
посмотреть панель на живом GTK-запуске.
