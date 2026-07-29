"""
ytaudio.py
----------
Descarga el audio de una URL (YouTube y demás sitios que soporte yt-dlp) para
poder analizarlo con el mismo pipeline que un archivo local.

yt-dlp se usa como ejecutable externo, no como dependencia empaquetada, por dos
razones: no engorda el .exe, y sobre todo no se pudre — los sitios cambian cada
pocas semanas y yt-dlp publica correcciones al ritmo. Si no está instalado, la
función simplemente no aparece en la interfaz.

Formato: se prefiere **remux a .opus** cuando la pista es Opus (que es lo que
sirve YouTube habitualmente). Remuxear sólo cambia el contenedor conservando el
códec intacto: es instantáneo y sin pérdida. Si la pista es AAC, se transcodifica
a MP3.

Ojo con la extensión: tiene que ser .opus, no .ogg. SDL_mixer elige el
decodificador por ella, y ante un .ogg usa el de Vorbis, que no sabe leer Opus y
falla con "VORBIS_invalid_first_page" aunque el contenido sea válido.

Por qué no descargar siempre a MP3: sería una segunda generación de pérdida
innecesaria. Y por qué no dejar el .m4a/.webm original: madmom lo analizaría sin
problema, pero SDL_mixer (pygame) no reproduce ni AAC ni WebM, así que el
reproductor de la aplicación quedaría inservible.
"""
from __future__ import annotations

import glob
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from typing import Callable, Optional

# Medido en este proyecto con madmom/deepchroma: el consumo crece de forma
# lineal con la duración del audio (520 MB a 2 min, 1204 a 5, 2344 a 10).
BASE_MB = 60.0
MB_PER_AUDIO_SECOND = 3.8
ANALYSIS_SECONDS_PER_AUDIO_SECOND = 0.21

# Por encima de esto se avisa antes de descargar: 10 min ya son ~2,3 GB.
LONG_AUDIO_SECONDS = 10 * 60

_PROGRESS = re.compile(r"\[download\]\s+(\d{1,3}(?:\.\d)?)%")


class YtdlpMissing(Exception):
    """yt-dlp no está instalado o no se encuentra en el PATH."""


class YtdlpFailed(Exception):
    """yt-dlp devolvió un error."""


@dataclass
class VideoInfo:
    id: str
    title: str
    duration: float          # segundos
    uploader: str
    has_opus: bool

    @property
    def estimated_ram_mb(self) -> float:
        return BASE_MB + MB_PER_AUDIO_SECOND * self.duration

    @property
    def estimated_analysis_seconds(self) -> float:
        return ANALYSIS_SECONDS_PER_AUDIO_SECOND * self.duration

    @property
    def is_long(self) -> bool:
        return self.duration > LONG_AUDIO_SECONDS


_ytdlp_cache: list = []          # [] = sin buscar todavía; [None] = no está


def _winget_candidates(name: str) -> list[str]:
    """
    Rutas donde winget deja los ejecutables. Hace falta mirarlas porque winget
    añade la carpeta al PATH *persistente*, pero los procesos ya abiertos siguen
    con el PATH viejo: recién instalado, shutil.which() no lo encuentra hasta
    que cierras la sesión.
    """
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        return []
    base = os.path.join(local, "Microsoft", "WinGet")
    patterns = [
        os.path.join(base, "Links", f"{name}.exe"),
        os.path.join(base, "Packages", "*", f"{name}.exe"),
        os.path.join(base, "Packages", "*", "*", f"{name}.exe"),
        os.path.join(base, "Packages", "*", "*", "*", f"{name}.exe"),
    ]
    found = []
    for pattern in patterns:
        found.extend(glob.glob(pattern))
    return found


def find_ytdlp(refresh: bool = False) -> Optional[str]:
    """Ruta al ejecutable de yt-dlp, o None si no se encuentra."""
    if _ytdlp_cache and not refresh:
        return _ytdlp_cache[0]
    found = shutil.which("yt-dlp") or shutil.which("yt-dlp.exe")
    if not found and sys.platform == "win32":
        candidates = _winget_candidates("yt-dlp")
        found = candidates[0] if candidates else None
    _ytdlp_cache[:] = [found]
    return found


