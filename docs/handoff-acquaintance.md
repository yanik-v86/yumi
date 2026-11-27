# Handoff: команда знакомства и явная фиксация голоса

Статус: **MVP доработан: web UI polling + web_sync, guard конфликта с туром, автотесты добавлены; остаётся ручной smoke на реальном аудио**.  
Дата: 2026-11-22 (обновлено).  
Связанные документы: `docs/tasks-acquaintance.md`, `docs/handoff-speaker-dialogue.md`, `AGENTS.md`.

## 1. Зачем это нужно

В проекте уже была запись голосового профиля (`speaker_enroll`) через меню и веб-панель, но она выглядела как техническая кнопка «Записать голос». Пользователю нужен явный человеческий сценарий: «познакомиться», где Юми сама объясняет шаги, просит сказать фразу, записывает слепок и подтверждает результат.

Цель изменения: добавить команду знакомства, которая закрепляет голос (создаёт/обновляет voiceprint-профиль) и одинаково доступна из голосового управления, GTK и веб-панели.

## 2. Что уже было в кодовой базе

Существующий стек speaker/voice:

- `yumi/speaker.py` — хранилище профилей `speakers.json`, cosine verify/enroll/rename/delete.
- `yumi/speaker_sherpa.py` — embedding через sherpa-onnx 3D-Speaker / CAMPPlus.
- `yumi/stt_daemon.py` — `/speaker/status|enroll|test|rename|delete`, `speaker_record()`, запись и качество.
- `yumi/ears.py` — клиент к daemon speaker routes.
- `yumi/ui/senses.py` — GTK worker `speaker_action()` с паузой wake loop.
- `yumi/ui/bridge.py` — `speaker_status/enroll/test/rename/delete/clear_participants`.
- `yumi/webpanel/server.py` — `/api/speaker/*`.
- `yumi/webui/static/js/pages/voice.js` — кнопки записи/проверки/переименования/удаления.

Важно: ручной enroll в daemon работает даже при `speaker_verify=false`. Это сохранено.

## 3. Что реализовано

### 3.1 Голосовая команда

Файлы: `yumi/addressing.py` (канонический матчер), `yumi/brain.py` (тонкая обёртка)

- Добавлены `ACQUAINTANCE_PHRASES` и `acquaintance_command(text)`.
- Матчер вынесен в `addressing.py`: уши (fallback после wake), gate многоголосого диалога и `heard_text()` в мозгу принимают решение по одному и тому же списку фраз. `brain.acquaintance_command()` просто делегирует ему.
- `addressing.route()` возвращает `command` для «давай знакомиться/познакомимся/запомни мой голос», `addressing.addressee()` — `yumi`. Без этого wake-вход «юми давай знакомиться» попадал в `recogn.txt` (малое ухо слышало имя и фразу целиком), но `fallback_route()` называл хвост шумом и выбрасывал команду — «распознала, но не обработала». Guard тура «покажи знакомство» сохранён.
- `Brain.acquaintance_begin(again=False)`:
  - останавливает активное listen, если было;
  - закрывает меню/радиал;
  - если текущий говорящий уже известен (`_speaker_current.status == known`) — говорит `acquaintance_already` с именем и **останавливает знакомство**;
  - иначе произносит `acquaintance_intro` или `acquaintance_again`;
  - ставит запрос `('speaker_acquaintance', None)`.
- В `heard_text()` команда перехватывается до fallback/chat:

```py
if acquaintance_command(text) or (alt and alt != text and acquaintance_command(alt)):
    self.acquaintance_begin()
    return
```

Команда срабатывает на явные фразы, например «давай познакомимся», «запомни мой голос», "remember my voice", а также на безопасный паттерн «голос/voice + запомни/record/enroll/...».

Guard от конфликта с туром: «покажи/показать/открой знакомство» не запускает enrollment, если в фразе нет слов про голос/запись. Fallback по `познаком/acquaint` ограничен self-acquaintance/voice-контекстом.

### 3.2 GTK меню и запрос

Файлы: `yumi/brain.py`, `yumi/ui/app.py`

