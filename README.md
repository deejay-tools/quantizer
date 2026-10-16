# quantizer

Raddrizza brani a tempo variabile (batteristi veri, anni '70/'80) portandoli a BPM
costante, con griglia pronta per Rekordbox.

Pipeline: ffmpeg → beat_this (beat/downbeat) → riparazione beat → tempo map →
`rubberband --fine --timemap` (R3) → ffmpeg (MP3 320k, tag ID3v2.3, copertina) →
`rekordbox.xml` (playlist "Quantized") + `report.json`.

## Setup (macOS Apple Silicon, senza Xcode)

Homebrew non fornisce più bottle (binari precompilati) per macOS 14, quindi
`brew install ffmpeg` prova a compilare dai sorgenti e chiede Xcode. Qui si usano solo
binari precompilati, e il ffmpeg di Homebrew già installato (usato da altre app)
resta com'è: **non lanciare `brew install ffmpeg` né `brew upgrade`**.

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

## Interfaccia grafica

Doppio clic su **`Quantizer.command`** nel Finder, oppure `.venv/bin/python gui.py`.
Si apre `http://127.0.0.1:8765` nel browser: trascini i brani, scegli le opzioni,
premi **Quantizza** e ascolti il risultato nella pagina. Per uscire chiudi la finestra
del Terminale. I file trascinati vengono copiati in `inbox/`; quelli scelti con
"Scegli file…" restano dove sono.

"Apri nella griglia" mostra la forma d'onda del brano quantizzato con la stessa
griglia che vedrà Rekordbox, cioè battute numerate dal primo downbeat. Con
"Controllo qualità" attivo compaiono anche i beat rilevati sull'uscita, colorati
in base alla distanza dalla griglia: verde entro 10 ms, giallo fino a 30 ms,
rosso oltre. I punti rossi sono elencati e con un clic si ascoltano. Il metronomo
suona sulla griglia insieme alla musica. La scheda "Collezione" elenca tutti i
brani già presenti nella cartella di uscita.

Per correggere la griglia senza rielaborare l'audio:

- attiva **"Sposta griglia"** e trascina la forma d'onda;
- oppure usa ±1/±10 ms (o le frecce ←/→);
- "◀ 1 beat ▶" sposta il "1" della battuta;
- "Allinea ai beat" centra la griglia sui beat rilevati.

**"Salva in rekordbox.xml"** aggiorna `report.json` e `rekordbox.xml`; poi reimporta
l'XML in Rekordbox.

## Uso da terminale

```sh
.venv/bin/python quantize.py "brano.mp3" --device mps --verify
```

I file escono in `quantized/`, insieme a `rekordbox.xml` (da importare in Rekordbox)
e `report.json`. I due file sono cumulativi: ogni elaborazione aggiunge i nuovi brani a
quelli già presenti nella cartella. Rielaborare un brano con lo stesso BPM lo sostituisce;
i brani di cui hai cancellato il file vengono tolti.

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

## File del progetto

| Percorso | Contenuto |
|---|---|
| `quantize.py` | pipeline completa, usabile da sola da terminale |
| `gui.py`, `gui/index.html` | interfaccia locale (server Flask su 127.0.0.1:8765 + pagina) |
| `Quantizer.command` | avvio della GUI con doppio clic |
| `bin/` | ffmpeg, ffprobe, rubberband precompilati (non nel repo) |
| `.venv/` | Python 3.12 e dipendenze (non nel repo) |
| `quantized/` | brani elaborati, `rekordbox.xml`, `report.json` (non nel repo) |
| `inbox/` | copie dei file trascinati nella GUI (non nel repo) |

La GUI tiene una copia WAV dei brani aperti nella griglia in
`$TMPDIR/quantizer-pcm/`: è temporanea e si può cancellare in qualsiasi momento.
