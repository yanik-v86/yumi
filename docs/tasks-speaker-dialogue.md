# Задачи: голосовые профили и диалог с несколькими участниками

Статус: **T-01–T-12 выполнены; T-13 не делался (P2, по решению владельца)**.  
Дата: 2026-11-22.  
Связанный документ: `docs/handoff-speaker-dialogue.md` (архитектура, контракты, риски).  
Правило проекта: см. `AGENTS.md` — каждая возможность должна работать **и в GTK, и в веб-панели**.

## Решения владельца (зафиксированы)

1. Слепок снимается **автоматически** при wake-word; ручная перезапись/добавление — кнопкой в GTK и панели.
2. Профилей **несколько**, у каждого своя метка (`Голос 1`, переименовывается).
3. В активный диалог может **вклиниться другой пользователь без имени**: обращённая реплика неизвестного голоса создаёт новый профиль и добавляет участника.
4. Отвечать **только на обращённые реплики**: разговор участников между собой не должен вызывать ответ Юми.
5. Модель — **sherpa-onnx / 3D-Speaker** в уже существующем venv из `tools/nemotron_setup.sh`.

## Легенда

- Приоритет: P0 — блокирующий, P1 — важный, P2 — улучшение.
- Статус: `DONE` у T-01–T-12, `SKIPPED` у T-13; commit-id указан в строке задачи.
- Зависимости указаны в поле `Зависит от`.
- ID задач используются в коммитах: `feat(speaker-dialogue): T-01 ...`.

---

## Фаза 1 — чистое ядро без UI и без микрофона

### T-01. Хранилище голосовых профилей (P0)

**Статус:** DONE — commit `b92c82b`.  
**Зависит от:** —  
**Файлы:** `yumi/speaker.py` (новый), `tests/test_speaker.py` (новый).

**Что сделать:**
- Профиль: `{id, label, embedding: list[float], created_at, updated_at, source: 'wake'|'join'|'manual'}`.
- Файл `STATE_DIR / 'speakers.json'`, версия схемы `1`, атомарная запись (по образцу `config.save_settings()`). Путь переопределяется env `YUMI_SPEAKER_FILE` для тестов.
- API без GTK: `load()`, `save()`, `enroll(embedding, label=None, source=...) -> id`, `verify(embedding, threshold) -> {'status': 'known'|'unknown'|'disabled', 'id', 'score'}`, `list()`, `rename(id, label)`, `delete(id)`, `snapshot()`.
- Косинусная близость, `numpy` только как опция; при отсутствии `numpy` — чистый Python. Сырые векторы **не** попадают в логи и API.
- `speaker.py` не импортирует `brain`, `ui`, `webpanel`.

**Критерии приёмки:**
- save→load→verify→rename→delete работает на временном `YUMI_SPEAKER_FILE`.
- Повторный enroll того же голоса обновляет профиль, а не создаёт дубликат (решение: по id или по score ≥ `0.95`).
- Битые/пустые файлы не ломают запуск: пустой список профилей + диагностика.
- Тесты не трогают домашний каталог.

---

### T-02. Адаптер sherpa-onnx / 3D-Speaker (P0)

**Статус:** DONE — commit `b92c82b`; smoke с реальной моделью пройден отдельно.  
**Зависит от:** T-01  
**Файлы:** `yumi/speaker_sherpa.py` (новый), `tools/speaker_setup.sh` (новый) или дополнение к `tools/nemotron_setup.sh`, `tests/test_speaker.py`.

**Что сделать:**
- Обёртка над `sherpa_onnx.SpeakerEmbeddingExtractor` из venv `~/.local/share/yumi/stt`: `available()`, `embedding(pcm_s16le_16k) -> list[float] | None`, `model_info()`.
- Модель 3D-Speaker зафиксировать в `tools/speaker_setup.sh` (имя + контрольная сумма), путь переопределяется `YUMI_SPEAKER_MODEL`.
- Если модель/venv недоступны — `available() == False`, фича мягко выключается, старый путь wake/listen работает как раньше.
- Минимальная длина чистого голоса — `speaker_min_ms`; короткие/шумевые окна возвращают `None`.

