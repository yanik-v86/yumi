#!/usr/bin/env python3
"""A/B the ears on one set of wavs: GigaAM ONNX vs whisper, Nemotron and vosk.

Run with the ears' Python (it has onnxruntime, faster-whisper, sherpa-onnx and
vosk). The data directory holds 16 kHz mono wavs and manifest.tsv lines of
``name<TAB>the phrase that was actually said``. A fixed TTS phrase list gives a
reference without hand transcription; real recordings need a transcript.

    ~/.local/share/yumi/stt/bin/python tools/gigaam_bench.py --data /tmp/yumi-ab
"""
import argparse
import json
import re
import sys
import time
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

HOME = Path(__import__('os').environ.get('YUMI_STT_HOME')
             or Path.home() / '.local/share/yumi/stt')
DEFAULT_ENGINES = ('gigaam', 'gigaam-raw', 'whisper', 'nemotron', 'vosk')


def pcm(path):
    with wave.open(str(path), 'rb') as f:
        if f.getframerate() != 16000 or f.getnchannels() != 1:
            raise ValueError(f'need 16 kHz mono wav: {path}')
        return np.frombuffer(f.readframes(f.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0


def normal(text):
    text = text.lower().replace('ё', 'е')
    return ' '.join(re.sub(r'[^\w\s]', ' ', text).split())


def edit_distance(a, b):
    """Levenshtein over words (or characters); enough for a few dozen clips"""
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(cur[-1] + 1, prev[j] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def make_engines(names):
    """Only the ears that are actually installed join the comparison"""
    out = {}
    if 'gigaam' in names or 'gigaam-raw' in names:
        from yumi import gigaam_onnx
        if gigaam_onnx.available():
            model = gigaam_onnx.load()
            if 'gigaam' in names:
                out['gigaam'] = lambda a: model.transcribe(a)['e2e']
            if 'gigaam-raw' in names:
                out['gigaam-raw'] = lambda a: model.transcribe(a)['raw']
        else:
            print('skip gigaam: no ONNX export (run tools/gigaam_setup.sh)')
    if 'whisper' in names:
        try:
            from faster_whisper import WhisperModel
            whisper_model = WhisperModel('small', device='cpu', compute_type='int8',
                                         cpu_threads=2,
                                         download_root=str(HOME / 'whisper'))
            out['whisper'] = lambda a: ' '.join(
                s.text for s in whisper_model.transcribe(
                    a, language='ru', beam_size=5, vad_filter=True,
                    condition_on_previous_text=False)[0]).strip()
        except Exception as e:                  # noqa: BLE001 - a missing ear is not fatal
            print(f'skip whisper: {e}')
    if 'nemotron' in names:
        try:
            import sherpa_onnx
            d = HOME / ('sherpa-onnx-nemotron-3.5-asr-streaming-0.6b-560ms-int8-2026-06-11')
            if not (d / 'encoder.int8.onnx').exists():
                raise FileNotFoundError(d)
            nemotron_rec = sherpa_onnx.OnlineRecognizer.from_transducer(
                tokens=str(d / 'tokens.txt'), encoder=str(d / 'encoder.int8.onnx'),
                decoder=str(d / 'decoder.int8.onnx'), joiner=str(d / 'joiner.int8.onnx'),
                num_threads=2, sample_rate=16000, feature_dim=80,
                decoding_method='modified_beam_search', max_active_paths=5)

            def nemotron(audio):
                st = nemotron_rec.create_stream()
                st.accept_waveform(16000, audio)
                st.input_finished()
                while nemotron_rec.is_ready(st):
                    nemotron_rec.decode_stream(st)
                try:
                    return json.loads(
                        nemotron_rec.get_result_as_json_string(st)).get('text', '')
                except Exception:               # noqa: BLE001 - older sherpa has plain results
                    return str(nemotron_rec.get_result(st))
            out['nemotron'] = nemotron
        except Exception as e:                  # noqa: BLE001
            print(f'skip nemotron: {e}')
    if 'vosk' in names:
        try:
            from vosk import KaldiRecognizer, Model
            vosk_model = Model(str(HOME / 'vosk-model-small-ru-0.22'))
            def vosk(audio):
                data = (np.clip(audio, -1, 1) * 32767).astype(np.int16).tobytes()
                r = KaldiRecognizer(vosk_model, 16000)
                r.SetWords(False)
                text = ''
                for i in range(0, len(data), 4000):
                    if r.AcceptWaveform(data[i:i + 4000]):
                        text += ' ' + json.loads(r.FinalResult() or '{}').get('text', '')
                text += ' ' + json.loads(r.FinalResult() or '{}').get('text', '')
                return text.strip()
            out['vosk'] = vosk
        except Exception as e:                  # noqa: BLE001
            print(f'skip vosk: {e}')
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--data', default='/tmp/yumi-ab', help='wavs + manifest.tsv')
    ap.add_argument('--manifest', help='a different manifest (default: <data>/manifest.tsv)')
    ap.add_argument('--engines', default=','.join(DEFAULT_ENGINES))
    ap.add_argument('--json', help='save per-clip results here')
    a = ap.parse_args()

    data = Path(a.data)
    manifest = Path(a.manifest) if a.manifest else data / 'manifest.tsv'
    clips = []
    for line in manifest.read_text().splitlines():
        if not line.strip() or line.startswith('#'):
            continue
        name, ref = line.split('\t', 1)
        clips.append((data / name, ref.strip()))
    if not clips:
        raise SystemExit(f'no clips in {manifest}')
    print(f'{len(clips)} clips in {data}', flush=True)

    engines = make_engines([e.strip() for e in a.engines.split(',') if e.strip()])
    if not engines:
        raise SystemExit('no ears available')
    details, summary = [], {}
    for path, ref in clips:
        audio = pcm(path)
        row = {'file': path.name, 'ref': ref, 'heard': {}}
        print(f'\nREF: {ref}', flush=True)
        for name, fn in engines.items():
            t = time.monotonic()
            try:
                text = fn(audio)
            except Exception as e:              # noqa: BLE001 - one bad ear must not stop the run
                text = f'<ERROR {type(e).__name__}: {e}>'
            dt = time.monotonic() - t
            words_ref, words_got = normal(ref).split(), normal(text).split()
            chars_ref, chars_got = normal(ref), normal(text)
            wer = edit_distance(words_ref, words_got) / max(1, len(words_ref))
            cer = edit_distance(chars_ref, chars_got) / max(1, len(chars_ref))
            row['heard'][name] = {'text': text, 'wer': round(wer, 3),
                                  'cer': round(cer, 3), 'sec': round(dt, 3)}
            print(f'  {name:10} WER {wer:.2f} CER {cer:.2f} {dt:.2f}s :: {text[:90]}',
                  flush=True)
        details.append(row)
    print('\nSUMMARY')
    for name in engines:
        vals = [r['heard'][name] for r in details]
        times = sorted(v['sec'] for v in vals)
        summary[name] = {
            'wer': round(sum(v['wer'] for v in vals) / len(vals), 3),
            'cer': round(sum(v['cer'] for v in vals) / len(vals), 3),
            'p50_sec': times[len(times) // 2],
            'max_sec': times[-1],
        }
        print(f"  {name:10} WER {summary[name]['wer']:.3f} "
              f"CER {summary[name]['cer']:.3f} "
              f"p50 {summary[name]['p50_sec']:.2f}s max {summary[name]['max_sec']:.2f}s")
    if a.json:
        Path(a.json).write_text(json.dumps({'summary': summary, 'clips': details},
                                           ensure_ascii=False, indent=2) + '\n')
        print(f'saved {a.json}')


if __name__ == '__main__':
    main()
