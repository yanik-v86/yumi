import { api } from '../api.js';
import {
  el, tr, errToast, toast, sectionTitle, buildSetting, emptyBox, badge,
} from '../ui.js';

const CARD_KEYS = {
  activation: ['wake_ears', 'wake_word', 'wake_ear', 'wake_sensitivity',
    'wake_confirm', 'wake_model_size'],
  judge: ['stt_engine', 'stt_size', 'stt_beam', 'stt_crosscheck', 'wake_read_s',
    'phrase_tail_ms', 'wake_after', 'wake_judge_log'],
  voice: ['voice_kind', 'voice_vol', 'tts_ru_speaker', 'tts_en_speaker',
    'tts_pitch', 'tts_ru_model'],
  rest: ['stt_mic', 'stt_echo', 'stt_selfmute', 'name_duck', 'tap_ears', 'timer_sound'],
};
const SPEAKER_KEYS = ['speaker_verify', 'speaker_threshold', 'speaker_min_ms',
  'speaker_join_policy'];
const ALL_KEYS = [...new Set([...Object.values(CARD_KEYS).flat(), ...SPEAKER_KEYS])];

export function render(view, ctx) {
  const lang = () => ctx.lang;
  let status = ctx.status || {};
  let drawnSig = '';
  // Keep the outcome of a microphone test across status redraws: a fresh
  // /api/status tick must not wipe the answer the user came here to see.
  let speakerNotice = '';
  let speakerPick = '';
  let speakerName = '';
  let speakerBusy = false;
  let speakerOut = null;              // one node, carried over between status redraws

  const say = (ru, en) => (lang() === 'ru' ? ru : en);
  const entries = () => {
    const map = {};
    for (const entry of (ctx.schema?.settings || [])) map[entry.key] = entry;
    return map;
  };

  view.append(
    el('h2', { class: 'pagehead', text: say('Ушки и голос', 'Ears & voice') }),
    el('p', { class: 'pagelead', text: say(
      'Какое ухо ловит имя, кто читает фразу и каким голосом она отвечает — всё можно проверить здесь же.',
      'Which ear hears the name, who reads the phrase and which voice answers — test all three right here.') }),
  );

  // ---------------------------------------------------------------- live state
  const heard = el('div', { class: 'bubble', text: say('Нажми «Слушать» и скажи что-нибудь.', 'Press “Listen” and say something.') });
  const secs = el('input', { type: 'number', min: 2, max: 30, value: 8, style: { maxWidth: '80px' } });
  const speakInput = el('input', { type: 'text', placeholder: say('Что ей сказать?', 'What should she say?') });
  const testCard = el('div', { class: 'card' },
    el('h3', { text: say('Быстрая проверка слуха', 'A quick listening test') }),
    el('div', { class: 'row' },
      secs,
      el('button', {
        class: 'btn btn-primary', type: 'button', text: say('Слушать', 'Listen'),
        onclick: async () => {
          heard.textContent = say('слушаю…', 'listening…');
          try {
            const data = await api.post('/api/voice/listen', { seconds: Number(secs.value) || 8 });
            heard.textContent = data.heard
              ? `${say('услышала', 'heard')}: «${data.heard}» (${data.engine || ''})`
              : say('тишина', 'silence');
          } catch (err) {
            heard.textContent = err.message;
            errToast(err);
          }
        },
      }),
      el('button', {
        class: 'btn btn-danger', type: 'button', text: say('Закрыть ушки', 'Stop listening'),
        onclick: async () => {
          try {
            await api.post('/api/voice/stop');
            heard.textContent = say('ушки закрыты', 'ears closed');
          } catch (err) { errToast(err); }
        },
      })),
    el('div', { class: 'row', style: { marginTop: '10px' } },
      speakInput,
      el('button', {
        class: 'btn', type: 'button', text: say('Сказать', 'Speak'),
        onclick: async () => {
          const text = speakInput.value.trim();
          if (!text) return;
          try {
            await api.post('/api/voice/speak', { text });
            toast(say('Говорит', 'Speaking'), 'good');
          } catch (err) { errToast(err); }
        },
      })),
    el('div', { style: { marginTop: '12px' } }, heard));

  const live = el('div', { class: 'card' },
    el('h3', { text: say('Прямо сейчас', 'Right now') }));

  view.append(el('div', { class: 'grid two' }, testCard, live));

  // ---------------------------------------------------------------- the three pickers
  const activationBox = el('div', { class: 'card' });
  const judgeBox = el('div', { class: 'card' });
  const voiceBox = el('div', { class: 'card' });
  const restBox = el('div', { class: 'card', style: { marginTop: '16px' } });
  const speakerBox = el('div', { class: 'card', style: { marginTop: '16px' } });

  view.append(sectionTitle(say('Активация, судья и голос', 'Activation, judge and voice')));
  view.append(el('div', { class: 'stack' }, activationBox, judgeBox, voiceBox));
  view.append(sectionTitle(say('Голоса в разговоре', 'Voices in a talk')));
  view.append(speakerBox);
  view.append(sectionTitle(say('Тонкая настройка', 'Fine tuning')));
  view.append(restBox);

  function value(key) {
    return status.settings?.[key];
  }

  async function apply(key, next) {
    try {
      const data = await ctx.applySettings({ [key]: next });
      if (data?.result?.saved) {
        status.settings = { ...(status.settings || {}), ...data.result.saved };
      }
      return data;
    } catch (err) {
      errToast(err);
      return null;
    }
  }

  function fill(box, keys, title, lead) {
    box.replaceChildren(el('h3', { text: title }));
    if (lead) box.append(el('p', { class: 'card-hint', text: lead }));
    const map = entries();
    let any = false;
    for (const key of keys) {
      const entry = map[key];
      if (!entry) continue;
      any = true;
      box.append(buildSetting(entry, value(key), (next) => apply(key, next)));
    }
    if (!any) box.append(emptyBox(say('Нет настроек', 'No settings')));
    return box;
  }

  function engineLine(label, info, note) {
    const ok = Boolean(info?.available);
    return el('div', { class: 'row' },
      el('span', { class: 'dot', style: { background: ok ? 'var(--mint)' : 'var(--red)' } }),
      el('span', { text: `${label}: ${ok ? say('готово', 'ready') : say('нет', 'missing')}` }),
      note ? el('span', { class: 'card-hint', text: note }) : null);
  }

  function testRow(buttonText, onclick, extra, busy) {
    const out = el('div', { class: 'bubble', text: say('результат появится здесь', 'the result will appear here') });
    const button = el('button', { class: 'btn btn-primary', type: 'button', text: buttonText, onclick: async () => {
      button.disabled = true;
      const old = button.textContent;
      button.textContent = busy?.button || say('слушаю…', 'listening…');
      out.textContent = busy?.out || say('говорю с микрофоном, подожди…', 'holding the microphone, wait…');
      try {
        const text = await onclick();
        out.textContent = text;
      } catch (err) {
        out.textContent = err.message;
        errToast(err);
      } finally {
        button.disabled = false;
        button.textContent = old;
      }
    } });
    return el('div', { class: 'row', style: { marginTop: '10px' } }, ...(extra || []), button, out);
  }

  function drawActivation() {
    const voice = status.runtime?.voice || {};
    const act = voice.activation || {};
    const seconds = el('input', { type: 'number', min: 3, max: 30, value: 8, style: { maxWidth: '80px' } });
    fill(activationBox, CARD_KEYS.activation,
      say('1. Активация: кто слышит имя', '1. Activation: who hears the name'),
      say('openWakeWord — обученное ухо «Юми»; vosk — прежнее угадывание по словам. Если имя прозевали, vosk-фолбэк разбирает хвост: команда выполняется, вопрос уходит в мозг, чужая болтовня молчит.',
          'openWakeWord is the trained «Yumi» ear; vosk is the old word guessing. If the name was missed, the vosk fallback routes the tail: a command runs, a question goes to her mind, background talk stays silent.'));
    activationBox.append(engineLine('openWakeWord', act.oww,
      act.oww?.model_ok ? `${Math.round((act.oww.model_bytes || 0) / 1024)} KB` : ''));
    activationBox.append(engineLine('vosk', act.vosk));
    activationBox.append(testRow(
      say('Проверить имя', 'Test the name'),
      async () => {
        const ear = value('wake_ear') || 'auto';
        const data = await api.post('/api/voice/test-wake', {
          seconds: Number(seconds.value) || 8, ear,
        });
        if (data.woke) {
          return say(`услышала имя (${data.ear}, ${data.elapsed} с)`,
            `heard the name (${data.ear}, ${data.elapsed}s)`);
        }
        return say(`тишина за ${data.seconds} с (${data.ear})`,
          `silence for ${data.seconds}s (${data.ear})`);
      },
      [seconds]));
  }

  function drawJudge() {
    const voice = status.runtime?.voice || {};
    const judge = voice.judge || {};
    const seconds = el('input', { type: 'number', min: 2, max: 30, value: 8, style: { maxWidth: '80px' } });
    fill(judgeBox, CARD_KEYS.judge,
      say('2. Судья: кто читает фразу', '2. Judge: who reads the phrase'),
      say('Nemotron 0.6b читает первым; whisper — фоллбэк, если модели нет или она молчит.',
          'Nemotron 0.6b reads first; whisper is the fallback when the model is away or silent.'));
    judgeBox.append(engineLine('Whisper', judge.whisper));
    judgeBox.append(engineLine('Nemotron 0.6b', judge.nemotron,
      judge.nemotron?.available ? '' : say('нет модели — whisper прочитает запасным', 'no model — whisper reads as the fallback')));
    judgeBox.append(testRow(
      say('Проверить судью', 'Test the judge'),
      async () => {
        const engine = value('stt_engine') || 'whisper';
        const data = await api.post('/api/voice/listen', {
          seconds: Number(seconds.value) || 8, engine,
        });
        return data.heard
          ? `${engine}: «${data.heard}»`
          : say(`${engine}: тишина или не разобрала`, `${engine}: silence or nothing read`);
      },
      [seconds]));
  }

  function drawVoice() {
    const voice = status.runtime?.voice || {};
    const info = voice.tts || {};
    const sample = el('input', {
      type: 'text',
      placeholder: say('Фраза для проверки голоса', 'A phrase to test the voice'),
      value: say('Привет! Это Юми, я говорю своим голосом.', 'Hi! This is Yumi, speaking with my real voice.'),
    });
    fill(voiceBox, CARD_KEYS.voice,
      say('3. Голос: чем она говорит', '3. Voice: how she sounds'),
      say('Голос, модель и высота применяются сразу; проверка звучит даже при типе «Пищалка».',
          'Voice, model and pitch apply at once; the test plays even when the type is “8-bit blips”.'));
    voiceBox.append(engineLine(say('настоящий голос', 'real voice'), info,
      voice.tts_error ? say(`причина: ${voice.tts_error}`, `reason: ${voice.tts_error}`) :
        (info.profile ? `${info.profile.ru_speaker} / ${info.profile.en_speaker} · ${info.profile.pitch}` : '')));
    voiceBox.append(testRow(
      say('Послушать голос', 'Listen to the voice'),
      async () => {
        const data = await api.post('/api/voice/test', {
          text: sample.value.trim() || undefined,
          lang: value('speech_lang') || lang(),
        });
        return say(`сказала «${data.text}» (${data.profile?.ru_speaker || ''} / ${data.profile?.pitch ?? ''})`,
          `said “${data.text}” (${data.profile?.ru_speaker || ''} / ${data.profile?.pitch ?? ''})`);
      },
      [sample],
      {
        button: say('синтезирую…', 'synthesizing…'),
        out: say('готовлю голос, сейчас зазвучит… (в первый раз это может занять до минуты)',
          'preparing the voice, it will sound in a moment… (the first run can take a minute)'),
      }));
  }

  function drawRest() {
    restBox.replaceChildren();
    fill(restBox, CARD_KEYS.rest,
      say('Остальные настройки ушей', 'The rest of the ears'),
      say('Микрофон, эхо, тишина и дневник ушек.', 'Microphone, echo, quiet and the ears’ diary.'));
  }

  function drawSpeaker() {
    const spk = status.runtime?.speaker || {};
    const profiles = Array.isArray(spk.profiles) ? spk.profiles : [];
    const names = new Map(profiles.map((p) => [p.id, p.label || p.id]));
    const labelOf = (id) => names.get(id) || id || '—';
    const labelNow = (id) => {
      const found = (status.runtime?.speaker?.profiles || []).find((p) => p.id === id);
      return (found && (found.label || found.id)) || id || '—';
    };
    if (speakerPick && !names.has(speakerPick)) speakerPick = '';
    fill(speakerBox, SPEAKER_KEYS,
      say('Чьи голоса она слышит', 'Whose voices she hears'),
      say('Знакомый голос продолжает диалог без имени; чужой требует обращения. Векторы голосов хранятся только в приложении.',
        'A known voice can continue a talk without the name; a stranger must address her. Voice vectors stay inside the app.'));
    speakerBox.append(engineLine(say('модель голосов', 'voice model'),
      { available: Boolean(spk.model?.ready) }, spk.model?.error || ''));
    const events = {
      joined: say('новый голос вошёл', 'a new voice joined'),
      recognized: say('узнала голос', 'voice recognised'),
      ignored: say('чужую речь пропустила', 'other talk ignored'),
    };
    const facts = el('div', { class: 'stack', style: { marginTop: '10px' } });
    facts.append(el('div', { class: 'card-hint', text:
      `${say('сейчас в разговоре', 'in this talk')}: ${(spk.participants || []).map(labelOf).join(', ') || '—'}` }));
    facts.append(el('div', { class: 'card-hint', text:
      `${say('последний голос', 'last voice')}: ${spk.current ? labelOf(spk.current.id) : '—'}` }));
    facts.append(el('div', { class: 'card-hint', text:
      `${say('последнее событие', 'last event')}: ${events[spk.last_event] || spk.last_event || '—'}` }));
    speakerBox.append(facts);

    // The result node is created once and only re-appended: a status tick can
    // redraw the card a hundred times without erasing what a button just said.
    if (!speakerOut) speakerOut = el('div', { class: 'bubble' });
    speakerOut.textContent = speakerNotice || say(
      'Нажми кнопку — здесь появится результат проверки.',
      'Press a button — the result will show up here.');
    const setNotice = (text) => {
      speakerNotice = String(text || '');
      speakerOut.textContent = speakerNotice;
    };
    const refresh = async () => {
      await ctx.refreshStatus();
      drawSpeaker();
    };
    const run = (label, fn, message, note) => el('button', {
      class: 'btn btn-small', type: 'button', text: label,
      onclick: async () => {
        if (speakerBusy) return;
        speakerBusy = true;
        setNotice(note || say('подожди…', 'wait…'));
        try {
          const data = await fn();
          await refresh();
          setNotice(message(data) || data?.error || data?.speaker?.error ||
            say('готово', 'done'));
        } catch (err) {
          setNotice(err.message);
          errToast(err);
        } finally {
          speakerBusy = false;
        }
      },
    });
    const listening = say('слушаю голос…', 'listening for the voice…');
    const acquaintanceBtn = el('button', {
      class: 'btn btn-small btn-primary', type: 'button',
      text: say('Познакомиться', 'Get acquainted'),
      onclick: async () => {
        if (speakerBusy) return;
        speakerBusy = true;
        acquaintanceBtn.disabled = true;
        setNotice(say('Юми начинает знакомство: послушай её подсказку и скажи фразу обычным голосом.',
          'Yumi is starting the acquaintance: listen to her prompt and say a phrase in your normal voice.'));
        try {
          await api.speakerAcquaintance();
          const before = new Set((status.runtime?.speaker?.profiles || []).map((p) => p.id));
          for (let i = 0; i < 24; i++) {  // ~12s, enough for TTS + 4s record
            await new Promise((r) => setTimeout(r, 500));
            await ctx.refreshStatus();
            status = ctx.status || status;
            const profiles = status.runtime?.speaker?.profiles || [];
            const added = profiles.find((p) => !before.has(p.id));
            const current = status.runtime?.speaker?.current;
            if (added?.id) {
              speakerPick = added.id;
              speakerName = labelNow(added.id);
              setNotice(say(`Готово: ${speakerName}. Теперь можно нажать «Проверить голос».`,
                `Done: ${speakerName}. Now you can press “Check a voice”.`));
              return;
            }
            if (current?.id && status.runtime?.speaker?.last_event === 'recognized') {
              setNotice(say(`Юми услышала голос: ${labelNow(current.id)}.`,
                `Yumi heard a voice: ${labelNow(current.id)}.`));
              return;
            }
          }
          setNotice(say('Знакомство запущено. Если профиль не появился, проверь микрофон/модель и попробуй ещё раз.',
            'Acquaintance started. If no profile appeared, check microphone/model and try again.'));
        } catch (err) {
          setNotice(err.message);
          errToast(err);
        } finally {
          speakerBusy = false;
          acquaintanceBtn.disabled = false;
        }
      },
    });
    speakerBox.append(el('div', { class: 'row', style: { marginTop: '10px' } },
      acquaintanceBtn,
      run(say('Записать голос', 'Record a voice'), api.speakerEnroll, (data) => {
        const id = data?.speaker?.id || data?.id;
        if (!id) return data?.error || say('голос не записан — проверь микрофон',
          'no voice recorded — check the microphone');
        speakerPick = id;
        speakerName = labelNow(id);
        return say(`записала: ${speakerName}. Теперь нажми «Проверить голос».`,
          `recorded: ${speakerName}. Now press “Check a voice”.`);
      }, listening),
      run(say('Проверить голос', 'Check a voice'), api.speakerTest, (data) => {
        const verdict = data?.speaker || {};
        const score = Number(verdict.score || 0).toFixed(2);
        return verdict.id
          ? say(`узнала: ${labelNow(verdict.id)} (${score})`,
            `recognised: ${labelNow(verdict.id)} (${score})`)
          : data?.error || verdict.error || say(
            'голос незнаком — сначала запиши его кнопкой «Записать голос».',
            'the voice is new — record it with “Record a voice” first.');
      }, listening),
      run(say('Забыть участников', 'Clear participants'), async () => {
        await api.speakerClear();
        return say('диалог забыл участников; профили остались',
          'the talk forgot everyone; the profiles remain');
      })));

    // A profile must be chosen explicitly, and the field starts with its
    // current name (the same way the GTK rename dialog does).
    if (!profiles.length) {
      speakerBox.append(el('div', { class: 'card-hint', style: { marginTop: '10px' }, text:
        say('Профилей пока нет — нажми «Записать голос».',
          'No profiles yet — press “Record a voice”.') }));
    }
    const picker = el('select', {
      disabled: !profiles.length,
      onchange: (ev) => {
        speakerPick = ev.target.value;
        speakerName = names.get(speakerPick) || '';
        rename.value = speakerName;
      },
    });
    picker.append(el('option', { value: '', text: say('выбери профиль', 'pick a profile') }));
    for (const p of profiles) picker.append(el('option', { value: p.id, text: labelOf(p.id) }));
    picker.value = speakerPick;
    const rename = el('input', {
      type: 'text', value: speakerName, disabled: !profiles.length,
      placeholder: say('новое имя', 'a new name'),
      oninput: (ev) => { speakerName = ev.target.value; },
    });
    const change = (label, fn, needsLabel = false) => el('button', {
      class: 'btn btn-small', type: 'button', text: label, disabled: !profiles.length,
      onclick: async () => {
        const id = speakerPick;
        if (!id) { setNotice(say('сначала выбери профиль', 'pick a profile first')); return; }
        if (speakerBusy) return;
        const labelText = rename.value.trim();
        if (needsLabel && !labelText) {
          setNotice(say('введи новое имя', 'type a new name'));
          rename.focus();
          return;
        }
        speakerBusy = true;
        setNotice(say('подожди…', 'wait…'));
        try {
          const before = labelOf(id);
          const data = await fn(id, labelText);
          await refresh();
          setNotice(needsLabel
            ? say(`«${before}» → «${labelText}»`, `“${before}” → “${labelText}”`)
            : (data?.error || say('профиль удалён', 'profile deleted')));
          if (needsLabel) speakerName = labelText;
        } catch (err) {
          setNotice(err.message);
          errToast(err);
        } finally {
          speakerBusy = false;
        }
      },
    });
    const field = (title, node) => el('div', { class: 'field', style: { flex: '1 1 170px' } },
      el('span', { text: title }), node);
    speakerBox.append(el('div', { class: 'card-hint', style: { marginTop: '10px' }, text:
      say('Выбери профиль, чтобы переименовать или удалить:',
        'Pick a profile to rename or delete:') }));
    speakerBox.append(el('div', { class: 'row', style: { marginTop: '6px' } },
      field(say('профиль', 'profile'), picker),
      field(say('новое имя', 'new name'), rename)));
    speakerBox.append(el('div', { class: 'row', style: { marginTop: '8px' } },
      change(say('Переименовать', 'Rename'), (id, next) => api.speakerRename(id, next), true),
      change(say('Удалить', 'Delete'), (id) => api.speakerDelete(id))));
    speakerBox.append(speakerOut);
  }

  function drawLive() {
    const runtime = status.runtime || {};
    const mics = (runtime.mics || [])
      .map((mic) => (typeof mic === 'string' ? { name: mic, label: mic } : mic))
      .filter((mic) => mic && mic.name);
    const current = value('stt_mic');
    const unavailable = runtime.unavailable || [];
    const liveText = [];
    liveText.push(el('div', { class: 'row' },
      el('span', { class: 'dot', style: { background: runtime.wake_on ? 'var(--mint)' : 'var(--red)' } }),
      el('span', { text: runtime.wake_on
        ? say('имя слышит', 'listening for her name')
        : say('имя не слышит', 'name listening is off') })));
    if (runtime.sleeping) liveText.push(badge(say('не мешать', 'dnd'), 'amber'));
    if (runtime.listening) liveText.push(badge(say('слушает фразу', 'listening'), 'mint'));
    if (runtime.conversation_active) liveText.push(badge(say('диалог без имени', 'hands-free talk'), 'mint'));
    if (runtime.busy) liveText.push(badge(say('занята', 'busy'), 'amber'));
    const vs = runtime.voice_state || {};
    const ST = {
      watching: ['имя слышит', 'watching'], candidate: ['имя услышано', 'candidate'],
      listening: ['слушает', 'listening'], held_for_answer: ['ждёт ответа', 'held for answer'],
      awaiting_followup: ['ждёт продолжения', 'waiting for follow-up'],
      paused: ['на паузе', 'paused'], muted: ['заглушено', 'muted'],
      missing: ['нет микрофона', 'no mic'], busy: ['занята', 'busy'], off: ['выключено', 'off'],
    };
    const stText = ST[vs.state] || [vs.state || '—', vs.state || '—'];
    liveText.push(el('div', { class: 'row', style: { justifyContent: 'flex-start', gap: '8px' } },
      el('span', { class: 'card-hint', text: say('состояние:', 'state:') }),
      badge(lang() === 'ru' ? stText[0] : stText[1], 'mint'),
      el('span', { class: 'card-hint', text: `#${vs.generation || 0}${vs.owner ? ` · ${vs.owner}` : ''}` })));
    const micBtn = (label, action) => el('button', {
      class: 'btn btn-small', type: 'button', text: label,
      onclick: async () => {
        try {
          await action();
          await ctx.refreshStatus();
        } catch (err) { errToast(err); }
      },
    });
    liveText.push(el('div', { class: 'row', style: { marginTop: '4px' } },
      micBtn(say('Пауза', 'Pause'), api.voicePause),
      micBtn(say('Продолжить', 'Resume'), api.voiceResume),
      micBtn(say('Освободить', 'Release'), api.voiceRelease)));
    if (unavailable.length) {
      liveText.push(el('div', { class: 'card-hint', text: `${say('недоступно', 'unavailable')}: ${unavailable.join(', ')}` }));
    }
    live.replaceChildren(el('h3', { text: say('Прямо сейчас', 'Right now') }));
    live.append(el('div', { class: 'stack' }, ...liveText));
    live.append(el('div', { class: 'card-hint', style: { marginTop: '10px' },
      text: say('микрофон, которым она слушает:', 'the microphone she hears with:') }));
    const list = el('div', { class: 'stack', style: { marginTop: '4px' } });
    const pick = (next) => async () => {
      await apply('stt_mic', next);
      await ctx.refreshStatus();
      drawAll(true);
    };
    list.append(el('button', {
      class: `btn btn-small${current ? '' : ' btn-primary'}`, type: 'button',
      text: `${current ? '' : '✓ '}${say('авто (рабочий стол)', 'auto (the desktop)')}`,
      title: say('пусть выбирает рабочий стол', 'leave the choice to the desktop'),
      onclick: pick(null),
    }));
    for (const mic of mics) {
      const chosen = current === mic.name;
      list.append(el('button', {
        class: `btn btn-small${chosen ? ' btn-primary' : ''}`, type: 'button',
        text: `${chosen ? '✓ ' : ''}${mic.label || mic.name}`,
        title: mic.name,
        onclick: pick(mic.name),
      }));
    }
    live.append(list);
    if (!mics.length) {
      live.append(el('div', { class: 'card-hint', style: { marginTop: '4px' },
        text: say('микрофоны пока не найдены', 'no microphones found yet') }));
    }
    const find = el('button', {
      class: 'btn btn-small', type: 'button', text: say('Найти микрофоны', 'Find microphones'),
      onclick: async () => {
        find.disabled = true;
        find.textContent = say('ищу…', 'looking…');
        await refreshMics({ quiet: false });
      },
    });
    live.append(el('div', { class: 'row', style: { marginTop: '8px' } }, find));
  }

  async function refreshMics({ quiet = true } = {}) {
    try {
      return await ctx.refreshMics();
    } catch (err) {
      if (!quiet) errToast(err);
      return [];
    }
  }

  function signature() {
    const parts = [];
    for (const key of ALL_KEYS) parts.push(value(key));
    parts.push((status.runtime?.mics || []).map((mic) => (
      typeof mic === 'string' ? mic : `${mic.name}:${mic.label || ''}`)).join('|'));
    const voice = status.runtime?.voice || {};
    parts.push(voice.activation?.oww?.available, voice.activation?.vosk?.available,
      voice.judge?.nemotron?.available, voice.tts?.available);
    const spk = status.runtime?.speaker || {};
    parts.push(JSON.stringify({
      enabled: spk.enabled, policy: spk.policy, last: spk.last_event,
      profiles: (spk.profiles || []).map((p) => `${p.id}:${p.label || ''}`),
      participants: spk.participants || [], current: spk.current?.id || null,
      ready: spk.model?.ready, error: spk.model?.error || null,
    }));
    return JSON.stringify(parts);
  }

  function drawAll(force = false) {
    const sig = signature();
    if (!force && sig === drawnSig) return;
    drawnSig = sig;
    drawActivation();
    drawJudge();
    drawVoice();
    drawSpeaker();
    drawRest();
  }

  const offStatus = ctx.onStatus((next) => {
    status = next;
    drawLive();
    drawAll();
  });
  status = ctx.status || status;
  drawLive();
  drawAll(true);
  if (!(status.runtime?.mics || []).length) refreshMics();

  return () => { offStatus(); };
}
