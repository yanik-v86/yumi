// The only place that talks HTTP.  Cookies stay HttpOnly; every mutation
// carries the readable CSRF value in a header, as the server demands.

let csrf = null;

export class ApiError extends Error {
  constructor(status, message, data) {
    super(message || `HTTP ${status}`);
    this.name = 'ApiError';
    this.status = status;
    this.data = data;
  }
}

export function setCsrf(value) {
  csrf = value || null;
}

export function getCsrf() {
  return csrf;
}

async function parse(res) {
  const type = res.headers.get('Content-Type') || '';
  if (type.includes('application/json')) {
    return res.json().catch(() => null);
  }
  return res.text();
}

export async function request(method, path, body, opts = {}) {
  const headers = { Accept: 'application/json' };
  const hasBody = body !== undefined;
  if (hasBody) headers['Content-Type'] = 'application/json';
  if (csrf && method !== 'GET' && method !== 'HEAD') headers['X-Yumi-CSRF'] = csrf;
  let res;
  try {
    res = await fetch(path, {
      method,
      headers,
      credentials: 'same-origin',
      body: hasBody ? JSON.stringify(body) : undefined,
      signal: opts.signal,
      cache: 'no-store',
    });
  } catch (err) {
    if (err.name === 'AbortError') throw err;
    const ru = (document.documentElement.lang || '') === 'ru';
    throw new ApiError(0, ru
      ? 'Юми не отвечает. Проверь, запущено ли приложение.'
      : 'Yumi is not answering. Check that the app is running.', null);
  }
  const data = await parse(res);
  if (!res.ok) {
    const message = (data && (data.error || data.message)) || res.statusText || `HTTP ${res.status}`;
    if (res.status === 401) window.dispatchEvent(new CustomEvent('yumi:unauthorized'));
    throw new ApiError(res.status, String(message), data);
  }
  return data;
}

// Binary import: the browser sets the multipart boundary itself, so only the
// CSRF header is added here (never Content-Type).
async function postFile(path, file) {
  const form = new FormData();
  form.append('file', file, file.name || 'upload.zip');
  const headers = {};
  if (csrf) headers['X-Yumi-CSRF'] = csrf;
  let res;
  try {
    res = await fetch(path, {
      method: 'POST', headers, credentials: 'same-origin', body: form, cache: 'no-store',
    });
  } catch (err) {
    if (err.name === 'AbortError') throw err;
    const ru = (document.documentElement.lang || '') === 'ru';
    throw new ApiError(0, ru ? 'Юми не отвечает.' : 'Yumi is not answering.', null);
  }
  const data = await parse(res);
  if (!res.ok) {
    if (res.status === 401) window.dispatchEvent(new CustomEvent('yumi:unauthorized'));
    const message = (data && (data.error || data.message)) || res.statusText || `HTTP ${res.status}`;
    throw new ApiError(res.status, String(message), data);
  }
  return data;
}

