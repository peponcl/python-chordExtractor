#!/usr/bin/env bash
#
# instalar-entorno.sh — monta desde cero el entorno de Chord Extractor en Fedora.
#
# Equivalente de packaging/instalar-entorno.ps1. Instala y verifica lo necesario:
# Python 3.12, compilador, git, ffmpeg, yt-dlp, el entorno virtual y las
# dependencias de Python. Al final comprueba que la cadena completa funciona
# analizando un audio sintético de acordes conocidos.
#
# Es idempotente: se puede volver a ejecutar sin romper nada.
#
# El punto delicado es madmom. Exige numpy<2, que no publica ruedas para Python
# 3.13+, así que hace falta Python 3.12 como máximo — y Fedora reciente trae 3.13
# como intérprete por defecto, de ahí que se instale python3.12 aparte. Además
# madmom se instala desde git, porque la versión de PyPI (0.16.1, de 2018) no
# compila en Python moderno; al venir del repositorio hay que compilar cuatro
# extensiones Cython, y eso requiere gcc y las cabeceras de desarrollo.
#
# Uso:
#   ./packaging/instalar-entorno.sh
#   ./packaging/instalar-entorno.sh --sin-herramientas
#   ./packaging/instalar-entorno.sh --con-demucs --venv ~/entornos/chords
#
set -euo pipefail

PROYECTO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$PROYECTO/.venv"
SIN_HERRAMIENTAS=0
CON_DEMUCS=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --sin-herramientas) SIN_HERRAMIENTAS=1; shift ;;
        --con-demucs)       CON_DEMUCS=1; shift ;;
        --venv)             VENV="$2"; shift 2 ;;
        -h|--help)          sed -n '2,30p' "${BASH_SOURCE[0]}"; exit 0 ;;
        *) echo "Opción desconocida: $1" >&2; exit 2 ;;
    esac
done

if [[ -t 1 ]]; then
    ROJO=$'\e[31m'; VERDE=$'\e[32m'; AMARILLO=$'\e[33m'
    CIAN=$'\e[36m'; GRIS=$'\e[90m'; FIN=$'\e[0m'
else
    ROJO=; VERDE=; AMARILLO=; CIAN=; GRIS=; FIN=
fi

PROBLEMAS=()

titulo() { printf '\n%s=== %s ===%s\n' "$CIAN" "$1" "$FIN"; }
bien()   { printf '  %s[ok]%s    %s\n' "$VERDE" "$FIN" "$1"; }
nota()   { printf '  %s[info]%s  %s\n' "$GRIS" "$FIN" "$1"; }
aviso()  { printf '  %s[aviso]%s %s\n' "$AMARILLO" "$FIN" "$1"; }
falla()  { printf '  %s[FALTA]%s %s\n' "$ROJO" "$FIN" "$1"; PROBLEMAS+=("$1"); }

printf '%sChord Extractor — instalación del entorno%s\n' "$CIAN" "$FIN"
nota "Proyecto : $PROYECTO"
nota "Entorno  : $VENV"

if [[ $EUID -eq 0 ]]; then
    echo "No lo ejecutes como root: el entorno virtual debe pertenecer a tu usuario." >&2
    exit 1
fi

# ---------------------------------------------------------------- paquetes rpm
titulo "Paquetes del sistema"

# paquete -> ejecutable o ruta con la que se comprueba si ya está
declare -A REQUERIDOS=(
    [python3.12]="/usr/bin/python3.12"
    [python3.12-devel]="/usr/include/python3.12/Python.h"
    [python3.12-tkinter]=""     # sin ruta fija: se comprueba importando
    [gcc]="/usr/bin/gcc"
    [gcc-c++]="/usr/bin/g++"
    [make]="/usr/bin/make"
    [git]="/usr/bin/git"
    [ffmpeg-free]="/usr/bin/ffmpeg"
    [yt-dlp]="/usr/bin/yt-dlp"
)
ORDEN=(python3.12 python3.12-devel python3.12-tkinter gcc gcc-c++ make git ffmpeg-free yt-dlp)

FALTAN=()
for paquete in "${ORDEN[@]}"; do
    ruta="${REQUERIDOS[$paquete]}"
    if [[ -n "$ruta" && -e "$ruta" ]]; then
        bien "$paquete"
    elif [[ -z "$ruta" ]] && /usr/bin/python3.12 -c 'import tkinter' 2>/dev/null; then
        bien "$paquete"
    else
        nota "$paquete no encontrado"
        FALTAN+=("$paquete")
    fi
done

