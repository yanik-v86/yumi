import { api } from '../api.js';
import {
  el, clear, tr, icon, buildSetting, errToast, toast, confirmDialog, emptyBox, badge,
} from '../ui.js';

export function render(view, ctx) {
  const lang = () => ctx.lang;
  let status = ctx.status || {};
  let active = 'behavior';
  let query = '';
  let micsAsked = false;
  let mindSig = '';

  view.append(
    el('h2', { class: 'pagehead', text: lang() === 'ru' ? 'Настройки' : 'Settings' }),
    el('p', { class: 'pagelead', text: lang() === 'ru'
      ? 'Каждый ключ Yumi, сгруппированный по смыслу. Изменения сохраняются сразу и применяются к живой Юми.'
      : 'Every Yumi key, grouped by meaning. Changes save at once and apply to the live app.' }),
  );

  const search = el('input', {
    type: 'search',
    placeholder: lang() === 'ru' ? 'Найти настройку…' : 'Find a setting…',
    spellcheck: 'false',
  });
  const changedCount = el('span', { class: 'badge', text: '' });
  const resetAll = el('button', {
    class: 'btn btn-danger btn-small', type: 'button', text: lang() === 'ru' ? 'Сбросить всё' : 'Reset everything',
    onclick: async () => {
      if (!await confirmDialog({
        title: lang() === 'ru' ? 'Сбросить все настройки?' : 'Reset every setting?',
        message: lang() === 'ru'
          ? 'Все ключи вернутся к значениям по умолчанию, включая секреты и адреса. Панель может перезапуститься.'
          : 'Every key returns to its default, secrets and addresses included. The panel may restart.',
        confirmLabel: lang() === 'ru' ? 'Сбросить' : 'Reset', danger: true,
      })) return;
      const result = await ctx.resetSetting();
      if (result) {
        await ctx.refreshStatus();
        status = ctx.status || status;
        drawAll();
      }
    },
  });

  const toolbar = el('div', { class: 'row', style: { marginBottom: '16px' } },
    search, changedCount, el('span', { class: 'spacer' }), resetAll);

  const nav = el('div', { class: 'settings-nav' });
  const content = el('div', { class: 'stack' });
  const layout = el('div', { class: 'settings-layout' }, nav, content);
  view.append(toolbar, layout);

  search.addEventListener('input', () => {
    query = search.value.trim().toLowerCase();
    drawContent();
  });

  const entries = () => (ctx.schema?.settings || []).filter((entry) => !entry.hidden);
  const sections = () => ctx.schema?.sections || [];

  function valueOf(entry) {
    return status.settings?.[entry.key] ?? entry.default;
  }

  function isChanged(entry) {
    const value = valueOf(entry);
    const def = entry.default;
    if (Array.isArray(def)) return JSON.stringify(value || []) !== JSON.stringify(def);
    return value !== def;
  }

  function changedIn(sectionId) {
    return entries().filter((entry) => entry.section === sectionId && isChanged(entry)).length;
  }

  function drawNav() {
    clear(nav);
    for (const section of sections()) {
      const count = changedIn(section.id);
      const button = el('button', {
        class: active === section.id ? 'active' : '',
        type: 'button',
        text: tr(section.title),
      });
      if (count) button.append(el('span', { class: 'nav-count', text: ` ${count}` }));
      button.addEventListener('click', () => {
        active = section.id;
        query = '';
        search.value = '';
        drawNav();
        drawContent();
        content.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
      });
      nav.append(button);
    }
  }

  function updateCounts() {
    const total = entries().filter(isChanged).length;
    changedCount.textContent = total
      ? `${lang() === 'ru' ? 'изменено' : 'changed'}: ${total}`
      : (lang() === 'ru' ? 'всё по умолчанию' : 'all defaults');
    changedCount.className = total ? 'badge amber' : 'badge';
    drawNav();
  }

  function sectionHead(section) {
    return el('div', { class: 'section-title' },
      el('span', { text: tr(section.title) }),
      el('span', { class: 'card-hint', text: tr(section.hint) }));
  }

  function linkNote(section) {
    if (section.id === 'behavior') {
      return el('div', { class: 'card-hint', style: { marginBottom: '12px' } },
        lang() === 'ru'
          ? 'Справочник фактов, источники и свой JSON — на странице «Факты».'
          : 'The fact book, its sources and your own JSON live on the Facts page.',
        el('button', {
          class: 'btn btn-small', type: 'button', style: { marginLeft: '8px' },
          text: lang() === 'ru' ? 'Открыть' : 'Open',
          onclick: () => ctx.navigate('facts'),
        }));
    }
    if (section.id === 'web') {
      return el('div', { class: 'ok-box', style: { marginBottom: '12px' } },
        el('div', { class: 'row between' },
          el('span', { text: lang() === 'ru'
            ? 'Ссылка с токеном, сессии и журнал доступа — на странице «Безопасность».'
            : 'The token link, sessions and audit live on the Security page.' }),
          el('button', {
            class: 'btn btn-small', type: 'button', text: lang() === 'ru' ? 'Открыть' : 'Open',
            onclick: () => ctx.navigate('security'),
          })));
    }
    if (section.id === 'music') {
      return el('div', { class: 'card-hint', style: { marginBottom: '12px' } },
        lang() === 'ru'
          ? 'Плеер и поиск — на странице «Музыка».'
          : 'The player and search live on the Music page.');
    }
    if (section.id === 'ears') {
      return el('div', { class: 'card-hint', style: { marginBottom: '12px' } },
        lang() === 'ru'
          ? 'Проверить микрофон и голос можно на странице «Ушки и голос».'
          : 'Test the microphone and voice on the Ears & voice page.');
    }
    if (section.id === 'dialogue') {
      return el('div', { class: 'card-hint', style: { marginBottom: '12px' } },
        lang() === 'ru'
          ? 'Живой статус диалога (открыт, число реплик, секунды) — на странице «Разговор».'
          : 'The live dialogue status (open, exchanges, seconds) is on the Talk page.');
    }
    return null;
  }

  function settingRow(entry) {
    const row = buildSetting(entry, valueOf(entry), async (next) => {
      if (entry.key === 'chat_provider') {
        // the shared selector also resets chat_model to this provider's default
        try {
          await api.llmProviderSelect(next);
          await ctx.refreshStatus();
          status = ctx.status || status;
          drawAll();
        } catch (err) {
          errToast(err);
        }
        return;
      }
      const result = await ctx.applySettings({ [entry.key]: next });
      if (result?.result?.saved) {
        status.settings = { ...(status.settings || {}), ...result.result.saved };
        if (status.settings_full) {
          status.settings_full = { ...status.settings_full, ...result.result.saved };
        }
        // The control already shows the new value; only the counters change.
        updateCounts();
        row.querySelector('.control')?.querySelector('.reset-setting')?.remove();
        if (isChanged(entry)) addReset(row, entry);
      }
    });
    if (isChanged(entry)) addReset(row, entry);
    return row;
  }

  function addReset(row, entry) {
    const control = row.querySelector('.control');
    if (!control) return;
    const reset = el('button', {
      class: 'btn btn-small btn-ghost reset-setting', type: 'button',
      title: `${lang() === 'ru' ? 'вернуть по умолчанию' : 'reset to default'}: ${JSON.stringify(entry.default)}`,
      text: '↺',
      onclick: async () => {
        const result = await ctx.resetSetting(entry.key);
        if (!result) return;
        await ctx.refreshStatus();
        status = ctx.status || status;
        drawAll();
      },
    });
    control.append(reset);
  }

  function drawContent() {
    clear(content);
    let list = entries();
    if (query) {
      list = list.filter((entry) => {
        const hay = [entry.key, tr(entry.title), tr(entry.hint)].join(' ').toLowerCase();
        return hay.includes(query);
      });
    }
    const groups = query
      ? sections().map((section) => [section, list.filter((entry) => entry.section === section.id)]).filter(([, items]) => items.length)
      : sections().map((section) => [section, list.filter((entry) => entry.section === section.id)]);
    let shown = 0;
    for (const [section, items] of groups) {
      if (!items.length) continue;
      if (!query && section.id !== active) continue;
      shown += items.length;
      content.append(sectionHead(section));
      const note = linkNote(section);
      if (note) content.append(note);
      const card = el('div', { class: 'card' });
      let rows = items;
      if (section.id === 'mind') {
        // provider, answer model and thinking belong together, in that order
        const first = ['chat_provider', 'chat_model', 'chat_think'];
        rows = [...items].sort((a, b) => {
          const ai = first.indexOf(a.key), bi = first.indexOf(b.key);
          return (ai < 0 ? first.length : ai) - (bi < 0 ? first.length : bi);
        });
      }
      for (const entry of rows) card.append(settingRow(entry));
      content.append(card);
      if (section.id === 'ears' && !micsAsked && !(status.runtime?.mics || []).length) {
        // the picker needs the live device list; ask once, then redraw with it
        micsAsked = true;
        ctx.refreshMics()
          .then(() => { status = ctx.status || status; drawAll(); })
          .catch(() => {});
      }
    }
    if (!shown) {
      content.append(emptyBox(lang() === 'ru'
        ? 'Ничего не нашлось. Попробуй ключ вроде «wake» или «voice».'
        : 'Nothing found. Try a key such as “wake” or “voice”.'));
    }
  }

  function drawAll() {
    drawNav();
    drawContent();
    updateCounts();
  }

  const offStatus = ctx.onStatus((next) => {
    status = next;
    // redraw when the provider registry or the choice changes, not every tick
    const sig = JSON.stringify([
      next?.runtime?.llm?.providers || null,
      next?.settings?.chat_provider || '',
      next?.settings?.chat_model || '',
    ]);
    if (sig !== mindSig) {
      mindSig = sig;
      drawContent();
      updateCounts();
    }
  });
  const offEvent = ctx.onEvent('settings', () => {
    ctx.refreshStatus();
  });

  status = ctx.status || status;
  drawAll();

  return () => {
    offStatus();
    offEvent();
  };
}
