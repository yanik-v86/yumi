"""The bridge the HTTP panel sees: GTK calls hop to the main thread, pure ones stay put."""
import threading
import time
from pathlib import Path

from yumi import (chat, config, doctor as doctor_mod, ears, engines, facts, files, jobs,
                  memory, models, music, notes, permission, system, tts)


class WebBridge:
    """The bridge the HTTP server sees. Every call that touches GTK is wrapped by
    ``App._web_call``; the pure ones (chat, music, memory) stay on the HTTP thread."""

    def __init__(self, app):
        self.app = app

    def _on(self, fn, timeout=30):
        return self.app._web_call(fn, timeout)

    # ---- read side
    def snapshot(self):
        return self._on(self.app._web_snapshot)

    def configs(self):
        return self._on(self.app._web_configs)

    def config_get(self, name):
        return self._on(lambda: self.app._web_config_get(name))

    def config_save(self, name, value):
        return self._on(lambda: self.app._web_config_save(name, value), 60)

    def actions_get(self):
        return self._on(self.app._web_actions_get)

    def actions_save(self, actions):
        return self._on(lambda: self.app._web_config_save('actions', actions), 60)

    # ---- your own intents (the panel is the editor, the folders are the source)
    def user_intents_get(self):
        return self._on(self.app._web_user_intents_get)

    def user_intents_put(self, payload):
        return self._on(lambda: self.app._web_user_intents_put(payload), 60)

    def user_intents_import_zip(self, raw, name=''):
        return self._on(lambda: self.app._web_user_intents_import_zip(raw, name), 60)

    def user_intents_export_zip(self):
        return self._on(self.app._web_user_intents_export_zip, 60)

    def user_intents_remote_index(self):
        return self._on(self.app._web_user_intents_remote_index, 60)

    def user_intents_remote_install(self, bundle_id, mode='merge'):
        return self._on(
            lambda: self.app._web_user_intents_remote_install(bundle_id, mode), 120)

    def user_intents_test(self, text):
        return self._on(lambda: self.app._web_user_intents_test(text))

    def user_intents_run(self, text):
        """match and execute a custom rule as if the phrase had been heard"""
        return self._on(lambda: self.app._web_user_intents_run(text))

    def intents_log_get(self, limit=200, intent='', stage=''):
        return self._on(lambda: self.app._web_intents_log_get(limit, intent, stage))

    def intents_log_clear(self):
        return self._on(self.app._web_intents_log_clear)

    def action_run(self, index):
        b = self.app.brain
        self._on(lambda: b.extras_do('custom', int(index)))
        return {'ran': int(index)}

    def confirm_action(self, ok):
        """answer the pending requires_confirmation command from the browser"""
        b = self.app.brain
        return self._on(lambda: {'confirmed': bool(b._voice_confirm_web(bool(ok)))})

    def apply_settings(self, patch):
        return self._on(lambda: self.app._web_apply_settings(patch), 60)

    # ---- voice profiles (nothing but ids, labels and verdicts crosses this line)
    @staticmethod
    def _speaker_public(data):
        """allow-list the daemon's answer: a raw embedding must never reach the panel"""
        if not isinstance(data, dict):
            return {'ok': False, 'error': 'bad answer from the ears'}
        out = {'ok': bool(data.get('ok', True))}
        for key in ('id', 'error', 'label'):
            if key in data:
                out[key] = str(data[key])[:160]
        if isinstance(data.get('speaker'), dict):
            out['speaker'] = {k: data['speaker'][k]
                              for k in ('status', 'id', 'score', 'quality', 'ms', 'joined_id')
                              if k in data['speaker']}
        if isinstance(data.get('profiles'), list):
            profs = []
            for p in data['profiles']:
                if not isinstance(p, dict):
                    continue
                row = {k: str(p[k])[:160] for k in ('id', 'label', 'source') if k in p}
                info = p.get('info')
                if isinstance(info, dict) and info:
                    row['info'] = {k: str(v)[:256] for k, v in info.items()
                                   if isinstance(k, str) and isinstance(v, str) and v}
                profs.append(row)
            out['profiles'] = profs
        if isinstance(data.get('profile'), dict):
            p = data['profile']
            row = {k: str(p[k])[:160] for k in ('id', 'label', 'source') if k in p}
            info = p.get('info')
            if isinstance(info, dict) and info:
                row['info'] = {k: str(v)[:256] for k, v in info.items()
                               if isinstance(k, str) and isinstance(v, str) and v}
            out['profile'] = row
        if 'text' in data and isinstance(data['text'], str):
            out['text'] = data['text'][:2000]
        if 'created' in data:
            out['created'] = bool(data['created'])
        return out

    def speaker_status(self):
        return self._on(self.app._web_speaker_snapshot)

    def speaker_enroll(self):
        """record a clean voice through the daemon; the background wake ear pauses"""
        return self._speaker_public(self._ears_exclusive(ears.speaker_enroll))

    def speaker_acquaintance(self):
        """guided voice registration: Yumi speaks intro, then records a voiceprint"""
        def start():
            b = self.app.brain
            cur = getattr(b, '_speaker_current', None)
            if isinstance(cur, dict) and cur.get('id') and cur.get('status') == 'known':
                label = cur.get('label') or b._voice_label(cur.get('id')) or str(cur.get('id'))
                b.say('acquaintance_already', label=label)
                return {'ok': True, 'started': False, 'already': True, 'label': label}
            b.acquaintance_begin()
            return {'ok': True, 'started': True}
        return self._on(start)

    def speaker_test(self):
        return self._speaker_public(self._ears_exclusive(ears.speaker_test))

    def speaker_rename(self, pid, label):
        result = ears.speaker_rename(pid, label)
        snap = self._on(self.app._web_speaker_changed)
        out = self._speaker_public(result)
        out['speaker'] = snap
        return out

    def speaker_delete(self, pid):
        result = ears.speaker_delete(pid)
        snap = self._on(lambda: self.app._web_speaker_changed(str(pid)))
        out = self._speaker_public(result)
        out['speaker'] = snap
        return out

    def speaker_clear_participants(self):
        return self._on(self.app._web_speaker_clear)

    # ---- diagnostics and explicit model checks
    def doctor(self, sections=None, text=None):
        """one full self-test with the wake loop parked; the audio calls run on
        the HTTP thread so the GTK loop stays free (only pause/resume hop over)"""
        report = self._ears_exclusive(lambda: doctor_mod.run(
            self.app.settings, sections=sections, roundtrip_text=text))
        self._on(lambda: self.app._web_doctor_done(report))
        return report

    def models_verify(self):
        """explicit SHA-256 check (never called on a status tick); cached for status"""
        return models.verify_cached(force=True)

    def models_verify_cached(self):
        """the last cached model check (cheap, safe for a GET)"""
        return models.cached()

    def models_record(self, names=None):
        """trust the model copies that are here now, then refresh the cached check"""
        result = models.record(names)
        result['models'] = models.verify_cached(force=True)['models']
        return result

    # ---- voice state
    def voice_state(self):
        return self._on(lambda: self.app.voice_state.snapshot())

    def voice_pause(self):
        return self._on(self.app._web_voice_pause)

    def voice_resume(self):
        return self._on(self.app._web_voice_resume)

    def voice_release(self):
        self.voice_stop()
        return self._on(self.app._web_voice_released)

    # ---- permissions
    def permission_answer(self, decision, origin='panel'):
        return self._on(lambda: self.app.brain.answer_permission(decision, origin))

    def permissions_list(self):
        return permission.snapshot()

    def permissions_clear(self):
        return {'ok': bool(permission.clear())}

    # ---- world actions
    def state_action(self, name, payload):
        a = self.app
        b = a.brain

        def run():
            if name in ('toggle', 'show'):
                b.toggle()
            elif name == 'hide':
                b.close_all()
                b.pop(False)
            elif name == 'home':
                b.go_home()
            elif name == 'monitor':
                a.cycle_monitor()
            elif name == 'pipette':
                b.start_pipette()
            elif name == 'recent':
                b.toggle_pile('recent')
            elif name == 'shelf':
                b.toggle_pile('shelf')
            elif name == 'dnd':
                on = bool(payload.get('on', not b.sleeping))
                if not on:
                    b.nap = False
                b.requests.append(('dnd', on))
            elif name == 'pin':
                on = bool(payload.get('on', not a.settings.get('pinned')))
                a.settings['pinned'] = on
                a.settings.save()
                if on:
                    b.pop(True)
            elif name == 'sound':
                b.requests.append(('sound', 'timer'))
            elif name == 'stop':
                b.stop_all()
            elif name == 'listen':
                b.requests.append(('listen', int(payload.get('seconds') or 8)))
            elif name == 'joke':
                b.requests.append(('joke_ask', {'lang': a.settings.get('speech_lang', 'en'),
                                                'text': payload.get('text') or ''}))
            elif name == 'tour':
                b.start_tour()
            elif name == 'config-dir':
                system.spawn('xdg-open', str(config.CONFIG_DIR))
            elif name == 'restart':
                b.requests.append(('restart',))
            elif name == 'quit':
                b.requests.append(('quit',))
            else:
                raise ValueError(f'unknown action: {name}')
            return {'action': name}
        return self._on(run)

    def files_recent(self):
        return self._on(self._files_recent)

    def _files_recent(self):
        items = sorted(getattr(self.app.recent, 'items', {}).items(), key=lambda x: -x[1])[:60]
        return [self._file_info(p, t) for p, t in items]

    @staticmethod
    def _file_info(path, mtime=None):
        p = Path(path)
        try:
            st = p.stat()
            size, mtime, exists = st.st_size, mtime or st.st_mtime, True
        except OSError:
            size, exists = 0, False
        kind = jobs.kind_of(p) or ('archive' if p.suffix.lower().lstrip('.') in
                                   ('zip', 'tar', 'gz', 'xz', 'zst', '7z', 'rar', 'bz2') else 'other')
        return {'path': str(p), 'name': p.name, 'size': size, 'mtime': mtime,
                'exists': exists, 'kind': kind, 'ext': p.suffix.lower().lstrip('.')}

    def files_shelf(self):
        return self._on(lambda: [self._file_info(p) for p in
                                 (self.app.state.get('shelf') or [])])

    def shelf_change(self, paths, add=True):
        def run():
            shelf = self.app.state.setdefault('shelf', [])
            for path in paths:
                p = str(Path(path).expanduser())
                if add:
                    if p not in shelf:
                        shelf.insert(0, p)
                else:
                    while p in shelf:
                        shelf.remove(p)
            del shelf[40:]
            self.app.state.save()
            return {'shelf': list(shelf)}
        return self._on(run)

    def files_open(self, path):
        def run():
            if not self.app._web_file_allowed(path):
                raise ValueError('this file is not one the panel knows')
            return {'opened': bool(files.open_path(path))}
        return self._on(run)

    def file_allowed(self, path):
        return self._on(lambda: self.app._web_file_allowed(path))

    def job_add(self, op, path, arg):
        def run():
            if op not in ('convert', 'compress'):
                raise ValueError('unknown job')
            if not self.app._web_file_allowed(path):
                raise ValueError('this file is not one the panel knows')
            p = Path(path).expanduser()
            if not p.is_file():
                raise ValueError('the file is gone')
            kind = jobs.kind_of(p)
            if not kind:
                raise ValueError('this file is not a picture, sound or video')
            allowed = jobs.TARGETS.get(kind, []) if op == 'convert' else jobs.PRESETS.get(kind, [])
            if arg not in allowed:
                raise ValueError(f'unknown target: {arg}')
            self.app.queue.add(op, str(p), arg)
            return {'queued': True, 'kind': kind, 'op': op, 'arg': arg}
        return self._on(run)

    def jobs_cancel(self):
        return self._on(lambda: self.app.queue.cancel())

    def timer_get(self):
        return self._on(self.app._web_timer_get)

    def timer(self, action, seconds):
        return self._on(lambda: self.app._web_timer(action, seconds))

    def ask(self, text, speak=True):
        def run():
            b = self.app.brain
            if b.thinking:
                return {'queued': False, 'reason': 'she is thinking already'}
            b.wake_up(text)
            return {'queued': True}
        return self._on(run)

    def chat(self, text):
        return self.app._web_chat(text)

    def chat_history(self):
        """the old, plain list — kept for callers that only want the messages"""
        with self.app.web_chat_lock:
            return list(self.app.web_chat)

    def chat_state(self):
        """messages + revision, for GET /api/chat/history"""
        with self.app.web_chat_lock:
            return {'messages': list(self.app.web_chat), 'rev': self.app.web_chat_rev}

    def chat_ops(self, since=0):
        """ops newer than `since`, so a tab that missed SSE can catch up"""
        try:
            since = max(0, int(since or 0))
        except (TypeError, ValueError):
            since = 0
        with self.app.web_chat_lock:
            return {'rev': self.app.web_chat_rev,
                    'ops': [dict(op) for op in self.app.web_chat_ops if op['rev'] > since]}

    def chat_message_update(self, message_id, text):
        return self.app._web_chat_update(message_id, {'text': text})

    def chat_message_remove(self, message_id):
        return self.app._web_chat_remove(message_id)

    def chat_clear(self):
        with self.app.web_chat_lock:
            self.app.web_chat = []
            op = self.app._web_chat_op('clear')
            self.app.save_web_chat()
        self.app._web_chat_publish([op])
        return {'cleared': True, 'rev': op['rev'], 'ops': [op]}

    def memory_recent(self, limit=50):
        return memory.recent(limit, hide_sassy=not self.app.settings.get('sassy'))

    def memory_search(self, query, limit=50):
        return memory.recall(query, self.app.settings, k=min(50, limit))

    def memory_clear(self, tag):
        if tag == 'all':
            return {'deleted': memory.clear_all()}
        return {'deleted': memory.clear_tag(tag)}

    # ---- notes: the same book her ears write into (yumi/notes.py)
    def notes_list(self, limit=50):
        return notes.recent(limit)

    def notes_search(self, query, limit=50):
        return notes.search(query, self.app.settings, limit=limit)

    def notes_get(self, note_id):
        return notes.get(note_id)

    def notes_add(self, text, title=None, source='web'):
        return notes.add(text, self.app.settings, title=title, source=source)

    def notes_update(self, note_id, text, title=None):
        return notes.update(note_id, text, self.app.settings, title=title)

    def notes_delete(self, note_id):
        if not notes.delete(note_id):
            raise ValueError('there is no such note')
        return {'deleted': True, 'id': int(note_id)}

    def notes_clear(self):
        return {'deleted': notes.clear()}

    def music_status(self):
        playing = music.now_playing()
        return {'now_playing': playing, 'volume': music.read_volume(),
                'mpd': bool(music.get_mpd_status()),
                'resumable': bool(music.resume_available()),
                'source': self.app.settings.get('music_source')}

    def music_search(self, kind, query):
        from yumi import library
        res = library.resolve(self.app.settings, kind, query)
        tracks = [{'title': t.get('title', ''), 'artist': t.get('artist', ''),
                   'album': t.get('album', ''), 'source': t.get('source', ''),
                   'path': t.get('path', ''), 'url': t.get('url', '')}
                  for t in (res.get('tracks') or [])[:40]]
        return {'source': res.get('source'), 'tracks': tracks, 'kind': kind, 'query': query}

    def music_play(self, kind, query):
        music.apply_settings(self.app.settings)
        report = music.play_query(kind, query, self.app.settings)
        track = report.get('track')
        return {'report': {'ok': report.get('ok'), 'source': report.get('source'),
                           'count': report.get('count'), 'kind': report.get('kind'),
                           'query': report.get('query'),
                           'track': {'artist': track[0], 'title': track[1]} if track else None}}

    def music_control(self, cmd):
        if cmd == 'like':
            return {**self.music_like(), 'cmd': cmd, 'volume': music.read_volume()}
        ok = music.music_control(cmd)
        return {'ok': bool(ok), 'cmd': cmd, 'volume': music.read_volume()}

    def music_like(self):
        report = music.like_playing(self.app.settings)
        track = report.get('track')
        return {'ok': bool(report.get('ok')),
                'reason': report.get('reason'),
                'source': report.get('source'),
                'track': {'artist': track[0], 'title': track[1]} if track else None}

    def voice_listen(self, seconds, engine=None):
        """one phrase through the chosen judge; the background wake loop is paused
        first, or the daemon would answer «busy» (one microphone, one ear)"""
        engine = str(engine or self.app.settings.get('stt_engine') or 'whisper')
        if engine not in ('whisper', 'nemotron'):
            raise ValueError(f'unknown judge: {engine}')
        info = engines.status(self.app.settings)
        if engine == 'nemotron' and not info['judge']['nemotron']['available']:
            raise ValueError('nemotron is not installed (tools/nemotron_setup.sh)')

        def work():
            return ears.listen(lang=self.app.settings.get('speech_lang', 'en'),
                               secs=max(2, min(30, float(seconds or 8))),
                               size=self.app.settings.get('stt_size', 'small'),
                               mic=self.app.settings.get('stt_mic'),
                               engine=engine,
                               beam=self.app.settings.get('stt_beam', 5))

        res = self._ears_exclusive(work)
        if res is None:
            return {'heard': None, 'readings': None, 'engine': engine,
                    'reason': 'the ears are away or busy'}
        heard = str(res.get('text') or res.get('vosk') or '').strip()
        return {'heard': heard or None, 'readings': res, 'engine': engine}

    def voice_test_wake(self, seconds=8, ear=None):
        """hold the microphone for a few seconds with the chosen activation ear:
        say the name and the panel gets a yes/no, not a guess"""
        s = self.app.settings
        ear = str(ear or s.get('wake_ear') or 'auto')
        if ear not in ('auto', 'oww', 'vosk'):
            raise ValueError(f'unknown activation ear: {ear}')
        info = engines.status(s)
        if ear == 'oww' and not info['activation']['oww']['available']:
            raise ValueError('openWakeWord is not installed (model or oww venv is missing)')
        if ear == 'vosk' and not info['activation']['vosk']['available']:
            raise ValueError('the Vosk ear is not installed (tools/stt_setup.sh)')
        secs = max(3.0, min(30.0, float(seconds or 8)))

        def work():
            started = time.monotonic()
            res = ears.wake(lang=s.get('speech_lang', 'en'),
                            word=s.get('wake_word', 'юми'),
                            secs=secs,
                            size=s.get('stt_size', 'small'),
                            mic=s.get('stt_mic'),
                            sensitivity=s.get('wake_sensitivity', 'normal'),
                            confirm=s.get('wake_confirm', True),
                            model_size=s.get('wake_model_size', 'small'),
                            judge_log=s.get('wake_judge_log', True),
                            engine=s.get('stt_engine'),
                            beam=s.get('stt_beam', 5),
                            oww_ear=ear)
            return res, round(time.monotonic() - started, 2)

        res, elapsed = self._ears_exclusive(work)
        if res is None:
            raise ValueError('the ears are away: run tools/stt_setup.sh')
        return {'woke': bool(res.get('woke')), 'text': str(res.get('text') or ''),
                'ear': ear, 'word': str(s.get('wake_word') or 'юми'),
                'seconds': secs, 'elapsed': elapsed}

    def voice_test(self, text=None, lang=None):
        """say a sample with the current TTS profile even when her usual voice is
        blips; a changed profile is written and the daemon restarted first"""
        s = self.app.settings
        lang = str(lang or s.get('speech_lang') or 'en')
        if lang not in ('ru', 'en'):
            lang = 'en'
        text = ' '.join(str(text or '').split())[:300]
        if not text:
            text = ('Привет! Это Юми, я говорю своим голосом.' if lang == 'ru'
                    else 'Hi! This is Yumi, speaking with my real voice.')
        report = tts.sync_profile(s)
        volume = max(0.1, min(1.0, float(s.get('voice_vol', 50) or 50) / 100.0))
        path = tts.speak(text, volume, en_ru=bool(s.get('voice_en_ru')))
        if not path:
            raise ValueError('the real voice is not set up (tools/tts_setup.sh)')
        started = self._on(lambda: self.app.play_voice_file(path))
        if not started:
            raise ValueError('the sample is ready, but no audio player could play it')
        return {'text': text, 'lang': lang, 'path': str(path), 'playing': True,
                'profile': report.get('profile'), 'changed': report.get('changed', False)}

    def voice_engines(self):
        return engines.status(self.app.settings)

    def voice_mics(self):
        """the microphones the ears can hear right now, for the panel's picker;
        the in-world settings row sees the same list"""
        mics = ears.mics()
        self._on(lambda: self.app.brain.mics_loaded(mics))
        return {'mics': mics}

    def _ears_exclusive(self, fn):
        """run one microphone test with the background wake loop parked"""
        was_on = self._on(lambda: self.app.wake_pause())
        try:
            return fn()
        finally:
            try:
                self._on(lambda: self.app.wake_resume(was_on))
            except Exception:
                pass

    def voice_stop(self):
        threading.Thread(target=ears.stop, daemon=True).start()
        return {'stopped': True}

    def voice_speak(self, text):
        self._on(lambda: self.app.brain.say_text(text))
        return {'spoke': True}

    def tools_time(self):
        return {'time': chat.the_time(self.app.settings.get('speech_lang', 'en')),
                'stamp': time.strftime('%Y-%m-%d %H:%M:%S')}

    def tools_weather(self, where, when):
        s = self.app.settings
        lang = s.get('speech_lang', 'en')
        place = where or str(s.get('weather_city') or '')
        return {'report': chat.weather_report(place, lang, when or 'today'),
                'place': place, 'when': when or 'today'}

    def tools_joke(self):
        s = self.app.settings
        return {'joke': chat.joke(s, s.get('speech_lang', 'en'))}

    # ---- the vetted fact book (no model call: facts must not be invented)
    def facts_list(self, lang=None):
        s = self.app.settings
        book = facts.get_book(s)
        return {'items': book.items(lang or s.get('speech_lang', 'en')),
                'info': book.info()}

    def facts_check(self, path=''):
        return facts.FactBook(path).info()

    def facts_say(self, fact_id=None):
        """show one checked fact in the world; an explicit panel action ignores the gap"""

        def run():
            b = self.app.brain
            if b.sleeping:
                return {'ok': False, 'reason': 'sleeping'}
            if str(self.app.settings.get('chatter_facts') or 'off') == 'off':
                return {'ok': False, 'reason': 'off'}
            ok = bool(b.say('fact', force=True, fact_id=fact_id or None))
            return {'ok': ok, 'fact': getattr(b.speech, 'last_fact', None) if ok else None,
                    'text': ((b.bubble or {}).get('text') or '') if ok else ''}
        return self._on(run)

    def tools_params(self):
        lang = self.app.settings.get('speech_lang', 'en')
        return {'report': self._on(lambda: self.app.brain.params_report(lang))}

    def logs(self, name, lines):
        return self.app._web_logs(name, lines)