export const api = {
  get: (path, opts) => request('GET', path, undefined, opts),
  post: (path, body = {}) => request('POST', path, body),
  put: (path, body = {}) => request('PUT', path, body),
  patch: (path, body = {}) => request('PATCH', path, body),
  del: (path) => request('DELETE', path),

  async session() {
    const data = await this.get('/api/session');
    if (data && data.authed && data.csrf) setCsrf(data.csrf);
    return data;
  },

  async login(token) {
    const data = await this.post('/api/login', { token });
    if (data && data.csrf) setCsrf(data.csrf);
    return data;
  },

  async logout() {
    try {
      await this.post('/api/logout');
    } finally {
      setCsrf(null);
    }
  },

  status: () => api.get('/api/status'),
  schema: () => api.get('/api/schema'),

  factsList: (lang = '') => api.get(`/api/facts?lang=${encodeURIComponent(lang || '')}`),
  factsCheck: (path = '') => api.post('/api/facts/check', { path: String(path || '') }),
  factsSay: (id = '') => api.post('/api/facts/say', { id: String(id || '') }),

  nluConfirm: (ok) => api.post('/api/nlu/confirm', { ok: Boolean(ok) }),

  userIntentsGet: () => api.get('/api/user-intents'),
  userIntentsPut: (payload) => api.put('/api/user-intents', payload),
  userIntentsImportZip: (file) => postFile('/api/user-intents/import.zip', file),
  userIntentsTest: (text) => api.post('/api/user-intents/test', { text: String(text || '') }),
  userIntentsRemoteIndex: () => api.get('/api/user-intents/remote'),
  userIntentsRemoteInstall: (id, mode = 'merge') =>
    api.post('/api/user-intents/remote/install', { id: String(id || ''), mode }),

  // Matches the phrase and runs the intent through Brain (bubble, voice, command).
  userIntentsRun: (text) => api.post('/api/user-intents/run', { text: String(text || '') }),

  intentsLogGet: (params = '') => api.get(`/api/user-intents/log${params ? `?${params}` : ''}`),
  intentsLogClear: () => api.post('/api/user-intents/log/clear'),

  chatHistory: () => api.get('/api/chat/history'),
  chatModels: () => api.get('/api/chat/models'),
  chatModelsRefresh: (provider) => api.post('/api/chat/models/refresh', { provider: provider || null }),

  llmProviders: () => api.get('/api/llm/providers'),
  llmProviderCheck: (record, key) =>
    api.post('/api/llm/providers/check', { record, key: key || null }),
  llmProviderSave: (record, key) => api.post('/api/llm/providers', { record, key: key || null }),
  llmProviderUpdate: (id, record, key) =>
    api.put(`/api/llm/providers/${encodeURIComponent(id)}`, { record, key: key || null }),
  llmProviderDelete: (id) => api.del(`/api/llm/providers/${encodeURIComponent(id)}`),
  llmProviderSelect: (id) => api.post(`/api/llm/providers/${encodeURIComponent(id)}/select`),
  llmProviderTest: (id) => api.post(`/api/llm/providers/${encodeURIComponent(id)}/test`),
  llmProviderRefresh: (id) =>
    api.post(`/api/llm/providers/${encodeURIComponent(id)}/models/refresh`),

  chatOps: (since = 0) => api.get(`/api/chat/ops?since=${Number(since) || 0}`),
  chatClear: () => api.del('/api/chat/history'),
  chatUpdate: (id, text) => api.post('/api/chat/message/update', { id, text }),
  chatRemove: (id) => api.post('/api/chat/message/remove', { id }),

  doctor: (sections, text) => api.post('/api/doctor', { sections: sections || null, text: text || null }),
  modelsGet: () => api.get('/api/models'),
  modelsVerify: () => api.post('/api/models/verify'),
  modelsRecord: (names) => api.post('/api/models/record', { names: names || null }),

  speakerGet: () => api.get('/api/speaker'),
  speakerEnroll: () => api.post('/api/speaker/enroll'),
  speakerAcquaintance: () => api.post('/api/speaker/acquaintance'),
  speakerTest: () => api.post('/api/speaker/test'),
  speakerRename: (id, label) => api.post('/api/speaker/rename', { id, label }),
  speakerDelete: (id) => api.post('/api/speaker/delete', { id }),
  speakerClear: () => api.post('/api/speaker/clear'),

  voiceState: () => api.get('/api/voice/state'),
  voicePause: () => api.post('/api/voice/pause'),
  voiceResume: () => api.post('/api/voice/resume'),
  voiceRelease: () => api.post('/api/voice/release'),

  permissionAnswer: (decision) => api.post('/api/permissions/answer', { decision }),
  permissionsList: () => api.get('/api/permissions'),
  permissionsClear: () => api.post('/api/permissions/clear'),

  notesList: (params = '') => api.get(`/api/notes${params ? `?${params}` : ''}`),
  noteAdd: (text, title) => api.post('/api/notes', { text, title }),
  noteUpdate: (id, text, title) => api.patch(`/api/notes/${id}`, { text, title }),
  noteDelete: (id) => api.del(`/api/notes/${id}`),
  notesClear: () => api.post('/api/notes/clear', { all: true }),

  async patchSettings(patch) {
    return api.patch('/api/settings', { patch });
  },

  resetSetting: (key) => api.post('/api/settings/reset', key ? { key } : { all: true }),

  async upload(file) {
    const query = new URLSearchParams({ name: file.name || 'file' });
    const headers = { 'X-Yumi-CSRF': csrf || '' };
    const res = await fetch(`/api/upload?${query}`, {
      method: 'POST',
      headers,
      credentials: 'same-origin',
      body: file,
    });
    const data = await parse(res);
    if (!res.ok) {
      if (res.status === 401) window.dispatchEvent(new CustomEvent('yumi:unauthorized'));
      const ru = (document.documentElement.lang || '') === 'ru';
      throw new ApiError(res.status, (data && data.error) || (ru ? 'не удалось загрузить' : 'upload failed'), data);
    }
    return data;
  },
};

export const EVENTS = ['hello', 'status', 'bubble', 'settings', 'files', 'jobs', 'actions', 'chat', 'chat_models', 'llm', 'notes', 'server', 'doctor', 'intents_log'];

export function connectEvents(onEvent, onState) {
  let source = null;
  let retry = 0;
  let stopped = false;

  const open = () => {
    if (stopped) return;
    source = new EventSource('/api/events');
    source.addEventListener('open', () => {
      retry = 0;
      onState && onState(true);
    });
    for (const name of EVENTS) {
      source.addEventListener(name, (ev) => {
        let data = null;
        try {
          data = JSON.parse(ev.data);
        } catch {
          data = null;
        }
        onEvent && onEvent(name, data);
      });
    }
    source.addEventListener('error', () => {
      onState && onState(false);
      source.close();
      if (stopped) return;
      retry = Math.min(retry + 1, 8);
      setTimeout(open, 600 * retry);
    });
  };

  open();
  return () => {
    stopped = true;
    if (source) source.close();
  };
}
