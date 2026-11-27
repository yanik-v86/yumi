# GigaAM-v4: установка с нуля

GigaAM-v4 — опциональный чтец фраз после имени «Юми». Он читает русскую речь
значительно устойчивее whisper под музыку и шум и отвечает за ~0.1–0.2 с вместо
~4 с. В Юми он работает как ONNX-граф: **torch и Hugging Face не нужны ушкам в
момент распознавания**. Ниже — полный путь от пустой машины до `stt_engine:
gigaam`.

## 1. Что понадобится

- Linux, интернет **только на время установки** (модель скачивается с Hugging Face).
- ~6–8 ГБ свободного места в пике: CPU-torch в одноразовом venv (~2 ГБ), кэш HF
  с весами (~1 ГБ) и готовый экспорт ONNX (~0.9 ГБ). После экспорта venv и кэш
  можно удалить — рантайм оставит только ONNX.
- Python 3.10–3.12 для экспорта. `uv` желателен, но подойдёт и обычный `venv`.
- Базовый venv ушек: его создаёт `tools/stt_setup.sh`. Он нужен даже если вы не
  хотите whisper: запасное ухо всё равно остаётся в цепочке.

```sh
cd ~/Projects/yumi
./tools/stt_setup.sh
```

Если `stt_setup.sh` ещё не запускался, `gigaam_setup.sh` сам попросит это сделать.

## 2. Одна команда

```sh
./tools/gigaam_setup.sh
```

Скрипт делает всё сам:

1. ставит `onnxruntime` и `sentencepiece` в `~/.local/share/yumi/stt/bin/python`;
2. если подходящего venv с torch нет, создаёт одноразовый
   `~/.local/share/yumi/stt/gigaam-export` и ставит туда CPU-сборки
   `torch==2.5.1` / `torchaudio==2.5.1`, `transformers==4.57.6`, `onnx`,
   `omegaconf`, `soundfile`, `safetensors`, `sentencepiece`, `tqdm`;
3. скачивает `ai-sage/GigaAM-v4` **только ревизии
   `9fe3ebf50c9e0cce5eed60d546938632238b6a96`** (переопределяется через
   `GIGAAM_SHA`) и вызывает `to_onnx()` один раз;
4. кладёт `rnnt_encoder.onnx`, `rnnt_advance.onnx`, два `*_tokenizer.model`,
   `rnnt.yaml` и `revision.txt` в
   `~/.local/share/yumi/stt/gigaam/full` и проверяет их из ears-venv.

`trust_remote_code=True` используется **только здесь**, в одноразовом venv, для
кастомного `modeling_gigaam.py` из репозитория модели. Ушки во время работы
никакой код из Hugging Face не исполняют.

### Если уже есть venv с torch

Можно не ставить второй:

```sh
YUMI_GIGA_EXPORT_PY=/home/you/Recog/.venv/bin/python ./tools/gigaam_setup.sh
```

Скрипт сам найдёт `~/Projects/Recog/.venv`, если он подходит. Требования к
нему: importable `torch`, `torchaudio`, `transformers`, `onnx`, `omegaconf`,
`soundfile`, `sentencepiece`.

### Другие интерпретаторы и каталоги

```sh
YUMI_GIGA_PYTHON=python3.11 YUMI_STT_HOME=/mnt/ssd/yumi-stt ./tools/gigaam_setup.sh
```

`YUMI_GIGA_PYTHON` задаёт базу для нового export-venv, `YUMI_STT_HOME` — куда
ложатся все модели. Переменные нужно повторить и при запуске Юми, если каталог
изменён.

## 3. Проверка

```sh
./tools/gigaam_setup.sh
PYTHONPATH=. ~/.local/share/yumi/stt/bin/python -c \
  'from yumi import gigaam_onnx; print(gigaam_onnx.available())'
```

Второе должно вывести `True`. В веб-панели на странице «Ушки и голос» карточка
«Судья» покажет `GigaAM-v4 (RU): готово`, а GTK-меню покажет модель в списке
уха для фраз. Если ONNX нет, там честно напишут «нет» — распознавание не
сломается.

Перед включением можно прогнать свой A/B на своих записях:

```sh
~/.local/share/yumi/stt/bin/python tools/gigaam_bench.py --data /path/to/wavs
```

В каталоге должен лежать `manifest.tsv` с колонками `file<TAB>reference`.

## 4. Включение

GigaAM **не включается по умолчанию**. Выберите его в одном из двух мест:

- GTK: **Настройки → Её ушки → Ухо для фраз** → `GigaAM-v4 (русский, ONNX)`;
- веб-панель: **Ушки и голос → 2. Судья**;
- или в `~/.config/yumi/settings.json`:

```json
{ "stt_engine": "gigaam" }
```

Цепочка чтения фразы после имени: `gigaam → whisper → vosk`. Если GigaAM
молчит, его нет или фраза не русская, ту же ленту читает whisper, затем vosk.
Само имя «Юми» по-прежнему ловят OpenWakeWord/Vosk, а запасное ухо для сырого
микрофона под музыкой остаётся whisper. `stt_beam`, `stt_hotwords` и `stt_size`
на GigaAM не действуют.

Изменение применяется на ходу: перезапускать Юми не нужно, но демон ушек с
старой версией протокола перезапустится сам (VERSION 32).

## 5. Повторная установка и удаление

```sh
./tools/gigaam_setup.sh --force                  # скачать и экспортировать заново
rm -rf ~/.local/share/yumi/stt/gigaam-export     # удалить одноразовый torch-venv
rm -rf ~/.cache/huggingface/hub/models--ai-sage--GigaAM-v4  # удалить кэш HF
rm -rf ~/.local/share/yumi/stt/gigaam            # полностью убрать GigaAM
```

После удаления export-venv повторный `./tools/gigaam_setup.sh` создаст его
снова. Если вы удалили только ONNX, но оставили venv, экспорт пройдёт быстрее —
без повторной установки torch.

## 6. Если что-то пошло не так

- **«export needs Python 3.10-3.12»** — в системе по умолчанию Python 3.13+,
  у CPU-сборок torch ещё нет wheel. Укажите `YUMI_GIGA_PYTHON=python3.12`.
- **Нет доступа к Hugging Face** — проверьте сеть/прокси; при необходимости
  задайте `HF_ENDPOINT=https://hf-mirror.com`. Веса берутся только один раз.
- **Мало места** — удалите `gigaam-export` и кэш HF после успешного экспорта;
  рантайму нужны только ~0.9 ГБ в `stt/gigaam/full`.
- **Скрипт нашёл чужой venv без onnx** — он доставит `onnx==1.23.2` только в
  него. Если конфликтуют версии, задайте чистый `YUMI_GIGA_EXPORT_PY` или
  удалите `$YUMI_STT_HOME/gigaam-export`.
- **GigaAM молчит на английском** — это ожидаемо: включённая ветка читает только
  русский, английский берёт whisper. Смените `speech_lang` или верните
  `stt_engine: whisper`.

Подробнее о бенчмарке и причинах выбора — `tools/gigaam_bench.py` и раздел про
ушки в `README.ru.md` / `README.md`.
