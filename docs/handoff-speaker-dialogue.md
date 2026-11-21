# Handoff: голосовые профили и диалог с несколькими участниками

Статус: **проект/передаточный документ, реализация не начата**.  
Дата: 2026-11-21.  
Аудитория: агент, который будет реализовывать фичу, и ревьюер.  
Список задач: `docs/tasks-speaker-dialogue.md`.  
Обязательно к прочтению: `AGENTS.md`, `docs/handoff-conversation-mode.md`, `docs/handoff-web-panel.md`.

## 1. Что нужно сделать

Сейчас голосовой диалог Юми («conversation mode») умеет слушать продолжение
без wake-word, но **не различает, кто говорит**. В активном окне любая распознанная
фраза уходит в мозг:

- `yumi/ui/senses.py:236-274` — `followup_listen()` после `ears.listen()` вызывает
  `br.heard_text(t, wake=True, alt=v, followup=True)`;
- `yumi/brain.py:1336` — `heard_text()` не имеет информации о говорящем;
- `yumi/conversation.py:21-32` — есть `active/id/until/waiting_answer`, но нет участников.

Из-за этого в беседу попадают телевизор, разговор в комнате, второй человек — и Юми отвечает
на всё подряд. Нужно добавить **голосовые профили (embedding) и гейт по говорящему**,
при этом сохранить возможность «вклиниться» в идущий диалог без имени.

### Решения владельца

| Вопрос | Решение |
|---|---|
| Первый слепок | автоматически по wake-word + ручная запись/перезапись в GTK и панели |
| Профилей | несколько, с метками (`Голос 1`, переименование) |
| Вход нового человека | любая **обращённая** реплика без имени создаёт профиль и добавляет участника |
| Разговор участников между собой | не должен вызывать ответ Юми |
| Модель | sherpa-onnx / 3D-Speaker, уже стоящий venv `~/.local/share/yumi/stt` |

Термины:

- **профиль** — постоянная запись с embedding'ом в `speakers.json`;
- **участник** — id профиля внутри текущего окна `Conversation`;
- **слепок/embedding** — вектор чисел, **не** аудиозапись и не секрет для UI;
- **адресация** — решение, обращена ли реплика к Юми, а не к другому человеку.

---

## 2. Текущая архитектура (где что искать)

### Слух и диалог

- `yumi/ui/senses.py:357-380` — wake-цикл; в активном диалоге вместо `/wake` вызывает
  `followup_listen()`, что исключает гонку двух слушателей за один микрофон.
- `yumi/ui/senses.py:236-274` — follow-up listen; сейчас это **точка утечки** любой речи в мозг.
- `yumi/stt_daemon.py`:
  - `:1597-1722` — `Ears.wake()`, кольцевой буфер `ring` (`:1632-1635`), имя из OWW
    (`:2052-2072`), `wake_result()` (`:1662-1683`);
  - `:1496-1595` — `Ears.listen()`, возвращает `{'text', 'vosk'}` (`:1575`);
  - `:1784-1827` — `read_and_confirm()` собираетPCM фразы для STT;
  - `:2416-2471` — роуты `/wake` и `/listen`; `:63-64` уже добавляет корень репозитория
    в `sys.path`, `:1042` импортирует `yumi.addressing` — значит чистые модули можно
    импортировать и в демоне.
- `yumi/ears.py:215-283` — клиент демона; контракты `listen()` и `wake()`.
- `yumi/conversation.py:13-134` —纯粹ная логика окна диалога, `id` для отмены устаревших
  callback'ов, `hold/due/wait_start/stale`, `snapshot()`.
- `yumi/brain.py:1247-1281`, `:1336-1478`, `:1908` — открытие/продление/закрытие диалога,
  маршрутизация услышанного текста, вызов чата.
- `yumi/addressing.py:184-196` — `route(text, hints)` → `command|chat|ignore`.
  **Важно:** сейчас любая фраза со знаком `?` считается `chat`, поэтому
  «Борис, где ключи?» ошибочно станет обращением. Это нужно исправить через новый
  `addressee()`, не ломая `route()`.
