# -*- mode: python ; coding: utf-8 -*-
"""
chordextractor.spec — receta de PyInstaller para distribuir la GUI como
aplicación autónoma, sin que el usuario final instale Python, madmom ni ffmpeg.

    pyinstaller chordextractor.spec --noconfirm

Resultado: dist/ChordExtractor/ChordExtractor.exe (carpeta completa, onedir).
Reparte la carpeta entera comprimida, no solo el .exe.

Puntos delicados que resuelve este spec:

  1. madmom.models construye sus constantes con glob() sobre el directorio del
     paquete EN TIEMPO DE IMPORTACIÓN. Hay que empaquetar los 72 .pkl (~28 MB)
     conservando la estructura de subcarpetas o el glob no encuentra nada y
     madmom se importa con las listas de modelos vacías.
  2. chord_extractor importa los procesadores de madmom dentro de las funciones;
     collect_submodules() garantiza que entren todos, incluidas las extensiones
     Cython (.pyd).
  3. madmom llama a ffmpeg/ffprobe por PATH: se empaquetan y el runtime hook
     antepone el directorio del bundle al PATH.
  4. Se excluye torch/demucs a propósito (son varios GB). La GUI desactiva la
     casilla de separación cuando detecta que corre empaquetada.
"""
import os
import shutil

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

APP_NAME = "ChordExtractor"

# Los binarios "full_build" de Gyan son estáticos y pesan ~231 MB cada uno, así
# que ffmpeg+ffprobe son ~70% del bundle. Con CHORDEXTRACTOR_BUNDLE_FFMPEG=0 se
# omiten: el .exe baja de ~658 MB a ~196 MB, pero entonces el equipo destino
# necesita ffmpeg instalado y en el PATH (si no, solo podrá abrir WAV).
BUNDLE_FFMPEG = os.environ.get("CHORDEXTRACTOR_BUNDLE_FFMPEG", "1") != "0"


def find_tool(name):
    """Localiza ffmpeg/ffprobe: primero en el PATH, luego donde los deja winget."""
    found = shutil.which(name)
    if found:
        return found
    local = os.environ.get("LOCALAPPDATA", "")
    winget = os.path.join(local, "Microsoft", "WinGet", "Packages")
    if os.path.isdir(winget):
        for root, _dirs, files in os.walk(winget):
            if f"{name}.exe" in files:
                return os.path.join(root, f"{name}.exe")
    return None


# --- ffmpeg / ffprobe -------------------------------------------------------
# Hacen falta LOS DOS: madmom decodifica con ffmpeg, pero antes consulta el
# sample rate y los canales con ffprobe (get_file_info), así que quitar ffprobe
# rompe la lectura de MP3 aunque ffmpeg esté.
binaries = []
if BUNDLE_FFMPEG:
    for tool in ("ffmpeg", "ffprobe"):
        path = find_tool(tool)
        if path:
            binaries.append((path, "."))
            print(f"[spec] {tool}: {path}")
        else:
            print(f"[spec] AVISO: no se encontró {tool}. El .exe solo leerá WAV; "
                  f"instálalo (winget install Gyan.FFmpeg) y reconstruye para MP3.")
else:
    print("[spec] ffmpeg NO se empaqueta (CHORDEXTRACTOR_BUNDLE_FFMPEG=0): "
          "el equipo destino lo necesitará instalado para leer MP3.")

# --- madmom: modelos + submódulos ------------------------------------------
datas = collect_data_files("madmom")          # incluye models/**/*.pkl
hidden = collect_submodules("madmom")
model_count = sum(1 for src, _dst in datas if src.endswith(".pkl"))
print(f"[spec] madmom: {model_count} modelos .pkl, {len(hidden)} submódulos")
if model_count == 0:
    raise SystemExit("[spec] ERROR: no se recogió ningún modelo de madmom. "
                     "¿Está madmom instalado en el entorno desde el que ejecutas "
                     "pyinstaller?")

a = Analysis(
    ["gui.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=["packaging/runtime_hook_ffmpeg.py"],
    # Pesos muertos: la GUI no usa el servidor, y torch/demucs son varios GB.
    excludes=[
        "torch", "torchaudio", "demucs", "matplotlib", "PIL",
        "fastapi", "uvicorn", "starlette", "pydantic", "pydantic_core",
        "IPython", "pytest", "setuptools", "pip",
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,          # UPX suele corromper las DLL de numpy/scipy
    console=False,      # sin ventana de consola: los errores van al log
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,          # pon aquí la ruta a un .ico si quieres icono propio
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name=APP_NAME,
)
