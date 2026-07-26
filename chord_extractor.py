"""
chord_extractor.py
------------------
Extrae acordes (y estima tonalidad y tempo) de un archivo de audio
(MP3, WAV, FLAC, OGG... cualquier cosa que ffmpeg pueda decodificar)
usando los modelos preentrenados de madmom.

Opcionalmente, con --separate, primero separa la canción con Demucs y analiza
solo la parte armónica (bass + other, sin batería ni voz), lo que mejora la
detección de acordes en mezclas densas. Usa la GPU si está disponible.

Uso como módulo:
    from chord_extractor import extract
    result = extract("cancion.mp3")
    result = extract("cancion.mp3", separate=True)   # con separación Demucs
    print(result.to_dict())

Uso como CLI:
    python chord_extractor.py cancion.mp3
    python chord_extractor.py cancion.mp3 --method cnn --json out.json
    python chord_extractor.py cancion.mp3 --separate            # Demucs + GPU auto
    python chord_extractor.py cancion.mp3 --separate --device cpu

Métodos de acordes:
    "deepchroma" (por defecto): DeepChroma + decoder. Rápido, sólido en pop/rock.
    "cnn":                      CNNChordFeature + CRF. A veces mejor en audio real.
Ambos modelos reconocen los 24 acordes mayores/menores (tríadas). No detectan
séptimas, sus4, acordes de jazz, etc. Para eso hace falta otro modelo.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import warnings
from dataclasses import dataclass, field, asdict
from typing import List, Optional

warnings.filterwarnings("ignore")


@dataclass
class ChordSegment:
    start: float      # segundos
    end: float        # segundos
    chord: str        # p.ej. "C:maj", "A:min", "N" (sin acorde)


@dataclass
class ExtractionResult:
    source: str
    method: str
    separated: bool = False
    key: Optional[str] = None
    tempo_bpm: Optional[float] = None
    chords: List[ChordSegment] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self, **kw) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, **kw)

    def to_lab(self) -> str:
        """
        Formato .lab estándar (MIREX / Chordino / mir_eval / Sonic Visualiser):
        una línea por segmento -> "inicio<TAB>fin<TAB>etiqueta", tiempos en
        segundos. 'N' = sin acorde (convención del formato).
        """
        return "".join(
            f"{c.start:.6f}\t{c.end:.6f}\t{c.chord}\n" for c in self.chords
        )


# --------------------------------------------------------------------------- #
# Separación de fuentes con Demucs (opcional)
# --------------------------------------------------------------------------- #
def _pick_device(requested: str) -> str:
    """Resuelve 'auto' -> 'cuda' si hay GPU disponible, si no 'cpu'."""
    if requested and requested != "auto":
        return requested
    try:
        import torch
        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


def _to_float_mono(rate, data):
    """Normaliza un array de wav (int o float, mono o estéreo) a float32 mono."""
    import numpy as np
    data = np.asarray(data)
    if np.issubdtype(data.dtype, np.integer):
        data = data.astype(np.float32) / np.iinfo(data.dtype).max
    else:
        data = data.astype(np.float32)
    if data.ndim > 1:            # estéreo -> mono
        data = data.mean(axis=1)
    return rate, data


def _combine_stems(stem_dir: str, out_path: str, stems=("bass", "other")) -> str:
    """Suma los stems indicados y escribe un wav mono para analizar."""
    import numpy as np
    from scipy.io import wavfile

    mix = None
    sr = None
    for s in stems:
        p = os.path.join(stem_dir, f"{s}.wav")
        if not os.path.exists(p):
            raise FileNotFoundError(f"No se encontró el stem esperado: {p}")
        rate, data = _to_float_mono(*wavfile.read(p))
        sr = rate if sr is None else sr
        if mix is None:
            mix = data.copy()
        else:
            n = min(len(mix), len(data))
            mix = mix[:n] + data[:n]

    peak = float(np.max(np.abs(mix))) or 1.0
    mix = (mix / peak * 0.98 * 32767).astype(np.int16)
    wavfile.write(out_path, sr, mix)
    return out_path


def separate_harmonic(path: str, device: str = "auto",
                      model: str = "htdemucs", keep_dir: bool = False) -> str:
    """
    Separa la canción con Demucs y devuelve la ruta a un wav con bass+other
    (batería y voz eliminadas). Requiere el paquete 'demucs' instalado.
    """
    device = _pick_device(device)
    workdir = tempfile.mkdtemp(prefix="demucs_")
    cmd = [sys.executable, "-m", "demucs", "-n", model,
           "--device", device, "-o", workdir, path]
    subprocess.run(cmd, check=True)

    track = os.path.splitext(os.path.basename(path))[0]
    stem_dir = os.path.join(workdir, model, track)
    out = os.path.join(tempfile.gettempdir(), f"{track}_harmonic.wav")
    _combine_stems(stem_dir, out, stems=("bass", "other"))
    if not keep_dir:
        shutil.rmtree(workdir, ignore_errors=True)
    return out


# --------------------------------------------------------------------------- #
# Extracción de acordes (madmom)
# --------------------------------------------------------------------------- #
def _merge_adjacent(segments) -> List[ChordSegment]:
    merged: List[ChordSegment] = []
    for start, end, label in segments:
        label = str(label)
        if merged and merged[-1].chord == label:
            merged[-1].end = round(float(end), 2)
        else:
            merged.append(ChordSegment(round(float(start), 2), round(float(end), 2), label))
    return merged


def _extract_chords(path: str, method: str) -> List[ChordSegment]:
    if method == "deepchroma":
        from madmom.audio.chroma import DeepChromaProcessor
        from madmom.features.chords import DeepChromaChordRecognitionProcessor
        chroma = DeepChromaProcessor()(path)
        raw = DeepChromaChordRecognitionProcessor()(chroma)
    elif method == "cnn":
        from madmom.features.chords import (
            CNNChordFeatureProcessor,
            CRFChordRecognitionProcessor,
        )
        feats = CNNChordFeatureProcessor()(path)
        raw = CRFChordRecognitionProcessor()(feats)
    else:
        raise ValueError(f"Método desconocido: {method!r} (usa 'deepchroma' o 'cnn')")
    return _merge_adjacent(raw)


def _estimate_key(path: str) -> Optional[str]:
    try:
        from madmom.features.key import (
            CNNKeyRecognitionProcessor,
            key_prediction_to_label,
        )
        return key_prediction_to_label(CNNKeyRecognitionProcessor()(path))
    except Exception:
        return None


def _estimate_tempo(path: str) -> Optional[float]:
    try:
        from madmom.features.beats import RNNBeatProcessor
        from madmom.features.tempo import TempoEstimationProcessor
        act = RNNBeatProcessor()(path)
        tempo = TempoEstimationProcessor(fps=100)(act)
        return round(float(tempo[0][0]), 1)
    except Exception:
        return None


def extract(
    path: str,
    method: str = "deepchroma",
    with_key: bool = True,
    with_tempo: bool = True,
    separate: bool = False,
    device: str = "auto",
) -> ExtractionResult:
    """
    Analiza un archivo de audio y devuelve acordes, tonalidad y tempo.

    path       : ruta al archivo (mp3, wav, flac, ...). Requiere ffmpeg para mp3.
    method     : "deepchroma" | "cnn".
    with_key   : estimar tonalidad (poco fiable en clips cortos).
    with_tempo : estimar tempo (BPM).
    separate   : si True, separa con Demucs y analiza acordes/tonalidad sobre la
                 parte armónica (bass+other). El tempo se estima sobre el
                 original (necesita la batería).
    device     : "auto" | "cuda" | "cpu" (para Demucs).
    """
    result = ExtractionResult(source=path, method=method, separated=separate)

    chord_input = path
    if separate:
        chord_input = separate_harmonic(path, device=device)

    result.chords = _extract_chords(chord_input, method)
    if with_key:
        result.key = _estimate_key(chord_input)
    if with_tempo:
        result.tempo_bpm = _estimate_tempo(path)  # siempre sobre el original

    # limpieza del wav temporal de separación
    if separate and chord_input != path and os.path.exists(chord_input):
        try:
            os.remove(chord_input)
        except OSError:
            pass

    return result


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _format_table(result: ExtractionResult) -> str:
    lines = []
    lines.append(f"Archivo   : {result.source}")
    lines.append(f"Método    : {result.method}")
    lines.append(f"Separado  : {'sí (Demucs: bass+other)' if result.separated else 'no'}")
    lines.append(f"Tonalidad estimada : {result.key or '—'}")
    lines.append(f"Tempo estimado     : {result.tempo_bpm or '—'} BPM")
    lines.append("")
    lines.append(f"{'inicio':>8} {'fin':>8}   acorde")
    lines.append("-" * 32)
    for c in result.chords:
        label = "N.C." if c.chord == "N" else c.chord
        lines.append(f"{c.start:8.2f} {c.end:8.2f}   {label}")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="Extrae acordes de un archivo de audio.")
    ap.add_argument("audio", help="ruta al archivo (mp3/wav/flac/...)")
    ap.add_argument("--method", choices=["deepchroma", "cnn"], default="deepchroma")
    ap.add_argument("--separate", action="store_true",
                    help="separar con Demucs y analizar solo la parte armónica")
    ap.add_argument("--device", choices=["auto", "cuda", "cpu"], default="auto",
                    help="dispositivo para Demucs (por defecto auto: GPU si hay)")
    ap.add_argument("--no-key", action="store_true", help="no estimar tonalidad")
    ap.add_argument("--no-tempo", action="store_true", help="no estimar tempo")
    ap.add_argument("--json", metavar="RUTA", help="guardar resultado como JSON")
    ap.add_argument("--lab", metavar="RUTA",
                    help="guardar acordes en formato .lab (start end etiqueta)")
    args = ap.parse_args()

    result = extract(
        args.audio,
        method=args.method,
        with_key=not args.no_key,
        with_tempo=not args.no_tempo,
        separate=args.separate,
        device=args.device,
    )
    print(_format_table(result))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            f.write(result.to_json(indent=2))
        print(f"\nJSON guardado en {args.json}")
    if args.lab:
        with open(args.lab, "w", encoding="utf-8") as f:
            f.write(result.to_lab())
        print(f".lab guardado en {args.lab}")


if __name__ == "__main__":
    main()