- В меню `set_ears` добавлен пункт `('acquaintance', None, t('acquaintance'))`.
- Действие `acquaintance` вызывает `self.acquaintance_begin()`.
- `App.handle_requests()` обрабатывает `speaker_acquaintance` через `self.speaker_action('speaker_acquaintance', ...)`.

### 3.3 Управляемая запись в Senses

Файл: `yumi/ui/senses.py`

- `speaker_action()` теперь принимает `speaker_acquaintance`.
- Добавлен `_wait_voice_quiet(timeout=8.0)`: ждёт, пока очередь TTS/blips не опустеет, чтобы запись не захватила голос Юми. Для знакомства таймаут 45 с; дополнительно учитываются одиночная реплика `speak()` (`voice_pending`, пока WAV синтезируется) и уже звучащий `voice_proc` — иначе микрофон открывался через 0.3 с после запроса и глотал подсказку «Назови своё имя…», из-за чего речь Юми «соскакивала». Обе проверки покрыты тестами в `tests/test_acquaintance.py`.
- Для `speaker_acquaintance` worker:
  1. ставит wake loop на паузу;
  2. выставляет фазу `waiting_tts` в `runtime.acquaintance` и публикует status;
  3. ждёт тишину TTS;
  4. перед записью выставляет `recording`, показывает bubble `Слушаю, говори...` / `Listening, speak now...` (`voice=False`) и face `listening`;
  5. вызывает `ears.speaker_enroll(secs=15, lang=speech_lang)` — запись ~15с, чтобы пользователь назвал имя, город, музыку, работу и хобби;
  6. после записи выставляет `processing`, показывает bubble `Запись закончена, обрабатываю...` (`voice=False`, face `think`);
  7. если слепок уже есть (`created == False`) — не извлекает данные, говорит `acquaintance_already` и останавливает знакомство;
  8. если новый слепок — извлекает из транскрипта `name/city/music/work/hobbies/about` через `chat.ask`, обновляет профиль через `ears.speaker_update`, ставит имя профиля;
  9. возобновляет wake, озвучивает результат, выставляет `done`/`error`.
- Результат:
  - новый профиль: `acquaintance_ok` с `{label}`;
  - слепок уже есть: `acquaintance_already` с `{label}`, знакомство останавливается;
  - нет модели: `acquaintance_nomodel`;
  - другая ошибка/плохая запись: `acquaintance_fail`.
- В конце `_speaker_action_done()` вызывается `self.web_sync_soon()`, чтобы веб-панель получила свежий status/speaker snapshot.

Это переиспользует существующий backend enroll, не дублируя хранение embedding.

### 3.4 Профиль пользователя (голос + данные)

Файлы: `yumi/speaker.py`, `yumi/stt_daemon.py`, `yumi/ears.py`, `yumi/ui/senses.py`, `yumi/ui/webpanel.py`

- Профиль голоса (`speakers.json`, schema v3) хранит несколько образцов `embeddings` и `info`: `name`, `city`, `music`, `work`, `hobbies`, `about` (без векторов в API). Файлы v1/v2 читаются без миграции.
- При знакомстве Юми просит назвать имя, город, музыку, работу и хобби; транскрипт берётся из записи enrollment, LLM (`chat.ask`) извлекает поля, профиль обновляется.
- Если голосовой слепок уже существует (dedup/`created == False` или текущий говорящий уже известен), Юми говорит `acquaintance_already` с именем и останавливает знакомство.
- Web snapshot/bridge отдают `profiles[].info`; страница «Ушки и голос» показывает данные выбранного профиля.
- Исправлен разрыв между daemon и модулем: `stt_daemon.py` вызывает `profiles.enroll(..., info=...)`, `profiles.profile()` и `profiles.update_info()`, но на уровне модуля `speaker.py` этих обёрток не было. Из-за `TypeError: enroll() got an unexpected keyword argument 'info'` `/speaker/enroll` падал с HTTP 500, а Юми говорила общее `acquaintance_fail` («не расслышала чистый голос») даже на тихой и хорошо распознаваемой записи. Обёртки добавлены, регрессия покрыта `tests/test_speaker.py`.

