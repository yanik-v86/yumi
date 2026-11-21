"""The optional browser panel and the App-side helpers its bridge calls (a mixin for App)."""
import json
import os
import shutil
import sys
import threading
import time
from pathlib import Path

from gi.repository import Gdk, GLib

from yumi import (chat, config, doctor, ears, engines, memory, models, music,
                  notes, permission, pixui, system, tts, webpanel)
from yumi.sprites import ui_colors
from yumi.webpanel import catalog as webcatalog

from .bridge import WebBridge


class PanelMixin:
    """Lifecycle of the HTTP panel plus the snapshot/settings/config calls behind it."""

    # ------------------------------------------------------------------ browser panel
    def load_web_chat(self):
        """the panel's own conversation, so a browser reload does not lose the talk.

        New files hold the messages, their revision and a short op journal; the
        old plain list is still read (and gets message ids) without losing a line.
        """
        try:
            data = json.loads(self.web_chat_path.read_text())
        except (OSError, ValueError):
            return []
        messages, rev, ops = [], 0, []
        if isinstance(data, dict):
            raw = data.get('messages')
            if isinstance(raw, list):
                messages = [m for m in raw if isinstance(m, dict) and m.get('text')][-100:]
            try:
                rev = max(0, int(data.get('rev') or 0))
            except (TypeError, ValueError):
                rev = 0
            raw_ops = data.get('ops')
            if isinstance(raw_ops, list):
                ops = [o for o in raw_ops
                       if isinstance(o, dict) and o.get('op') in ('insert', 'update', 'remove', 'clear')][-200:]
        elif isinstance(data, list):
            messages = [m for m in data if isinstance(m, dict) and m.get('text')][-100:]
        if not messages:
            self.web_chat_rev, self.web_chat_ops = rev, ops
            return []
        # every message needs an id: update/remove ops name it, not its position
        for i, message in enumerate(messages, 1):
            if not message.get('id'):
                message['id'] = f'm{i}'
        op_rev = max((int(o.get('rev') or 0) for o in ops), default=0)
        self.web_chat_rev = max(rev, op_rev)
        self.web_chat_ops = ops
        return messages

    def save_web_chat(self):
        try:
            self.web_chat_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.web_chat_path.with_suffix('.tmp')
            payload = {'messages': self.web_chat[-100:], 'rev': self.web_chat_rev,
                       'ops': self.web_chat_ops[-200:]}
            tmp.write_text(json.dumps(payload, indent=1, ensure_ascii=False))
            try:
                os.chmod(tmp, 0o600)
            except OSError:
                pass
            tmp.replace(self.web_chat_path)
        except OSError:
            pass

    # ---- chat change journal: one revision per op, published over SSE --------
    def _web_chat_op(self, op, **fields):
        """record one mutation under web_chat_lock; returns the SSE op"""
        self.web_chat_rev += 1
        entry = {'rev': self.web_chat_rev, 'op': op}
        entry.update(fields)
        self.web_chat_ops.append(entry)
        self.web_chat_ops = self.web_chat_ops[-200:]
        return entry

    def _web_chat_publish(self, ops):
        """let every open tab see the same chat change"""
        if not ops:
            return
        web = self.web
        if not web or not web.running:
            return
        try:
            web.publish('chat', {'rev': self.web_chat_rev, 'ops': ops})
        except Exception:
            pass

    def _web_chat_insert(self, message):
        """append one message and journal the insert (call under web_chat_lock)"""
        entry = dict(message)
        entry.setdefault('id', f'm{self.web_chat_rev + 1}')
        op = self._web_chat_op('insert', message=dict(entry))
        self.web_chat.append(entry)
        self.web_chat = self.web_chat[-100:]
        return op

    def _web_chat_update(self, message_id, patch):
        """edit one message by id; missing ids are a no-op, not an exception"""
        op = None
        with self.web_chat_lock:
            for message in self.web_chat:
                if str(message.get('id')) == str(message_id):
                    changes = {k: str(v)[:8000] for k, v in (patch or {}).items()
                               if k in ('text',) and isinstance(v, (str, int, float))}
                    if not changes:
                        break
                    message.update(changes)
                    op = self._web_chat_op('update', id=str(message_id), patch=changes)
                    self.save_web_chat()
                    break
        self._web_chat_publish([op] if op else [])
        return {'ok': bool(op), 'rev': self.web_chat_rev, 'ops': [op] if op else []}

    def _web_chat_remove(self, message_id):
        op = None
        with self.web_chat_lock:
            before = len(self.web_chat)
            self.web_chat = [m for m in self.web_chat
                             if str(m.get('id')) != str(message_id)]
            if len(self.web_chat) != before:
                op = self._web_chat_op('remove', id=str(message_id))
                self.save_web_chat()
        self._web_chat_publish([op] if op else [])
        return {'ok': bool(op), 'rev': self.web_chat_rev, 'ops': [op] if op else []}

    def web_config_sig(self):
        try:
            return (bool(self.settings.get('web_panel')), str(self.settings.get('web_panel_host')),
                    int(self.settings.get('web_panel_port') or 8765),
                    int(self.settings.get('web_panel_session_hours') or 168))
        except (TypeError, ValueError):
            return (bool(self.settings.get('web_panel')), '127.0.0.1', 8765, 168)

    def web_sync_soon(self):
        """a setting changed: start/stop/restart after the frame, so the response can leave"""
        if self.web_sync_src:
            return
        self.web_sync_src = GLib.timeout_add(250, self._web_sync_later)

    def _web_sync_later(self):
        self.web_sync_src = None
        self.web_sync()
        return False

    def _web_panel_report(self, state, detail=''):
        """say the panel's state only when it changes: retries must not spam the log"""
        report = (state, str(detail))
        if getattr(self, 'web_report', None) == report:
            return
        self.web_report = report
        if state == 'on':
            print(f'yumi: browser panel at {detail}', file=sys.stderr)
            return
        print(f'yumi: the browser panel did not start: {detail}', file=sys.stderr)
        b = getattr(self, 'brain', None)
        if b:
            b.say_text(config.tr(self.settings, 'web_fail', err=detail or 'port is busy'))

    def web_sync(self):
        sig = self.web_config_sig()
        if not sig[0]:
            if self.web:
                self.web.stop()
                self.web = None
            self.web_sig = None
            self.web_opened = False
            self.web_report = None
            return
        if self.web and self.web.running and self.web_sig == sig:
            self.web.auth.set_session_hours(sig[3])
            return
        if self.web:
            self.web.stop()
            self.web = None
        panel = webpanel.Panel(self.settings, WebBridge(self))
        if panel.start():
            self.web = panel
            self.web_sig = sig
            self._web_panel_report('on', panel.url(True))
            if self.settings.get('web_panel_open') and not self.web_opened:
                self.web_opened = True
                system.open_url(panel.url(True))
        else:
            self.web = None
            self.web_sig = None
            self._web_panel_report('off', panel.error or 'port is busy')

    def web_open(self):
        was_running = bool(self.web and self.web.running)
        if not self.settings.get('web_panel'):
            self.settings['web_panel'] = True
            self.settings.save()
            self.web_sync()
        elif not self.web:
            self.web_sync()
        if self.web and self.web.running:
            # web_sync() may already have opened the browser via web_panel_open
            if was_running or not self.settings.get('web_panel_open'):
                system.open_url(self.web.url(True))
            self.brain.say_text(config.tr(self.settings, 'web_on', url=self.web.url(False)))
        else:
            err = (self.web.error if self.web else 'port is busy') or 'port is busy'
            self.brain.say_text(config.tr(self.settings, 'web_fail', err=err))

    def web_copy(self):
        if not self.web or not self.web.running:
            self.web_sync()
        if self.web and self.web.running:
            url = self.web.url(True)
            if not system.copy_text(url):
                Gdk.Display.get_default().get_clipboard().set(url)
            self.brain.say_text(config.tr(self.settings, 'web_on', url=self.web.url(False)))
        else:
            self.brain.say_text(config.tr(self.settings, 'web_off'))

    def web_rotate(self):
        if not self.web or not self.web.running:
            self.brain.say_text(config.tr(self.settings, 'web_off'))
            return
        token = self.web.rotate()
        url = self.web.url(False) + '?t=' + token
        if not system.copy_text(url):
            Gdk.Display.get_default().get_clipboard().set(url)
        self.brain.say_text(config.tr(self.settings, 'web_on', url=self.web.url(False)))

    def _web_call(self, fn, timeout=30):
        """run a bridge call on the GTK thread; the HTTP worker waits for the answer"""
        if threading.current_thread() is threading.main_thread():
            return fn()
        box = {}
        done = threading.Event()

        def run():
            try:
                box['value'] = fn()
            except BaseException as exc:      # the HTTP layer turns it into a response
                box['error'] = exc
            finally:
                done.set()
            return False
        GLib.idle_add(run)
        if not done.wait(timeout):
            raise TimeoutError('Yumi is busy')
        if 'error' in box:
            raise box['error']
        return box.get('value')

    def web_tick(self):
        """the live feed: the bubble and a light status, only while a browser listens"""
        web = self.web
        if not web or not web.running:
            return
        with web.bus.lock:
            listening = bool(web.bus.subs)
        if not listening:
            return
        b = self.brain
        text = str((b.bubble or {}).get('text') or '')
        if text != self._web_bubble:
            self._web_bubble = text
            web.publish('bubble', {'text': text,
                                   'kind': (b.bubble or {}).get('kind'),
                                   'until': (b.bubble or {}).get('until')})
        now = time.monotonic()
        if now - self._web_status_at > 2.0:
            self._web_status_at = now
            try:
                web.publish('status', self._web_snapshot(light=True))
            except Exception:
                pass

    @staticmethod
    def _hex_color(rgb, fallback=None):
        try:
            if isinstance(rgb, str):
                return rgb
            return '#%02x%02x%02x' % tuple(max(0, min(255, round(float(c) * 255))) for c in rgb[:3])
        except (TypeError, ValueError):
            return fallback or '#c7a8db'

    def _web_snapshot(self, light=False):
        b = self.brain
        s = self.settings
        st = self.state
        now = time.monotonic()
        if now - self._web_music_at > 4.0:
            self._web_music_at = now
            try:
                self._web_music = music.now_playing()
            except Exception:
                self._web_music = None
            try:
                self._web_volume = music.read_volume()
            except Exception:
                self._web_volume = None
        tm = b.timer or {}
        timer = {
            'seconds': int(round(b.timer_seconds())),
            'text': b.timer_text() if tm else '',
            'running': bool(tm and not tm.get('done') and tm.get('end') is not None),
            'pending': bool(tm.get('pending')),
            'paused': bool(tm.get('paused')),
            'done': bool(tm.get('done')),
        }
        palette = self.palette or {}
        ui = {}
        try:
            ui = {k: self._hex_color(v) for k, v in ui_colors(palette).items()}
        except Exception:
            pass
        queue = self.queue
        cur = queue.current if queue else None
        jobs = {
            'busy': bool(queue.busy) if queue else False,
            'current': None if not cur else {
                'op': cur.op, 'src': str(cur.src), 'arg': cur.arg,
                'fraction': round(float(cur.fraction or 0), 3)},
            'queued': [{'op': j.op, 'src': str(j.src), 'arg': j.arg}
                       for j in (queue.jobs if queue else [])][:20],
        }
        conv = (b.conversation_snapshot() if hasattr(b, 'conversation_snapshot') else
                {'active': False, 'source': None, 'since': 0, 'until': 0,
                 'remaining': 0, 'last_at': 0, 'exchanges': 0, 'timeout': 10,
                 'waiting_answer': False, 'reason': '', 'id': 0})
        data = {
            'time': time.time(),
            'version': __import__('yumi').__version__,
            'uptime': int(time.time() - self.started),
            'settings': webcatalog.redact(s),
            'state': {
                'mode': st.get('mode'), 'monitor': st.get('monitor'),
                'shelf': st.get('shelf') or [], 'colors': st.get('colors') or [],
            },
            'runtime': {
                'mode': b.mode, 'out': bool(b.out), 'sleeping': bool(b.sleeping),
                'pinned': bool(s.get('pinned')), 'thinking': bool(b.thinking),
                'listening': bool(b.listening), 'busy': bool(b.busy),
                'progress': b.progress,
                'bubble': (b.bubble or {}).get('text') or '',
                'face': b.face,
                'timer': timer,
                'monitors': int(getattr(b, 'monitors', 1) or 1),
                'chat_models': list(b.chat_models or []),
                'mics': list(b.mics or []),
                'unavailable': sorted(b.unavailable or []),
                'palette': palette,
                'ui_colors': ui,
                'music': {'now_playing': self._web_music, 'volume': self._web_volume},
                'nlu': {'last_intent': getattr(b, 'last_intent', ''),
                        'last_confidence': round(float(getattr(b, 'last_confidence', 0.0)), 3),
                        'confirm': bool(getattr(b, 'intent_confirm', None)),
                        'pending_permission': (b.permission_snapshot()
                                               if hasattr(b, 'permission_snapshot') else None)},
                'wake_on': bool(self.wake_on),
                'conversation': conv,
                'conversation_active': bool(conv.get('active')),
                'voice_state': (self.voice_state.snapshot() if hasattr(self, 'voice_state')
                                else {'state': 'off', 'owner': None, 'generation': 0,
                                      'since': 0, 'reason': '', 'wake_enabled': False,
                                      'transitions': []}),
                'doctor': getattr(self, 'doctor_last', None),
                'models_check': models.cached(),
                'tap_ears': bool(s.get('tap_ears')),
                'voice': dict(engines.status(s), tts_error=tts.last_error),
                'downloads': self.dl_announced,
                'outfit': getattr(self.meta, 'outfit', None),
                'shelf_count': len([p for p in (st.get('shelf') or []) if Path(p).exists()]),
                'recent_count': len(getattr(self.recent, 'items', {}) or {}),
                'notes_count': notes.count(),
            },
            'jobs': jobs,
            'panel': self.web.info() if self.web else {'running': False},
            'features': {
                'ffmpeg': bool(shutil.which('ffmpeg')),
                'magick': bool(shutil.which('magick') or shutil.which('convert')),
                'playerctl': bool(shutil.which('playerctl')),
                'mpd': bool(shutil.which('mpc') or shutil.which('mpd')),
                'idle': bool(getattr(self.world, 'can_idle', False)),
                'wallpaper': bool(getattr(self.world, 'wall', None)),
                'desktop': 'wayland',
            },
        }
        if not light:
            data['settings_full'] = webcatalog.redact(s)
        return data

    def _web_apply_settings(self, patch):
        old = {k: self.settings.get(k) for k in patch}
        self.settings.update(patch)
        self.settings.save()
        b = self.brain
        if 'outfit' in patch:
            b.requests.append(('outfit',))
        if 'recolor' in patch or 'hue' in patch:
            b.requests.append(('recolor',))
        if 'wake_ears' in patch:
            b.requests.append(('wake_set', bool(self.settings.get('wake_ears'))))
            if not self.settings.get('wake_ears'):
                b.conversation_close('wake off')
        if 'conversation_mode' in patch and not self.settings.get('conversation_mode'):
            b.conversation_close('setting')
        if 'conversation_timeout_s' in patch:
            try:
                b.conversation.timeout = float(self.settings.get('conversation_timeout_s', 10))
            except (TypeError, ValueError):
                pass
        if 'tap_ears' in patch:
            b.requests.append(('tap_set', bool(self.settings.get('tap_ears'))))
        if 'pinned' in patch and self.settings.get('pinned'):
            b.pop(True)
        if 'sassy' in patch and not self.settings.get('sassy'):
            b.chat_history = []
            threading.Thread(target=memory.clear_tag, args=(memory.TAG_SASSY,),
                             daemon=True).start()
        if 'nlu' in patch and not self.settings.get('nlu'):
            b.intent_confirm = None         # voice commands switched off: no pending answer
        # nlu_confidence is read from settings on every phrase, so it applies at once
        if 'chat_provider' in patch:
            b.chat_models = []
            b.requests.append(('chat_models',))
        if any(k.startswith('tts_') for k in patch):
            try:
                tts.sync_profile(self.settings)
            except Exception:
                pass
        try:
            music.apply_settings(self.settings)
        except Exception:
            pass
        self.web_sync_soon()
        return {'saved': {k: self.settings.get(k) for k in patch},
                'before': old, 'restart': 'scale' in patch}

    def _web_timer_get(self):
        b = self.brain
        tm = b.timer or {}
        return {'seconds': int(round(b.timer_seconds())), 'text': b.timer_text() if tm else '',
                'running': bool(tm and not tm.get('done') and tm.get('end') is not None),
                'pending': bool(tm.get('pending')), 'paused': bool(tm.get('paused')),
                'done': bool(tm.get('done'))}

    def _web_timer(self, action, seconds):
        b = self.brain
        try:
            secs = int(seconds or 0)
        except (TypeError, ValueError):
            raise ValueError('seconds must be a number')
        if action in ('set', 'start'):
            if secs <= 0:
                b.timer = None
                b.kb_hover = False
            else:
                b.timer_set(min(secs, 24 * 3600 - 1), start_in=0)
                if b.mode == 'docked' and not b.out:
                    b.pop(True)
        elif action == 'add':
            b.timer_set(int(b.timer_seconds()) + max(1, secs), start_in=0)
        elif action == 'stop':
            b.timer = None
            b.kb_hover = False
        elif action == 'pause':
            tm = b.timer
            if tm and not tm.get('done'):
                tm['left'] = b.timer_seconds()
                tm['end'] = None
                tm['pending'] = None
                tm['paused'] = True
        elif action == 'resume':
            tm = b.timer
            if tm and not tm.get('done'):
                left = tm.get('left') or tm.get('total') or 0
                tm['end'] = b.now + left
                tm['pending'] = None
                tm['paused'] = False
        else:
            raise ValueError('unknown timer action')
        return {'timer': self._web_timer_get()}

    def _web_backup(self, name, path):
        path = Path(path)
        if not path.exists():
            return ''
        try:
            folder = config.CONFIG_DIR / 'backups'
            folder.mkdir(parents=True, exist_ok=True)
            dest = folder / f"{name}-{time.strftime('%Y%m%d-%H%M%S')}.json"
            shutil.copyfile(path, dest)
            old = sorted(folder.glob(f'{name}-*.json'))
            for extra in old[:-20]:
                try:
                    extra.unlink()
                except OSError:
                    pass
            return str(dest)
        except OSError:
            return ''

    def _web_config_info(self, name):
        spec = webcatalog.CONFIG_FILES[name]
        path = Path(spec['path']())
        try:
            st = path.stat()
            return {'name': name, 'path': str(path), 'exists': True,
                    'size': st.st_size, 'mtime': st.st_mtime,
                    'title': spec['title'], 'kind': spec['kind']}
        except OSError:
            return {'name': name, 'path': str(path), 'exists': False,
                    'size': 0, 'mtime': 0, 'title': spec['title'], 'kind': spec['kind']}

    def _web_configs(self):
        return [self._web_config_info(name) for name in webcatalog.CONFIG_FILES]

    def _web_config_get(self, name):
        info = self._web_config_info(name)
        spec = webcatalog.CONFIG_FILES[name]
        path = Path(spec['path']())
        writable = name != 'webpanel'
        data = None
        raw = ''
        if name == 'settings':
            data = webcatalog.redact(self.settings)
            raw = json.dumps(data, indent=1, ensure_ascii=False)
        elif name == 'actions':
            data = [dict(a) for a in self.brain.custom]
            raw = path.read_text() if path.exists() else json.dumps(data, indent=1, ensure_ascii=False)
        elif name == 'state':
            data = dict(self.state)
            raw = json.dumps(data, indent=1, ensure_ascii=False)
        elif name == 'webpanel':
            data = {'token': webcatalog.MASK if self.web else '',
                    'secret': webcatalog.MASK, 'created': None,
                    'path': str(path), 'note': 'managed on the Security page'}
            raw = json.dumps(data, indent=1, ensure_ascii=False)
        else:
            try:
                text = path.read_text()
            except OSError:
                text = '{\n}\n'
            try:
                data = json.loads(text)
            except ValueError:
                data = None
            raw = text
        return {'file': info, 'data': data, 'text': raw, 'writable': writable}

    def _web_config_save(self, name, value):
        if name not in webcatalog.CONFIG_FILES:
            raise ValueError('unknown config file')
        if name == 'webpanel':
            raise ValueError('the panel token is changed on the Security page')
        spec = webcatalog.CONFIG_FILES[name]
        path = Path(spec['path']())
        if isinstance(value, str):
            try:
                data = json.loads(value)
            except ValueError as exc:
                raise ValueError(f'this is not JSON: {exc}')
        else:
            data = value
        backup = self._web_backup(name, path)
        if name == 'settings':
            if not isinstance(data, dict):
                raise ValueError('settings must be an object')
            patch = webcatalog.validate_settings_patch(data)
            result = self._web_apply_settings(patch)
            return {'saved': list(patch), 'backup': backup, 'restart': result.get('restart')}
        if name == 'actions':
            cleaned = self._clean_actions(data)
            config.save_actions(cleaned)
            self.brain.custom = config.load_actions()
            self.brain.actions_check()
            return {'saved': len(cleaned), 'backup': backup}
        if name == 'state':
            if not isinstance(data, dict):
                raise ValueError('state must be an object')
            if data.get('mode') not in (None, 'docked', 'air'):
                raise ValueError('mode must be docked or air')
            self.state.update(data)
            self.state.save()
            return {'saved': list(data), 'backup': backup}
        if not isinstance(data, (dict, list)):
            raise ValueError('this file holds a JSON object or list')
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix('.tmp')
        tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False))
        tmp.replace(path)
        if name == 'palette':
            self.brain.requests.append(('recolor',))
        return {'saved': True, 'backup': backup}

    def _clean_actions(self, actions):
        if not isinstance(actions, list):
            raise ValueError('actions must be a list')
        out = []
        seen = set()
        for raw in actions:
            if not isinstance(raw, dict):
                continue
            command = str(raw.get('command') or '').strip()
            if not command or command in seen:
                continue
            seen.add(command)
            label = str(raw.get('label') or command)[:18]
            label_ru = str(raw.get('label_ru') or label)[:18]
            item = {'label': label, 'label_ru': label_ru,
                    'icon': str(raw.get('icon') or 'star')[:120],
                    'command': command[:2000],
                    # the same optional fields config.load_actions keeps: saving
                    # from the browser must not erase what the in-world form wrote
                    'id': str(raw.get('id') or '').strip()[:64],
                    'priority': config._as_int(raw.get('priority')),
                    'requires_confirmation': config._as_bool(raw.get('requires_confirmation')),
                    'entities': config._as_entities(raw.get('entities'))}
            phrases = [str(p)[:200] for p in (raw.get('phrases') or []) if str(p).strip()]
            keywords = [str(k)[:80] for k in (raw.get('keywords') or []) if str(k).strip()]
            if phrases:
                item['phrases'] = phrases
            if keywords:
                item['keywords'] = keywords
            if str(raw.get('speak') or '').strip():
                item['speak'] = str(raw['speak'])[:300]
            if str(raw.get('url') or '').strip():
                item['url'] = str(raw['url'])[:2000]
            out.append(item)
        return out

    def _web_actions_get(self):
        b = self.brain
        table = b.ring_table()
        ids = b.ring_ids(table)
        ring = []
        for i in ids:
            if i not in table:
                continue
            action, arg, icon, label, ident = table[i]
            ring.append({'id': i, 'label': label, 'icon': icon,
                         'custom': i.startswith('cmd:') or i.startswith('/'),
                         'off': not b.ring_shown(i), 'fixed': i == 'settings'})
        return {'actions': [dict(a) for a in b.custom], 'ring': ring,
                'ring_order': list(b.settings.get('ring') or []),
                'ring_off': list(b.settings.get('ring_off') or []),
                'icons': sorted(pixui.ICONS),
                'icon_patterns': dict(pixui.ICONS)}

    def _web_logs(self, name, lines):
        paths = {
            'yumi': config.STATE_DIR / 'yumi.log',
            'mind': Path('/tmp/yumi/mind.log'),
            'judge': Path('/tmp/yumi/judge.log'),
            'ears': Path('/tmp/yumi/recogn.txt'),
            'stt': config.STATE_DIR / 'stt.log',
            'app': Path('/tmp/yumi/app.log'),
            'web': Path(config.STATE_DIR) / 'web-audit.log',
        }
        path = paths.get(name)
        if path is None:
            raise ValueError('unknown log')
        try:
            with path.open('rb') as fh:
                fh.seek(0, 2)
                size = fh.tell()
                fh.seek(max(0, size - 512 * 1024))
                text = fh.read().decode('utf-8', 'replace')
        except OSError:
            text = ''
        return {'name': name, 'path': str(path), 'text': '\n'.join(text.splitlines()[-lines:])}

    def _web_file_allowed(self, path):
        """the panel may preview or open the files it knows about: recent, shelf and
        its own uploads.  A crafted ``?path=/home/…/secret.png`` gets nothing."""
        try:
            target = Path(str(path or '')).expanduser().resolve()
        except (OSError, RuntimeError, ValueError):
            return False
        if not target.is_file():
            return False
        known = set()
        for source in ((self.state.get('shelf') or []),
                       list(getattr(self.recent, 'items', {}) or {})):
            for item in source:
                try:
                    known.add(Path(str(item)).expanduser().resolve())
                except (OSError, RuntimeError, ValueError):
                    pass
        if target in known:
            return True
        try:
            uploads = (Path(config.CACHE_DIR) / 'uploads').resolve()
        except (OSError, RuntimeError):
            return False
        return target == uploads or uploads in target.parents

    def _web_chat(self, text):
        """the panel's own talk with the same mind and diary, away from the GTK thread"""
        text = ' '.join(str(text or '').split())
        if not text:
            raise ValueError('a message is needed')
        with self.web_chat_lock:
            history = list(self.web_chat)
        s = self.settings
        lang = s.get('speech_lang', 'en')
        n = max(2, int(s.get('chat_history_n', 10)))
        turns = [{'role': m['role'], 'content': m['text']} for m in history[-n:]]
        note = ''
        if s.get('chat_memory', True):
            try:
                note = chat.recalled_note(memory.recall(text, s, skip_recent=len(turns)), lang)
            except Exception:
                note = ''
        messages = [{'role': 'system', 'content': chat.system_prompt(lang, bool(s.get('sassy')))}]
        messages += turns
        if note:
            messages.append({'role': 'system', 'content': note})
        messages.append({'role': 'user', 'content': text})
        reply = chat.ask(s, messages)
        ops = []
        with self.web_chat_lock:
            ops.append(self._web_chat_insert({'role': 'user', 'text': text, 'ts': time.time()}))
            if reply:
                ops.append(self._web_chat_insert({'role': 'assistant', 'text': reply,
                                                  'ts': time.time()}))
            self.save_web_chat()
            rev = self.web_chat_rev
            history = len(self.web_chat)
        self._web_chat_publish(ops)
        sassy = bool(s.get('sassy'))
        if s.get('chat_memory', True) and bool(s.get('sassy')) == sassy:
            tag = memory.TAG_SASSY if sassy else None
            try:
                memory.remember('user', text, s, tag=tag)
                if reply:
                    memory.remember('assistant', reply, s, tag=tag)
            except Exception:
                pass
        return {'reply': reply or '', 'recalled': note != '',
                'history': history, 'rev': rev, 'ops': ops}

    # ---------------------------------------------------------------- voice state
    def _web_voice_pause(self):
        """park the microphone from the panel and remember whether wake was on"""
        self._voice_pause_was_on = bool(self.wake_on)
        self.wake_pause()
        if hasattr(self, 'voice_state'):
            self.voice_state.wake_paused('paused from the panel')
        return self.voice_state.snapshot() if hasattr(self, 'voice_state') else {}

    def _web_voice_resume(self):
        """give the microphone back to the wake loop after a panel pause"""
        was_on = getattr(self, '_voice_pause_was_on', bool(self.wake_on))
        self.wake_resume(was_on)
        if hasattr(self, 'voice_state') and not was_on:
            self.voice_state.wake_off()
        return self.voice_state.snapshot() if hasattr(self, 'voice_state') else {}

    def _web_voice_released(self):
        """let go of the microphone entirely (stop the current ear)"""
        if hasattr(self, 'voice_state'):
            self.voice_state.missing('released from the panel')
        return self.voice_state.snapshot() if hasattr(self, 'voice_state') else {}

    # ---------------------------------------------------------------- diagnostics
    def _web_doctor_done(self, report):
        """remember only the light summary for the status snapshot / SSE"""
        summary = report.get('summary', {}) if isinstance(report, dict) else {}
        self.doctor_last = {
            'last_run': report.get('started') if isinstance(report, dict) else None,
            'elapsed': report.get('elapsed') if isinstance(report, dict) else None,
            'ok': bool(summary.get('ok')),
            'failed': list(summary.get('failed') or []),
        }
        web = self.web
        if web and web.running:
            try:
                web.publish('doctor', self.doctor_last)
            except Exception:
                pass
        return self.doctor_last