if [[ ${#FALTAN[@]} -gt 0 ]]; then
    if [[ $SIN_HERRAMIENTAS -eq 1 ]]; then
        falla "Faltan paquetes (omitido por --sin-herramientas): sudo dnf install ${FALTAN[*]}"
    else
        nota "Instalando: ${FALTAN[*]}"
        sudo dnf install -y "${FALTAN[@]}"
        for paquete in "${FALTAN[@]}"; do
            ruta="${REQUERIDOS[$paquete]}"
            if [[ -n "$ruta" && ! -e "$ruta" ]]; then
                falla "$paquete no quedó instalado"
            fi
        done
    fi
fi

# ffmpeg-free basta para MP3, M4A y Opus. Si algún archivo no se decodifica,
# el ffmpeg completo de RPM Fusion cubre los formatos que Fedora excluye.
if [[ -e /usr/bin/ffmpeg ]]; then
    nota "ffmpeg-free cubre MP3/M4A/Opus. Para formatos exóticos: RPM Fusion."
fi

if [[ ${#PROBLEMAS[@]} -gt 0 ]]; then
    printf '\n%sNo se puede continuar. Resuelve primero:%s\n' "$ROJO" "$FIN"
    for p in "${PROBLEMAS[@]}"; do printf '  - %s\n' "$p"; done
    exit 1
fi

# ---------------------------------------------------------------- venv
titulo "Entorno virtual"
PY="$VENV/bin/python"
if [[ -x "$PY" ]]; then
    bien "ya existe en $VENV"
else
    nota "Creando…"
    /usr/bin/python3.12 -m venv "$VENV"
    bien "creado"
fi

version_venv="$("$PY" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
if [[ "$version_venv" != "3.12" ]]; then
    printf '%sEl entorno es Python %s; madmom necesita 3.12 o anterior.%s\n' \
           "$ROJO" "$version_venv" "$FIN" >&2
    exit 1
fi
bien "Python $version_venv"

"$PY" -m pip install --upgrade pip --quiet
bien "pip $("$PY" -m pip --version | cut -d' ' -f2)"

# ---------------------------------------------------------------- paquetes pip
titulo "Dependencias de Python"

# El orden importa: madmom se compila contra numpy y Cython, así que tienen que
# estar instalados ANTES de intentar instalarlo.
nota "numpy<2, Cython, scipy  (deben ir ANTES que madmom)"
"$PY" -m pip install "numpy<2" Cython scipy
bien "base instalada"

# -I aísla el intérprete: sin él, «python -c» mete el directorio actual en
# sys.path y ejecutar esto desde una carpeta con un madmom dentro daría un falso
# positivo, saltándose la instalación.
if [[ "$("$PY" -I -c "import importlib.util; print('SI' if importlib.util.find_spec('madmom') else 'NO')")" == "SI" ]]; then
    bien "madmom ya estaba instalado"
else
    nota "madmom desde git (compila 4 extensiones Cython; tarda un poco)…"
    "$PY" -m pip install "git+https://github.com/CPJKU/madmom.git"
    bien "madmom instalado"
fi

nota "pygame, fastapi, uvicorn, python-multipart, pyinstaller"
"$PY" -m pip install pygame fastapi "uvicorn[standard]" python-multipart pyinstaller
bien "resto de dependencias instaladas"

if [[ $CON_DEMUCS -eq 1 ]]; then
    nota "demucs (arrastra PyTorch: varios GB)…"
    "$PY" -m pip install demucs
    bien "demucs instalado"
fi

# ---------------------------------------------------------------- verificación
titulo "Verificación"
PRUEBA="$(mktemp --suffix=.py)"
trap 'rm -f "$PRUEBA"' EXIT

cat > "$PRUEBA" <<'PYCODE'
import os, sys, tempfile
sys.path.insert(0, sys.argv[1])
os.chdir(tempfile.mkdtemp())

import numpy, scipy
print("  numpy %s | scipy %s" % (numpy.__version__, scipy.__version__))

import madmom
from madmom.models import CHORDS_DCCRF, CHROMA_DNN, KEY_CNN
print("  madmom %s | modelos: chroma=%d chords=%d key=%d"
      % (madmom.__version__, len(CHROMA_DNN), len(CHORDS_DCCRF), len(KEY_CNN)))
if not (CHROMA_DNN and CHORDS_DCCRF):
    print("  FALLO: madmom no encuentra sus modelos"); sys.exit(1)

try:
    import tkinter
    print("  tkinter disponible (necesario para la interfaz de escritorio)")
except ImportError:
    print("  FALTA tkinter: instala python3.12-tkinter")

try:
    import pygame
    print("  pygame %s" % pygame.version.ver)
except ImportError:
    print("  pygame no instalado: la GUI funcionara sin reproductor")

# Audio sintetico de acordes conocidos: C -> G -> Am -> F
exec(open(os.path.join(sys.argv[1], "make_test_audio.py")).read())

from chord_extractor import extract
r = extract("test_progression.wav", method="deepchroma",
            with_key=False, with_tempo=False)
obtenidos = [c.chord for c in r.chords]
print("  esperado : C:maj -> G:maj -> A:min -> F:maj")
print("  obtenido : " + " -> ".join(obtenidos))
aciertos = sum(1 for e in ("C:maj", "G:maj", "A:min", "F:maj") if e in obtenidos)
print("  aciertos : %d de 4" % aciertos)
sys.exit(0 if aciertos >= 3 else 1)
PYCODE

if "$PY" "$PRUEBA" "$PROYECTO"; then
    OK=1
else
    OK=0
fi

# ---------------------------------------------------------------- resumen
titulo "Resumen"
if [[ $OK -eq 1 ]]; then
    bien "El entorno funciona de punta a punta."
    printf '\n  Interfaz de escritorio:\n    %s %s\n' "$PY" "$PROYECTO/gui.py"
    printf '  Interfaz web:\n    %s/bin/uvicorn server:app --port 8000\n' "$VENV"
    printf '  CLI:\n    %s %s cancion.mp3\n' "$PY" "$PROYECTO/chord_extractor.py"
else
    printf '  %sLa verificación no pasó. Revisa los mensajes de arriba.%s\n' "$ROJO" "$FIN"
    exit 1
fi
