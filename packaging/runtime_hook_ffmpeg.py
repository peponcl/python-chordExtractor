"""
Runtime hook de PyInstaller.

madmom decodifica MP3/M4A llamando a 'ffmpeg' y 'ffprobe' como comandos sueltos
(subprocess), así que los resuelve por PATH. Como el spec empaqueta ambos
binarios dentro del bundle, aquí anteponemos el directorio del bundle al PATH
para que los encuentre sin depender de que estén instalados en el sistema.
"""
import os
import sys

bundle = getattr(sys, "_MEIPASS", None) or os.path.dirname(sys.executable)
os.environ["PATH"] = bundle + os.pathsep + os.environ.get("PATH", "")
