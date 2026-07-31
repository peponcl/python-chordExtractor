"""
lyrics.py
---------
Letra con marcas de tiempo, para poder colocar los acordes sobre ella.

Dos modos, según lo que tengas:

  - **Sin letra** (canción ajena): transcripción automática. Cómoda, pero el
    reconocimiento sobre voz cantada es bastante peor que sobre voz hablada, y
    con mezclas densas o voz agresiva la calidad cae mucho.
  - **Con letra** (canción propia, o la tienes escrita): alineamiento. Se
    transcribe igual, pero el resultado sólo se usa para los *tiempos*: las
    palabras son las tuyas. Mucho más fiable, porque el problema pasa de
    «adivinar qué dice» a «encontrar dónde lo dice».

El alineamiento no necesita ninguna dependencia extra: se comparan las dos
secuencias de palabras con difflib y se trasladan los tiempos de las que casan,
interpolando las que no.

La dependencia (faster-whisper) vive en un entorno virtual aparte, dentro de la
carpeta de datos de la aplicación, y se instala desde la propia interfaz. Se hace
así porque el ejecutable empaquetado no lleva pip, y porque son cientos de MB que
no tiene sentido meter dentro del paquete.

Se usa faster-whisper y no openai-whisper porque el primero corre sobre
CTranslate2 y no arrastra PyTorch: misma calidad, una fracción del tamaño.
"""
from __future__ import annotations

import difflib
import json
import os
import re
import shutil
import subprocess
import sys
import unicodedata
from dataclasses import dataclass, field
from typing import Callable, Optional

PAQUETE = "faster-whisper"
WORKER = "transcribe_worker.py"

# tiny/base van demasiado justos con voz cantada; small es el equilibrio
# razonable. medium y large mejoran, a costa de tamaño y tiempo.
MODELOS = {
    "tiny":     "~75 MB · el más rápido, poco fiable cantando",
    "base":     "~145 MB · rápido, aún flojo cantando",
    "small":    "~480 MB · equilibrio recomendado",
    "medium":   "~1,5 GB · mejor, bastante más lento",
    "large-v3": "~3 GB · el mejor, muy lento sin GPU",
}
MODELO_POR_DEFECTO = "small"


class SinPython(Exception):
    """No hay ningún intérprete de Python con el que montar el entorno."""


class TranscripcionFallida(Exception):
    pass


@dataclass
class Palabra:
    texto: str
    inicio: float
    fin: float


@dataclass
class Linea:
    """Una línea de letra, con las palabras que la componen."""
    palabras: list[Palabra] = field(default_factory=list)

    @property
    def inicio(self) -> float:
        return self.palabras[0].inicio if self.palabras else 0.0

    @property
    def fin(self) -> float:
        return self.palabras[-1].fin if self.palabras else 0.0

    @property
    def texto(self) -> str:
        return " ".join(p.texto for p in self.palabras)


# --------------------------------------------------------------------------- #
# Entorno de trabajo: se crea e instala desde la propia aplicación
# --------------------------------------------------------------------------- #
def _sin_consola() -> dict:
    """Evita que asome una ventana de consola en el ejecutable windowed."""
    if sys.platform == "win32":
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}


def entorno_dir(base: str) -> str:
    return os.path.join(base, "transcripcion")


def python_del_entorno(base: str) -> Optional[str]:
    """Intérprete del entorno de transcripción, si ya existe."""
    directorio = entorno_dir(base)
    ruta = (os.path.join(directorio, "Scripts", "python.exe")
            if sys.platform == "win32"
            else os.path.join(directorio, "bin", "python"))
    return ruta if os.path.isfile(ruta) else None


