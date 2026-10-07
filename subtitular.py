"""Genera subtítulos en español (.srt) para videos en checo y los abre en VLC.

Uso: python subtitular.py video1.mp4 [video2.mp4 ...] [--modelo small|medium] [--no-abrir]
"""
import argparse
import subprocess
import sys
from pathlib import Path

import argostranslate.translate as argos
import numpy as np
from faster_whisper import WhisperModel

VLC = r"C:\Program Files\VideoLAN\VLC\vlc.exe"


def cargar_audio(video):
    """Extrae el audio con ffmpeg a 16 kHz mono (evita depender de PyAV)."""
    pcm = subprocess.run(
        ["ffmpeg", "-nostdin", "-loglevel", "error", "-i", str(video),
         "-ac", "1", "-ar", "16000", "-f", "s16le", "-"],
        capture_output=True, check=True,
    ).stdout
    return np.frombuffer(pcm, np.int16).astype(np.float32) / 32768.0


def tiempo_srt(seg):
    ms = int(round(seg * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def traducir(textos):
    """Traduce checo -> español offline con Argos (pasa por inglés)."""
    salida = []
    for i, t in enumerate(textos, 1):
        salida.append(argos.translate(t, "cs", "es") or t)
        if i % 25 == 0:
            print(f"  traducidas {i}/{len(textos)}")
    return salida


def procesar(video, modelo):
    srt = video.with_suffix(".es.srt")
    print(f"\n== {video.name}: transcribiendo audio en checo (puede tardar)...")
    segmentos, info = modelo.transcribe(cargar_audio(video), language="cs", vad_filter=True)
    segs = []
    for s in segmentos:
        texto = s.text.strip()
        if texto:
            segs.append((s.start, s.end, texto))
            print(f"  {tiempo_srt(s.start)} / {tiempo_srt(info.duration)}  {texto}")
    print(f"== Traduciendo {len(segs)} frases al español...")
    es = traducir([t for _, _, t in segs])
    with srt.open("w", encoding="utf-8") as f:
        for i, ((ini, fin, _), txt) in enumerate(zip(segs, es), 1):
            f.write(f"{i}\n{tiempo_srt(ini)} --> {tiempo_srt(fin)}\n{txt.strip()}\n\n")
    print(f"== Listo: {srt}")
    return srt


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("videos", nargs="+", type=Path)
    ap.add_argument("--modelo", default="small", help="small (rápido) o medium (mejor, más lento)")
    ap.add_argument("--no-abrir", action="store_true")
    args = ap.parse_args()

    print(f"Cargando modelo Whisper '{args.modelo}' (la primera vez se descarga)...")
    modelo = WhisperModel(args.modelo, device="cpu", compute_type="int8")
    for video in args.videos:
        if not video.exists():
            print(f"No existe: {video}", file=sys.stderr)
            continue
        srt = video.with_suffix(".es.srt")
        if not srt.exists():
            srt = procesar(video, modelo)
        if not args.no_abrir:
            subprocess.Popen([VLC, str(video), f"--sub-file={srt}"])


if __name__ == "__main__":
    main()
