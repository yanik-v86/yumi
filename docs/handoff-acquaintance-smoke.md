# Handoff: smoke знакомства (шум/тихо/коротко, нет модели, TTS overlap, GTK/web UI)

Статус: **автоматизированная часть закрыта; hardware smoke на реальном микрофоне не выполнялся в этой среде**.  
Дата: 2026-11-22.  
Связанные документы: `docs/tasks-acquaintance-smoke.md`, `docs/tasks-acquaintance.md`, `docs/handoff-acquaintance.md`.

## 1. Область

Этот handoff закрывает доработку/проверку сценария «Познакомиться» по четырём рискам:

1. Шум / тихая речь / слишком короткая фраза.
2. Отсутствие модели голосов.
3. Перекрытие TTS Юми и записи слепка.
4. Проверка в GTK и web UI.

## 2. Что проверено автоматически

### Кодовые контракты

| Сценарий | Поведение | Где |
|---|---|---|
| Плохая/шумная/короткая запись | `speaker_record()`/enroll возвращает ошибку качества; GTK acquaintance говорит `acquaintance_fail` и вызывает `web_sync_soon()` | `yumi/stt_daemon.py`, `yumi/ui/senses.py` |
| Нет модели | ошибка model unavailable → `acquaintance_nomodel` и `web_sync_soon()` | `yumi/stt_daemon.py`, `yumi/ui/senses.py` |
| TTS overlap | `_wait_voice_quiet()` ждёт drain TTS/blips перед записью | `yumi/ui/senses.py` |
| GTK path | voice command/menu → `speaker_acquaintance` → pause/resume wake → enroll → say result → `web_sync_soon` | `yumi/brain.py`, `yumi/ui/app.py`, `yumi/ui/senses.py` |
| Web UI path | `POST /api/speaker/acquaintance` (CSRF) → `{started}`; UI polling показывает итог | `yumi/ui/bridge.py`, `yumi/webpanel/server.py`, `yumi/webui/static/js/api.js`, `yumi/webui/static/js/pages/voice.js` |

### Автотесты

`tests/test_acquaintance.py`:

- `test_acquaintance_fail_on_noisy_or_short_voice` — мок `not enough clear voice` => `acquaintance_fail` + `web_sync_soon`.
- `test_acquaintance_nomodel` — мок `speaker model is not available` => `acquaintance_nomodel`.
- `test_wait_voice_quiet_blocks_until_tts_drains` — запись не стартует, пока TTS очередь не опустела.
- `test_speaker_acquaintance_action_path_mock` — полный GTK mock path.
- `test_acquaintance_command_matches_explicit_phrases` / `rejects_tour_and_noise`.
- `test_heard_text_starts_acquaintance` / alt / `acquaintance_begin_emits_request`.

`tests/test_webpanel.py`:

- CSRF + `POST /api/speaker/acquaintance` => `{ok:true, started:true}`.

## 3. Что НЕ закрыто автоматически (требует ручного hardware smoke)

В этой среде нет реального микрофона/акустической петли/установленной speaker model, поэтому следующие пункты нельзя честно пометить выполненными:

- [ ] Реальный шумный фон: профиль не создаётся/не портится.
- [ ] Реальная тихая/короткая речь: корректный отказ.
- [ ] Реальное отсутствие модели: понятный UX в GTK и web UI.
- [ ] Реальный TTS overlap: голос Юми не попадает в слепок (особенно PipeWire/echo-cancel).
- [ ] E2E GTK: меню + голосовая команда.
- [ ] E2E Web UI: кнопка, старт, polling, итог, появление профиля.

## 4. Как проводить ручной smoke

### Подготовка

1. Запустить Юми с рабочим микрофоном.
2. Для сценария модели: временно убрать/не настраивать speaker model (`tools/speaker_setup.sh` не запускать или изолировать env).
3. Открыть web-панель на странице «Ушки и голос».

### Кейсы

1. **Нормальный**: «Юми, давай познакомимся» / кнопка «Познакомиться» → подсказка, 3–5с обычной речи, `acquaintance_ok`, профиль появился.
2. **Шум**: включить фон/говорить поверх шума → отказ, профиль не должен стать мусорным.
3. **Тихо/коротко**: шёпот или <1с → отказ, без падений.
4. **Нет модели**: `acquaintance_nomodel`, UI показывает причину.
5. **TTS overlap**: убедиться, что запись начинается после окончания подсказки Юми.
6. **Web UI**: кнопка показывает старт, затем итог; после успеха «Проверить голос» распознаёт профиль.

## 5. Команды автоматической проверки

```bash
python3 -m py_compile yumi/brain.py yumi/ui/app.py yumi/ui/senses.py yumi/ui/bridge.py yumi/webpanel/server.py tests/test_acquaintance.py
python3 -m pytest tests/test_acquaintance.py tests/test_webpanel.py -q
for f in yumi/webui/static/js/api.js yumi/webui/static/js/pages/voice.js; do
  node --input-type=module --check < "$f" || echo "FAIL $f"
done
```

## 6. Рекомендация по статусу

Не закрывать задачу как «выполнено полностью» без ручного hardware smoke. Закрывать как «автоматизировано + ожидает ручного подтверждения на устройстве».