- `yumi/voice_state.py`, `yumi/ui/app.py:367-390` (`_conversation_tick()`) — владелец
  микрофона и прерывание зависшего `/wake`.

### Панель и конфиг

- `yumi/config.py:20-139` — `DEFAULT_SETTINGS`; новый ключ автоматически появляется в схеме.
- `yumi/webpanel/catalog.py:95-126, 185-215, 217-377` — `KEY_SECTION`, `TYPES`, `RANGES`,
  `TITLES`, `HINTS`; `:379-394` — `CONFIG_FILES`.
- `yumi/ui/webpanel.py:291-395` — `_web_snapshot()`; `:397-442` — `_web_apply_settings()`.
- `yumi/ui/bridge.py:17-18, 432-441` — `_on()` → `App._web_call`, `_ears_exclusive()` —
  единственный безопасный способ забрать микрофон из панели.
- `yumi/webpanel/server.py:412-422, 888-949` — роуты и обработчики, CSRF/аудит.
- `yumi/webui/static/js/api.js`, `pages/voice.js:253-295`, `pages/chat.js:38-64`.
- `tests/test_webpanel.py:300-334, 403-406, 454-518` — схема, статус, голосовые вызовы.

**Запрещено:** добавлять `speakers.json` в `catalog.CONFIG_FILES`, логировать embedding'ы,
отдавать сырые векторы через HTTP или показывать их в панели.

---

## 3. Контракты

### 3.1 Хранилище `speakers.json`

Путь: `config.STATE_DIR / 'speakers.json'`, env `YUMI_SPEAKER_FILE` для тестов.

```json
{
  "version": 1,
  "profiles": [
    {
      "id": "spk_01",
      "label": "Голос 1",
      "embedding": [0.0123, -0.0456],
      "created_at": "2026-11-21T12:00:00Z",
      "updated_at": "2026-11-21T12:00:00Z",
      "source": "wake"
    }
  ]
}
```

`source`: `wake` | `join` | `manual`. Запись атомарная. При битом файле — пустой список
профилей и diag-сообщение, не падение.

### 3.2 Поле `speaker` в `/wake` и `/listen`

```json
"speaker": {
  "status": "known | unknown | disabled",
  "id": "spk_01",
  "score": 0.81,
  "quality": true,
  "ms": 1800,
  "joined_id": null
}
```

- `status='disabled'` — модель/настройка выключены; поле может отсутствовать в старом демоне.
- `quality` — хватает ли чистого голоса (длина ≥ `speaker_min_ms`, один говорящий).
- `joined_id` — заполняется только когда профиль только что создан (`wake`/`join`).
- Сырой embedding **никогда** не передаётся.

`yumi/ears.py` пробрасывает поле в `listen()`/`wake()` как опциональное: старый демон
не ломает вызов.

### 3.3 `Conversation`

```python
participants: set[str]      # id профилей, принимаемых в этом окне
last_speaker: str | None
last_route: str             # 'chat' | 'command' | 'ignore' | 'other'
join_events: int
add_participant(id), remove_participant(id), clear_participants()
snapshot() -> + 'participants', 'last_speaker', 'last_route'
```

Таймеры и `id` не меняются; `close()` очищает участников.

### 3.4 `runtime.speaker` в `/api/status`

```json
{
  "enabled": true,
  "profiles": [{"id": "spk_01", "label": "Голос 1"}],
  "participants": ["spk_01", "spk_02"],
  "current": {"id": "spk_02", "label": "Голос 2", "score": 0.78, "status": "known"},
  "last_event": "joined",
  "model": {"ready": true, "error": null}
}
```

Никаких embedding'ов, путей к модели и секретов.

### 3.5 Роуты

Демон (только `127.0.0.1`, как остальные): `GET /speaker/status`,
`POST /speaker/enroll|test|rename|delete`.

Панель (CSRF на все POST):

| Метод | Роут | Назначение |
|---|---|---|
| GET | `/api/speaker` | статус, профили, участники, текущий говорящий |
| POST | `/api/speaker/enroll` | записать 3–5 с голоса через `ears.listen()` |
| POST | `/api/speaker/test` | проверить голос, не создавая профиль |
| POST | `/api/speaker/rename` | `{id, label}` |
| POST | `/api/speaker/delete` | `{id}` |
| POST | `/api/speaker/clear` | очистить участников текущего диалога |

