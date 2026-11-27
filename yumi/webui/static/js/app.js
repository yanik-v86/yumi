// The shell: session, navigation, the hash router and the live status stream.
import { api, connectEvents } from './api.js';
import {
  el, clear, setLang, tr, icon, toast, errToast, closeModal, fmtTime,
} from './ui.js';

const PAGES = {
  dashboard: './pages/dashboard.js',
  chat: './pages/chat.js',
  notes: './pages/notes.js',
  facts: './pages/facts.js',
  files: './pages/files.js',
  music: './pages/music.js',
  voice: './pages/voice.js',
  doctor: './pages/doctor.js',
  buttons: './pages/buttons.js',
  'user-intents': './pages/user-intents.js',
  appearance: './pages/appearance.js',
  settings: './pages/settings.js',
  memory: './pages/memory.js',
  configs: './pages/configs.js',
  security: './pages/security.js',
  logs: './pages/logs.js',
};

const state = {
  schema: null,
  status: null,
  chatModels: { provider: '', models: [], error: '' },
  chatModelSchema: null,
  lang: 'ru',
  page: '',
  cleanup: null,
  statusSubs: new Set(),
  eventSubs: new Map(),
  stopEvents: null,
  pollTimer: 0,
  timer: null,
  timerAt: 0,
  entered: false,
};

const $ = (id) => document.getElementById(id);

// ---------------------------------------------------------------- live state
function pageSubscribe(name, fn) {
  if (!state.eventSubs.has(name)) state.eventSubs.set(name, new Set());
  state.eventSubs.get(name).add(fn);
  return () => state.eventSubs.get(name)?.delete(fn);
}

function emitEvent(name, payload) {
  const subs = state.eventSubs.get(name);
  if (!subs) return;
  for (const fn of [...subs]) {
    try {
      fn(payload);
    } catch (err) {
      console.error(err);
    }
  }
}

function notifyStatus() {
  for (const fn of [...state.statusSubs]) {
    try {
      fn(state.status);
    } catch (err) {
      console.error(err);
    }
  }
}

function resetPageSubs() {
  state.statusSubs.clear();
  state.eventSubs.clear();
}

function localizeLogin() {
  const ru = state.lang === 'ru';
  document.documentElement.lang = ru ? 'ru' : 'en';
  const title = $('login-title');
  if (title) {
    title.replaceChildren(
      document.createTextNode(ru ? 'Юми ждёт ' : 'Yumi is waiting '),
      el('span', { class: 'blink', text: '_' }),
    );
  }
  const help = $('login-help');
  if (help) {
    help.replaceChildren(
      document.createTextNode(ru
        ? 'Вставь ссылку с токеном или сам токен. Он лежит в Yumi: '
        : 'Paste the token link or the token itself. It lives in Yumi: '),
      el('b', { text: ru
        ? 'Настройки → Веб-панель → Скопировать ссылку'
        : 'Settings → Web panel → Copy link' }),
      document.createTextNode('.'),
    );
  }
  const label = $('login-label');
  if (label) label.textContent = ru ? 'Токен или ссылка' : 'Token or link';
  const submit = $('login-submit');
  if (submit) submit.textContent = ru ? 'Открыть панель' : 'Open the panel';
  const foot = $('login-foot');
  if (foot) {
    foot.textContent = ru
      ? 'Панель по умолчанию слушает только 127.0.0.1 · сессия HttpOnly'
      : 'By default the panel listens only on 127.0.0.1 · HttpOnly session';
  }
  if (!state.entered) document.title = ru ? 'Юми · панель' : 'Yumi · panel';
}

function localizeShell() {
  const ru = state.lang === 'ru';
  localizeLogin();
  const brand = document.querySelector('.brand-text b');
  if (brand) brand.textContent = ru ? 'ЮМИ' : 'YUMI';
  const name = $('chip-show-name');
  if (name) name.textContent = ru ? 'ЮМИ' : 'YUMI';
  const logout = $('logout');
  if (logout) logout.textContent = ru ? 'Выйти' : 'Log out';
  const menu = $('menu-toggle');
  if (menu) menu.setAttribute('aria-label', ru ? 'Меню' : 'Menu');
  const show = $('chip-show');
  if (show) show.title = ru ? 'Показать / спрятать' : 'Show / hide';
  const pin = $('chip-pin');
  if (pin) pin.title = ru ? 'Не прятаться' : 'Stay out';
  const dnd = $('chip-dnd');
  if (dnd) dnd.title = ru ? 'Не мешать' : 'Do not disturb';
  const ears = $('chip-ears');
  if (ears) ears.title = ru ? 'Ушки: слушать имя «Юми»' : 'Ears: listen for the name';
  const earsName = $('chip-ears-name');
  if (earsName) earsName.textContent = ru ? 'УШКИ' : 'EARS';
}

