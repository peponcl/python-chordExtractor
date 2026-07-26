"""
chordviz.py
-----------
Utilidades de presentación compartidas por las interfaces (escritorio y web):
etiquetas legibles, color por acorde y formato de tiempo.

El color se deriva de la fundamental (tono cromático -> matiz) y de la calidad
(mayor = claro y saturado, menor = más oscuro). Así dos acordes distintos nunca
se confunden y un mismo acorde siempre se ve igual en toda la app.

La misma fórmula está replicada en web/index.html para que la interfaz web y la
de escritorio pinten los acordes con los mismos colores.
"""
from __future__ import annotations

import colorsys
from typing import Optional, Tuple

# Clases de altura: acepta sostenidos y bemoles, y los enarmónicos raros.
_PITCH_CLASS = {
    "C": 0, "B#": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3,
    "E": 4, "Fb": 4, "E#": 5, "F": 5, "F#": 6, "Gb": 6, "G": 7,
    "G#": 8, "Ab": 8, "A": 9, "A#": 10, "Bb": 10, "B": 11, "Cb": 11,
}

NO_CHORD = "N"


def parse_chord(label: str) -> Tuple[Optional[int], str]:
    """
    Descompone una etiqueta de madmom ("C:maj", "A:min", "N") en
    (clase de altura 0-11, calidad). Devuelve (None, "") si no hay acorde.
    """
    if not label or label == NO_CHORD:
        return None, ""
    root, _, quality = label.partition(":")
    return _PITCH_CLASS.get(root.strip()), (quality.strip() or "maj")


def pretty_label(label: str) -> str:
    """"C:maj" -> "C" | "A:min" -> "Am" | "N" -> "N.C." """
    if not label or label == NO_CHORD:
        return "N.C."
    root, _, quality = label.partition(":")
    if quality == "min":
        return f"{root}m"
    if quality in ("", "maj"):
        return root
    return f"{root}{quality}"


def _hex(r: float, g: float, b: float) -> str:
    return "#{:02x}{:02x}{:02x}".format(int(r * 255), int(g * 255), int(b * 255))


def color_for(label: str) -> str:
    """Color sólido del acorde, para los bloques de la línea de tiempo."""
    pc, quality = parse_chord(label)
    if pc is None:
        return "#c9ccd6"                       # sin acorde: gris neutro
    hue = pc / 12.0
    if quality == "min":
        return _hex(*colorsys.hsv_to_rgb(hue, 0.52, 0.66))
    return _hex(*colorsys.hsv_to_rgb(hue, 0.62, 0.94))


def tint_for(label: str) -> str:
    """Versión pálida del color, para el fondo de las filas de la tabla."""
    pc, quality = parse_chord(label)
    if pc is None:
        return "#f1f2f5"
    hue = pc / 12.0
    sat = 0.16 if quality == "min" else 0.20
    return _hex(*colorsys.hsv_to_rgb(hue, sat, 0.99))


def text_color_for(label: str) -> str:
    """Negro o blanco según lo oscuro que sea color_for(label)."""
    c = color_for(label).lstrip("#")
    r, g, b = (int(c[i:i + 2], 16) / 255 for i in (0, 2, 4))
    luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b
    return "#101014" if luminance > 0.55 else "#ffffff"


def format_time(seconds: float) -> str:
    """123.4 -> '2:03.4'"""
    seconds = max(0.0, float(seconds))
    minutes, rest = divmod(seconds, 60)
    return f"{int(minutes)}:{rest:04.1f}"


def ruler_step(duration: float, target_ticks: int = 10) -> float:
    """Elige un intervalo 'redondo' para las marcas de tiempo."""
    if duration <= 0:
        return 1.0
    for step in (1, 2, 5, 10, 15, 30, 60, 120, 300, 600):
        if duration / step <= target_ticks:
            return float(step)
    return 900.0
