#!/usr/bin/env python3
"""
gui.py — interfaccia locale per quantize.py.

Avvio: .venv/bin/python gui.py  (oppure doppio clic su Quantizer.command)
Si apre http://127.0.0.1:8765 nel browser. L'elaborazione la fa quantize.py,
lanciato come processo separato con le opzioni scelte nella pagina.
"""
from __future__ import annotations

import json
import logging
import os
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from datetime import datetime
from pathlib import Path

from flask import Flask, abort, jsonify, request, send_file

ROOT = Path(__file__).resolve().parent
PAGE = ROOT / "gui" / "index.html"
INBOX = ROOT / "inbox"
DEFAULT_OUT = ROOT / "quantized"
HOST, PORT = "127.0.0.1", 8765
ALLOWED_HOSTS = {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}
AUDIO_EXT = {".mp3", ".wav", ".aif", ".aiff", ".flac", ".m4a", ".ogg"}

FORMATS = {"mp3", "aiff", "wav", "flac"}
BITRATES = {"320k", "256k", "192k"}
DEVICES = {"mps", "cpu"}

app = Flask(__name__, static_folder=None)


class Job:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.proc: subprocess.Popen | None = None
        self.state = "idle"            # idle | running | done | error | cancelled
        self.log: list[str] = []
        self.total = 0
        self.outdir = DEFAULT_OUT
        self.reports: list[dict] = []
        self.cancelled = False


job = Job()


# ---------------------------------------------------------------- sicurezza

@app.before_request
def local_only():
    # accetta solo richieste dalla pagina stessa (niente altri siti né DNS rebinding)
    if request.host not in ALLOWED_HOSTS:
        abort(403)
    origin = request.headers.get("Origin")
    if origin and origin.removeprefix("http://") not in ALLOWED_HOSTS:
        abort(403)


def output_paths() -> set[Path]:
    return {Path(r["output"]).resolve() for r in job.reports}


# ---------------------------------------------------------------- dialoghi macOS