function applyLanguage(lang) {
  if (!lang || lang === state.lang) return false;
  state.lang = lang;
  setLang(lang);
  localizeShell();
  if (state.entered) {
    buildNav();
    renderRoute();
  }
  return true;
}

// The microphone list lives in the live status; feed it into the form map so
// every page draws stt_mic as a select of the real devices, not a bare "auto".
function syncMicChoices(mics, current) {
  const entry = (state.schema?.settings || []).find((e) => e.key === 'stt_mic');
  if (!entry) return;
  const found = (Array.isArray(mics) ? mics : [])
    .map((m) => (typeof m === 'string' ? { name: m, label: m } : m))
    .filter((m) => m && m.name);
  const names = [null, ...found.map((m) => m.name)];
  if (current && !names.includes(current)) names.push(current);
  entry.type = 'select';
  entry.choices = names;
  entry.choice_labels = Object.fromEntries(found.map((m) => [String(m.name), m.label || m.name]));
  if (current) entry.choice_labels[String(current)] = entry.choice_labels[String(current)] || current;
}

// The answer model is a plain text field until the provider reports its models;
// then it becomes a select. Keep the pristine entry so a failed refresh restores it.
function syncChatModelChoices(models, current) {
  const entry = (state.schema?.settings || []).find((e) => e.key === 'chat_model');
  if (!entry) return;
  if (!state.chatModelSchema) {
    state.chatModelSchema = {
      type: entry.type, choices: entry.choices, choice_labels: entry.choice_labels,
    };
  }
  const names = [...new Set((Array.isArray(models) ? models : []).filter(Boolean).map(String))];
  if (current && !names.includes(String(current))) names.unshift(String(current));
  if (!names.length) {
    Object.assign(entry, state.chatModelSchema);
    return;
  }
  entry.type = 'select';
  entry.choices = names;
  entry.choice_labels = Object.fromEntries(names.map((name) => [name, name]));
}

function setChatModelsInfo(info, current) {
  state.chatModels = {
    provider: String(info?.provider || ''),
    models: Array.isArray(info?.models) ? info.models.filter(Boolean).map(String) : [],
    error: String(info?.error || ''),
  };
  syncChatModelChoices(state.chatModels.models, current ?? state.status?.settings?.chat_model);
  notifyStatus();
  return state.chatModels;
}

// a pending permission must be visible from every page, not just Buttons
let permBannerKey = '';
function updatePermBanner() {
  const box = document.getElementById('perm-banner');
  if (!box) return;
  const p = state.status?.runtime?.nlu?.pending_permission;
  if (!p) {
    box.hidden = true;
    box.replaceChildren();
    permBannerKey = '';
    return;
  }
  const key = String(p.id || '');
  if (key === permBannerKey && !box.hidden) return;
  permBannerKey = key;
  box.hidden = false;
  const decide = async (decision) => {
    try {
      await api.permissionAnswer(decision);
      await refreshStatus();
    } catch (err) { errToast(err); }
  };
  const buttons = (p.options || ['once', 'deny']).map((key) => el('button', {
    class: `btn btn-small ${key === 'deny' ? 'btn-danger' : key === 'once' ? 'btn-primary' : ''}`.trim(),
    type: 'button',
    text: key === 'once' ? (state.lang === 'ru' ? 'Разово' : 'Allow once')
      : key === 'always' ? (state.lang === 'ru' ? 'Всегда' : 'Always')
        : (state.lang === 'ru' ? 'Запретить' : 'Deny'),
    onclick: () => decide(key),
  }));
  box.replaceChildren(
    el('strong', { text: state.lang === 'ru' ? 'Юми просит разрешения' : 'Yumi asks permission' }),
    el('span', { text: (p.text || '') + (p.target ? ` · ${p.target}` : '') }),
    ...buttons,
  );
}