**Критерии приёмки:**
- Есть тест с поддельным бэкендом (без загрузки модели) и smoke-проверка с реальной моделью на 2–3 WAV из `dataset/`.
- Один и тот же файл даёт score выше порога, другой голос — ниже.
- Отсутствие модели не вызывает исключений в демоне.

---

### T-03. Определение адресата: `addressee()` (P0)

**Статус:** DONE — commit `b92c82b`.  
**Зависит от:** —  
**Файлы:** `yumi/addressing.py`, `tests/test_addressing.py`.

**Что сделать:**
- Добавить `addressee(text, labels=()) -> 'yumi'|'other'|'unclear'`, не ломая `route()`.
- Признаки «обращено к Юми»: вопросительное слово в первых 2 токенах, второе лицо, приветствие/вежливое слово, «я хочу / мне скучно», императив, явное имя wake-word, `?` — только в сочетании с хотя бы одним другим признаком (сейчас `route()` считает `chat` любую фразу со `?`, из-за чего «Борис, где ключи?» станет обращением).
- Признак «не ей»: фраза начинается с имени/метки другого участника или с «Анна, …» / «Борис, …» (имена подставляются через `labels`).
- `route()` оставить совместимым; при желании добавить `route_strict()`, который использует `addressee()`.

**Критерии приёмки:**
- «как дела?», «включи музыку», «ты можешь?», «Юми, привет» → `yumi`.
- «Борис, где ключи?», «он сказал, что придёт» → `other`/`unclear`.
- Существующие `tests/test_addressing.py` зелёные без изменения ожиданий.

---

## Фаза 2 — демон ушей (сырой PCM)

### T-04. Speaker-метаданные в `/wake` и `/listen` (P0)

**Статус:** DONE — commit `e0530ed`.  
**Зависит от:** T-01, T-02  
**Файлы:** `yumi/stt_daemon.py` (`Ears.listen()` `:1568-1575`, `read_and_confirm()` `:1784-1797`, `wake_result()` `:1662-1683`, роуты `:2416-2471`), `yumi/ears.py:215-283`, `tests/test_wake.py`.

**Что сделать:**
- В `Ears.listen()` считать embedding из того жеPCM, который ушёл в STT; вернуть `speaker: {status, id, score, quality, ms}`.
- В `/wake` — embedding из `ring` + `wake_result()` (голос сказал имя); вернуть то же поле.
- Старые клиенты игнорируют новое поле; при выключенной фиче поле может отсутствовать.
- Сырой embedding по HTTP не передавать.

**Критерии приёмки:**
- `/listen` и `/wake` отвечают по-старому при выключенной настройке и с новым полем при включённой.
- `yumi/ears.py` пробрасывает `speaker` и не падает, если демона старой версии.
- `python3 -m py_compile yumi/stt_daemon.py yumi/ears.py`.

---

### T-05. Авто-enroll по wake-word и join-режим follow-up (P0)

**Статус:** DONE — commit `e0530ed`.  
**Зависит от:** T-02, T-03, T-04  
**Файлы:** `yumi/stt_daemon.py`, `yumi/speaker.py`, `tests/test_wake.py`, новый `tests/test_speaker.py`.

**Что сделать:**
- При успешном `/wake`: если профилей нет или голос неизвестен — `speaker.enroll(..., source='wake')`, вернуть `speaker.joined_id`. При известном голосе — только `verify`.
- В `/listen` добавить параметр `join=1|0` (follow-up шлёт его, когда `speaker_join_policy != 'off'`). При `join=1`, `speaker.status == 'unknown'`, длине чистого голоса ≥ `speaker_min_ms` и тексте не `ignore` — создать профиль `source='join'` и вернуть `speaker.joined_id`.
- Ограничение: enroll только по одному доминирующему голосу; при перекрытии двух голосов — `quality=False`, участник не добавляется.