### 3.5 Веб-панель

Файлы: `yumi/ui/bridge.py`, `yumi/webpanel/server.py`, `yumi/webui/static/js/api.js`, `yumi/webui/static/js/pages/voice.js`

- Bridge: `speaker_acquaintance()` проверяет уже известного говорящего; если известен — возвращает `{ok, started:false, already:true, label}`. Иначе запускает `brain.acquaintance_begin()` и возвращает `{ok, started:true}`.
- Server: `POST /api/speaker/acquaintance` с CSRF+audit.
- API: `api.speakerAcquaintance()`.
- Voice page: кнопка «Познакомиться» / "Get acquainted" запускает guided flow, показывает подсказку и делает явный polling `ctx.refreshStatus()` ~20 секунд. UI читает `runtime.acquaintance.phase` и показывает сигналы: ожидание TTS, 🔴 запись, запись закончена/обработка, готово/ошибка.
- Snapshot: `runtime.acquaintance` содержит `{active, phase, action, at}`.

Важно: web endpoint асинхронный по смыслу. Он возвращает `started`, а не готовый профиль. Итог определяется polling'ом статуса и фазой `runtime.acquaintance`; для более чистого UX можно добавить отдельное SSE событие завершения.

### 3.6 Строки/тексты

Файл: `yumi/config.py`

Добавлены ключи UI:

- `acquaintance`
- `acquaintance_intro`
- `acquaintance_again`
- `acquaintance_ok`
- `acquaintance_fail`
- `acquaintance_nomodel`

RU/EN тексты подобраны так, чтобы Юми объясняла действие простыми словами.

### 3.7 Тесты

Файлы: `tests/test_webpanel.py`, `tests/test_acquaintance.py`

- Webpanel: stub bridge получил `speaker_acquaintance()`, тест проверяет CSRF, `{'ok': True, 'started': True}` и попадание в `speaker_calls`.
- `tests/test_acquaintance.py`:
  - `acquaintance_command()` — RU/EN положительные случаи;
  - `acquaintance_command()` — отклоняет «покажи знакомство»/tour/noise;
  - `Brain.heard_text()` — запускает знакомство по основной и alt-фразе;
  - `Brain.acquaintance_begin()` — ставит `speaker_acquaintance`;
  - mock GTK path — `SensesMixin.speaker_action('speaker_acquaintance')` ждёт TTS, вызывает `ears.speaker_enroll()`, делает `wake_resume`, говорит `acquaintance_ok`, вызывает `web_sync_soon()`.

### 3.8 Исправление «Голос 1» (после ручного smoke 2026-11-22)

Три независимые причины заставляли Юми называть пользователя «Голос 1» даже после clears всех профилей. Все устранены и покрыты регрессионными тестами.

1. **Wake-word сам создавал профиль до интервью.** `speaker_voice(..., wake=True)` автоматически регистрировал каждую адресованную фразу, в том числе саму команду «юми давай познакомимся». К моменту запуска интервью профиль `Голос 1` уже существовал, и `Brain.acquaintance_begin()` говорил «Мы уже знакомы, Голос 1». Добавлен `stt_daemon.wake_enrollment_allowed(text, alt)`, который подавляет авто-enroll, когда фраза (или её альтернативное чтение) — команда знакомства (`yumi/addressing.py`). Канонический детектор — `acquaintance_command()` в `addressing.py`; `brain.acquaintance_command()` просто делегирует ему.

2. **Сгенерированная метка принималась за имя.** `speaker.is_generic_label()` распознаёт плейсхолдеры `Голос 1`, `voice 2`, `spk_03`, пустую строку. `brain.named_voice_label()` возвращает '' для них. `acquaintance_begin()` больше не считает такой профиль «уже знакомым», а `_speaker_action_done()` не произносит плейсхолдер вслух: при dedup без имени Юми просит назвать имя, а не говорит «Тебя зовут Голос 1».

