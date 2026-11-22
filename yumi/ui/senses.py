"""Her voice, ears, wake word and the minds she asks (a mixin for App)."""
import json
import re
import sys
import threading
import time

from gi.repository import GLib

from yumi import addressing, chat, config, ears, memory, music, notes, speaker as voices, system, tts, voice


_PROFILE_FIELD_STOP = frozenset((
    'я', 'и', 'а', 'но', 'живу', 'работаю', 'работает', 'увлекаюсь', 'хобби',
    'музыку', 'люблю', 'город', 'в', 'во', 'на', 'где', 'что', 'как', 'мой',
    'моё', 'мое', 'мне', 'из', 'по', 'с', 'со', 'это', 'был', 'была',
    'and', 'but', 'i', 'live', 'work', 'my', 'hobby', 'music', 'in', 'is',
))


def _first_profile_field(value):
    """The first 1–3 words of a captured field, before the next field starts."""
    out = []
    for word in str(value or '').split():
        clean = word.strip('.,!?;:—-«»"\'')
        if clean.lower() in _PROFILE_FIELD_STOP:
            break
        if clean:
            out.append(clean)
        if len(out) == 3:
            break
    return ' '.join(out)[:64]


def local_profile_fields(text):
    """A modest RU/EN fallback for «меня зовут …» when the mind is offline.

    The guided interview asks for a name and a city first; those two are easy
    to read without an LLM.  Without this, a missing API key left the profile
    labelled «Голос 1» and she later said «Тебя зовут Голос 1».
    """
    low = ' '.join(str(text or '').lower().split())
    if not low:
        return {}
    out = {}
    m = re.search(r'(?:меня\s+зовут|зовут\s+меня|my\s+name\s+is|i\s+am|im|this\s+is|это)\s+([^,.!?;]+)', low)
    if m:
        name = _first_profile_field(m.group(1))
        if name and not voices.is_generic_label(name):
            out['name'] = name[:1].upper() + name[1:]
    m = re.search(r'(?:я\s+живу\s+в\s+(?:городе\s+)?|живу\s+в\s+(?:городе\s+)?|город\s+|i\s+live\s+in\s+|live\s+in\s+)([^,.!?;]+)', low)
    if m:
        city = _first_profile_field(m.group(1))
        if city:
            out['city'] = city[:1].upper() + city[1:]
    return out