**Критерии приёмки:**
- Первый wake создаёт профиль; повторный тем же голосом не создаёт второй.
- Неизвестная обращённая реплика в `join=1` создаёт профиль; фоновая речь (`route == 'ignore'`) — нет.
- Короткая реплика (< `speaker_min_ms`) не создаёт профиль.

---

### T-06. Роуты управления профилями в демоне (P1)

**Статус:** DONE — commit `e0530ed`.  
**Зависит от:** T-01, T-04  
**Файлы:** `yumi/stt_daemon.py`, `yumi/ears.py`, `tests/test_webpanel.py` (только контракт/статус).

**Что сделать:**
- Локальные роуты (только `127.0.0.1`, как остальные): `GET /speaker/status`, `POST /speaker/enroll` (записать 3–5 с), `POST /speaker/test`, `POST /speaker/rename`, `POST /speaker/delete`.
- `status` отдаёт `{profiles: [{id, label}], model: {ready, error}}` — без векторов.
- `enroll` использует тот же путь записи, что и `listen`, и `ears.unmute()` до вызова — конфликта за микрофон быть не должно (вызов только через `_ears_exclusive()` на стороне панели).

**Критерии приёмки:**
- Вызовы работают при включённой фиче и вежливо отвечают `{'ok': False, 'error': ...}` при отсутствии модели.
- В логах демона нет embedding'ов.

---

## Фаза 3 — приложение: состояние и гейт

### T-07. Участники беседы в `Conversation` (P0)

**Статус:** DONE — commit `019aa59`.  
**Зависит от:** T-03  
**Файлы:** `yumi/conversation.py`, `tests/test_conversation_mode.py`.

**Что сделать:**
- Поля `participants: set[str]`, `last_speaker: str|None`, `last_route: str`, `join_events: int`.
- Методы `add_participant(id)`, `remove_participant(id)`, `participant_seen(id)`, `clear_participants()`; `close()` сбрасывает участников, `id` инкрементится как раньше.
- `snapshot()` публикует `participants` (список id), `last_speaker`, `last_route`.
- Никаких изменений таймеров/окна — `hold()`, `due()`, `wait_start()`, `stale()` остаются как есть.

**Критерии приёмки:**
- Участники живут только внутри окна диалога и сбрасываются при `close()`/таймауте.
- `tests/test_conversation_mode.py` зелёный.

---

### T-08. Гейт в `Brain.heard_text()` и подпись реплик (P0)

**Статус:** DONE — commit `019aa59`.  
**Зависит от:** T-03, T-04, T-05, T-07  
**Файлы:** `yumi/brain.py:1336-1478`, `yumi/ui/senses.py:236-274`, `tests/test_speaker_gate.py` (новый).

**Что сделать:**
- `heard_text(..., speaker=None, join=False)`; в `senses.followup_listen()` передавать `speaker=res.get('speaker')` и `join=1` в `ears.listen()`.
- Порядок гейта: `stop_command` → всегда; фича выключена или старый демон без `speaker` → старое поведение; `addressee() == 'other'` или `route() == 'ignore'` → игнорировать; `known` + id в `participants` → в чат; `unknown` + `join` + адресация → `add_participant(joined_id)` + в чат + один раз подсказка.
- `speaker_id`/метку добавлять в `chat_history` (поле `speaker` или префикс «Голос 2: …» в `content`), чтобы LLM различал участников. Не ломать `memory.recall()`.
- Подсказка о новом участнике — через существующие `phrases`/`say`, ru/en.

**Критерии приёмки:**
- Сценарный тест: стоп от любого голоса проходит; «Борис, где ключи?» не вызывает ответ; чужой голос без адресации не вызывает ответ; обращённый чужой голос добавляется в участники; двое участников по очереди ведут диалог без wake-word.
- При `speaker_verify=False` поведение совпадает с текущим.
- Собственный TTS не создаёт участника (self-mute/`talking()` как раньше).