function setStatus(next, { light = false } = {}) {
  if (!next) return;
  if (!state.status) {
    state.status = next;
  } else {
    state.status = { ...state.status, ...next };
    if (light && !next.settings_full && state.status.settings_full) {
      state.status.settings_full = state.status.settings_full;
    }
  }
  // A light snapshot has no settings_full; the merge above keeps the old one.
  syncMicChoices(state.status.runtime?.mics, state.status.settings?.stt_mic);
  const mind = next.runtime?.chat_models_info;
  if (mind) {
    state.chatModels = {
      provider: String(mind.provider || ''),
      models: Array.isArray(mind.models) ? mind.models.filter(Boolean).map(String) : [],
      error: String(mind.error || ''),
    };
  }
  syncChatModelChoices(state.chatModels.models, state.status.settings?.chat_model);
  applyLanguage(state.status.settings?.ui_lang);
  const tm = state.status.runtime?.timer;
  if (tm) {
    state.timer = tm;
    state.timerAt = Date.now();
  }
  updateChips();
  updateSide();
  updatePermBanner();
  notifyStatus();
}

async function refreshStatus() {
  try {
    const data = await api.status();
    setStatus(data);
    return data;
  } catch (err) {
    if (err.status !== 401) console.warn('status:', err.message);
    return null;
  }
}

// Ask the app for a fresh look at the sound system and fold it into the status.
async function refreshMics() {
  const data = await api.get('/api/voice/mics');
  state.status = state.status || {};
  state.status.runtime = { ...(state.status.runtime || {}), mics: data.mics || [] };
  syncMicChoices(data.mics || [], state.status.settings?.stt_mic);
  notifyStatus();
  return data.mics || [];
}

// Ask the current mind provider for its models (or another one, without switching).
async function refreshChatModels(provider) {
  try {
    const data = await api.chatModelsRefresh(provider);
    state.status = state.status || {};
    state.status.runtime = {
      ...(state.status.runtime || {}),
      chat_models: data.models || [],
      chat_models_info: data,
    };
    return setChatModelsInfo(data);
  } catch (err) {
    errToast(err);
    return null;
  }
}

async function applySettings(patch, { quiet = true } = {}) {
  try {
    const data = await api.patchSettings(patch);
    if (data?.settings) {
      state.status = state.status || {};
      state.status.settings = { ...(state.status.settings || {}), ...data.settings };
      if (state.status.settings_full) {
        state.status.settings_full = { ...state.status.settings_full, ...data.settings };
      }
      applyLanguage(data.settings.ui_lang);
    }
    // a new provider (or endpoint) means a new list of answer models
    if (['chat_provider', 'ollama_url', 'polza_url'].some(
      (key) => Object.prototype.hasOwnProperty.call(patch, key))) {
      await refreshChatModels();
    }
    notifyStatus();
    updateChips();
    if (!quiet) toast(state.lang === 'ru' ? 'Сохранено' : 'Saved', 'good');
    if (data?.result?.restart) {
      toast(state.lang === 'ru'
        ? 'Масштаб изменится после перезапуска окна'
        : 'The window scale changes after a restart', 'warn');
    }
    return data;
  } catch (err) {
    errToast(err);
    return null;
  }
}

async function resetSetting(key) {
  try {
    const data = key ? await api.resetSetting(key) : await api.resetSetting();
    toast(state.lang === 'ru' ? 'Сброшено' : 'Reset', 'good');
    await refreshStatus();
    return data;
  } catch (err) {
    errToast(err);
    return null;
  }
}

const ctx = {
  get schema() { return state.schema; },
  get status() { return state.status; },
  get chatModels() { return state.chatModels; },
  get lang() { return state.lang; },
  refreshStatus,
  refreshMics,
  refreshChatModels,
  applySettings,
  resetSetting,
  navigate,
  onStatus(fn) {
    state.statusSubs.add(fn);
    return () => state.statusSubs.delete(fn);
  },
  onEvent: pageSubscribe,
  toast,
  errToast,
  openModal: null,
  tr,
};

