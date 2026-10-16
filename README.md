# quantizer

Raddrizza brani a tempo variabile (batteristi veri, anni '70/'80) portandoli a BPM
costante, con griglia pronta per Rekordbox.

Pipeline: ffmpeg → beat_this (beat/downbeat) → riparazione beat → tempo map →
`rubberband --fine --timemap` (R3) → ffmpeg (MP3 320k, tag ID3v2.3, copertina) →
`rekordbox.xml` (playlist "Quantized") + `report.json`.

## Setup (macOS Apple Silicon, senza Xcode)

Homebrew non compila più bottle per macOS 14, quindi `brew install ffmpeg` prova a
compilare e chiede Xcode. Qui si usano solo binari precompilati.

```sh
# 1. uv (in ~/.local/bin, nessun sudo)
curl -LsSf https://astral.sh/uv/install.sh | UV_NO_MODIFY_PATH=1 sh

# 2. venv con Python 3.12 gestito da uv + dipendenze
uv venv --python 3.12 --managed-python .venv
uv pip install --python .venv -r requirements.txt

# 3. binari esterni in ./bin (usati solo da quantize.py, non entrano nel PATH)
mkdir -p bin && cd bin
curl -LO https://breakfastquay.com/files/releases/rubberband-4.0.0-gpl-executable-macos.tar.bz2
tar xjf rubberband-4.0.0-gpl-executable-macos.tar.bz2
mv rubberband-4.0.0-gpl-executable-macos/rubberband . && rm -rf rubberband-4.0.0-gpl-*
curl -LO https://www.osxexperts.net/ffmpeg9arm.zip && unzip -oj ffmpeg9arm.zip ffmpeg
curl -LO https://www.osxexperts.net/ffprobe9arm.zip && unzip -oj ffprobe9arm.zip ffprobe
rm -f *.zip && chmod +x ffmpeg ffprobe rubberband && xattr -c ffmpeg ffprobe rubberband
cd ..
```

Serve Rubber Band **3 o superiore** (opzioni `--fine` e `--timemap`): verifica con
`bin/rubberband --version`.

Ordine di ricerca dei binari:

1. `QUANTIZER_FFMPEG`, `QUANTIZER_FFPROBE`, `QUANTIZER_RUBBERBAND`
2. `./bin`
3. `PATH`

Al primo avvio beat_this scarica il checkpoint `final0` in `~/.cache/torch/hub/checkpoints/`.

## Uso

```sh
.venv/bin/python quantize.py "brano.mp3" --device mps --verify
```

I file escono in `quantized/`, insieme a `rekordbox.xml` (da importare in Rekordbox)
e `report.json`.

| Opzione | Descrizione |
|---|---|
| `--every N` | ancoraggio ogni N beat (1 = ogni beat, 4 = ogni battuta, più morbido) |
| `--bpm X` | BPM di destinazione forzato |
| `--round X` | arrotondamento del BPM stimato (0.01, 0.5, 1…) |
| `--format` | `mp3` (default), `aiff`, `wav`, `flac` |
| `--bitrate` | bitrate MP3, default `320k` |
| `--offset-ms` | sposta il primo downbeat nell'XML |
| `--device` | `cpu` o `mps` (su M1, `mps` è circa 2,3× più veloce nell'analisi) |
| `--outdir` | cartella di uscita, default `quantized` |
| `--verify` | rianalizza l'output e misura l'errore residuo |