`WebBridge`: `speaker_status/enroll/test/rename/delete/clear_participants`, все через
`App._web_call` → `GLib.idle_add`; микрофон — только через `_ears_exclusive()`.

### 3.6 Настройки

| Ключ | Тип | По умолчанию | Смысл |
|---|---|---:|---|
| `speaker_verify` | bool | `false` | вся фича; при `false` — текущее поведение |
| `speaker_threshold` | float | `0.65` | порог косинусной близости |
| `speaker_min_ms` | int | `1200` | минимум чистого голоса для enroll |
| `speaker_join_policy` | choice | `addressed` | `addressed` / `strict` / `off` |

`speaker_model` — **не** настройка панели, только env `YUMI_SPEAKER_MODEL` для тестов.

---

## 4. Потоки (поведение)

### 4.1 Первый вход (wake-word)

1. `ears.wake()` → демон слышит имя → берёт embedding из `ring` + фразы.
2. Профилей нет → `speaker.enroll(..., source='wake')`, `joined_id`.
3. `senses.py` получает `speaker`, `brain.wake_up(..., speaker=...)`.
4. `conversation_begin()` → `participants = {joined_id}`.

### 4.2 Своя реплика в активном диалоге

1. wake-цикл вызывает `followup_listen()` с `join=1`.
2. `/listen` возвращает текст + `speaker`.
3. `Brain.heard_text()`:
   - `stop_command(text)` → `stop_all()` (независимо от голоса);
   - `speaker.status='known'` и id в `participants` → обработка как сейчас;
   - в `chat_history` пишется метка говорящего.

### 4.3 Вклинившийся человек без имени

1. Неизвестный голос говорит обращённую фразу во время follow-up окна.
2. Демон: `route(text) != 'ignore'`, `addressee()=='yumi'`, `quality=True` →
   `speaker.enroll(source='join')`, `joined_id`.
3. Мозг: `conversation.add_participant(joined_id)`, фраза идёт в чат, один раз
   подсказка «Кажется, ещё один голос — я тебя запомнила».
4. Следующие реплики этого голоса принимаются без wake-word.

### 4.4 Разговор участников между собой

`addressee(text, labels)=='other'` → реплика игнорируется, окно диалога продолжает тикать.
`speaker_join_policy='strict'` требует два подтверждения подряд для нового участника;
`off` запрещает авто-join (только ручная запись).

### 4.5 Гейт (псевдокод для T-08)

```python
def speaker_gate(text, spk, conv, hints):
    if stop_command(text):
        return 'pass'
    if not settings.get('speaker_verify') or spk is None:
        return 'pass'                       # старый демон / выключенная фича
    route = addressing.route(text, hints)
    who = addressing.addressee(text, labels(conv.participants))
    if route == 'ignore' or who == 'other':
        return 'ignore'
    if spk['status'] == 'known' and spk['id'] in conv.participants:
        return 'pass'
    if spk['status'] == 'unknown' and spk.get('quality') and spk.get('joined_id'):
        return 'join'                       # только в follow-up и policy != off
    return 'ignore'
```

---

## 5. Изменения по файлам

