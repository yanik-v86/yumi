import { api } from '../api.js';
import {
  el, clear, errToast, toast, emptyBox, badge, field,
} from '../ui.js';

export function render(view, ctx) {
  const ru = () => ctx.lang === 'ru';
  let data = null;

  view.append(
    el('h2', { class: 'pagehead', text: ru() ? 'Факты' : 'Facts' }),
    el('p', {
      class: 'pagelead',
      text: ru()
        ? 'Короткие настоящие факты с источниками. Юми берёт их из проверенного справочника, а не просит модель выдумать текст.'
        : 'Short real facts with sources. Yumi reads them from a checked book; the model is never asked to invent a fact.',
    }),
  );

  const info = el('div', { class: 'card-hint', text: '' });
  const sayOut = el('div', {
    class: 'bubble',
    text: ru() ? 'Нажми, чтобы Юми сказала случайный факт.' : 'Press to have Yumi say a random fact.',
  });
  const sayButton = el('button', {
    class: 'btn btn-primary', type: 'button',
    text: ru() ? 'Сказать факт' : 'Say a fact',
    onclick: async () => {
      try {
        const result = await api.factsSay();
        if (result.ok) {
          sayOut.textContent = result.text || (result.fact && result.fact.text) || '…';
          await ctx.refreshStatus();
        } else {
          sayOut.textContent = result.reason === 'sleeping'
            ? (ru() ? 'Она спит — разбуди её сначала.' : 'She is asleep — wake her first.')
            : (ru() ? 'Факты выключены в настройках болтовни.' : 'Facts are off in the chatter settings.');
        }
      } catch (err) { errToast(err); }
    },
  });
  const sayCard = el('div', { class: 'card' },
    el('h3', { text: ru() ? 'В мир' : 'Into the room' }),
    el('div', { class: 'row' }, sayButton),
    el('div', { style: { marginTop: '12px' } }, sayOut));

  const fileInput = el('input', {
    type: 'text', spellcheck: 'false',
    value: ctx.status?.settings?.chatter_facts_file || '',
    placeholder: ru() ? '/путь/к/mo-facts.json (пусто = встроенный)' : '/path/to/my-facts.json (empty = built-in)',
  });
  const checkOut = el('div', { class: 'card-hint', text: '' });
  const applyFile = async () => {
    const path = fileInput.value.trim();
    checkOut.textContent = ru() ? 'проверяю…' : 'checking…';
    try {
      const result = await api.factsCheck(path);
      if (!result.ok) {
        checkOut.textContent = result.error || (ru() ? 'Справочник не подошёл.' : 'Not a usable fact book.');
        return;
      }
      await ctx.applySettings({ chatter_facts_file: path });
      checkOut.textContent = ru()
        ? `Готово: ${result.custom} своих фактов, всего ${result.total}.`
        : `Saved: ${result.custom} custom facts, ${result.total} in total.`;
      await ctx.refreshStatus();
      await load();
    } catch (err) { errToast(err); }
  };
  const clearFile = async () => {
    fileInput.value = '';
    try {
      await ctx.applySettings({ chatter_facts_file: '' });
      checkOut.textContent = ru() ? 'Снова встроенный справочник.' : 'Back to the built-in book.';
      await ctx.refreshStatus();
      await load();
    } catch (err) { errToast(err); }
  };
  const fileCard = el('div', { class: 'card' },
    el('h3', { text: ru() ? 'Свой справочник' : 'Your own book' }),
    el('p', {
      class: 'card-hint',
      text: ru()
        ? 'Файл на этом компьютере: {"facts": [{"id": "…", "ru": "…", "en": "…", "source": "…", "url": "https://…"}]}. Без поля url источник просто не будет ссылкой.'
        : 'A file on this machine: {"facts": [{"id": "…", "ru": "…", "en": "…", "source": "…", "url": "https://…"}]}. The url field is optional.',
    }),
    field(ru() ? 'Путь к JSON' : 'JSON path', fileInput),
    el('div', { class: 'row', style: { marginTop: '12px' } },
      el('button', {
        class: 'btn btn-primary', type: 'button',
        text: ru() ? 'Проверить и включить' : 'Check and enable',
        onclick: applyFile,
      }),
      el('button', {
        class: 'btn btn-small', type: 'button',
        text: ru() ? 'Встроенный' : 'Built-in',
        onclick: clearFile,
      })),
    el('div', { style: { marginTop: '10px' } }, checkOut));

  const search = el('input', {
    type: 'search', spellcheck: 'false',
    placeholder: ru() ? 'Найти факт…' : 'Find a fact…',
  });
  const list = el('div', { class: 'stack' });
  view.append(info, el('div', { class: 'grid two' }, sayCard, fileCard));
  view.append(el('div', { class: 'section-title' },
    el('span', { text: ru() ? 'Справочник' : 'The book' })));
  view.append(el('div', { class: 'row', style: { marginBottom: '12px' } }, search), list);

  function draw() {
    clear(list);
    const book = data?.info || {};
    info.textContent = ru()
      ? `Встроенных: ${book.builtin ?? 0} · своих: ${book.custom ?? 0} · всего: ${book.total ?? 0}${book.error ? ` · ошибка: ${book.error}` : ''}`
      : `Built-in: ${book.builtin ?? 0} · custom: ${book.custom ?? 0} · total: ${book.total ?? 0}${book.error ? ` · error: ${book.error}` : ''}`;
    const q = search.value.trim().toLowerCase();
    const items = (data?.items || []).filter((fact) =>
      !q || `${fact.id} ${fact.text} ${fact.source}`.toLowerCase().includes(q));
    if (!items.length) {
      list.append(emptyBox(ru() ? 'Ничего не нашлось.' : 'Nothing found.'));
      return;
    }
    for (const fact of items) {
      const source = fact.url
        ? el('a', {
          href: fact.url, target: '_blank', rel: 'noopener noreferrer',
          text: fact.source || (ru() ? 'источник' : 'source'),
        })
        : el('small', { class: 'dim', text: fact.source || '' });
      const card = el('div', { class: 'card' },
        el('div', { class: 'row between' },
          el('b', { text: fact.id }),
          fact.url ? badge(ru() ? 'источник' : 'source', 'amber') : null),
        el('p', { style: { margin: '10px 0', lineHeight: '1.55' }, text: fact.text }),
        el('div', { class: 'row' },
          source,
          el('span', { class: 'spacer' }),
          el('button', {
            class: 'btn btn-small', type: 'button',
            text: ru() ? 'Сказать' : 'Say it',
            onclick: async () => {
              try {
                const result = await api.factsSay(fact.id);
                if (result.ok) {
                  sayOut.textContent = result.text;
                  toast(ru() ? 'Говорю' : 'Saying it', 'good');
                  await ctx.refreshStatus();
                } else {
                  errToast(new Error(result.reason || 'failed'));
                }
              } catch (err) { errToast(err); }
            },
          })));
      list.append(card);
    }
  }

  search.addEventListener('input', draw);

  async function load() {
    try {
      data = await api.factsList(ctx.lang);
      draw();
    } catch (err) {
      data = { items: [], info: {} };
      draw();
      errToast(err);
    }
  }

  load();
}