3. **Без API-ключа имя не извлекалось.** `_extract_acquaintance_info()` звал `chat.ask()`, который при выбранном провайдере без ключа сразу возвращает '' — профиль оставался без имени. Добавлен локальный fallback `senses.local_profile_fields()`: регулярки для «меня зовут …» / «my name is …» и «я живу в городе …» / «I live in …». Он используется, когда LLM вернул пустой ответ, и запрещает сохранять плейсхолдер как имя.

4. **Контракт daemon ↔ модуль.** Подробнее в §3.5: `stt_daemon.py` дёргал `profiles.enroll(..., info=...)`, `profiles.profile()`, `profiles.update_info()`, которых не было на уровне `speaker.py`. Из-за `TypeError`/`AttributeError` `/speaker/enroll` падал, и Юми говорила общее «не расслышала» даже на идеально чистой записи. Обёртки добавлены.

Тесты: `tests/test_addressing.py` (wake fallback + `wake_enrollment_allowed()`), `tests/test_acquaintance.py` (плейсхолдеры, dedup с обучением имени, локальное извлечение), `tests/test_speaker.py` (daemon API-обёртки и `is_generic_label()`).

### 3.9 Узнавание голоса на коротких wake-фразах (2026-11-22, вторая правка)

Ручной smoke выявил: Юми не узнавала голос на «юми привет» / «как меня зовут», хотя профиль «Николай» был записан. Три причины, все устранены:

1. **Причина: короткая лента.** `stt_daemon.py` брал для voiceprint `wake_pcm = utt.take()` — это хвост после имени, обычно 1–2 с. При `speaker_min_ms=3000` `quality()` возвращала False и embedding вообще не считался (`status='unknown'`). Теперь wake берёт 8-секундный кольцевой буфер `ring` (тот же, что идёт в STT); его длина не зависит от длины фразы, а `wake_pcm` остаётся только для распознавания слов. Строка `tape = bytes(ring[-RING_MAX:]) or wake_pcm` в `recorder.wake()`.

2. **Один вектор на профиль.** Реальный 3D-Speaker даёт для одного голоса cos 0.35–0.95 в зависимости от фразы. С одним `embedding` dedup=0.95 плодил профили (`Голос 2`, `Голос 4`, `Хуй`), а живая проверка с порогом 0.65 часто проваливалась. `speaker.py`: schema v3 (`SUPPORTED_SCHEMA = {1,2,3}`), в профиле `embeddings: [vec, ...]` (до `MAX_EMBEDDINGS=12`), `_best()` берёт максимум по всем образцам, `DEDUP_SCORE=0.75`, новое enroll при совпадении **добавляет** образец, а не перезаписывает. Старые файлы v1/v2 грузятся: `_vecs()` превращает одиночный `embedding` в список. `SpeakerStore.merge(ids, label)` (+ модульная обёртка `speaker.merge()`) склеивает уже существующие дубли, сохраняя все их образцы.

3. **Тест портил живой файл.** `tests/test_speaker.py::test_fake_backend` не задавал `YUMI_SPEAKER_FILE` и писал фейковый профиль в реальный `speakers.json`. Добавлен `monkeypatch.setenv('YUMI_SPEAKER_FILE', ...)`; хэш живого файла до/после `pytest tests/` теперь совпадает.

Проверено на реальном аудио из дневника ушек: фразы «юми привет», «юнг меня зовут», «юми как меня зовут», «меня зовут николай» дают `known spk_01` с score 0.84–0.94. Живые профили восстановлены из tap-записей и слиты в один «Николай» (`info: {name: Николай, city: Анапа}`); демон и приложение перезапущены после `./install.sh`.

### 3.10 Почти-совпадение на wake и «мы ещё не знакомы» (третья правка)

После предыдущей правки пользователь всё равно слышал «Мы ещё не знакомы» сразу после «Юми, как меня зовут». Причина: та самая живая фраза давала 0.67 против «Николай» (чуть ниже порога 0.65), wake её не узнавал и создавал новый профиль «Голос 3» через авто-enroll. `Brain._speaker_remember()` клал этот профиль в `_speaker_current`, `named_voice_label()` отвергала заглушку как имя, и ответ про имя честно говорил «не знакомы». Одновременно проверка на другой записи той же фразы давала 0.90 — отсюда расхождение между «тест зелёный» и «вживую не работает».