// ---------------------------------------------------------------- top bar
function updateChips() {
  const s = state.status;
  if (!s) return;
  const runtime = s.runtime || {};
  const settings = s.settings || {};

  const dnd = $('chip-dnd');
  if (dnd) {
    const on = Boolean(runtime.sleeping);
    dnd.classList.toggle('on', on);
    dnd.querySelector('span:last-child').textContent = on
      ? (state.lang === 'ru' ? 'Тишина' : 'quiet')
      : 'DND';
  }

  const show = $('chip-show');
  if (show) {
    show.classList.toggle('on', Boolean(runtime.out));
    const action = $('chip-show-action');
    if (action) action.textContent = runtime.out
      ? (state.lang === 'ru' ? 'СПРЯТАТЬ' : 'HIDE')
      : (state.lang === 'ru' ? 'ПОКАЗАТЬ' : 'SHOW');
  }

  const pin = $('chip-pin');
  if (pin) pin.classList.toggle('on', Boolean(settings.pinned || runtime.pinned));

  const ears = $('chip-ears');
  if (ears) {
    const on = Boolean(settings.wake_ears);
    ears.classList.toggle('on', on);
    const earsState = $('chip-ears-state');
    if (earsState) {
      earsState.textContent = on
        ? (state.lang === 'ru' ? 'ВКЛ' : 'ON')
        : (state.lang === 'ru' ? 'ВЫКЛ' : 'OFF');
    }
  }

  const timerChip = $('chip-timer');
  if (timerChip) {
    const tm = currentTimer();
    const visible = tm && (tm.text || tm.seconds > 0 || tm.pending || tm.done);
    timerChip.hidden = !visible;
    if (visible) timerChip.textContent = timerLabel(tm);
  }
}

function currentTimer() {
  const base = state.timer;
  if (!base) return null;
  let seconds = Number(base.seconds) || 0;
  if (base.running) {
    seconds = Math.max(0, seconds - Math.floor((Date.now() - state.timerAt) / 1000));
  }
  return { ...base, seconds };
}

function timerLabel(tm) {
  if (!tm) return '';
  if (tm.done) return state.lang === 'ru' ? 'ГОТОВО' : 'DONE';
  if (tm.paused) return `${fmtTime(tm.seconds)} ⏸`;
  return fmtTime(tm.seconds);
}

function updateSide() {
  const s = state.status;
  const runtime = s?.runtime || {};
  const label = $('side-state');
  const dot = $('side-dot');
  if (label) {
    let text;
    if (runtime.sleeping) text = state.lang === 'ru' ? 'не мешать' : 'do not disturb';
    else if (runtime.listening) text = state.lang === 'ru' ? 'слушает' : 'listening';
    else if (runtime.thinking) text = state.lang === 'ru' ? 'думает' : 'thinking';
    else if (runtime.out) text = state.lang === 'ru' ? 'гуляет' : 'out';
    else text = state.lang === 'ru' ? 'рядом' : 'here';
    label.textContent = text;
  }
  if (dot) {
    dot.classList.toggle('off', false);
    dot.classList.toggle('sleep', Boolean(runtime.sleeping));
  }
}

function setConn(ok) {
  const conn = $('conn');
  if (!conn) return;
  conn.classList.toggle('off', !ok);
  conn.textContent = ok ? '●' : '○';
  conn.title = ok
    ? (state.lang === 'ru' ? 'живое соединение' : 'live connection')
    : (state.lang === 'ru' ? 'переподключаюсь' : 'reconnecting');
}

// ---------------------------------------------------------------- shell
function showLogin(message = '') {
  const login = $('login');
  const shell = $('shell');
  if (login) login.hidden = false;
  if (shell) shell.hidden = true;
  const error = $('login-error');
  if (error) error.textContent = message;
  const input = $('login-token');
  if (input) {
    input.value = '';
    window.setTimeout(() => input.focus(), 60);
  }
}

function buildNav() {
  const nav = $('nav');
  if (!nav) return;
  clear(nav);
  for (const page of state.schema?.pages || []) {
    const link = el('a', { href: `#/${page.id}`, dataset: { page: page.id } });
    link.append(icon(page.icon, 18), el('span', { text: tr(page.title) }));
    nav.append(link);
  }
}

let shellBound = false;

