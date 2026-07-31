"""
chordpro.py
-----------
Lee una hoja en formato ChordPro y la convierte al formato clásico de dos
líneas: los acordes encima, la letra debajo.

    [D]Bajo el cielo [G]gris

    D              G
    Bajo el cielo gris

Ese formato exige tipografía monoespaciada: la alineación se sostiene sobre que
todos los caracteres midan lo mismo.

Incluye transporte, que es casi gratis teniéndolo ya parseado y es lo primero
que pide cualquiera que use una hoja de acordes.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

DIRECTIVA = re.compile(r"^\s*\{\s*([a-zA-Z_]+)\s*:?\s*(.*?)\s*\}\s*$")
ACORDE = re.compile(r"\[([^\]]*)\]")

# Se escribe con sostenidos: no sabemos si la tonalidad pide bemoles, y mezclar
# ambos quedaría peor que ser consistente.
ESCALA = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
_PC = {"C": 0, "B#": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3, "E": 4,
       "Fb": 4, "E#": 5, "F": 5, "F#": 6, "Gb": 6, "G": 7, "G#": 8, "Ab": 8,
       "A": 9, "A#": 10, "Bb": 10, "B": 11, "Cb": 11}
_RAIZ = re.compile(r"^([A-G][#b]?)(.*)$")


@dataclass
class Bloque:
    """Un par de líneas: acordes arriba, letra abajo."""
    acordes: str = ""
    letra: str = ""
    comentario: Optional[str] = None
    en_blanco: bool = False


@dataclass
class Hoja:
    directivas: dict = field(default_factory=dict)
    bloques: list[Bloque] = field(default_factory=list)

    @property
    def titulo(self) -> str:
        return self.directivas.get("title", "Hoja de acordes")


def transponer_acorde(acorde: str, semitonos: int) -> str:
    """'Am' + 2 -> 'Bm'. Deja intacto lo que no reconozca, como N.C."""
    if not acorde or semitonos == 0:
        return acorde
    # Un acorde con bajo distinto: D/F#
    if "/" in acorde:
        izquierda, _, derecha = acorde.partition("/")
        return (f"{transponer_acorde(izquierda, semitonos)}"
                f"/{transponer_acorde(derecha, semitonos)}")
    match = _RAIZ.match(acorde)
    if not match:
        return acorde
    raiz, resto = match.groups()
    if raiz not in _PC:
        return acorde
    return ESCALA[(_PC[raiz] + semitonos) % 12] + resto


def _componer(linea: str, semitonos: int = 0) -> Bloque:
    """
    Reparte una línea de ChordPro en sus dos filas.

    Si dos acordes caen tan juntos que se solaparían, el segundo se empuja a la
    derecha: es preferible desalinearlo un poco a que se pisen y no se lean.
    """
    letra_partes = []
    acordes: list[tuple[int, str]] = []
    posicion = 0
    resto = linea
    while True:
        match = ACORDE.search(resto)
        if not match:
            letra_partes.append(resto)
            break
        antes = resto[:match.start()]
        letra_partes.append(antes)
        posicion += len(antes)
        acordes.append((posicion, transponer_acorde(match.group(1), semitonos)))
        resto = resto[match.end():]

    letra = "".join(letra_partes)

    # Una línea sin letra (intro, puente, solo) no tiene nada a lo que alinearse:
    # colocarlos por columna los amontonaría, así que se separan y ya está.
    if not letra.strip():
        return Bloque(acordes=" ".join(a for _c, a in acordes), letra="")

    fila = ""
    for columna, acorde in acordes:
        # <= y no <: si el acorde empieza justo donde acaba el anterior quedarían
        # pegados y se leerían como uno solo.
        if fila and columna <= len(fila):
            fila += " "
        fila += " " * (columna - len(fila)) + acorde
    return Bloque(acordes=fila.rstrip(), letra=letra.rstrip())


def parsear(texto: str, semitonos: int = 0) -> Hoja:
    hoja = Hoja()
    for linea in texto.splitlines():
        if not linea.strip():
            hoja.bloques.append(Bloque(en_blanco=True))
            continue
        directiva = DIRECTIVA.match(linea)
        if directiva:
            nombre, valor = directiva.group(1).lower(), directiva.group(2)
            if nombre in ("comment", "c", "ci", "comment_italic"):
                hoja.bloques.append(Bloque(comentario=valor))
            else:
                hoja.directivas[nombre] = valor
            continue
        hoja.bloques.append(_componer(linea, semitonos))
    return hoja


def a_texto(hoja: Hoja) -> str:
    """Vuelca la hoja como texto plano listo para imprimir o pegar."""
    salida = []
    if hoja.directivas.get("title"):
        salida.append(hoja.directivas["title"])
    cabecera = [f"{etiqueta}: {hoja.directivas[clave]}"
                for clave, etiqueta in (("key", "Tonalidad"), ("tempo", "Tempo"))
                if hoja.directivas.get(clave)]
    if cabecera:
        salida.append("   ".join(cabecera))
    if salida:
        salida.append("")

    for bloque in hoja.bloques:
        if bloque.en_blanco:
            salida.append("")
        elif bloque.comentario is not None:
            salida.append(f"[{bloque.comentario}]")
        else:
            if bloque.acordes:
                salida.append(bloque.acordes)
            if bloque.letra:
                salida.append(bloque.letra)
    return "\n".join(salida) + "\n"


def transponer_texto(texto: str, semitonos: int) -> str:
    """Devuelve el mismo ChordPro con los acordes transportados."""
    def reemplazo(match):
        return "[" + transponer_acorde(match.group(1), semitonos) + "]"
    return ACORDE.sub(reemplazo, texto)