---

## Фаза 4 — настройки, GTK и веб-панель

### T-09. Настройки и живое применение (P0)

**Статус:** DONE — commit `08043ab`.  
**Зависит от:** T-01  
**Файлы:** `yumi/config.py` (`DEFAULT_SETTINGS`, `UI`), `yumi/webpanel/catalog.py`, `yumi/ui/webpanel.py` (`_web_apply_settings`, `_web_snapshot`), `tests/test_webpanel.py`.

**Что сделать:**
- Ключи: `speaker_verify=False`, `speaker_threshold=0.65`, `speaker_min_ms=1200`, `speaker_join_policy='addressed'` (`addressed|strict|off`).
- В `catalog.py`: `KEY_SECTION` → `ears` или `dialogue`, `TYPES`, `CHOICES`, `RANGES`, `TITLES`, `HINTS` ru/en.
- `_web_apply_settings`: выключение сбрасывает `participants` и кэш verify (профили **не** удаляет); изменение порога/политики применяется сразу.
- `_web_snapshot`: `runtime.speaker` (см. handoff §3.4), без embedding'ов.
- **Не** добавлять `speakers.json` в `catalog.CONFIG_FILES` — биометрию нельзя редактировать как обычный JSON через панель.

**Критерии приёмки:**
- `python3 tests/test_webpanel.py` зелёный: все ключи `DEFAULT_SETTINGS` попали в схему.
- PATCH `speaker_verify` меняет поведение без перезапуска; статус в `/api/status` обновляется.

---

### T-10. WebBridge, роуты и страницы панели (P0)

**Статус:** DONE — commit `08043ab`.  
**Зависит от:** T-06, T-09  
**Файлы:** `yumi/ui/bridge.py`, `yumi/webpanel/server.py`, `yumi/webui/static/js/api.js`, `pages/voice.js`, `pages/chat.js`, `tests/test_webpanel.py`.

**Что сделать:**
- `WebBridge`: `speaker_status()`, `speaker_enroll()`, `speaker_test()`, `speaker_rename(id,label)`, `speaker_delete(id)`, `speaker_clear_participants()`. Микрофон — через `_ears_exclusive()`, всё через `App._web_call` → `GLib.idle_add`.
- Роуты: `GET /api/speaker`, `POST /api/speaker/enroll|test|rename|delete|clear`. CSRF на всех POST, аудит без векторов.
- `api.js`: методы `speakerGet/Enroll/Test/Rename/Delete/Clear`.
- `pages/voice.js`: список профилей, «Записать голос», «Проверить», «Переименовать», «Удалить», текущий говорящий и его score.
- `pages/chat.js`: индикатор «участники беседы» рядом с карточкой Hands-free talk; обновление из `runtime.speaker`.
- Только `createElement`/`textContent`, никакого `innerHTML` с данными.

**Критерии приёмки:**
- Авторизованный GET/POST работают; без CSRF → 403.
- Панель показывает список профилей, текущего говорящего и участников; `node --input-type=module --check` проходит.

---

### T-11. GTK-эквивалент (P0)

**Статус:** DONE — commit `08043ab`.  
**Зависит от:** T-08, T-09  
**Файлы:** `yumi/brain.py` (меню слуха), `yumi/config.py` (строки UI), при нужде новый `yumi/ui/speaker_dialog.py`.

**Что сделать:**
- Пункты меню рядом с «Слух»: «Записать голос», «Проверить голос», «Список голосов» (переименовать/удалить), «Очистить участников беседы».
- Вызовы идут в те же методы приложения, что и панель (общее состояние), без прямой работы с микрофоном из GTK-потока.

**Критерии приёмки:**
- Из GTK можно записать/переименовать/удалить профиль и увидеть того же участника в панели.
- Все новые строки ru/en.

---

## Фаза 5 — завершение

### T-12. Тесты, smoke, документация (P0)

