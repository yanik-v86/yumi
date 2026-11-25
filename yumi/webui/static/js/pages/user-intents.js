// Your own intents: the same JSON you can edit by hand, with a validating form.
// Commands are never shown as plain cards here: the card names the rule, the
// form is the deliberate place where its command or address is written.
import { api } from '../api.js';
import {
  el, icon, toast, errToast, sectionTitle, emptyBox, modal, field,
  confirmDialog, badge, button,
} from '../ui.js';

export function render(view, ctx) {
  const L = (ru, en) => (ctx.lang === 'ru' ? ru : en);
  let data = { version: 1, revision: 0, mtime: 0, intents: [] };

  view.append(
    el('h2', { class: 'pagehead', text: L('Мои фразы', 'My phrases') }),
    el('p', { class: 'pagelead', text: L(
      'Свои правила распознавания в user_intents.json. Они работают после встроенных навыков '
      + 'и кнопок, не требуют дообучения ONNX и подхватываются без перезапуска. '
      + 'Редактора в GTK нет: правь здесь или прямо в файле.',
      'Your own rules in user_intents.json. They run after the built-in skills and buttons, '
      + 'need no ONNX retraining and are picked up without a restart. There is no GTK editor: '
      + 'use this page or edit the file by hand.') }),
  );

  const fileInput = el('input', {
    type: 'file', accept: '.json,application/json', style: { display: 'none' },
  });
  fileInput.addEventListener('change', async () => {
    const file = fileInput.files?.[0];
    if (!file) return;
    try {
      const result = await api.userIntentsImport(await file.text());
      toast(L(`Импортировано правил: ${result.intents?.length || 0}`,
              `Imported ${result.intents?.length || 0} intents`), 'good');
      await load();
    } catch (err) { errToast(err); }
    fileInput.value = '';
  });

  const toolbar = el('div', { class: 'row' },
    button(L('Новое правило', 'New intent'), {
      kind: 'btn-primary', iconName: 'plus', onClick: () => edit(null),
    }),
    button(L('Импорт JSON', 'Import JSON'), {
      iconName: 'upload', onClick: () => fileInput.click(),
    }),
    el('a', {
      class: 'btn', href: '/api/user-intents/export', download: 'user_intents.json',
      title: L('Скачать JSON', 'Download JSON'),
    }, icon('download', 15), el('span', { text: L('Экспорт', 'Export') })),
    fileInput,
  );
  view.append(toolbar);

  const meta = el('p', { class: 'card-hint' });
  const list = el('div', { class: 'grid auto', style: { marginTop: '12px' } });
  view.append(meta, sectionTitle(L('Правила', 'Rules')), list);

  const testInput = el('input', {
    type: 'text', placeholder: L('Фраза для проверки…', 'A phrase to check…'),
    'aria-label': L('Фраза для проверки', 'Phrase to check'),
  });
  const testResult = el('div', { class: 'card-hint' });
  view.append(el('div', { class: 'card', style: { marginTop: '16px' } },
    el('h3', { text: L('Проверить совпадение', 'Check a match') }),
    el('div', { class: 'row' },
      testInput,
      button(L('Совпадение?', 'Match?'), {
        kind: 'btn-primary', iconName: 'search', onClick: async () => {
          try {
            const result = await api.userIntentsTest(testInput.value);
            if (!result.matched) {
              testResult.textContent = L('Совпадений нет', 'No match');
              return;
            }
            const name = result.intent?.name || result.intent?.id || '';
            testResult.textContent = L(
              `Совпадение: ${name} · уверенность ${result.score}`,
              `Matched: ${name} · score ${result.score}`);
          } catch (err) { errToast(err); }
        },
      })),
    testResult,
    el('p', { class: 'card-hint', text: L(
      'Здесь только совпадение: ничего не запускается и файл не меняется. Кнопка «Проверить» на карточке запускает интент.',
      'Match only: nothing runs and the file is unchanged. The card’s “Test” button runs the intent.') }),
  ));

  async function load() {
    try {
      data = await api.userIntentsGet();
      data.intents = data.intents || [];
      draw();
    } catch (err) {
      list.replaceChildren(emptyBox(err.message));
    }
  }

  function lines(value) {
    return String(value || '').split('\n').map((v) => v.trim()).filter(Boolean);
  }

  function draw() {
    meta.textContent = L(
      `Версия ${data.version} · правка ${data.revision} · правил: ${data.intents.length}`,
      `Version ${data.version} · revision ${data.revision} · ${data.intents.length} intents`);
    list.replaceChildren();
    if (!data.intents.length) {
      list.append(emptyBox(L('Пока нет своих правил. Добавь фразу, которую Юми должна узнать.',
                             'No rules yet. Add a phrase Yumi should recognise.')));
      return;
    }
    data.intents.forEach((intent, index) => {
      const actionType = intent.action?.type || '';
      const card = el('div', { class: 'card action-card' },
        el('div', { class: 'row between' },
          el('div', { class: 'row' },
            el('b', { text: intent.name || intent.id }),
            intent.capture ? badge(L('ответ', 'answer'), 'good') : null,
            intent.capture && intent.voice_answer === false
              ? badge(L('без голоса', 'no voice'), 'red') : null,
            intent.capture && intent.bubble_answer === false
              ? badge(L('без бабла', 'no bubble'), 'red') : null,
            intent.enabled ? null : badge(L('выкл', 'off'), 'red')),
          el('span', { class: 'card-hint', text: actionType })),
        el('div', { class: 'card-hint', text: `id: ${intent.id}` }),
        el('div', { class: 'card-hint', text:
          (intent.phrases || []).concat(intent.keywords || []).join(' · ') }),
        intent.capture ? el('div', { class: 'card-hint', text: L(
          `Пузырь до ${intent.bubble_limit || 1000} символов`,
          `Bubble up to ${intent.bubble_limit || 1000} characters`) }) : null,
        el('div', { class: 'row', style: { marginTop: 'auto', paddingTop: '8px' } },
          button(L('Править', 'Edit'), { small: true, onClick: () => edit(index) }),
          button(L('Проверить', 'Test'), {
            small: true,
            title: L('Найти фразу и запустить интент с озвучкой',
                     'Match the phrase and run the intent with speech'),
            onClick: async () => {
              const phrase = (intent.phrases || [])[0] || (intent.keywords || [])[0] || '';
              testInput.value = phrase;
              testInput.dispatchEvent(new Event('change'));
              try {
                const result = await api.userIntentsRun(phrase);
                if (!result.matched) {
                  toast(L('Фраза не находится', 'Phrase does not match'), 'bad');
                } else if (!result.ran) {
                  toast(L('Интент найден, но не запущен', 'Matched, but not run'), 'bad');
                } else {
                  toast(L(`Запущено: ${result.intent?.name || result.intent?.id || ''}`,
                          `Running: ${result.intent?.name || result.intent?.id || ''}`), 'good');
                }
              } catch (err) { errToast(err); }
            },
          }),
          button(L('Удалить', 'Delete'), {
            small: true, kind: 'btn-danger', onClick: () => remove(index),
          })));
      list.append(card);
    });
  }

  function edit(index) {
    const original = index == null ? null : data.intents[index];
    const draft = original ? JSON.parse(JSON.stringify(original)) : {
      id: '', name: '', enabled: true, phrases: [], keywords: [],
      action: { type: 'say', value: '' }, speak: '', capture: false, priority: 0,
      requires_confirmation: false, voice_answer: true, bubble_answer: true,
      bubble_limit: 1000, voice_text: '', bubble_text: '',
    };
    const id = el('input', {
      type: 'text', value: draft.id || '', maxlength: 64, spellcheck: 'false',
      placeholder: 'lights_on',
    });
    const name = el('input', { type: 'text', value: draft.name || '', maxlength: 200 });
    const phrases = el('textarea', { rows: 4, placeholder: L('по одной фразе на строку', 'one phrase per line') });
    phrases.value = (draft.phrases || []).join('\n');
    const keywords = el('textarea', { rows: 3, placeholder: L('по одному слову на строку', 'one keyword per line') });
    keywords.value = (draft.keywords || []).join('\n');
    const kind = el('select');
    for (const [value, label] of [
      ['command', L('Команда (shell)', 'Command (shell)')],
      ['url', L('Ссылка', 'URL')],
      ['say', L('Просто сказать', 'Just say it')],
    ]) {
      kind.append(el('option', { value, text: label, selected: value === draft.action?.type }));
    }
    const value = el('textarea', { rows: 2, spellcheck: 'false',
      placeholder: draft.action?.type === 'url' ? 'https://…' : 'lights on' });
    value.value = draft.action?.value || '';
    const speak = el('input', { type: 'text', value: draft.speak || '', maxlength: 200 });
    const priority = el('input', {
      type: 'number', value: String(draft.priority ?? 0), min: '-100', max: '100', step: '1',
    });
    const enabled = el('input', { type: 'checkbox', checked: draft.enabled !== false });
    const confirmFirst = el('input', {
      type: 'checkbox', checked: Boolean(draft.requires_confirmation),
    });
    const capture = el('input', {
      type: 'checkbox', checked: Boolean(draft.capture),
    });
    const voiceAnswer = el('input', {
      type: 'checkbox', checked: draft.voice_answer !== false,
    });
    const bubbleAnswer = el('input', {
      type: 'checkbox', checked: draft.bubble_answer !== false,
    });
    const bubbleLimit = el('input', {
      type: 'number', value: String(draft.bubble_limit ?? 1000),
      min: '100', max: '4000', step: '100',
    });
    const voiceLine = el('input', {
      type: 'text', value: draft.voice_text || '', maxlength: 1000,
      placeholder: L('Голос: {stdout}', 'Voice: {stdout}'),
    });
    const bubbleLine = el('input', {
      type: 'text', value: draft.bubble_text || '', maxlength: 1000,
      placeholder: L('Бабла: {stdout}', 'Bubble: {stdout}'),
    });
    const captureRow = el('div', { class: 'row' },
      el('label', { class: 'row' }, capture,
        el('span', { text: L('Использовать вывод команды', 'Use the command output') })));
    const answerRows = el('div', { class: 'stack' },
      el('div', { class: 'row' },
        el('label', { class: 'row' }, voiceAnswer,
          el('span', { text: L('Озвучивать отдельно', 'Voice separately') })),
        el('label', { class: 'row' }, bubbleAnswer,
          el('span', { text: L('Пузыть отдельно', 'Bubble separately') }))),
      field(L('Голосовая реплика', 'Voice line'), voiceLine,
        L('Пусто — общая реплика ниже. {stdout} заменяется выводом; без маркера строка дословно.',
          'Empty uses the shared line. {stdout} inserts the output; without it, the line is literal.')),
      field(L('Реплика в бабле', 'Bubble line'), bubbleLine,
        L('Пусто — общая реплика ниже. {stdout} заменяется выводом, лимит обрезает текст.',
          'Empty uses the shared line. {stdout} inserts the output; the limit clips the text.')),
      field(L('Лимит бабла', 'Bubble limit'), bubbleLimit,
        L('От 100 до 4000 символов, по умолчанию 1000.',
          '100 to 4000 characters, 1000 by default.')));
    const captureBlock = el('div', { class: 'full' }, captureRow, answerRows);
    const syncCapture = () => {
      answerRows.style.display = capture.checked ? '' : 'none';
    };
    const syncKind = () => {
      captureBlock.style.display = kind.value === 'command' ? '' : 'none';
      if (kind.value !== 'command') capture.checked = false;
      syncCapture();
    };
    kind.addEventListener('change', syncKind);
    capture.addEventListener('change', syncCapture);
    syncKind();
    const revision = el('input', { type: 'hidden', value: String(data.revision || 0) });

    const body = el('div', { class: 'stack' },
      el('div', { class: 'form-grid' },
        field(L('Название', 'Name'), name),
        field('ID', id),
        el('div', { class: 'full' }, field(L('Фразы', 'Phrases'), phrases,
          L('Точная фраза даёт 1.0; без неё работают ключевые слова.',
            'An exact phrase scores 1.0; keywords work without it.'))),
        el('div', { class: 'full' }, field(L('Ключевые слова', 'Keywords'), keywords)),
        field(L('Действие', 'Action'), kind),
        field(L('Приоритет', 'Priority'), priority,
          L('Только разрешает ничьи после совпадения, не перебивает точную фразу.',
            'Only breaks a tie after scoring; never beats an exact phrase.')),
        el('div', { class: 'full' }, field(L('Значение', 'Value'), value,
          L('Команда, адрес http(s) или реплика для «просто сказать».',
            'A command, an http(s) address, or the line for “just say it”.'))),
        captureBlock,
        el('div', { class: 'full' }, field(L('Реплика после действия', 'Line to say'), speak,
          L('В ответе команды {stdout} заменяется её выводом.',
            'In a captured answer, {stdout} becomes the command output.'))),
        el('div', { class: 'full' }, el('div', { class: 'row' },
          el('label', { class: 'row' }, enabled,
            el('span', { text: L('Включено', 'Enabled') })),
          el('label', { class: 'row' }, confirmFirst,
            el('span', { text: L('Спрашивать перед запуском', 'Ask before running') })))),
        revision,
      ),
    );

    modal({
      title: original ? L('Править правило', 'Edit intent') : L('Новое правило', 'New intent'),
      body, wide: true,
      actions: [
        { label: L('Отмена', 'Cancel') },
        {
          label: L('Сохранить', 'Save'), kind: 'btn-primary',
          onClick: async () => {
            const type = kind.value;
            const entry = {
              ...draft,
              id: id.value.trim(),
              name: name.value.trim() || id.value.trim(),
              enabled: enabled.checked,
              phrases: lines(phrases.value),
              keywords: lines(keywords.value),
              action: { type, value: value.value.trim() },
              speak: speak.value.trim(),
              capture: type === 'command' && capture.checked,
              voice_answer: voiceAnswer.checked,
              bubble_answer: bubbleAnswer.checked,
              bubble_limit: Number.parseInt(bubbleLimit.value, 10) || 1000,
              voice_text: type === 'command' && capture.checked ? voiceLine.value.trim() : '',
              bubble_text: type === 'command' && capture.checked ? bubbleLine.value.trim() : '',
              priority: Number.parseInt(priority.value, 10) || 0,
              requires_confirmation: confirmFirst.checked,
            };
            const next = data.intents.map((item) => ({ ...item }));
            if (index == null) next.push(entry);
            else next[index] = entry;
            try {
              const result = await api.userIntentsPut({
                version: data.version, revision: Number.parseInt(revision.value, 10) || 0,
                intents: next,
              });
              toast(L('Сохранено', 'Saved'), 'good');
              data.revision = result.revision;
              await load();
            } catch (err) {
              if (err.status === 409) toast(L('Файл изменился — обнови страницу',
                'The file changed — refresh the page'), 'bad');
              errToast(err);
              return false;
            }
            return true;
          },
        },
      ],
    });
  }

  async function remove(index) {
    const intent = data.intents[index];
    if (!intent || !await confirmDialog({
      title: L('Удалить правило?', 'Delete the intent?'),
      message: intent.name || intent.id,
      confirmLabel: L('Удалить', 'Delete'), danger: true,
    })) return;
    const next = data.intents.filter((_item, i) => i !== index);
    try {
      await api.userIntentsPut({
        version: data.version, revision: data.revision, intents: next,
      });
      toast(L('Удалено', 'Deleted'), 'good');
      await load();
    } catch (err) { errToast(err); }
  }

  load();
  return null;
}
