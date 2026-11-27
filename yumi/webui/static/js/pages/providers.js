// Mind providers: one shared registry for GTK and the panel.  Keys are written
// to a separate private file; the browser never reads them back.
import { api } from '../api.js';
import {
  el, icon, toast, errToast, sectionTitle, emptyBox, badge, button, field,
  modal, confirmDialog,
} from '../ui.js';

export function render(view, ctx) {
  const L = (ru, en) => (ctx.lang === 'ru' ? ru : en);
  const list = el('div', { class: 'provider-list' });
  let providers = [];

  async function load() {
    const data = await api.llmProviders();
    providers = data.providers || [];
    await draw();
  }

  function form(existing) {
    const id = el('input', { type: 'text', value: existing?.id || '', maxLength: 32,
      disabled: Boolean(existing), placeholder: 'local' });
    const name = el('input', { type: 'text', value: existing?.name || '', maxLength: 60 });
    const kind = el('select');
    for (const value of ['ollama', 'openai']) {
      kind.append(el('option', { value, text: value, selected: (existing?.kind || 'ollama') === value }));
    }
    const url = el('input', { type: 'url', value: existing?.url || '', placeholder: 'http://127.0.0.1:11434' });
    const model = el('input', { type: 'text', value: existing?.default_model || '' });
    const models = el('textarea', { rows: 3, value: (existing?.models || []).join('\n') });
    const enabled = el('input', { type: 'checkbox', checked: existing ? existing.enabled !== false : true });
    const key = el('input', { type: 'password', value: '', autocomplete: 'off',
      placeholder: L('не менять', 'leave unchanged') });
    return el('div', { class: 'provider-form' },
      el('div', { class: 'field-row' },
        field(L('ID', 'ID'), id, L('Не меняется после создания', 'Fixed after creation')),
        field(L('Имя', 'Name'), name)),
      el('div', { class: 'field-row' },
        field(L('Тип', 'Kind'), kind),
        field(L('Адрес', 'Address'), url)),
      field(L('Модель по умолчанию', 'Default model'), model),
      field(L('Модели (по одной на строку)', 'Models (one per line)'), models),
      field(L('Включён', 'Enabled'), enabled),
      field(L('Ключ API', 'API key'), key,
        L('Пусто — оставить прежний. Ключ хранится отдельно и никогда не показывается.',
          'Empty keeps the old one. The key is stored separately and is never shown.')));
  }

  function readForm(formNode) {
    const inputs = formNode.querySelectorAll('input, select, textarea');
    const [id, name, kind, url, model, models, enabled, key] = inputs;
    return {
      record: {
        id: (id.value || '').trim().toLowerCase(),
        name: (name.value || '').trim(),
        kind: kind.value,
        url: (url.value || '').trim().replace(/\/+$/, ''),
        default_model: (model.value || '').trim(),
        enabled: enabled.checked,
        models: (models.value || '').split(/[\n,]+/).map((m) => m.trim()).filter(Boolean),
      },
      key: (key.value || '').trim(),
    };
  }

  function openForm(existing) {
    const body = form(existing);
    modal({
      title: existing ? L('Правка провайдера', 'Edit provider') : L('Новый провайдер', 'New provider'),
      body,
      wide: true,
      actions: [
        { label: L('Отмена', 'Cancel') },
        { label: L('Сохранить', 'Save'), kind: 'btn-primary', onClick: async () => {
          const { record, key } = readForm(body);
          try {
            if (existing) await api.llmProviderUpdate(existing.id, record, key);
            else await api.llmProviderSave(record, key);
            await ctx.refreshStatus();
            await load();
            toast(L('Провайдер сохранён', 'Provider saved'), 'good');
          } catch (err) {
            errToast(err);
            return false;
          }
          return true;
        } },
      ],
    });
  }

  async function act(id, fn, okText) {
    try {
      const result = await fn();
      if (result?.error) toast(result.error, 'warn');
      else if (okText) toast(okText, 'good');
      await ctx.refreshStatus();
      await load();
    } catch (err) {
      errToast(err);
    }
  }

  function card(rec) {
    const badges = el('div', { class: 'row' });
    if (rec.active) badges.append(badge(L('активный', 'active'), 'good'));
    if (rec.kind === 'openai') badges.append(badge(rec.kind));
    badges.append(badge(rec.has_key
      ? L('ключ задан', 'key set') : L('ключа нет', 'no key'), rec.has_key ? 'good' : 'warn'));
    badges.append(badge(`${L('моделей', 'models')}: ${rec.models_count || 0}`));
    if (rec.error) badges.append(badge(rec.error, 'bad'));

    const actions = el('div', { class: 'row' });
    if (!rec.active) {
      actions.append(button(L('Выбрать', 'Select'), {
        iconName: 'check', onClick: () => act(rec.id,
          () => api.llmProviderSelect(rec.id), L('Провайдер выбран', 'Provider selected')),
      }));
    }
    actions.append(button(L('Проверить', 'Test'), {
      iconName: 'refresh', onClick: () => act(rec.id,
        () => api.llmProviderTest(rec.id)),
    }));
    actions.append(button(L('Обновить модели', 'Refresh models'), {
      iconName: 'refresh', onClick: () => act(rec.id,
        () => api.llmProviderRefresh(rec.id), L('Модели обновлены', 'Models refreshed')),
    }));
    actions.append(button(L('Правка', 'Edit'), {
      iconName: 'pencil', onClick: () => openForm(rec),
    }));
    actions.append(button(L('Удалить', 'Delete'), {
      iconName: 'trash', kind: 'btn-danger', onClick: async () => {
        const yes = await confirmDialog({
          title: L('Удалить провайдера?', 'Delete the provider?'),
          message: rec.name,
          confirmLabel: L('Удалить', 'Delete'),
          danger: true,
        });
        if (yes) await act(rec.id, () => api.llmProviderDelete(rec.id),
          L('Провайдер удалён', 'Provider deleted'));
      },
    }));

    return el('section', { class: 'card' },
      el('div', { class: 'row between' },
        el('h3', { text: rec.name || rec.id }), badges),
      el('p', { class: 'card-hint', text: `${rec.kind} · ${rec.url}` }),
      rec.default_model ? el('p', { class: 'card-hint',
        text: `${L('По умолчанию', 'Default')}: ${rec.default_model}` }) : null,
      actions);
  }

  async function draw() {
    list.replaceChildren();
    if (!providers.length) {
      list.append(emptyBox(L('Провайдеров пока нет.', 'There are no providers yet.')));
      return;
    }
    for (const rec of providers) list.append(card(rec));
  }

  view.append(
    el('h2', { class: 'pagehead', text: L('Провайдеры мозгов', 'Mind providers') }),
    el('p', { class: 'pagelead', text: L(
      'Один реестр для Юми в GTK и панели. Здесь можно добавить OpenAI-совместимый '
      + 'провайдер, проверить его, обновить модели и выбрать активного. Ключ попадает '
      + 'в отдельный приватный файл и больше не показывается. В GTK доступно только '
      + 'переключение провайдера и модели.',
      'One registry shared by GTK and the panel. Add an OpenAI-compatible provider, test '
      + 'it, refresh its models and pick the active one here. Its key goes into a separate '
      + 'private file and is never shown again. GTK only switches provider and model.') }),
    sectionTitle(L('Реестр', 'Registry'),
      el('span', { class: 'row' },
        button(L('Добавить', 'Add'), { iconName: 'plus', kind: 'btn-primary',
          onClick: () => openForm(null) }))),
    list,
  );

  const offEvent = ctx.onEvent('llm', () => { load().catch(errToast); });
  load().catch(errToast);
  return () => offEvent();
}