def _python_anfitrion() -> str:
    """
    Un Python con el que crear el entorno. Ejecutando desde el código vale el
    nuestro; dentro del .exe, sys.executable es el propio ejecutable, así que hay
    que buscar uno instalado en el sistema.
    """
    if not getattr(sys, "frozen", False):
        return sys.executable

    candidatos = ["python3.12", "python3.11", "python3.10", "python3", "python"]
    for nombre in candidatos:
        ruta = shutil.which(nombre)
        if ruta and _version_valida(ruta):
            return ruta
    if sys.platform == "win32":
        lanzador = shutil.which("py")
        if lanzador:
            for version in ("-3.12", "-3.11", "-3.10"):
                try:
                    salida = subprocess.run([lanzador, version, "-c", "print(1)"],
                                            capture_output=True, timeout=20,
                                            **_sin_consola())
                    if salida.returncode == 0:
                        return f"{lanzador}|{version}"
                except (OSError, subprocess.SubprocessError):
                    pass
    raise SinPython(
        "Hace falta Python instalado en el sistema para montar el entorno de "
        "transcripción. Instálalo con «winget install Python.Python.3.12» "
        "(Windows) o «sudo dnf install python3.12» (Fedora) y vuelve a "
        "intentarlo.")


def _version_valida(ruta: str) -> bool:
    """faster-whisper necesita 3.9+; se descartan intérpretes más viejos."""
    try:
        salida = subprocess.run(
            [ruta, "-c", "import sys; print(sys.version_info[:2])"],
            capture_output=True, text=True, timeout=20, **_sin_consola())
        return salida.returncode == 0 and "(3, " in salida.stdout
    except (OSError, subprocess.SubprocessError):
        return False


def _comando(python: str) -> list[str]:
    """Convierte 'py|-3.12' en ['py', '-3.12'] y deja el resto igual."""
    return python.split("|") if "|" in python else [python]


def instalar(base: str, on_line: Optional[Callable[[str], None]] = None) -> str:
    """
    Crea el entorno de transcripción e instala faster-whisper. Devuelve la ruta
    del intérprete. Si ya estaba, no hace nada.
    """
    ya = python_del_entorno(base)
    if ya and _tiene_paquete(ya):
        return ya

    def aviso(texto: str):
        if on_line:
            on_line(texto)

    if not ya:
        aviso("Creando el entorno de transcripción…")
        anfitrion = _python_anfitrion()
        directorio = entorno_dir(base)
        os.makedirs(base, exist_ok=True)
        resultado = subprocess.run(_comando(anfitrion) + ["-m", "venv", directorio],
                                   capture_output=True, text=True, **_sin_consola())
        if resultado.returncode != 0:
            raise TranscripcionFallida(
                f"No se pudo crear el entorno: {resultado.stderr.strip()[-300:]}")
        ya = python_del_entorno(base)
        if not ya:
            raise TranscripcionFallida("El entorno se creó sin intérprete")

    aviso(f"Descargando e instalando {PAQUETE}… (unos cientos de MB)")
    proceso = subprocess.Popen(
        [ya, "-m", "pip", "install", "--upgrade", PAQUETE],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        encoding="utf-8", errors="replace", **_sin_consola())
    ultimas = []
    for linea in proceso.stdout:
        linea = linea.rstrip()
        ultimas = (ultimas + [linea])[-15:]
        if on_line and linea:
            on_line(linea)
    proceso.wait()
    if proceso.returncode != 0:
        raise TranscripcionFallida("Falló la instalación:\n" + "\n".join(ultimas))

    aviso("Listo.")
    return ya


def _tiene_paquete(python: str) -> bool:
    try:
        salida = subprocess.run(
            [python, "-I", "-c",
             "import importlib.util as u; print('SI' if u.find_spec('faster_whisper') else 'NO')"],
            capture_output=True, text=True, timeout=60, **_sin_consola())
        return salida.stdout.strip() == "SI"
    except (OSError, subprocess.SubprocessError):
        return False


def instalado(base: str) -> bool:
    python = python_del_entorno(base)
    return bool(python) and _tiene_paquete(python)


def desinstalar(base: str) -> None:
    """Borra el entorno entero; los modelos descargados no se tocan."""
    shutil.rmtree(entorno_dir(base), ignore_errors=True)