Исправлено:

- `speaker.py`: `SOFT_MATCH_SCORE = 0.55`, `SpeakerStore.closest()` (pid + сырой score без порога), `SpeakerStore.add_sample(pid, vec, ...)` и модульные обёртки. Wake-ветка `stt_daemon.speaker_voice()` при `unknown`, но score ≥ 0.55, добавляет чтение в ближайший существующий профиль и возвращает `known` с его id и настоящей меткой. Новый профиль создаётся только для действительно чужого голоса (< 0.55). Это останавливает расплод «Голос 2/3/4» и делает имя доступным для ответа.
- В `judge.log` пишется строка `VOICE <status> id=… score=… ms=… tape_s=…` на каждом wake — вердикт голоса больше не надо угадывать (только число, без вектора и аудио).
- Живые профили (`spk_01` + авто-enroll `spk_02`/`spk_03`) снова слиты в один «Николай», 7 образцов. Бэкап: `speakers.json.before-softmatch`.
- Тесты: `test_wake_near_miss_joins_existing_profile` (0.60 → тот же профиль, два образца, метка «Николай») и `test_wake_new_voice_still_gets_own_profile` (чужой голос → новый профиль).

Важно: daemon и GTK держат отдельные экземпляры `SpeakerStore`; после ручной правки `speakers.json` нужно `yumi --quit`, затем `./install.sh` и `yumi` — один перезапуск без установки оставляет старый код работающим.

## 4. Шаги и слова знакомства

### Целевой сценарий

1. **Запуск**: голосовая команда / меню / веб-кнопка.
2. **Приглашение**: Юми говорит `acquaintance_intro`.
3. **Тишина перед записью**: приложение ждёт окончания TTS.
4. **Запись слепка**: daemon записывает ~15с, проверяет качество, считает embedding.
5. **Сохранение**: `speaker.enroll(..., source='manual')` создаёт или обновляет профиль.
6. **Подтверждение**: Юми говорит `acquaintance_ok` с меткой профиля.
7. **Ошибка**: `acquaintance_nomodel` или `acquaintance_fail`.

### Рекомендуемые слова для пользователя

Можно говорить свободно, но лучше короткую естественную фразу 3–5 секунд:

- «Привет, Юми, я здесь. Давай работать вместе.»
- «Сегодня я знакомлюсь с тобой и записываю свой голос.»
- "Hi Yumi, this is my normal voice. Let's work together."

Советы по качеству слепка:

- говорить обычным голосом, не шёпотом и не криком;
- без музыки/ТВ на фоне;
- один человек в кадре микрофона;
- держать расстояние до микрофона как в обычном разговоре.

## 5. Контракты и ограничения

### API

| Метод | Путь | Назначение | Ответ |
|---|---|---|---|
| POST | `/api/speaker/acquaintance` | Запустить управляемое знакомство в GTK | `{ok: true, started: true}` |

Существующие endpoints `/api/speaker/enroll|test|rename|delete|clear` не меняли семантику.

### Приватность

- Embedding не возвращается в web API, не логируется, не пишется в config editor.
- `speakers.json` остаётся локальным файлом состояния, не входит в `catalog.CONFIG_FILES`.

### Совместимость

- Старое поведение enroll/test/rename/delete сохранено.
- Тур `tour_again` не переименован и не удалён.
- `speaker_verify=false` не блокирует явное знакомство.

## 6. Известные ограничения / следующий шаг

1. **Web итог всё ещё эвристический**. Endpoint возвращает `started`; UI делает polling status ~20с и читает `runtime.acquaintance.phase` (`waiting_tts/recording/processing/done/error`). Для более точного UX можно добавить отдельное SSE событие завершения.
2. **Нет серверной блокировки повторного запуска**. Пока идёт запись, повторный запуск на bridge/server не блокируется явно.
3. **Нет отдельной команды «познакомиться заново»**. Сейчас повторный запуск делает обычный enroll; можно добавить `again=True` и специальный текст.
4. **Ручной smoke на живом микрофоне не завершён**. Проверка по записанному аудио (§3.9) прошла; требуется подтверждение пользователя на живом микрофоне (см. чек-лист ниже).

