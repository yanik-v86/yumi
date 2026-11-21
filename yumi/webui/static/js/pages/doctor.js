import { api } from '../api.js';
import { el, tr, errToast, toast, sectionTitle, badge, fmtClock } from '../ui.js';

const SECTION_LABELS = {
  engines: ['Движки', 'Engines'],
  mics: ['Микрофоны', 'Microphones'],
  models: ['Модели', 'Models'],
  wake: ['Имя', 'Wake word'],
  tts: ['Голос', 'Voice'],
  stt: ['Распознавание', 'Recognition'],
};
const FAST = ['engines', 'mics', 'models'];

export function render(view, ctx) {
  const lang = () => ctx.lang;
  const say = (ru, en) => (lang() === 'ru' ? ru : en);
  let report = null;
  let running = false;

  view.append(
    el('h2', { class: 'pagehead', text: say('Диагностика', 'Diagnostics') }),
    el('p', { class: 'pagelead', text: say(
      'Одна проверка ушек, голоса и моделей. На время теста микрофон забирается у цикла пробуждения — потом он возвращается.',
      'One pass over the ears, the voice and the models. The mic is parked from the wake loop during the test and given back after.'
    ) }),
  );

  const runBtn = el('button', {
    class: 'btn btn-primary', type: 'button',
    text: say('Запустить проверку', 'Run diagnostics'),
  });
  const fastBtn = el('button', {
    class: 'btn btn-small', type: 'button',
    text: say('Быстрая (без микрофона)', 'Quick (no microphone)'),
  });
  const copyBtn = el('button', {
    class: 'btn btn-small', type: 'button',
    text: say('Копировать отчёт', 'Copy report'),
  });
  const statusLine = el('div', { class: 'card-hint', text: '' });
  view.append(el('div', { class: 'row', style: { marginBottom: '12px' } },
    runBtn, fastBtn, copyBtn, statusLine));

  const sample = el('input', {
    type: 'text', value: 'Юми, проверка связи',
    placeholder: say('Контрольная фраза', 'Control phrase'),
    style: { flex: '1', minWidth: '220px' },
  });
  view.append(el('div', { class: 'row', style: { marginBottom: '16px' } },
    el('span', { class: 'card-hint', text: say('Фраза для проверки голоса:', 'Control phrase for the voice test:') }),
    sample));

  const resultBox = el('div', { class: 'card' });
  view.append(sectionTitle(say('Результат', 'Result')));
  view.append(resultBox);

  const summaryBox = el('div', { class: 'card', style: { marginTop: '16px' } });
  view.append(sectionTitle(say('Итог', 'Summary')));
  view.append(summaryBox);

  const modelsBox = el('div', { class: 'card', style: { marginTop: '16px' } });
  const verifyBtn = el('button', {
    class: 'btn btn-small', type: 'button',
    text: say('Проверить модели', 'Verify models'),
    onclick: () => runModels('verify'),
  });
  const recordBtn = el('button', {
    class: 'btn btn-small', type: 'button',
    text: say('Запомнить хэши', 'Record hashes'),
    onclick: () => runModels('record'),
  });
  view.append(sectionTitle(say('Целостность моделей', 'Model integrity'),
    el('div', { class: 'row' }, verifyBtn, recordBtn)));
  view.append(modelsBox);

  function label(name) {
    const pair = SECTION_LABELS[name] || [name, name];
    return lang() === 'ru' ? pair[0] : pair[1];
  }

  function drawReport() {
    resultBox.replaceChildren();
    summaryBox.replaceChildren();
    if (!report) {
      resultBox.append(el('div', { class: 'empty', text: say('Проверка ещё не запускалась.', 'No run yet.') }));
      return;
    }
    const checks = report.checks || {};
    for (const [name, data] of Object.entries(checks)) {
      const ok = Boolean(data && data.ok);
      const detail = data?.error || data?.note || data?.verdict?.reason || '';
      resultBox.append(el('div', { class: 'row', style: { justifyContent: 'flex-start', gap: '10px' } },
        el('span', { class: 'dot', style: { background: ok ? 'var(--mint)' : 'var(--red)' } }),
        el('span', { style: { minWidth: '130px' }, text: label(name) }),
        badge(ok ? say('норма', 'ok') : say('проблема', 'failed'), ok ? 'mint' : 'red'),
        data?.elapsed != null ? el('span', { class: 'card-hint', text: `${data.elapsed}s` }) : null,
        detail ? el('span', { class: 'card-hint', text: String(detail).slice(0, 160) }) : null,
      ));
    }
    const summary = report.summary || {};
    summaryBox.append(el('div', { class: 'row' },
      badge(summary.ok ? say('всё хорошо', 'all good') : say('есть проблемы', 'problems found'),
        summary.ok ? 'mint' : 'red'),
      el('span', { class: 'card-hint', text: `${report.elapsed ?? '—'}s` })));
    if ((summary.failed || []).length) {
      summaryBox.append(el('div', { class: 'card-hint', style: { marginTop: '6px' },
        text: `${say('не прошли', 'failed')}: ${summary.failed.map(label).join(', ')}` }));
    }
    for (const note of (summary.warnings || [])) {
      summaryBox.append(el('div', { class: 'card-hint', style: { marginTop: '4px' }, text: `! ${note}` }));
    }
    drawModels(report.checks?.models?.models || null);
  }

  function drawModels(models) {
    modelsBox.replaceChildren();
    const data = models || ctx.status?.runtime?.models_check?.models || null;
    if (!data || !Object.keys(data).length) {
      modelsBox.append(el('div', { class: 'empty',
        text: say('Хэши ещё не проверялись. Отсутствующая модель — не ошибка.',
          'No check yet. A missing model is not a failure.') }));
      return;
    }
    for (const [name, item] of Object.entries(data)) {
      const kind = item.status === 'ok' ? 'mint' : item.status === 'bad' ? 'red' : 'amber';
      modelsBox.append(el('div', { class: 'row', style: { justifyContent: 'flex-start', gap: '10px' } },
        el('span', { style: { minWidth: '130px' }, text: name }),
        badge(item.status, kind),
        el('span', { class: 'card-hint', text: item.exists ? `${Math.round(item.size / 1048576)} MB` : '—' }),
        item.note ? el('span', { class: 'card-hint', text: String(item.note).slice(0, 120) }) : null,
      ));
    }
  }

  async function run(sections) {
    if (running) return;
    running = true;
    runBtn.disabled = fastBtn.disabled = true;
    runBtn.textContent = say('проверяю…', 'checking…');
    statusLine.textContent = say('Микрофон занят, подожди…', 'The mic is busy, hang on…');
    try {
      report = await api.doctor(sections, sample.value.trim() || null);
      const summary = report.summary || {};
      statusLine.textContent = summary.ok
        ? say('готово', 'done')
        : say('готово, есть проблемы', 'done, with problems');
      drawReport();
      await ctx.refreshStatus();
    } catch (err) {
      statusLine.textContent = err.message || String(err);
      errToast(err);
    } finally {
      running = false;
      runBtn.disabled = fastBtn.disabled = false;
      runBtn.textContent = say('Запустить проверку', 'Run diagnostics');
    }
  }

  async function runModels(mode) {
    verifyBtn.disabled = recordBtn.disabled = true;
    statusLine.textContent = say('считаю хэши…', 'hashing…');
    try {
      const data = mode === 'record' ? await api.modelsRecord(null) : await api.modelsVerify();
      drawModels(data.models || null);
      statusLine.textContent = mode === 'record'
        ? say('хэши запомнены', 'hashes recorded')
        : say('проверено', 'verified');
      await ctx.refreshStatus();
    } catch (err) {
      statusLine.textContent = err.message || String(err);
      errToast(err);
    } finally {
      verifyBtn.disabled = recordBtn.disabled = false;
    }
  }

  runBtn.onclick = () => run(null);
  fastBtn.onclick = () => run(FAST);
  copyBtn.onclick = async () => {
    if (!report) { toast(say('Сначала запусти проверку.', 'Run a check first.')); return; }
    try {
      await navigator.clipboard.writeText(JSON.stringify(report, null, 2));
      toast(say('Отчёт скопирован.', 'Report copied.'));
    } catch (_) {
      toast(say('Не получилось скопировать.', 'Could not copy.'));
    }
  };

  const offStatus = ctx.onStatus((next) => {
    const last = next?.runtime?.doctor;
    if (last?.last_run && (!report || last.last_run > (report.started || 0))) {
      statusLine.textContent = `${say('последний запуск', 'last run')}: ${fmtClock(last.last_run)}`;
    }
    if (!report) drawModels();
  });
  const offDoctor = ctx.onEvent('doctor', (payload) => {
    statusLine.textContent = payload?.ok
      ? say('проверка завершена', 'diagnostics finished')
      : say('проверка завершена с проблемами', 'diagnostics finished with problems');
  });
  drawReport();

  return () => { offStatus(); offDoctor(); };
}