# --------------------------------------------------------------------------- #
# Transcripción
# --------------------------------------------------------------------------- #
def _ruta_worker() -> str:
    """El worker viaja junto al código, y dentro del paquete en el .exe."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    for candidata in (os.path.join(base, "packaging", WORKER),
                      os.path.join(base, WORKER)):
        if os.path.isfile(candidata):
            return candidata
    raise TranscripcionFallida(f"No se encontró {WORKER}")


def transcribir(audio: str, base: str, modelo: str = MODELO_POR_DEFECTO,
                idioma: str = "auto",
                on_line: Optional[Callable[[str], None]] = None) -> list[Palabra]:
    """Devuelve las palabras reconocidas con sus tiempos."""
    python = python_del_entorno(base)
    if not python or not _tiene_paquete(python):
        raise TranscripcionFallida("El entorno de transcripción no está instalado")

    if on_line:
        on_line(f"Transcribiendo con el modelo «{modelo}»… "
                f"(la primera vez se descarga)")

    proceso = subprocess.run(
        [python, _ruta_worker(), audio, modelo, idioma],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        **_sin_consola())

    salida = (proceso.stdout or "").strip()
    if not salida:
        raise TranscripcionFallida(
            (proceso.stderr or "El proceso no devolvió nada").strip()[-400:])
    try:
        datos = json.loads(salida.splitlines()[-1])
    except ValueError:
        raise TranscripcionFallida(salida[-400:])
    if "error" in datos:
        raise TranscripcionFallida(datos["error"])

    return [Palabra(p["text"], p["start"], p["end"]) for p in datos["words"]]


# --------------------------------------------------------------------------- #
# Alineamiento de una letra conocida contra lo reconocido
# --------------------------------------------------------------------------- #
def _normalizar(texto: str) -> str:
    """Minúsculas, sin tildes ni puntuación: para comparar, no para mostrar."""
    plano = unicodedata.normalize("NFD", texto.lower())
    plano = "".join(c for c in plano if unicodedata.category(c) != "Mn")
    return re.sub(r"[^\w]", "", plano)


def alinear(letra: str, reconocidas: list[Palabra]) -> list[Linea]:
    """
    Sitúa en el tiempo una letra escrita a mano, usando como referencia lo que
    reconoció el transcriptor.

    Se comparan las dos secuencias de palabras normalizadas; las que casan
    heredan directamente sus tiempos, y a las que no se les reparte el hueco
    entre la anterior y la siguiente que sí casaron. El texto que se conserva es
    SIEMPRE el tuyo: el reconocimiento sólo aporta los tiempos.
    """
    lineas_texto = [l.strip() for l in letra.splitlines()]
    # Se guarda a qué línea pertenece cada palabra para poder reagrupar al final.
    plano: list[tuple[int, str]] = []
    for indice, linea in enumerate(lineas_texto):
        for palabra in linea.split():
            plano.append((indice, palabra))

    if not plano:
        return []
    if not reconocidas:
        raise TranscripcionFallida(
            "No se reconoció ninguna palabra en el audio, así que no hay tiempos "
            "con los que alinear la letra.")

    claves_letra = [_normalizar(p) for _i, p in plano]
    claves_audio = [_normalizar(p.texto) for p in reconocidas]

    tiempos: list[Optional[tuple[float, float]]] = [None] * len(plano)
    matcher = difflib.SequenceMatcher(None, claves_letra, claves_audio,
                                      autojunk=False)

    for etiqueta, i1, i2, j1, j2 in matcher.get_opcodes():
        if etiqueta == "equal":
            for k in range(i2 - i1):
                w = reconocidas[j1 + k]
                tiempos[i1 + k] = (w.inicio, w.fin)
        elif etiqueta == "replace":
            # Cantando, el reconocedor falla por poco constantemente: oye
            # «camino» donde dice «caminas». Comparar sólo por igualdad exacta
            # tiraría ese emparejamiento y lo dejaría en interpolación, así que
            # dentro de cada tramo discrepante se busca el parecido suficiente.
            _emparejar_por_parecido(tiempos, claves_letra, reconocidas,
                                    i1, i2, j1, j2)

    _rellenar_huecos(tiempos, reconocidas)

    lineas: list[Linea] = []
    actual, indice_actual = Linea(), None
    for (indice, texto), tiempo in zip(plano, tiempos):
        if indice_actual is not None and indice != indice_actual:
            if actual.palabras:
                lineas.append(actual)
            actual = Linea()
        indice_actual = indice
        inicio, fin = tiempo  # type: ignore[misc]
        actual.palabras.append(Palabra(texto, inicio, fin))
    if actual.palabras:
        lineas.append(actual)
    return lineas


def _emparejar_por_parecido(tiempos: list, claves_letra: list[str],
                            reconocidas: list[Palabra],
                            i1: int, i2: int, j1: int, j2: int,
                            umbral: float = 0.7) -> None:
    """
    Dentro de un tramo que difflib marcó como discrepante, empareja las palabras
    que se parecen lo suficiente. Se avanza en orden por los dos lados, así que
    los tiempos nunca se cruzan.
    """
    j = j1
    for i in range(i1, i2):
        clave = claves_letra[i]
        if not clave:
            continue
        mejor_indice, mejor_ratio = None, 0.0
        # Se mira sólo un poco por delante: emparejar con algo lejano
        # desordenaría los tiempos más de lo que ayudaría.
        for candidato in range(j, min(j2, j + 3)):
            ratio = difflib.SequenceMatcher(
                None, clave, _normalizar(reconocidas[candidato].texto)).ratio()
            if ratio > mejor_ratio:
                mejor_indice, mejor_ratio = candidato, ratio
        if mejor_indice is not None and mejor_ratio >= umbral:
            w = reconocidas[mejor_indice]
            tiempos[i] = (w.inicio, w.fin)
            j = mejor_indice + 1


def _rellenar_huecos(tiempos: list, reconocidas: list[Palabra]) -> None:
    """Reparte el tiempo de las palabras que no casaron entre sus vecinas."""
    n = len(tiempos)
    primero = next((i for i, t in enumerate(tiempos) if t), None)
    if primero is None:
        # Nada casó: se reparte la duración total a partes iguales, que es poco
        # más que una conjetura, pero deja algo utilizable.
        total_ini = reconocidas[0].inicio
        total_fin = reconocidas[-1].fin
        paso = (total_fin - total_ini) / max(n, 1)
        for i in range(n):
            tiempos[i] = (total_ini + i * paso, total_ini + (i + 1) * paso)
        return

    ultimo = max(i for i, t in enumerate(tiempos) if t)
    for i in range(primero):                       # antes del primer acierto
        tiempos[i] = (reconocidas[0].inicio, tiempos[primero][0])
    for i in range(ultimo + 1, n):                 # después del último
        tiempos[i] = (tiempos[ultimo][1], reconocidas[-1].fin)

    i = primero
    while i <= ultimo:
        if tiempos[i]:
            i += 1
            continue
        hueco_ini = i
        while not tiempos[i]:
            i += 1
        cantidad = i - hueco_ini
        desde = tiempos[hueco_ini - 1][1]
        hasta = tiempos[i][0]
        paso = (hasta - desde) / cantidad if hasta > desde else 0.0
        for k in range(cantidad):
            tiempos[hueco_ini + k] = (desde + k * paso, desde + (k + 1) * paso)


# --------------------------------------------------------------------------- #
# Agrupado de lo transcrito en líneas
# --------------------------------------------------------------------------- #
def agrupar_en_lineas(palabras: list[Palabra], pausa: float = 1.0,
                      maximo: int = 10) -> list[Linea]:
    """
    Parte lo reconocido en líneas. Sin letra de referencia no hay versos que
    seguir, así que se corta por los silencios entre palabras y por longitud.
    """
    lineas: list[Linea] = []
    actual = Linea()
    for palabra in palabras:
        if actual.palabras:
            silencio = palabra.inicio - actual.palabras[-1].fin
            if silencio >= pausa or len(actual.palabras) >= maximo:
                lineas.append(actual)
                actual = Linea()
        actual.palabras.append(palabra)
    if actual.palabras:
        lineas.append(actual)
    return lineas