**Статус:** DONE — commit `cb1fb82`.  
**Зависит от:** T-01..T-11  
**Файлы:** `tests/test_speaker.py`, `tests/test_speaker_gate.py`, `tests/test_conversation_mode.py`, `tests/test_addressing.py`, `tests/test_webpanel.py`, `README.ru.md`, `README.md`, `docs/handoff-web-panel.md`, `docs/handoff-speaker-dialogue.md`, этот файл.

**Что сделать:**
- Обновить статусы задач и оставить commit-id в строках.
- Добавить в README: как включать, как записать голос, как вклиниться в беседу, что биометрия хранится локально.
- В `docs/handoff-web-panel.md` — новые роуты и поля статуса.
- Прогнать все проверки:

```bash
python3 tests/test_webpanel.py
pytest tests/ -q
python3 -m py_compile yumi/config.py yumi/brain.py yumi/conversation.py \
  yumi/addressing.py yumi/speaker.py yumi/speaker_sherpa.py \
  yumi/stt_daemon.py yumi/ears.py yumi/ui/*.py yumi/webpanel/*.py
for f in yumi/webui/static/js/*.js yumi/webui/static/js/pages/*.js; do
  node --input-type=module --check < "$f" || echo "FAIL $f"
done
```

- Ручная проверка с двумя людьми и микрофоном по сценариям из handoff §9.

**Критерии приёмки:**
- Все проверки зелёные; сценарии «два участника + чужой голос + стоп» проходят вручную.

---

### T-13 (P2, опционально). Улучшение адресации (P2)

**Статус:** SKIPPED — не входит в обязательный DoD, реализовывать по отдельному решению.  
**Зависит от:** T-08  
**Файлы:** `yumi/addressing.py`, `yumi/chat.py`, `tests/test_addressing.py`.

**Что сделать:**
- Подсказки в system prompt: кто именно из участников говорит сейчас.
- Лёгкий confidence score адресации (правила + LLM-проверка только при неоднозначности), чтобы не отвечать на реплики «Анна → Борис».

**Критерии приёмки:**
- Ложные ответы на реплики между участниками снижаются без роста задержки типичного ответа.

---

## Итоговый Definition of Done

- [x] T-01 — T-12 выполнены (T-13 пропущен как опциональный P2).
- [x] Юми сама снимает слепок по wake-word, профилей несколько, есть ручная запись и перезапись.
- [x] Новый человек может вклиниться обращённой репликой без имени и стать участником беседы.
- [x] Юми не отвечает на разговор участников между собой и на фоновую речь.
- [x] Стоп-слова работают независимо от голоса.
- [x] Всё доступно из GTK **и** из веб-панели; статус/настройки/роуты/тесты на месте.
- [x] Сырые embedding'ы не утекают в API, панель, логи или редактор конфигов.
- [x] README (ru/en) и handoff обновлены; `python3 -m pytest tests/ -q` →
  `18 passed, 1 skipped`, `python3 tests/test_webpanel.py` → `ok`, py_compile и
  JS syntax check без ошибок. Smoke с реальной моделью 3D-Speaker пройден отдельно.

## Порядок передачи между агентами

1. Агент A: T-01 → T-02 → T-03 (ядро, модель, адресация). Отчитаться `pytest tests/test_speaker.py tests/test_addressing.py`.
2. Агент B: T-04 → T-05 → T-06 (демон). Проверить `/wake`, `/listen`, `/speaker/*`.
3. Агент C: T-07 → T-08 (состояние и гейт). Проверить `tests/test_speaker_gate.py`, `tests/test_conversation_mode.py`.
4. Агент D: T-09 → T-10 (настройки + панель). Проверить `tests/test_webpanel.py` и JS syntax check. Можно параллельно с агентом E после T-08.
5. Агент E: T-11 (GTK) после T-08/T-09.
6. Агент F: T-12 (финальные тесты/доки) после всех.

При передаче всегда обновляйте статусы задач в этом файле и оставляйте commit-ид в строке задачи.
