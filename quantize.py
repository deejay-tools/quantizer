#!/usr/bin/env python3
"""
quantize.py — raddrizza brani a tempo variabile (batteristi veri) su BPM costante.

Pipeline:
  ffmpeg (decode WAV) -> beat_this (beat + downbeat) -> riparazione beat
  -> tempo map -> rubberband R3 --timemap -> ffmpeg (MP3 320k + tag e copertina)
  -> rekordbox.xml con griglia a BPM fisso + report.json

rekordbox.xml e report.json sono cumulativi: ogni esecuzione aggiunge i nuovi brani
a quelli già presenti nella cartella di uscita (stesso file di uscita = sostituito,
file cancellati = rimossi).

Binari esterni (ffmpeg, ffprobe, rubberband), cercati in quest'ordine:
  1. variabile d'ambiente QUANTIZER_FFMPEG / QUANTIZER_FFPROBE / QUANTIZER_RUBBERBAND
  2. cartella ./bin accanto a questo script
  3. PATH

Uso:
  python quantize.py brano.mp3 [altri file...] [--every 1] [--bpm 118] [--verify]
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import numpy as np
import soundfile as sf

BIN_DIR = Path(__file__).resolve().parent / "bin"

# nome -> percorso eseguibile, riempito da check_tools()
TOOLS: dict[str, str] = {}

# estensione, argomenti codec, Kind per Rekordbox, copia copertina
FORMATS = {
    "mp3": ("mp3", ["-c:a", "libmp3lame", "-b:a", "{bitrate}", "-id3v2_version", "3"],
            "MP3 File", True),
    "aiff": ("aiff", ["-c:a", "pcm_s24be", "-write_id3v2", "1"], "AIFF File", False),
    "wav": ("wav", ["-c:a", "pcm_s24le"], "WAV File", False),
    "flac": ("flac", ["-c:a", "flac"], "FLAC File", False),
}


# ---------------------------------------------------------------- utilità

def run(cmd: list) -> subprocess.CompletedProcess:
    r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"{Path(str(cmd[0])).name} fallito:\n{r.stderr[-1500:]}")
    return r


def find_tool(name: str) -> str | None:
    env = os.environ.get(f"QUANTIZER_{name.upper()}")
    if env:
        if not (os.path.isfile(env) and os.access(env, os.X_OK)):
            sys.exit(f"QUANTIZER_{name.upper()}={env} non è un eseguibile valido")
        return env
    local = BIN_DIR / name
    if local.is_file() and os.access(local, os.X_OK):
        return str(local)
    return shutil.which(name)


def check_tools() -> None:
    missing = []
    for name in ("ffmpeg", "ffprobe", "rubberband"):
        path = find_tool(name)
        if path:
            TOOLS[name] = path
        else:
            missing.append(name)
    if missing:
        sys.exit(f"Mancano: {', '.join(missing)}  ->  mettili in {BIN_DIR}, nel PATH "
                 f"o indica il percorso con QUANTIZER_<NOME> (vedi README)")


def read_tags(src: Path) -> dict:
    r = run([TOOLS["ffprobe"], "-v", "error", "-show_entries", "format_tags=title,artist",
             "-of", "json", src])
    tags = json.loads(r.stdout).get("format", {}).get("tags", {})
    return {k.lower(): v for k, v in tags.items()}


def decode(src: Path, dst: Path) -> None:
    run([TOOLS["ffmpeg"], "-y", "-v", "error", "-i", src, "-vn", "-c:a", "pcm_s24le", dst])


# ---------------------------------------------------------------- analisi

def repair_beats(beats: np.ndarray) -> tuple[np.ndarray, int, int]:
    """Inserisce beat mancanti e scarta beat spuri usando il periodo locale."""
    gmed = float(np.median(np.diff(beats)))
    out = [float(beats[0])]
    inserted = dropped = 0
    for b in beats[1:]:
        recent = np.diff(out[-9:])
        p = float(np.median(recent)) if len(recent) >= 4 else gmed
        gap = float(b) - out[-1]
        if gap < 0.6 * p:              # beat spurio (doppio, ghost note)
            dropped += 1
            continue
        n = int(round(gap / p))
        if n >= 2:                     # beat mancanti: interpola
            start = out[-1]
            out.extend(start + gap * k / n for k in range(1, n))
            inserted += n - 1
        out.append(float(b))
    return np.array(out), inserted, dropped


def build_plan(beats: np.ndarray, sr: int, duration: float, every: int,
               bpm: float | None, round_to: float) -> dict:
    i = np.arange(len(beats))
    slope, intercept = np.polyfit(i, beats, 1)
    est_bpm = 60.0 / slope
    target = bpm if bpm else round(est_bpm / round_to) * round_to
    pt = 60.0 / target

    d = np.diff(beats)
    p_start = float(np.median(d[:8]))
    p_end = float(np.median(d[-8:]))

    # intro e coda vengono scalate col tempo locale di inizio/fine,
    # così l'intero brano risulta a BPM costante
    t0 = beats[0] * pt / p_start
    targets = t0 + i * pt
    target_dur = float(targets[-1] + (duration - beats[-1]) * pt / p_end)

    keys = list(range(0, len(beats), every))
    if keys[-1] != len(beats) - 1:
        keys.append(len(beats) - 1)
    timemap = [(int(round(beats[k] * sr)), int(round(targets[k] * sr)))
               for k in keys if beats[k] > 0]

    smooth = np.convolve(d, np.ones(8) / 8, mode="valid") if len(d) >= 8 else d
    local = 60.0 / smooth
    resid = beats - (slope * i + intercept)

    return {
        "est_bpm": float(est_bpm),
        "target_bpm": float(target),
        "period": pt,
        "t0": float(t0),
        "target_dur": target_dur,
        "timemap": timemap,
        "local_bpm_min": float(local.min()),
        "local_bpm_max": float(local.max()),
        "drift_max_ms": float(np.max(np.abs(resid)) * 1000),
    }


def first_downbeat_target(beats: np.ndarray, downbeats: np.ndarray, plan: dict) -> float:
    if len(downbeats) == 0:
        return plan["t0"]
    k = int(np.argmin(np.abs(beats - downbeats[0])))
    return plan["t0"] + k * plan["period"]


def verify(f2b, wav: Path) -> dict:
    raw, down = f2b(str(wav))
    b, _, _ = repair_beats(np.asarray(raw, float))
    i = np.arange(len(b))
    s, c = np.polyfit(i, b, 1)
    r = np.abs(b - (s * i + c)) * 1000
    # beat e downbeat rilevati sull'output, per la vista forma d'onda della GUI
    return {"bpm": float(60 / s), "err_median_ms": float(np.median(r)),
            "err_max_ms": float(np.max(r)),
            "beats": [round(float(x), 4) for x in raw],
            "downbeats": [round(float(x), 4) for x in down]}


# ---------------------------------------------------------------- pipeline

def process(src: Path, f2b, args, tmp: Path) -> dict:
    tags = read_tags(src)
    dec = tmp / "in.wav"
    decode(src, dec)
    info = sf.info(str(dec))
    sr, duration = info.samplerate, info.frames / info.samplerate

    raw, down = f2b(str(dec))
    raw, down = np.asarray(raw, float), np.asarray(down, float)
    if len(raw) < 16:
        raise RuntimeError("troppo pochi beat rilevati")
    beats, inserted, dropped = repair_beats(raw)

    plan = build_plan(beats, sr, duration, args.every, args.bpm, args.round)

    mapfile = tmp / "map.txt"
    mapfile.write_text("".join(f"{s} {t}\n" for s, t in plan["timemap"]))
    stretched = tmp / "out.wav"
    run([TOOLS["rubberband"], "--fine", "-q", "-D", f"{plan['target_dur']:.6f}",
         "--timemap", mapfile, dec, stretched])

    ext, codec, kind, cover = FORMATS[args.format]
    codec = [c.format(bitrate=args.bitrate) for c in codec]
    dst = args.outdir / f"{src.stem} (Q {plan['target_bpm']:.2f}).{ext}"
    cover_args = (["-map", "1:v?", "-c:v", "copy", "-disposition:v", "attached_pic"]
                  if cover else [])
    run([TOOLS["ffmpeg"], "-y", "-v", "error", "-i", stretched, "-i", src,
         "-map", "0:a", "-map_metadata", "1", *cover_args, *codec, dst])

    report = {
        "source": str(src), "output": str(dst),
        "title": tags.get("title", src.stem), "artist": tags.get("artist", ""),
        "kind": kind,
        "processed_at": datetime.now().isoformat(timespec="seconds"),
        "beats_detected": int(len(raw)), "beats_inserted": inserted,
        "beats_dropped": dropped,
        "est_bpm": round(plan["est_bpm"], 3),
        "target_bpm": plan["target_bpm"],
        "local_bpm_range": [round(plan["local_bpm_min"], 2), round(plan["local_bpm_max"], 2)],
        "drift_max_ms": round(plan["drift_max_ms"], 1),
        "duration_in": round(duration, 3),
        "duration_out": round(plan["target_dur"], 3),
        "first_downbeat": round(first_downbeat_target(beats, down, plan)
                                + args.offset_ms / 1000, 3),
    }
    if args.verify:
        report["verify"] = verify(f2b, stretched)
    return report


# ---------------------------------------------------------------- collezione

def merge_collection(report_path: Path, new: list[dict]) -> list[dict]:
    """Unisce i nuovi brani a quelli già in report.json, una voce per file di uscita."""
    old: list[dict] = []
    if report_path.exists():
        try:
            old = json.loads(report_path.read_text())
        except (json.JSONDecodeError, OSError):
            backup = report_path.with_suffix(".json.bak")
            report_path.replace(backup)
            print(f"  ! {report_path.name} illeggibile, salvato come {backup.name}")
    merged = {str(Path(r["output"]).resolve()): r for r in old
              if Path(r.get("output", "")).is_file()}
    for r in new:
        merged[str(Path(r["output"]).resolve())] = r
    return list(merged.values())


def write_rekordbox_xml(reports: list[dict], path: Path) -> None:
    root = ET.Element("DJ_PLAYLISTS", Version="1.0.0")
    ET.SubElement(root, "PRODUCT", Name="quantize.py", Version="0.1", Company="")
    coll = ET.SubElement(root, "COLLECTION", Entries=str(len(reports)))
    for n, r in enumerate(reports, 1):
        bpm = f"{r['target_bpm']:.2f}"
        loc = "file://localhost" + quote(str(Path(r["output"]).resolve()))
        t = ET.SubElement(coll, "TRACK", TrackID=str(n), Name=r["title"],
                          Artist=r["artist"], Kind=r["kind"],
                          TotalTime=str(int(r["duration_out"])),
                          AverageBpm=bpm, Location=loc)
        ET.SubElement(t, "TEMPO", Inizio=f"{r['first_downbeat']:.3f}", Bpm=bpm,
                      Metro="4/4", Battito="1")
    pl = ET.SubElement(root, "PLAYLISTS")
    rootnode = ET.SubElement(pl, "NODE", Type="0", Name="ROOT", Count="1")
    node = ET.SubElement(rootnode, "NODE", Name="Quantized", Type="1",
                         KeyType="0", Entries=str(len(reports)))
    for n in range(1, len(reports) + 1):
        ET.SubElement(node, "TRACK", Key=str(n))
    ET.indent(root)
    ET.ElementTree(root).write(path, encoding="UTF-8", xml_declaration=True)


def main() -> None:
    ap = argparse.ArgumentParser(description="Quantizza brani a tempo variabile.")
    ap.add_argument("inputs", nargs="+", type=Path)
    ap.add_argument("--outdir", type=Path, default=Path("quantized"))
    ap.add_argument("--every", type=int, default=1,
                    help="punto di ancoraggio ogni N beat (1=ogni beat, 4=ogni battuta)")
    ap.add_argument("--bpm", type=float, help="BPM di destinazione forzato")
    ap.add_argument("--round", type=float, default=0.01,
                    help="arrotondamento del BPM stimato (0.01, 0.5, 1...)")
    ap.add_argument("--format", choices=FORMATS, default="mp3")
    ap.add_argument("--bitrate", default="320k", help="bitrate MP3 (default 320k CBR)")
    ap.add_argument("--offset-ms", type=float, default=0.0,
                    help="correzione manuale del primo downbeat nell'XML (ms)")
    ap.add_argument("--device", default="cpu", help="cpu oppure mps")
    ap.add_argument("--verify", action="store_true",
                    help="rianalizza l'output e misura l'errore residuo")
    args = ap.parse_args()

    check_tools()
    args.outdir.mkdir(parents=True, exist_ok=True)

    from beat_this.inference import File2Beats
    f2b = File2Beats(checkpoint_path="final0", device=args.device, dbn=False)

    reports = []
    for src in args.inputs:
        print(f"▶ {src.name}")
        try:
            with tempfile.TemporaryDirectory() as tmp:
                r = process(src, f2b, args, Path(tmp))
            reports.append(r)
            lo, hi = r["local_bpm_range"]
            print(f"  {r['est_bpm']:.2f} -> {r['target_bpm']:.2f} BPM | "
                  f"tempo locale {lo}-{hi} | deriva max {r['drift_max_ms']} ms | "
                  f"beat +{r['beats_inserted']}/-{r['beats_dropped']}")
            if "verify" in r:
                v = r["verify"]
                print(f"  verifica: errore mediano {v['err_median_ms']:.1f} ms, "
                      f"max {v['err_max_ms']:.1f} ms")
        except Exception as e:  # noqa: BLE001
            print(f"  ✗ {e}")

    if reports:
        report_path = args.outdir / "report.json"
        collection = merge_collection(report_path, reports)
        write_rekordbox_xml(collection, args.outdir / "rekordbox.xml")
        report_path.write_text(json.dumps(collection, indent=2, ensure_ascii=False))
        print(f"\n✓ {len(reports)} brani in {args.outdir}/ "
              f"(rekordbox.xml e report.json: {len(collection)} brani in totale)")


if __name__ == "__main__":
    main()