function bindShell() {
  if (shellBound) return;
  shellBound = true;
  const form = $('login-form');
  if (form) {
    form.addEventListener('submit', async (ev) => {
      ev.preventDefault();
      const input = $('login-token');
      const error = $('login-error');
      const button = form.querySelector('button[type=submit]');
      const token = (input?.value || '').trim();
      if (!token) return;
      if (error) error.textContent = '';
      if (button) button.disabled = true;
      try {
        await api.login(token);
        const s = await api.session();
        if (!s.authed) throw new Error(state.lang === 'ru' ? 'токен не принят' : 'token refused');
        await enter();
      } catch (err) {
        if (error) error.textContent = err.message || (state.lang === 'ru' ? 'Не вышло' : 'Failed');
      } finally {
        if (button) button.disabled = false;
      }
    });
  }

  $('logout')?.addEventListener('click', async () => {
    try {
      await api.logout();
    } finally {
      window.location.href = window.location.pathname;
    }
  });

  $('menu-toggle')?.addEventListener('click', () => {
    document.querySelector('.sidebar')?.classList.toggle('open');
  });

  $('nav')?.addEventListener('click', () => {
    document.querySelector('.sidebar')?.classList.remove('open');
  });

  $('chip-ears')?.addEventListener('click', async () => {
    const on = !state.status?.settings?.wake_ears;
    await applySettings({ wake_ears: on }, { quiet: false });
    await refreshStatus();
  });

  $('chip-dnd')?.addEventListener('click', async () => {
    const on = !state.status?.runtime?.sleeping;
    await stateAction('dnd', { on });
  });

  $('chip-show')?.addEventListener('click', async () => {
    await stateAction('toggle');
  });

  $('chip-pin')?.addEventListener('click', async () => {
    const on = !state.status?.settings?.pinned;
    await applySettings({ pinned: on }, { quiet: false });
    await refreshStatus();
  });

  $('chip-timer')?.addEventListener('click', () => navigate('dashboard'));

  document.addEventListener('click', (ev) => {
    const modal = $('modal');
    if (!modal || modal.hidden) return;
    if (ev.target === modal) closeModal();
  });
}

async function stateAction(name, payload = {}) {
  try {
    await api.post(`/api/state/${name}`, payload);
    toast(state.lang === 'ru' ? 'Сделано' : 'Done', 'good');
    await refreshStatus();
  } catch (err) {
    errToast(err);
  }
}

// Dashboard and buttons need the same tiny world actions.
ctx.stateAction = stateAction;