def _run(args: list[str], on_line: Optional[Callable[[str], None]] = None) -> str:
    """Ejecuta yt-dlp devolviendo su salida; sin abrir una consola en Windows."""
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, encoding="utf-8", errors="replace",
                            creationflags=flags)
    chunks = []
    for line in proc.stdout:
        chunks.append(line)
        if on_line:
            on_line(line.rstrip())
    stderr = proc.stderr.read()
    proc.wait()
    if proc.returncode != 0:
        raise YtdlpFailed((stderr or "".join(chunks)).strip()[-500:]
                          or f"yt-dlp terminó con código {proc.returncode}")
    return "".join(chunks)


def probe(url: str) -> VideoInfo:
    """Consulta los metadatos sin descargar nada."""
    exe = find_ytdlp()
    if exe is None:
        raise YtdlpMissing("yt-dlp no está instalado")
    raw = _run([exe, "--dump-single-json", "--no-playlist", "--skip-download", url])
    data = json.loads(raw)
    formats = data.get("formats") or []
    has_opus = any(str(f.get("acodec", "")).startswith("opus") for f in formats)
    return VideoInfo(
        id=data.get("id") or "sin_id",
        title=data.get("title") or "sin título",
        duration=float(data.get("duration") or 0.0),
        uploader=data.get("uploader") or "",
        has_opus=has_opus,
    )


def safe_name(title: str, limit: int = 60) -> str:
    """Título utilizable como nombre de archivo en Windows."""
    cleaned = re.sub(r'[<>:"/\\|?*]', "", title)
    cleaned = re.sub(r"\s+", " ", cleaned).strip().rstrip(". ")
    return (cleaned[:limit].strip() or "audio")


def cached_path(directory: str, video_id: str) -> Optional[str]:
    """Audio ya descargado para ese id, si lo hay."""
    matches = sorted(glob.glob(os.path.join(directory, f"*[[]{video_id}[]].*")))
    return matches[0] if matches else None


def download(url: str, directory: str, info: VideoInfo,
             on_progress: Optional[Callable[[float], None]] = None) -> str:
    """
    Descarga el audio y devuelve la ruta del archivo. Si ese vídeo ya se había
    descargado, lo reutiliza sin volver a bajarlo.
    """
    exe = find_ytdlp()
    if exe is None:
        raise YtdlpMissing("yt-dlp no está instalado")

    existing = cached_path(directory, info.id)
    if existing:
        return existing

    os.makedirs(directory, exist_ok=True)
    # El id entre corchetes hace de clave para la caché; el título es sólo para
    # que el archivo y el historial se lean bien.
    template = os.path.join(directory, f"{safe_name(info.title)} [{info.id}].%(ext)s")

    if info.has_opus:
        # Cambiar de contenedor conservando el códec: instantáneo y sin pérdida.
        # Tiene que quedar como .opus; con .ogg, SDL_mixer intenta decodificarlo
        # como Vorbis y no suena.
        selection = ["-f", "bestaudio[acodec^=opus]/bestaudio",
                     "--remux-video", "opus"]
    else:
        # Un contenedor Ogg no admite AAC, así que aquí toca recodificar.
        selection = ["-f", "bestaudio",
                     "--extract-audio", "--audio-format", "mp3",
                     "--audio-quality", "0"]

    def handle(line: str):
        match = _PROGRESS.search(line)
        if match and on_progress:
            on_progress(float(match.group(1)))

    _run([exe, "--no-playlist", "--newline", "-o", template, *selection, url],
         on_line=handle)

    produced = cached_path(directory, info.id)
    if produced is None:
        raise YtdlpFailed("yt-dlp terminó sin dejar ningún archivo de audio")
    return produced