class SensesMixin:
    """Talking, listening, the wake loop, music and the questions she asks in the background."""

    DUCK_LEVEL = 30                 # percent, while the ears wait for the phrase after her name
    DUCK_BACK_MS = 12000            # the loudness comes back this long after the name went by

    # ---- her voice: 8-bit blips, or a real one from a local Silero (yumi/tts.py)
    def _voice_state(self):
        if not hasattr(self, 'voice_queue'):
            self.voice_queue = []
        if not hasattr(self, 'voice_streaming'):
            self.voice_streaming = False
        if not hasattr(self, 'voice_pending'):
            self.voice_pending = 0
        if not hasattr(self, '_voice_seq'):
            self._voice_seq = 0
        if not hasattr(self, '_voice_next'):
            self._voice_next = 1
        if not hasattr(self, '_voice_ready'):
            self._voice_ready = {}

    def _voice_blips(self, text):
        """offsets for the blips of one segment, like voice.render expects"""
        from yumi.brain import reveal_times
        times, _ = reveal_times(text)
        return [t for t, ch in zip(times, text) if ch.isalnum()]

    def speak(self, blips, bid, end_pitch, volume=0.5, text=''):
        self.hush()
        self._voice_state()
        self.voice_queue.clear()
        self.voice_pending = 0
        self.voice_streaming = False
        self._voice_seq = 0
        self._voice_next = 1
        self._voice_ready.clear()
        self.voice_id = bid
        if not blips and not text:
            return
        # one whole line is being prepared.  The acquaintance recording waits
        # for this count to clear: otherwise it starts while her introduction
        # is still being synthesized and the instruction is cut off mid-word.
        self.voice_pending += 1
        path = config.CACHE_DIR / f'voice{bid % 3}.wav'
        real = bool(text) and self.settings.get('voice_kind') == 'tts'

        def work():
            p = tts.speak(text, volume) if real else None
            if real and not p:
                self.warn_tts()               # not set up or failed: the blips speak instead
            if not p:
                try:
                    config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
                    voice.render(blips, path, seed=bid, end_pitch=end_pitch, volume=volume)
                    p = path
                except OSError:
                    p = None

            def ready():
                try:
                    if p:
                        self.voice_start(p, bid)
                finally:
                    self.voice_pending = max(0, self.voice_pending - 1)
                return False
            GLib.idle_add(ready)
        threading.Thread(target=work, daemon=True).start()

    def speak_stream(self, text, bid, volume=0.5):
        """a piece of a streaming answer: synthesize it and play it in turn"""
        self._voice_state()
        if not self.voice_streaming or self.voice_id != bid:
            self.hush()
            self.voice_id = bid
            self.voice_streaming = True
        self._voice_seq += 1
        seq = self._voice_seq
        path = config.CACHE_DIR / f'voice{bid % 5}-{seq}.wav'

        def work():
            p = tts.speak(text, volume)
            if not p:
                self.warn_tts()
                try:
                    config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
                    blips = self._voice_blips(text)
                    voice.render(blips, path, seed=bid + seq,
                                 end_pitch=1 if text.rstrip().endswith('?') else 0,
                                 volume=volume)
                    p = path
                except Exception:
                    p = None
            GLib.idle_add(lambda s=seq, pp=p, b=bid: self.voice_stream_ready(pp, b, s) and False)
        threading.Thread(target=work, daemon=True).start()

    def speak_stream_blip(self, blips, bid, end_pitch, volume=0.5):
        """a piece of a streaming answer in blips: render it and play it in turn"""
        self._voice_state()
        if not self.voice_streaming or self.voice_id != bid:
            self.hush()
            self.voice_id = bid
            self.voice_streaming = True
        self._voice_seq += 1
        seq = self._voice_seq
        path = config.CACHE_DIR / f'voice{bid % 5}-{seq}.wav'

        def work():
            try:
                config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
                voice.render(blips, path, seed=bid + seq, end_pitch=end_pitch, volume=volume)
                p = path
            except OSError:
                p = None
            GLib.idle_add(lambda s=seq, pp=p, b=bid: self.voice_stream_ready(pp, b, s) and False)
        threading.Thread(target=work, daemon=True).start()

    def voice_stream_ready(self, path, bid, seq=None):
        """a streaming segment is ready: queue it in order when it is its turn"""
        self._voice_state()
        if bid != self.voice_id:
            return False
        b = self.brain
        # keep the bubble alive while this piece waits its turn: TTS can take longer
        # than the typed text, and an expired bubble would drop the last segment
        if path and b.bubble and b.bubble.get('id') == bid:
            secs = tts.wav_len(path)
            if secs:
                b.bubble['until'] = max(b.bubble['until'], b.now + secs + 3.0)
        if seq is None:
            if path:
                self.voice_queue.append(path)
            self._voice_pump()
            return False
        self._voice_ready[seq] = path
        while self._voice_next in self._voice_ready:
            p = self._voice_ready.pop(self._voice_next)
            self._voice_next += 1
            if p:
                self.voice_queue.append(p)
        self._voice_pump()
        return False

    def _voice_pump(self):
        """play the next queued segment when nothing is sounding"""
        self._voice_state()
        if self.talking():
            return
        b = self.brain
        while self.voice_queue:
            path = self.voice_queue.pop(0)
            if self.voice_id is None or not b.bubble or b.bubble.get('id') != self.voice_id:
                continue
            secs = tts.wav_len(path)
            if secs:
                b.bubble['until'] = max(b.bubble['until'], b.now + secs + 1.2)
            self.voice_proc = system.play_file(path)
            if self.voice_proc:
                return

    def voice_stream_done(self, bid):
        """the mind has no more words for this answer"""
        self._voice_state()
        if bid == self.voice_id:
            self.voice_streaming = False
            self._voice_pump()

    def warn_tts(self):
        """once, into the log: why the real voice did not happen"""
        first = not getattr(self, '_tts_warned', False)
        self._tts_warned = True
        if first:
            reason = getattr(tts, 'last_error', '') or 'the voice daemon did not answer'
            print(f'yumi: her real voice did not work ({reason}); '
                  'the 8-bit blips speak instead', file=sys.stderr)
        return first

    def voice_start(self, path, bid):
        b = self.brain
        if bid == self.voice_id and b.bubble and b.bubble.get('id') == bid:
            secs = tts.wav_len(path)
            if secs:                          # the voice may be longer than the typed words
                b.bubble['until'] = max(b.bubble['until'], b.now + secs + 1.2)
            self.voice_proc = system.play_file(path)

    def play_voice_file(self, path):
        """play a ready WAV out loud: the panel's «listen to this voice» uses it
        (the usual speech path would go through her blips and bubble)"""
        self.hush()
        self.voice_preview = True
        self.voice_proc = system.play_file(path)
        if not self.voice_proc:
            self.voice_preview = False
        return bool(self.voice_proc)

    def hush(self):
        self._voice_state()
        self.voice_preview = False
        self.voice_queue.clear()
        self.voice_pending = 0
        self.voice_streaming = False
        self._voice_seq = 0
        self._voice_next = 1
        self._voice_ready.clear()
        p, self.voice_proc = self.voice_proc, None
        try:
            if p:
                p.terminate()
        except (OSError, AttributeError):
            pass

    # ---- her ears and her mind: a local Vosk hears (yumi/ears.py), a local Ollama answers (yumi/chat.py)
    def listen_ears(self, secs):
        """one listen: the daemon records the mic and recognizes it, in its own thread.
        The mic opens only when she is done talking: her own line must not be heard"""
        def work():
            b = self.brain
            self._vs('listening', 'click_listen', 'waiting for your phrase')
            for _ in range(80):             # at most ~8 s: her line is not that long
                if not b.listening:
                    return                  # clicked again while she was talking: called off
                if b.now >= b.talk_until and not self.talking():
                    break
                time.sleep(0.1)
            if not b.listening:
                return
            self.hush()                     # still sounding after the wait: she gives way to you
            ears.unmute()                   # her voice is gone: the ears open for you at once
            res = ears.listen(lang=self.settings.get('speech_lang', 'en'), secs=secs,
                              size=self.settings.get('stt_size', 'small'),
                              mic=self.settings.get('stt_mic'),
                              engine=self.settings.get('stt_engine'),
                              beam=self.settings.get('stt_beam', 5))
            text = res.get('text') if isinstance(res, dict) else res
            vtxt = res.get('vosk', '') if isinstance(res, dict) else ''
            self._vs('held', 'processing the heard phrase')
            GLib.idle_add(lambda t=text, v=vtxt: self.ev(lambda b: b.heard(t, v)) and False)
        threading.Thread(target=work, daemon=True).start()

    def followup_listen(self, cid):
        """conversation mode: hear the next phrase without a wake word.

        Called only from the wake-loop thread, so no ``/wake`` can be holding
        the microphone at the same time.  The TTS is over (the caller checked
        ``talk_until`` and ``talking()``), so her own self-mute has expired too.
        Silence closes the dialogue quietly — no «я ничего не услышала» on
        every pause (hand-off §3.5).
        """
        b = self.brain
        conv = b.conversation
        secs = float(self.settings.get('conversation_timeout_s', 10))
        conv.wait_start(b.now, secs)
        self._vs('followup', 'the answer is over: waiting for your next phrase')
        ears.unmute()                 # her voice is gone: the ears open at once
        self.followup_waiting = True
        join = (bool(self.settings.get('speaker_verify', False))
                and self.settings.get('speaker_join_policy', 'addressed') != 'off')
        try:
            res = ears.listen(lang=self.settings.get('speech_lang', 'en'), secs=secs,
                              size=self.settings.get('stt_size', 'small'),
                              mic=self.settings.get('stt_mic'),
                              engine=self.settings.get('stt_engine'),
                              beam=self.settings.get('stt_beam', 5), join=join)
        finally:
            self.followup_waiting = False
        if conv.stale(cid) or not conv.active:
            return                  # stopped, slept, hid or reset while we listened
        if not res:
            GLib.idle_add(lambda: self.ev(
                lambda br: br.conversation_close('ears')) and False)
            return
        text = res.get('text') or ''
        alt = res.get('vosk') or ''
        if not text and not alt:
            GLib.idle_add(lambda: self.ev(
                lambda br: br.conversation_close('silence')) and False)
            return
        self._vs('held', 'processing the follow-up phrase')
        spk = res.get('speaker') if isinstance(res, dict) else None
        conv.waiting_answer = True      # the wake loop must not listen again just yet
        GLib.idle_add(lambda t=text, v=alt, s=spk: self.ev(
            lambda br: br.heard_text(t, wake=True, alt=v, followup=True,
                                     speaker=s, join=join)) and False)

    def talking(self):
        """her voice is sounding at this very moment"""
        p = self.voice_proc
        return bool(p) and p.poll() is None

    def duck_begin(self):
        """her name was heard: the sounds duck so the ears hear the phrase.
        The loudness before the duck is remembered and comes back in a while,
        unless you set the volume yourself — then the new level stays"""
        if not self.settings.get('name_duck'):
            return
        if self.duck_restore:
            GLib.source_remove(self.duck_restore)
        self.duck_restore = GLib.timeout_add(self.DUCK_BACK_MS, self.duck_end)
        if self.duck_saved is not None:
            return                      # already low: the first loudness is the one to keep
        try:
            saved = music.read_volume()
            if saved is None:
                print('yumi: the duck could not read the volume, it stays as it is')
                return
            self.duck_saved = saved
            music.system_volume(f'volume {min(saved, self.DUCK_LEVEL)}')
        except Exception:
            self.duck_saved = None

    def duck_keep(self):
        """a volume command went through: the level she just named is the one that stays"""
        if self.duck_restore:
            GLib.source_remove(self.duck_restore)
        self.duck_restore = None
        self.duck_saved = None

    def duck_end(self):
        """the phrase is over: the loudness you had comes back"""
        self.duck_restore = None
        saved, self.duck_saved = self.duck_saved, None
        if saved is not None:
            try:
                music.system_volume(f'volume {saved}')
            except Exception:
                pass
        return False

    def self_mute(self, secs):
        """her ears close while she speaks (system.play_file keeps the mute alive only
        while the sound plays): a click-listen waits her out anyway, and the wake's
        recorder drops the wake logic until the window runs out — she cannot wake to
        her own words, with or without the echo canceller; a shout of «стоп» gets
        through (the daemon judges the phrases it hears for a stop and nothing else)
        (stt_selfmute)"""
        if not self.settings.get('stt_selfmute', True):
            return
        threading.Thread(target=ears.mute, args=(secs,), daemon=True).start()

    def wake_hints(self, b):
        """the user's own phrases and keywords from actions.json: the ears run in
        another process, so a custom button's wish is passed into the wake router
        (yumi/addressing.py) or the fallback would not know it"""
        return addressing.hints_from(getattr(b, 'custom', None))

    def _vs(self, method, *args):
        """publish a voice-state transition on the GTK thread (safe from any worker)"""
        try:
            GLib.idle_add(lambda: getattr(self.voice_state, method)(*args) and False)
        except Exception:
            pass

    def wake_set(self, on):
        """the wake word: while it is on, a loop keeps the daemon listening for her name
        and, the moment it passes by, the phrase that follows goes straight to her mind"""
        self.wake_on = bool(on)
        if not self.wake_on:
            # A paused loop can still be inside a /wake HTTP call.  Bump the
            # generation so that even if it returns after we resume, it drops
            # out instead of silently stealing the microphone back.
            self.wake_gen = getattr(self, 'wake_gen', 0) + 1
            self.wake_waiting = False
            self._vs('wake_off')
            if self.wake_thread:            # a /wake may still be waiting: let it off the mic
                threading.Thread(target=ears.stop, daemon=True).start()
            return
        gen = getattr(self, 'wake_gen', 0)
        if (self.wake_thread and self.wake_thread.is_alive()
                and getattr(self, 'wake_thread_gen', gen) == gen):
            return
        self.wake_thread = None             # a stale or dead thread is not a live ear
        self._vs('wake_on')

        def work():
            b = self.brain
            while self.wake_on and gen == self.wake_gen:
                time.sleep(0.15)
                if gen != self.wake_gen:
                    return                  # paused while we were sleeping
                conv = getattr(b, 'conversation', None)
                if (conv and conv.active and self.settings.get('conversation_mode', False)
                        and not b.listening):
                    # One microphone, one owner: for the whole dialogue this loop
                    # owns the ears.  While she thinks or speaks it holds no /wake
                    # (so she cannot wake to her own voice); once it is quiet,
                    # the same loop listens for the next phrase without a name.
                    if b.thinking or self.talking() or b.now < b.talk_until:
                        # thinking and speaking are not silence: push the deadline
                        # forward so a long answer cannot expire its own follow-up
                        conv.hold(b.now, float(self.settings.get('conversation_timeout_s', 10)))
                        continue
                    if getattr(conv, 'waiting_answer', False):
                        continue            # a phrase is already on its way to her mind
                    if conv.due(b.now):
                        GLib.idle_add(lambda: self.ev(
                            lambda br: br.conversation_close('timeout')) and False)
                        continue
                    self.followup_listen(conv.id)
                    continue
                if b.listening:
                    continue            # the mic is lent to a click-listen: not ours now
                self._vs('listening', 'wake', 'listening for the wake word')
                self.wake_waiting = True
                try:
                    res = ears.wake(lang=self.settings.get('speech_lang', 'en'),
                                    word=self.settings.get('wake_word', 'юми'), secs=120,
                                    size=self.settings.get('stt_size', 'small'),
                                    mic=self.settings.get('stt_mic'),
                                    sensitivity=self.settings.get('wake_sensitivity', 'normal'),
                                    confirm=self.settings.get('wake_confirm', True),
                                    model_size=self.settings.get('wake_model_size', 'small'),
                                    judge_log=self.settings.get('wake_judge_log', True),
                                    engine=self.settings.get('stt_engine'),
                                    beam=self.settings.get('stt_beam', 5),
                                    oww_ear=self.settings.get('wake_ear', 'auto'),
                                    hints=self.wake_hints(b))
                finally:
                    # A stale loop must not clear the flag of the fresh one.
                    if gen == self.wake_gen:
                        self.wake_waiting = False
                if not self.wake_on or gen != self.wake_gen:
                    continue            # called off while the daemon was listening
                if not res:
                    self._vs('missing', 'the ears are away')
                    continue            # the ears are away
                if res.get('stop'):
                    # «стоп» overrides everything: even mid-word, asleep or thinking
                    GLib.idle_add(lambda: self.ev(lambda b: b.stop_all()) and False)
                    continue
                if res.get('cmd'):
                    # «тише» / «громче» без имени: тот же путь, что у «стоп» —
                    # маленькое ухо слышало слово, пока она ждёт имя, громкость
                    # поворачивается сразу, без обращения и без разговора с умом
                    cmd = res['cmd']
                    GLib.idle_add(lambda c=cmd: self.ev(
                        lambda br: br.music_control(c)) and False)
                    continue
                if not res.get('woke'):
                    continue            # quiet: nobody called her name
                self._vs('candidate')
                self._vs('held', 'wake word heard: waiting for the phrase')
                tail = res.get('text') or ''
                alt = res.get('alt') or ''  # the stop ear's reading, the other ear
                fb = bool(res.get('fallback'))   # the name from vosk, not from the trained ear
                spk = res.get('speaker')        # optional: a profile from the name's voice
                GLib.idle_add(self.duck_begin)   # her name passed: quiet now, whatever comes
                if b.thinking or b.listening:
                    continue            # she got busy in those seconds: the word is spent
                # the name was heard: the moth that marks where she hides becomes the
                # girl — asleep she wakes, hidden she comes out, right now, while the
                # phrase (or the wait for it) is still going
                GLib.idle_add(lambda: self.ev(lambda br: br.wake_form()) and False)
                if b.now < b.talk_until or self.talking():
                    self.hush()         # her own line was still sounding: it dies, your turn now
                if tail:
                    # name + text already recognised: pass the whole phrase straight to the brain
                    GLib.idle_add(lambda t=tail, a=alt, f=fb, s=spk:
                                  self.ev(lambda br: br.wake_up(t, a, f, speaker=s)) and False)
                else:
                    # «юми» без текста: ухо openWakeWord только имя ловит,
                    # команда за ней теряется — слушаем фразу, которая пошла после имени
                    cmd = ears.listen(lang=self.settings.get('speech_lang', 'ru'),
                                      secs=15,
                                      size=self.settings.get('stt_size', 'small'),
                                      mic=self.settings.get('stt_mic'),
                                      engine=self.settings.get('stt_engine'),
                                      beam=self.settings.get('stt_beam', 5))
                    if cmd:
                        said = cmd.get('text') or ''
                        vtxt = cmd.get('vosk') or ''   # the other reading, as on the click-listen
                        cmd_spk = cmd.get('speaker') or spk
                        if said:
                            GLib.idle_add(lambda t=said, v=vtxt, s=cmd_spk:
                                          self.ev(lambda br: br.wake_up(t, v, speaker=s)) and False)
                        else:
                            # silence after the name: she asks what you wanted
                            GLib.idle_add(lambda s=cmd_spk: self.ev(
                                lambda br: br.wake_up('', speaker=s)) and False)
                    else:
                        # ears unavailable: fall back to asking
                        GLib.idle_add(lambda s=spk: self.ev(
                            lambda br: br.wake_up('', speaker=s)) and False)

        self.wake_thread = threading.Thread(target=work, daemon=True)
        self.wake_thread_gen = gen
        self.wake_thread.start()

    def wake_pause(self, timeout=6.0):
        """give the microphone to a one-off test from the panel: stop the wake
        loop and wait for its daemon window to close (True if it was running)"""
        was_on = bool(self.wake_on)
        self.wake_set(False)
        self._vs('wake_paused')
        t = self.wake_thread
        # Forget the thread even when the join times out.  It was told to
        # leave by wake_set(False) (and by the generation bump); keeping the
        # dead/tired handle would make wake_resume() think the mic is already
        # owned and leave her deaf for good after a panel test.
        self.wake_thread = None
        if t and t.is_alive():
            t.join(timeout)
        return was_on

    def wake_resume(self, was_on):
        """the panel's test is over: the wake loop takes the microphone back"""
        if not was_on:
            return
        self.wake_on = True
        self.wake_set(True)             # a fresh thread with a fresh generation
        self._vs('wake_resumed')

    # ---- voice profiles from the in-world menu (the panel uses the same daemon routes)
    def _wait_voice_quiet(self, timeout=8.0):
        """wait until TTS/blips finish so the mic records the user, not Yumi

        A whole line from speak() is not in voice_queue: it lives in
        voice_pending while it is synthesized and in voice_proc while it
        sounds.  Without both checks the enrollment mic opened a fraction of a
        second after the «Nazovi svoyo imya...» request and swallowed her own
        introduction — the user heard her speech skip and never learned what
        to say.
        """
        def sounding():
            p = getattr(self, 'voice_proc', None)
            return bool(p) and p.poll() is None

        deadline = time.time() + max(0.5, float(timeout))
        quiet = 0
        while time.time() < deadline:
            q = getattr(self, 'voice_queue', None) or []
            ready = getattr(self, '_voice_ready', None) or {}
            pending = int(getattr(self, 'voice_pending', 0) or 0)
            streaming = bool(getattr(self, 'voice_streaming', False))
            if not q and not ready and not pending and not streaming and not sounding():
                quiet += 1
                if quiet >= 3:          # ~0.3s of real silence
                    return True
            else:
                quiet = 0
            time.sleep(0.1)
        return False

    def _extract_acquaintance_info(self, text):
        """Pull name/city/music/work/hobbies from a free-form acquaintance transcript."""
        text = ' '.join(str(text or '').split()).strip()
        if not text:
            return {}
        settings = getattr(self.brain, 'settings', {}) or {}
        prompt = (
            'Extract user profile fields from this self-introduction. '
            'Return ONLY a JSON object with keys: '
            'name, city, music, work, hobbies, about. '
            'Use empty string for unknown fields. Keep values short. '
            'The "about" field may contain one short extra detail if present.\n\n'
            f'Text: {text}'
        )
        try:
            reply = chat.ask(settings, [{'role': 'user', 'content': prompt}], timeout=20)
        except Exception:
            reply = ''
        info = {}
        if reply:
            # try to find JSON in reply
            m = re.search(r'\{[\s\S]*\}', reply)
            if m:
                try:
                    data = json.loads(m.group(0))
                    if isinstance(data, dict):
                        for k in ('name', 'city', 'music', 'work', 'hobbies', 'about'):
                            v = data.get(k)
                            if isinstance(v, str) and v.strip():
                                info[k] = v.strip()[:256]
                except Exception:
                    pass
        if voices.is_generic_label(info.get('name')):
            info.pop('name', None)
        for key, value in local_profile_fields(text).items():
            if not info.get(key):
                info[key] = value
        if not info:
            info['about'] = text[:256]
        return info

    def _acquaintance_set(self, phase, action=None, **extra):
        cur = getattr(self, 'acquaintance', {}) or {}
        self.acquaintance = {
            'active': phase in ('waiting_tts', 'recording', 'processing'),
            'phase': str(phase),
            'action': action or cur.get('action'),
            'at': time.time(),
        }
        for k in ('label', 'already', 'error'):
            if k in extra:
                self.acquaintance[k] = extra[k]
            elif k in cur and phase not in ('waiting_tts',):
                self.acquaintance[k] = cur[k]
        web = getattr(self, 'web', None)
        if web and getattr(web, 'running', False):
            try:
                web.publish('status', self._web_snapshot(light=True))
            except Exception:
                pass

    def speaker_action(self, action, pid=None, label=None):
        """record/check/rename/forget a voice in a worker: the wake ear is lent to the mic"""
        if action not in ('speaker_enroll', 'speaker_test', 'speaker_clear',
                          'speaker_delete', 'speaker_rename', 'speaker_acquaintance'):
            return
        was_on = self.wake_pause()
        if action == 'speaker_acquaintance':
            self._acquaintance_set('waiting_tts', action)

        def work():
            try:
                if action == 'speaker_acquaintance':
                    # the introduction is a long line: let her finish saying
                    # what to tell us before the microphone starts recording
                    self._wait_voice_quiet(timeout=45.0)
                    def rec_start():
                        self._acquaintance_set('recording', action)
                        b = self.brain
                        b.set_face('listening', 6.0)
                        b.say_text('Слушаю, говори...' if str(b.settings.get('speech_lang', 'ru')) == 'ru'
                                   else 'Listening, speak now...', face='listening', voice=False)
                        return False
                    GLib.idle_add(rec_start)
                    time.sleep(0.15)  # let UI publish before blocking record
                if action in ('speaker_enroll', 'speaker_acquaintance'):
                    lang = str(getattr(self.brain, 'settings', {}).get('speech_lang', 'ru') or 'ru')
                    secs = 15.0 if action == 'speaker_acquaintance' else 4.0
                    result = ears.speaker_enroll(secs=secs, lang=lang)
                    if action == 'speaker_acquaintance' and isinstance(result, dict) and result.get('ok'):
                        text = str(result.get('text') or '').strip()
                        info = self._extract_acquaintance_info(text) if text else {}
                        spk_id = result.get('id')
                        name = str(info.get('name') or '').strip()
                        if spk_id and info:
                            upd = ears.speaker_update(spk_id, label=name or None, info=info)
                            if isinstance(upd, dict) and upd.get('ok'):
                                result['profile'] = upd.get('profile') or result.get('profile')
                                result['profiles'] = upd.get('profiles') or result.get('profiles')
                        if name:
                            result['label'] = name
                        result['extracted_info'] = info
                        # A deduped profile with no name yet still needs the
                        # interview: learning the name is a success, not «already».
                        result['name_learned'] = bool(name)
                elif action == 'speaker_test':
                    result = ears.speaker_test()
                elif action == 'speaker_delete':
                    result = ears.speaker_delete(pid)
                elif action == 'speaker_rename':
                    result = ears.speaker_rename(pid, label)
                    if isinstance(result, dict):
                        result.setdefault('label', label)
                else:
                    result = {'ok': True}
            except Exception as exc:                 # noqa: BLE001 - she says the failure
                result = {'ok': False, 'error': str(exc)[:160]}

            def done():
                if action == 'speaker_acquaintance':
                    self._acquaintance_set('processing', action)
                    b = self.brain
                    b.set_face('think', 4.0)
                    b.say_text('Запись закончена, обрабатываю...' if str(b.settings.get('speech_lang', 'ru')) == 'ru'
                               else 'Recording finished, processing...', face='think', voice=False)
                self.wake_resume(was_on)
                self._speaker_action_done(action, result, pid)
                if action == 'speaker_acquaintance':
                    ok = isinstance(result, dict) and bool(result.get('ok'))
                    label = ''
                    already = False
                    if isinstance(result, dict):
                        profile = result.get('profile') if isinstance(result.get('profile'), dict) else {}
                        label = str(result.get('label') or profile.get('label') or '')
                        if voices.is_generic_label(label):
                            label = ''
                        already = ok and not result.get('created', True) and not result.get('name_learned')
                    err = '' if ok else str((result or {}).get('error') or '')
                    self._acquaintance_set('done' if ok else 'error', action,
                                           label=label, already=already, error=err)
                return False
            GLib.idle_add(done)

        threading.Thread(target=work, daemon=True).start()

    def _speaker_action_done(self, action, result, pid=None):
        b = self.brain
        if not isinstance(result, dict) or not result.get('ok'):
            err = str((result or {}).get('error') or '')
            if action == 'speaker_acquaintance':
                if 'no model' in err.lower() or 'not available' in err.lower():
                    b.say('acquaintance_nomodel')
                else:
                    b.say('acquaintance_fail')
            else:
                b.say('speaker_fail')
            self.web_sync_soon()
            return
        if action in ('speaker_enroll', 'speaker_acquaintance'):
            pid = result.get('id') or pid
            profile = result.get('profile') if isinstance(result.get('profile'), dict) else {}
            name = str((result.get('extracted_info') or {}).get('name') or '').strip()
            label = (name
                     or profile.get('label')
                     or next((p.get('label') for p in (result.get('profiles') or [])
                              if p.get('id') == pid), None)
                     or str(pid or ''))
            label = '' if voices.is_generic_label(label) else str(label).strip()
            b._speaker_remember({'status': 'known', 'id': pid, 'score': 1.0,
                                 'joined_id': None})
            ru = str(b.settings.get('speech_lang', 'ru')) == 'ru'
            if action == 'speaker_acquaintance':
                if not result.get('created', True) and not name:
                    if label:
                        b.say('acquaintance_already', label=label)
                    else:
                        b.say_text('Мы уже знакомы. Назови своё имя, и я запомню его.'
                                   if ru else "We've met. Tell me your name so I can remember it.",
                                   voice=True)
                elif label:
                    b.say('acquaintance_ok', label=label)
                else:
                    b.say_text('Я запомнила твой голос. Назови имя позже — и я его узнаю.'
                               if ru else "I've remembered your voice. Tell me your name later and I'll know it.",
                               voice=True)
            else:
                b.say('speaker_ready', label=label or str(pid or ''))
        elif action == 'speaker_test':
            field = result.get('speaker') or {}
            if field.get('id'):
                b.say('speaker_found', label=b._voice_label(field['id']))
            else:
                b.say('speaker_unknown')
        elif action == 'speaker_rename':
            b.say('speaker_renamed', label=(result.get('label') or ''))
        elif action == 'speaker_delete':
            b.conversation.remove_participant(str(pid))
            if (getattr(b, '_speaker_current', None) or {}).get('id') == str(pid):
                b._speaker_current = None
        else:                                       # clear the participants, not the profiles
            b.conversation.clear_participants()
            b._pending_speaker = None
            b._speaker_current = None
            b._speaker_last_event = ''
        self.web_sync_soon()

    def tap_set(self, on):
        """the ears' diary: while it is on, the daemon records everything the ears hear
        into /tmp/yumi (the sound and the words), in its own thread beside her work"""
        def work():
            ears.tap(bool(on), lang=self.settings.get('speech_lang', 'en'),
                     size=self.settings.get('stt_size', 'small'),
                     mic=self.settings.get('stt_mic'))
        threading.Thread(target=work, daemon=True).start()

    def _chat_reply_remember(self, reply):
        """a streamed reply finished; memory was already saved by the worker"""
        return False

    def chat_ask(self, history):
        """the question is away to Ollama; the answer comes back into her bubble"""
        def work():
            s = self.settings
            lang = s.get('speech_lang', 'en')
            # the copy the worker walks: `history` is the caller's list, and an
            # assignment to it here would make every read of it a crash
            # (UnboundLocalError — every question died before the answer)
            hist = list(history)
            user_text = str(hist[-1].get('content') or '')   # the question just asked
            sassy = bool(s.get('sassy'))
            tag = memory.TAG_SASSY if sassy else None
            use_stream = bool(s.get('chat_stream', True))
            if use_stream:
                GLib.idle_add(lambda: self.ev(lambda b: b.reply_stream_begin()) and False)

            # the diary: older lines about the same thing join the question, the
            # talks about other things stay out of the way (yumi/memory.py)
            if s.get('chat_memory', True):
                try:
                    note = chat.recalled_note(
                        memory.recall(user_text, s, skip_recent=len(hist)), lang, s)
                except Exception:
                    note = ''
                if note:
                    hist.append({'role': 'system', 'content': note})
            prompt = chat.system_prompt(lang, sassy, s)
            full = [{'role': 'system', 'content': prompt}] + hist

            if not use_stream:
                reply = chat.ask(s, full)
                GLib.idle_add(lambda: self.ev(lambda b: b.replied(reply)) and False)
                if s.get('chat_memory', True) and bool(s.get('sassy')) == sassy:
                    def _remember():
                        try:
                            memory.remember('user', user_text, s, tag=tag)
                            if reply:
                                memory.remember('assistant', reply, s, tag=tag)
                        except Exception:
                            pass
                    threading.Thread(target=_remember, daemon=True).start()
                return
            reply_parts = []
            try:
                for chunk in chat.ask_stream(s, full):
                    if not chunk:
                        continue
                    reply_parts.append(chunk)
                    GLib.idle_add(lambda c=chunk: self.ev(lambda b: b.reply_stream_chunk(c)) and False)
            except Exception:
                pass

            reply = ' '.join(''.join(reply_parts).split())
            if reply:
                GLib.idle_add(lambda: self.ev(lambda b: b.reply_stream_end()) and False)
            else:
                GLib.idle_add(lambda: self.ev(lambda b: b.reply_stream_fail()) and False)

            if s.get('chat_memory', True) and bool(s.get('sassy')) == sassy and reply:
                def _remember():
                    try:
                        memory.remember('user', user_text, s, tag=tag)
                        memory.remember('assistant', reply, s, tag=tag)
                    except Exception:
                        pass
                threading.Thread(target=_remember, daemon=True).start()
        threading.Thread(target=work, daemon=True).start()

    def weather_ask(self, ask):
        """the weather question is away to the clouds; the peek comes back into her bubble"""
        def work():
            lang = self.settings.get('speech_lang', 'en')
            reply = chat.weather_report(ask.get('where', ''), lang, ask.get('when', 'today'))
            GLib.idle_add(lambda: self.ev(lambda b: b.said_weather(reply)) and False)
        threading.Thread(target=work, daemon=True).start()

    def music_who(self):
        """the «кто играет» question: the player is asked in its own thread
        (playerctl and mpc take a moment), the names go back into her bubble"""
        def work():
            playing = music.now_playing()
            GLib.idle_add(lambda: self.ev(lambda b: b.said_now_playing(playing)) and False)
        threading.Thread(target=work, daemon=True).start()

    def music_like(self):
        """«лайк»: the current track is marked as favorite away from her main thread"""
        def work():
            report = music.like_playing(self.settings)
            GLib.idle_add(lambda: self.ev(lambda b: b.said_music_liked(report)) and False)
        threading.Thread(target=work, daemon=True).start()

    def music_search(self, payload):
        """«включи песню ...»: the libraries are asked away from her main thread
        (a search walks the network and her folders, then the queue is built),
        the report goes back into her bubble"""
        def work():
            music.apply_settings(self.settings)
            report = music.play_query(payload.get('kind', 'song'),
                                      payload.get('query', ''), self.settings)
            GLib.idle_add(lambda: self.ev(lambda b: b.said_music_found(report)) and False)
        threading.Thread(target=work, daemon=True).start()

    def hourly_ask(self, payload):
        """her mind is asked for a funny line about this hour; the reply goes back to the brain"""
        def work():
            lang = payload.get('lang', 'en')
            hour = int(payload.get('hour', time.localtime().tm_hour))
            joke = chat.hourly_joke(self.settings, hour, lang)
            GLib.idle_add(lambda: self.ev(lambda b: b.hour_joked({'joke': joke})) and False)
        threading.Thread(target=work, daemon=True).start()

    def joke_ask(self, payload):
        """her mind is asked for a joke; the request and the joke go into the
        diary tagged (the vectors too), and in «Дерзкая 18+» the fourth one in a
        row gets a model-written brush-off instead"""
        def work():
            s = self.settings
            lang = payload.get('lang', 'en')
            sassy = bool(s.get('sassy'))
            tag = memory.TAG_SASSY_JOKE if sassy else memory.TAG_JOKE
            asked = str(payload.get('text') or '').strip() or (
                'анекдот' if str(lang) == 'ru' else 'a joke')
            # how many jokes in a row this one makes: the diary holds the ones
            # already asked, the current request has not been written down yet
            try:
                streak = memory.joke_streak(tag) + 1
            except Exception:
                streak = 1
            tired = sassy and streak >= chat.JOKE_TIRED_AFTER
            reply = chat.joke_tired(s, lang, streak) if tired else chat.joke(s, lang)
            GLib.idle_add(lambda: self.ev(lambda b: b.joked(reply, tired)) and False)
            # the request and the joke go into the diary tagged, with their
            # vectors (the jokes are written even when the resting chats are
            # not: the run is counted from them, and the mode's lines must be
            # found and wiped when «Дерзкая 18+» goes off)
            if bool(s.get('sassy')) != sassy:
                return                  # the mode changed mid-joke: leave the diary clean
            try:
                memory.remember('user', asked, s, tag=tag)
                if reply:
                    memory.remember('assistant', reply, s, tag=tag)
            except Exception:
                pass
        threading.Thread(target=work, daemon=True).start()

    def note_voice(self, wish):
        """the notes' answer to a spoken phrase: a new note goes into the book, a
        search reads the closest ones back; both away from the GTK thread (the
        embedder may be slow or missing)"""
        action = str((wish or {}).get('action') or '')
        text = str((wish or {}).get('text') or '')
        query = str((wish or {}).get('query') or '')

        def work():
            try:
                if action == 'add':
                    note = notes.add(text, self.settings, source='voice')
                    if self.web:
                        self.web.publish('notes', {'action': 'add', 'note': note})
                    GLib.idle_add(lambda: self.ev(lambda b: b.note_saved(note)) and False)
                    return
                if action == 'last':
                    items = notes.recent(1)
                    if items:
                        note = items[0]
                        try:
                            summary = chat.summarize(
                                self.settings, note.get('title'), note.get('text'),
                                self.settings.get('speech_lang', 'en'))
                        except Exception:
                            summary = ''
                        items = [dict(note, summary=summary or notes.brief(note.get('text')))]
                elif action == 'list':
                    items = notes.recent(5)
                else:
                    items = notes.search(query, self.settings, limit=5)
                payload = {'action': action, 'items': items, 'query': query}
                GLib.idle_add(lambda: self.ev(lambda b: b.note_found(payload)) and False)
            except Exception:
                GLib.idle_add(lambda: self.ev(lambda b: b.note_failed()) and False)
        threading.Thread(target=work, daemon=True).start()

    def fetch_chat_models(self):
        """the installed Ollama models, for Settings → Her mind → Answer model"""
        def work():
            names = chat.models(self.settings)
            GLib.idle_add(lambda: self.ev(lambda b: b.chat_models_loaded(names)) and False)
        threading.Thread(target=work, daemon=True).start()

    def fetch_mics(self):
        """the microphones her ears can hear, for Settings → Her ears → Microphone"""
        def work():
            mics = ears.mics()
            GLib.idle_add(lambda: self.ev(lambda b: b.mics_loaded(mics)) and False)
        threading.Thread(target=work, daemon=True).start()