// ---------------------------------------------------------------- router
async function renderRoute() {
  if (!state.entered || !state.schema) return;
  const raw = (window.location.hash || '#/dashboard').replace(/^#\/?/, '');
  const id = raw.split(/[/?]/)[0] || 'dashboard';
  const page = (state.schema.pages || []).find((p) => p.id === id)
    || (state.schema.pages || [])[0];
  if (!page) return;
  if (page.id !== id) {
    history.replaceState(null, '', `#/${page.id}`);
  }

  if (state.cleanup) {
    try {
      state.cleanup();
    } catch (err) {
      console.error(err);
    }
    state.cleanup = null;
  }
  resetPageSubs();

  const view = $('view');
  if (!view) return;
  clear(view);
  view.append(el('div', { class: 'loading pixel-frame', text: state.lang === 'ru' ? 'Юми просыпается…' : 'Yumi is waking…' }));

  for (const link of document.querySelectorAll('#nav a')) {
    link.classList.toggle('active', link.dataset.page === page.id);
  }
  const title = $('page-title');
  const hint = $('page-hint');
  if (title) title.textContent = tr(page.title);
  if (hint) hint.textContent = tr(page.hint);
  document.title = `${state.lang === 'ru' ? 'Юми' : 'Yumi'} · ${tr(page.title)}`;
  state.page = page.id;
  window.scrollTo({ top: 0 });
  view.focus({ preventScroll: true });

  const factory = PAGES[page.id];
  if (!factory) {
    clear(view);
    view.append(el('div', { class: 'empty', text: state.lang === 'ru' ? 'Страница ещё не собрана' : 'This page is not built yet' }));
    return;
  }
  try {
    const mod = await import(factory);
    if (state.page !== page.id) return;
    clear(view);
    const cleanup = mod.render(view, ctx);
    if (typeof cleanup === 'function') state.cleanup = cleanup;
  } catch (err) {
    console.error(err);
    clear(view);
    view.append(el('div', { class: 'warn-box' },
      el('b', { text: state.lang === 'ru' ? 'Страница не открылась' : 'The page did not open' }),
      el('p', { text: err.message || String(err) })));
  }
}

function navigate(id) {
  window.location.hash = `#/${id}`;
}

// ---------------------------------------------------------------- session
async function enter() {
  state.schema = await api.schema();
  state.schema.mask = state.schema.secret_mask;
  const status = await api.status();
  const lang = status?.settings?.ui_lang === 'en' ? 'en' : 'ru';
  state.lang = lang;
  setLang(state.lang);
  localizeShell();

  const login = $('login');
  const shell = $('shell');
  if (login) login.hidden = true;
  if (shell) shell.hidden = false;
  if (!state.entered) {
    state.entered = true;
    buildNav();
    bindShell();
    window.addEventListener('hashchange', renderRoute);
    window.addEventListener('yumi:unauthorized', handleUnauthorized);
    if (!window.location.hash) window.location.hash = '#/dashboard';
  } else {
    buildNav();
  }
  setStatus(status);
  setConn(true);
  startLive();
  await renderRoute();
}

let unauthorizedShown = false;
function handleUnauthorized() {
  if (unauthorizedShown) return;
  unauthorizedShown = true;
  stopLive();
  state.entered = false;
  showLogin(state.lang === 'ru'
    ? 'Сессия закончилась. Вставь ссылку с токеном ещё раз.'
    : 'The session ended. Paste the token link again.');
  window.setTimeout(() => { unauthorizedShown = false; }, 1500);
}

function startLive() {
  stopLive();
  state.pollTimer = window.setInterval(() => {
    if (document.visibilityState === 'visible') refreshStatus();
  }, 5000);
  state.stopEvents = connectEvents((name, payload) => {
    if (name === 'hello') return;
    if (name === 'status') {
      if (payload?.data) setStatus(payload.data, { light: true });
      return;
    }
    if (name === 'settings') {
      if (payload?.data?.settings) {
        state.status = state.status || {};
        state.status.settings = { ...(state.status.settings || {}), ...payload.data.settings };
      }
      emitEvent('settings', payload?.data || {});
      notifyStatus();
      return;
    }
    if (name === 'chat_models') {
      if (payload?.data) setChatModelsInfo(payload.data);
      emitEvent('chat_models', payload?.data || {});
      return;
    }
    if (name === 'bubble') {
      emitEvent('bubble', payload?.data || {});
      return;
    }
    emitEvent(name, payload?.data || payload || {});
    if (name === 'files' || name === 'jobs' || name === 'actions' || name === 'server') {
      refreshStatus();
    }
  }, setConn);
}

function stopLive() {
  if (state.pollTimer) window.clearInterval(state.pollTimer);
  state.pollTimer = 0;
  if (state.stopEvents) state.stopEvents();
  state.stopEvents = null;
  setConn(false);
}

// ---------------------------------------------------------------- boot
async function boot() {
  const prefersEn = !(navigator.language || 'ru').toLowerCase().startsWith('ru');
  state.lang = prefersEn ? 'en' : 'ru';
  setLang(state.lang);
  localizeLogin();
  const params = new URLSearchParams(window.location.search);
  const token = params.get('t');
  let loginError = '';
  if (token) {
    try {
      await api.login(token);
      history.replaceState(null, '', window.location.pathname + window.location.hash);
    } catch (err) {
      loginError = err.message || (state.lang === 'ru' ? 'Ссылка не подошла' : 'The link did not work');
      history.replaceState(null, '', window.location.pathname + window.location.hash);
    }
  }
  try {
    const session = await api.session();
    if (session.authed) {
      await enter();
      return;
    }
  } catch (err) {
    loginError = loginError || err.message;
  }
  showLogin(loginError);
  // Bind the form even before a session so the token can be entered here.
  if (!state.entered) bindShell();
  window.setInterval(() => {
    const tm = currentTimer();
    if (tm && tm.running && !$('chip-timer')?.hidden) {
      const chip = $('chip-timer');
      if (chip) chip.textContent = timerLabel(currentTimer());
    }
  }, 500);
}

boot();
