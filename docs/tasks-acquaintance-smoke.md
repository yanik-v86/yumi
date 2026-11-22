# Задачи: smoke-проверка знакомства (шум/тихо/коротко, нет модели, TTS overlap, GTK/web UI)

Статус: **автоматизированные проверки добавлены; аппаратный smoke на реальном микрофоне требует ручного подтверждения**.  
Дата: 2026-11-22.  
Связанные документы: `docs/handoff-acquaintance-smoke.md`, `docs/tasks-acquaintance.md`, `docs/handoff-acquaintance.md`.

## Цель

Закрыть риски сценария «Познакомиться»: плохой/шумный/тихий/короткий голос, отсутствие модели голосов, перекрытие TTS и записи, проверка в GTK и веб-панели.

## Статус задач

### S-01. Шум / тихо / короткая речь (P0)

**Статус:** DONE (авто) / MANUAL REQUIRED (hardware).  
**Код/контракт:**
- Daemon `speaker_record()` возвращает `not enough clear voice` / `nothing was heard` / `the voice could not be read` при плохой записи (`yumi/stt_daemon.py`).
- `Senses._speaker_action_done()` маппит ошибку знакомства в `acquaintance_fail` (`yumi/ui/senses.py`).
- Web UI показывает итог через polling и подсказку проверить микрофон/модель (`yumi/webui/static/js/pages/voice.js`).

**Автотест:**
- `tests/test_acquaintance.py::test_acquaintance_fail_on_noisy_or_short_voice` — mock `ears.speaker_enroll` возвращает `not enough clear voice`, UI-путь говорит `acquaintance_fail` и вызывает `web_sync_soon`.

**Ручной smoke (нужен реальный микрофон):**
- [ ] Шумный фон (музыка/ТВ): знакомство не создаёт плохой профиль, Юми произносит понятный отказ.
- [ ] Тихая речь/шёпот: отказ по качеству, без падения.
- [ ] Слишком короткая фраза (< `speaker_min_ms` чистого голоса): отказ, без падения.
- [ ] Нормальная фраза 3–5с: профиль создаётся/обновляется.

### S-02. Отсутствие модели (P0)

**Статус:** DONE (авто) / MANUAL REQUIRED (hardware/env).  
**Код/контракт:**
- Daemon возвращает `speaker model is not available` / no model.
- Senses маппит в `acquaintance_nomodel`.
- Voice page показывает `model.ready/error` в карточке голосов.

**Автотест:**
- `tests/test_acquaintance.py::test_acquaintance_nomodel` — mock ошибки модели, Юми произносит `acquaintance_nomodel`.

**Ручной smoke:**
- [ ] Убрать/не устанавливать speaker model или запустить без `tools/speaker_setup.sh`: GTK/web показывают понятную причину, приложение не падает.

### S-03. TTS overlap / голос Юми не попадает в слепок (P0)

**Статус:** DONE (авто guard) / MANUAL REQUIRED (hardware).  
**Код/контракт:**
- `Senses._wait_voice_quiet()` ждёт опустошения `voice_queue/_voice_ready/voice_pending/voice_streaming` перед `ears.speaker_enroll()` (`yumi/ui/senses.py`).
- `Brain.acquaintance_begin()` говорит intro, затем ставит `speaker_acquaintance`; senses ждёт тишину.

**Автотесты:**
- `tests/test_acquaintance.py::test_wait_voice_quiet_blocks_until_tts_drains` — ожидание до очистки очереди.
- `tests/test_acquaintance.py::test_speaker_acquaintance_action_path_mock` — путь acquaintance вызывает enroll после pause/resume и публикует sync.

**Ручной smoke:**
- [ ] При знакомстве Юми договаривает подсказку до начала записи; её TTS не слышен в записанном слепке.
- [ ] На PipeWire/echo-cancel конфигурации повторить 2-3 раза.

### S-04. Проверка в GTK и web UI (P0)

**Статус:** DONE (авто/интеграция) / MANUAL REQUIRED (hardware).  
**Код/контракт:**
- GTK: меню «Ушки» → «Познакомиться», голосовая команда «Юми, давай познакомимся».
- Web: `POST /api/speaker/acquaintance` (CSRF), кнопка «Познакомиться», polling итога, `web_sync_soon()` после действия.

**Автотесты:**
- `tests/test_webpanel.py` — CSRF/started для `/api/speaker/acquaintance`.
- `tests/test_acquaintance.py` — voice command, heard_text, begin, GTK mock path, fail/nomodel.

**Ручной smoke:**
- [ ] GTK меню: сценарий проходит, итог озвучен.
- [ ] Голосовая команда: срабатывает, не конфликтует с «покажи знакомство».
- [ ] Web UI: кнопка показывает старт, затем итог после polling; профиль появляется в списке.

## Команды проверки

```bash
python3 -m py_compile yumi/brain.py yumi/ui/app.py yumi/ui/senses.py yumi/ui/bridge.py yumi/webpanel/server.py tests/test_acquaintance.py
python3 -m pytest tests/test_acquaintance.py tests/test_webpanel.py -q
for f in yumi/webui/static/js/api.js yumi/webui/static/js/pages/voice.js; do
  node --input-type=module --check < "$f" || echo "FAIL $f"
done
```

## Определение готовности

Задача считается **полностью закрытой** только после прохождения ручного hardware smoke по всем чек-боксам выше. Автоматизированные проверки закрывают регрессионную/логическую часть и не заменяют реальный микрофон.