| Файл | Что добавить |
|---|---|
| `yumi/speaker.py` (новый) | хранилище профилей, verify/enroll/list/rename/delete/snapshot, без GTK |
| `yumi/speaker_sherpa.py` (новый) | адаптер `SpeakerEmbeddingExtractor`, `available()`, `embedding(pcm)` |
| `tools/speaker_setup.sh` | фиксация модели 3D-Speaker и контрольной суммы в venv stt |
| `yumi/addressing.py` | `addressee(text, labels)`; не ломать `route()` |
| `yumi/stt_daemon.py` | embedding в wake/listen, auto-enroll, join-режим, `/speaker/*` |
| `yumi/ears.py` | проброс `speaker` в клиентских контрактах |
| `yumi/conversation.py` | `participants`, `last_speaker`, `last_route`, snapshot |
| `yumi/brain.py` | `heard_text(..., speaker=None, join=False)`, гейт, метки в chat_history, меню GTK |
| `yumi/ui/senses.py` | `speaker=`/`join=1` в follow-up, подсказка о новом участнике |
| `yumi/config.py` | 4 настройки, строки UI ru/en, `STATE_DIR`-путь профилей |
| `yumi/webpanel/catalog.py` | KEY_SECTION/TYPES/CHOICES/RANGES/TITLES/HINTS; **не** CONFIG_FILES |
| `yumi/ui/webpanel.py` | snapshot/live-apply |
| `yumi/ui/bridge.py` | 6 методов + `_ears_exclusive()` |
| `yumi/webpanel/server.py` | 6 роутов, CSRF, аудит без векторов |
| `yumi/webui/static/js/api.js`, `pages/voice.js`, `pages/chat.js` | кнопки, список профилей, индикатор участников |
| `tests/*` | `test_speaker.py`, `test_speaker_gate.py`, обновления addressing/conversation/webpanel |
| `README*.md`, `docs/handoff-web-panel.md`, этот файл | документация |

---

## 6. Риски и решения

| Риск | Смягчение |
|---|---|
| Ложный вход по ТВ/фоновой речи | `addressee()`, `route() != ignore`, `speaker_min_ms`, `quality`, политика `strict` |
| Ответ на реплику «Анна → Борис» | `addressee()` с метками участников; P2 — confidence score |
| Юми не узнала хозяина (простуда, шум, смена микрофона) | порог, ручная перезапись, wake-word всегда работает |
| Перекрытие двух голосов | `quality=False` → enroll не происходит; гейт по доминирующему голосу |
| Запись чужого голоса как своего | liveness нет; хранить только локально, не логировать, не отдавать в API |
| Конфликт за микрофон | только `_ears_exclusive()` и один владелец в wake-цикле |
| Старый демон без поля `speaker` | приложение работает по-старому, `speaker_verify` не ломает совместимость |
| Биометрия в редакторе конфигов | `speakers.json` не добавлять в `CONFIG_FILES` |

---

## 7. Тесты

- `tests/test_speaker.py`: хранилище, порог, quality, source, битый файл, поддельный бэкенд модели.
- `tests/test_addressing.py`: «как дела?», «Борис, где ключи?», «он сказал, что придёт».
- `tests/test_speaker_gate.py`: stop, выключенная фича, known, unknown+адресация, other, короткая фраза.
- `tests/test_conversation_mode.py`: участники живут до `close()`, сброс по таймауту.
- `tests/test_webpanel.py`: схема настроек, `/api/status`, CSRF, роуты speaker, отсутствие embedding'ов в ответе.

Команды проверки:

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

---

## 8. Критерии приёмки

1. При первом wake-word профиль создаётся сам; в панели и GTK есть список профилей и кнопки записи/проверки/переименования/удаления.
2. Два человека по очереди ведут диалог без повторного wake-word — Юми различает их по голосу и подписывает реплики в истории.
3. Третий человек говорит обращённую фразу — становится участником; неадресованная речь игнорируется.
4. «Борис, где ключи?» в активном диалоге не вызывает ответ Юми.
5. «Стоп» от любого голоса останавливает Юми.
6. Собственный TTS не создаёт участника и не продолжает диалог.
7. При `speaker_verify=false` поведение совпадает с текущим; старый демон совместим.
8. Сырые embedding'ы не видны в API, панели, логах или редакторе конфигов.
9. Все проверки §7 зелёные; ручные сценарии на реальном микрофоне пройдены.

---

## 9. Открытые технические детали (решить при реализации)

- Точная модель 3D-Speaker и её контрольная сумма в `tools/speaker_setup.sh` (не выдумывать URL).
- Формат метки в `chat_history`: отдельное поле `speaker` или префикс в `content` — выбрать то, что не ломает `chat.ask()`/`memory.remember()`.
- Поведение при `speaker.status='unknown'` и выключенном auto-join: молчать или один раз подсказать wake-word.
- Нужна ли отдельная voice-реплика «я запомнила новый голос» или достаточно индикатора в панели.