## 7. Ручной smoke-чеклист (требует человека с микрофоном)

- [ ] **GTK/голос**: сказать «Юми, давай познакомимся» — Юми даёт подсказку, ждёт, записывает, произносит `acquaintance_ok`.
- [ ] **GTK меню**: «Ушки» → «Познакомиться» — тот же сценарий.
- [ ] **Web UI**: «Ушки и голос» → «Познакомиться» — кнопка показывает старт, затем итог после polling.
- [ ] **Шум/тихо/коротко**: нет падения, нет плохого профиля, Юми даёт понятный отказ.
- [ ] **Нет модели**: `acquaintance_nomodel`.
- [ ] **TTS overlap**: голос Юми не попадает в слепок.
- [ ] **Конфликт с туром**: «покажи знакомство» не запускает enrollment.

## 8. Файлы, затронутые реализацией

- `yumi/config.py` — строки знакомства.
- `yumi/phrases.py` — TTS фразы знакомства/уже знакомы.
- `yumi/brain.py` — детектор команды, guard конфликта с туром, `acquaintance_begin()` с проверкой уже известного голоса, меню, heard_text.
- `yumi/ui/app.py` — обработка `speaker_acquaintance` request.
- `yumi/ui/senses.py` — ожидание тишины TTS, запись 15с, извлечение профиля из транскрипта, update профиля, фазы, `web_sync_soon()`.
- `yumi/ui/bridge.py` — `speaker_acquaintance()` (already/started), профили с info.
- `yumi/ui/webpanel.py` — `runtime.acquaintance` и profile info в snapshot.
- `yumi/webpanel/server.py` — route/handler.
- `yumi/webui/static/js/api.js` — `speakerAcquaintance()`.
- `yumi/webui/static/js/pages/voice.js` — кнопка «Познакомиться», polling фаз, already, отображение info профиля.
- `yumi/speaker.py` — schema v3 (несколько `embeddings` на профиль, `_best()` по максимуму, `merge()`, `closest()`, `add_sample()`, `SOFT_MATCH_SCORE`), `info` профиля, `update_info/profile`.
- `yumi/stt_daemon.py` — `/speaker/enroll` принимает secs/lang/info, возвращает text/created/profile; `/speaker/update`; voiceprint на wake берётся из 8-секундного ring-буфера, подавление авто-enroll на командах знакомства, near-miss добавляется в существующий профиль, лог `VOICE` в judge.log.
- `yumi/ears.py` — `speaker_enroll`/`speaker_update` с параметрами.
- `tests/test_webpanel.py` — stub + route tests.
- `tests/test_acquaintance.py` — unit/mock tests.
- `tests/test_speaker.py` — мульти-образцы, `merge()`, near-miss/чужой голос на wake, старая схема, изоляция `YUMI_SPEAKER_FILE` в `test_fake_backend`.
- `README.md`, `README.ru.md` — краткое упоминание.
- `docs/tasks-acquaintance.md`, `docs/handoff-acquaintance.md` — этот комплект.

## 9. Команды проверки

```bash
python3 -m py_compile yumi/brain.py yumi/ui/app.py yumi/ui/senses.py yumi/ui/bridge.py yumi/webpanel/server.py tests/test_acquaintance.py
python3 -m pytest tests/test_acquaintance.py tests/test_webpanel.py -q
for f in yumi/webui/static/js/api.js yumi/webui/static/js/pages/voice.js; do
  node --input-type=module --check < "$f" || echo "FAIL $f"
done
```

Ручной smoke:

1. Сказать «Юми, давай познакомимся» — должна прозвучать подсказка, затем запись.
2. В меню ушек нажать «Познакомиться».
3. В веб-панели нажать «Познакомиться».
4. После успеха проверить «Проверить голос».
5. Проверить отказ: без модели / шум / слишком тихо.
