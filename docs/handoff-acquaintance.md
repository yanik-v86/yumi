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

Файл: `yumi/brain.py`

- Добавлены `ACQUAINTANCE_PHRASES` и `acquaintance_command(text)`.
- `Brain.acquaintance_begin(again=False)`:
  - останавливает активное listen, если было;
  - закрывает меню/радиал;
  - произносит `acquaintance_intro` или `acquaintance_again`;
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
- Добавлен `_wait_voice_quiet(timeout=8.0)`: ждёт, пока очередь TTS/blips не опустеет, чтобы запись не захватила голос Юми.
- Для `speaker_acquaintance` worker:
  1. ставит wake loop на паузу;
  2. выставляет фазу `waiting_tts` в `runtime.acquaintance` и публикует status;
  3. ждёт тишину TTS;
  4. перед записью выставляет `recording`, показывает bubble `Слушаю, говори...` / `Listening, speak now...` (`voice=False`) и face `listening`;
  5. вызывает `ears.speaker_enroll()`;
  6. после записи выставляет `processing`, показывает bubble `Запись закончена, обрабатываю...` (`voice=False`, face `think`);
  7. возобновляет wake, озвучивает результат, выставляет `done`/`error`.
- Результат:
  - успех: `acquaintance_ok` с `{label}`;
  - нет модели: `acquaintance_nomodel`;
  - другая ошибка/плохая запись: `acquaintance_fail`.
- В конце `_speaker_action_done()` вызывается `self.web_sync_soon()`, чтобы веб-панель получила свежий status/speaker snapshot.

Это переиспользует существующий backend enroll, не дублируя хранение embedding.

### 3.4 Веб-панель

Файлы: `yumi/ui/bridge.py`, `yumi/webpanel/server.py`, `yumi/webui/static/js/api.js`, `yumi/webui/static/js/pages/voice.js`

- Bridge: `speaker_acquaintance()` вызывает GTK `app.speaker_action('speaker_acquaintance')` и возвращает `{ok: True, started: True}`.
- Server: `POST /api/speaker/acquaintance` с CSRF+audit.
- API: `api.speakerAcquaintance()`.
- Voice page: кнопка «Познакомиться» / "Get acquainted" запускает guided flow, показывает подсказку и делает явный polling `ctx.refreshStatus()` ~20 секунд. UI читает `runtime.acquaintance.phase` и показывает сигналы: ожидание TTS, 🔴 запись, запись закончена/обработка, готово/ошибка.
- Snapshot: `runtime.acquaintance` содержит `{active, phase, action, at}`.

Важно: web endpoint асинхронный по смыслу. Он возвращает `started`, а не готовый профиль. Итог определяется polling'ом статуса и фазой `runtime.acquaintance`; для более чистого UX можно добавить отдельное SSE событие завершения.

### 3.5 Строки/тексты

Файл: `yumi/config.py`

Добавлены ключи UI:

- `acquaintance`
- `acquaintance_intro`
- `acquaintance_again`
- `acquaintance_ok`
- `acquaintance_fail`
- `acquaintance_nomodel`

RU/EN тексты подобраны так, чтобы Юми объясняла действие простыми словами.

### 3.6 Тесты

Файлы: `tests/test_webpanel.py`, `tests/test_acquaintance.py`

- Webpanel: stub bridge получил `speaker_acquaintance()`, тест проверяет CSRF, `{'ok': True, 'started': True}` и попадание в `speaker_calls`.
- `tests/test_acquaintance.py`:
  - `acquaintance_command()` — RU/EN положительные случаи;
  - `acquaintance_command()` — отклоняет «покажи знакомство»/tour/noise;
  - `Brain.heard_text()` — запускает знакомство по основной и alt-фразе;
  - `Brain.acquaintance_begin()` — ставит `speaker_acquaintance`;
  - mock GTK path — `SensesMixin.speaker_action('speaker_acquaintance')` ждёт TTS, вызывает `ears.speaker_enroll()`, делает `wake_resume`, говорит `acquaintance_ok`, вызывает `web_sync_soon()`.

## 4. Шаги и слова знакомства

### Целевой сценарий

1. **Запуск**: голосовая команда / меню / веб-кнопка.
2. **Приглашение**: Юми говорит `acquaintance_intro`.
3. **Тишина перед записью**: приложение ждёт окончания TTS.
4. **Запись слепка**: daemon записывает ~4с, проверяет качество, считает embedding.
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
4. **Ручной smoke не выполнен**. Нужна проверка на реальном микрофоне (см. чек-лист ниже).

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
- `yumi/brain.py` — детектор команды, guard конфликта с туром, `acquaintance_begin()`, меню, heard_text.
- `yumi/ui/app.py` — обработка `speaker_acquaintance` request.
- `yumi/ui/senses.py` — ожидание тишины TTS, guided enroll, сообщения результата, `web_sync_soon()`.
- `yumi/ui/bridge.py` — `speaker_acquaintance()`.
- `yumi/webpanel/server.py` — route/handler.
- `yumi/webui/static/js/api.js` — `speakerAcquaintance()`.
- `yumi/webui/static/js/pages/voice.js` — кнопка «Познакомиться» + polling итога.
- `tests/test_webpanel.py` — stub + route tests.
- `tests/test_acquaintance.py` — unit/mock tests.
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