def osascript(lines: list[str]) -> str | None:
    args = ["osascript"]
    for line in lines:
        args += ["-e", line]
    r = subprocess.run(args, capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else None   # annullato -> None


@app.post("/api/pick-files")
def pick_files():
    out = osascript([
        "activate",
        'set fs to choose file with prompt "Scegli i brani da quantizzare" '
        "with multiple selections allowed",
        'set out to ""',
        "repeat with f in fs",
        "set out to out & POSIX path of f & linefeed",
        "end repeat",
        "return out",
    ])
    paths = [p for p in (out or "").splitlines()
             if p and Path(p).suffix.lower() in AUDIO_EXT]
    return jsonify(paths=paths)


@app.post("/api/pick-folder")
def pick_folder():
    out = osascript([
        "activate",
        'return POSIX path of (choose folder with prompt "Cartella di uscita")',
    ])
    return jsonify(path=out.strip() if out else None)


@app.post("/api/upload")
def upload():
    INBOX.mkdir(exist_ok=True)
    paths = []
    for f in request.files.getlist("files"):
        name = Path(f.filename or "").name
        if not name or Path(name).suffix.lower() not in AUDIO_EXT:
            continue
        dst = INBOX / name
        f.save(dst)
        paths.append(str(dst))
    return jsonify(paths=paths)


# ---------------------------------------------------------------- elaborazione

def build_cmd(files: list[str], o: dict, outdir: Path) -> list[str]:
    if o.get("format") not in FORMATS or o.get("bitrate") not in BITRATES \
            or o.get("device") not in DEVICES:
        raise ValueError("opzione non valida")
    cmd = [sys.executable, "-u", str(ROOT / "quantize.py"), *files,
           "--outdir", str(outdir),
           "--every", str(int(o["every"])),
           "--round", str(float(o["round"])),
           "--format", o["format"],
           "--bitrate", o["bitrate"],
           "--offset-ms", str(float(o["offset_ms"])),
           "--device", o["device"]]
    if o.get("bpm"):
        cmd += ["--bpm", str(float(o["bpm"]))]
    if o.get("verify"):
        cmd.append("--verify")
    return cmd


def watch(proc: subprocess.Popen, started: float) -> None:
    for line in proc.stdout:
        line = line.rstrip()
        if line and "Warning" not in line:
            with job.lock:
                job.log.append(line)
    proc.wait()
    report = job.outdir / "report.json"
    with job.lock:
        if report.exists() and report.stat().st_mtime >= started:
            # report.json è cumulativo: mostra solo i brani di questa elaborazione
            job.reports = [r for r in json.loads(report.read_text())
                           if datetime.fromisoformat(r.get("processed_at", "1970-01-01"))
                           .timestamp() >= started]
        if job.cancelled:
            job.state = "cancelled"
        elif proc.returncode == 0 and job.reports:
            job.state = "done"
        else:
            job.state = "error"
        job.proc = None


@app.post("/api/run")
def run():
    data = request.get_json(force=True)
    files = [f for f in data.get("files", []) if Path(f).is_file()]
    if not files:
        return jsonify(error="Nessun brano valido selezionato"), 400
    outdir = Path(data.get("outdir") or DEFAULT_OUT).expanduser()
    try:
        cmd = build_cmd(files, data.get("options", {}), outdir)
    except (KeyError, TypeError, ValueError) as e:
        return jsonify(error=f"Opzioni non valide: {e}"), 400

    with job.lock:
        if job.state == "running":
            return jsonify(error="Elaborazione già in corso"), 409
        job.state, job.log, job.reports = "running", [], []
        job.total, job.outdir, job.cancelled = len(files), outdir, False
        started = time.time() - 1
        job.proc = subprocess.Popen(
            cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1, env={**os.environ, "PYTHONUNBUFFERED": "1"})
    threading.Thread(target=watch, args=(job.proc, started), daemon=True).start()
    return jsonify(ok=True)


@app.post("/api/cancel")
def cancel():
    with job.lock:
        if job.proc:
            job.cancelled = True
            job.proc.terminate()
    return jsonify(ok=True)


@app.get("/api/status")
def status():
    with job.lock:
        done = sum(1 for line in job.log if line.startswith("▶"))
        return jsonify(state=job.state, log=job.log[-400:], total=job.total,
                       current=done, reports=job.reports, outdir=str(job.outdir))


# ---------------------------------------------------------------- risultati

@app.get("/api/audio")
def audio():
    p = Path(request.args.get("path", "")).resolve()
    if p not in output_paths() or not p.is_file():
        abort(404)
    return send_file(p, conditional=True)


@app.post("/api/reveal")
def reveal():
    p = request.get_json(force=True).get("path")
    if p:
        p = Path(p).resolve()
        if p not in output_paths():
            abort(404)
        subprocess.run(["open", "-R", str(p)])
    else:
        job.outdir.mkdir(parents=True, exist_ok=True)
        subprocess.run(["open", str(job.outdir)])
    return jsonify(ok=True)


@app.get("/api/defaults")
def defaults():
    return jsonify(outdir=str(DEFAULT_OUT))


@app.get("/")
def index():
    return send_file(PAGE)


# ---------------------------------------------------------------- avvio

def main() -> None:
    url = f"http://{HOST}:{PORT}"
    with socket.socket() as s:
        busy = s.connect_ex((HOST, PORT)) == 0
    if busy:   # già aperta: riapri solo la pagina
        webbrowser.open(url)
        return
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    threading.Timer(1.0, webbrowser.open, args=(url,)).start()
    print(f"Quantizer è aperto su {url}\nChiudi questa finestra (o Ctrl+C) per uscire.")
    app.run(host=HOST, port=PORT, threaded=True)


if __name__ == "__main__":
    main()
