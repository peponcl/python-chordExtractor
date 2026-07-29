<#
.SYNOPSIS
    Monta desde cero el entorno de Chord Extractor en Windows.

.DESCRIPTION
    Instala y verifica todo lo necesario: Python 3.12, git, ffmpeg, yt-dlp, el
    entorno virtual y las dependencias de Python. Al final comprueba que la
    cadena completa funciona analizando un audio sintético de acordes conocidos.

    Es idempotente: se puede volver a ejecutar sin romper nada.

    El punto delicado es madmom. Exige numpy<2, que no publica ruedas para
    Python 3.13+, así que hace falta Python 3.12 como máximo. Y se instala desde
    git porque la versión de PyPI (0.16.1, de 2018) no compila en Python
    moderno; al venir del repositorio hay que compilar cuatro extensiones
    Cython, y eso requiere un compilador de C++.

.PARAMETER VenvPath
    Dónde crear el entorno virtual. Por defecto, venv312 en la raíz del proyecto.

.PARAMETER SinHerramientas
    No instala nada con winget; sólo comprueba y avisa de lo que falte.

.PARAMETER ConDemucs
    Instala además demucs para la separación de pistas. Arrastra PyTorch:
    son varios GB.

.EXAMPLE
    .\packaging\instalar-entorno.ps1
    .\packaging\instalar-entorno.ps1 -SinHerramientas
#>
param(
    [string]$VenvPath = "",
    [switch]$SinHerramientas,
    [switch]$ConDemucs
)

# NO usar "Stop": pip, git y winget escriben su progreso en stderr, y PowerShell
# 5.1 envuelve esa salida en ErrorRecords. Con "Stop" el script abortaría en
# mitad de una instalación correcta. Se comprueba $LASTEXITCODE explícitamente.
$ErrorActionPreference = "Continue"

$Proyecto = Split-Path -Parent $PSScriptRoot
if (-not $VenvPath) { $VenvPath = Join-Path $Proyecto "venv312" }

$problemas = @()
$avisos = @()

function Titulo($texto) {
    Write-Host ""
    Write-Host "=== $texto ===" -ForegroundColor Cyan
}
function Bien($texto)  { Write-Host "  [ok]    $texto" -ForegroundColor Green }
function Nota($texto)  { Write-Host "  [info]  $texto" -ForegroundColor Gray }
function Aviso($texto) {
    Write-Host "  [aviso] $texto" -ForegroundColor Yellow
    $script:avisos += $texto
}
function Falla($texto) {
    Write-Host "  [FALTA] $texto" -ForegroundColor Red
    $script:problemas += $texto
}

function Comprobar($descripcion) {
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  [ERROR] $descripcion (código $LASTEXITCODE)" -ForegroundColor Red
        exit 1
    }
}

function Refrescar-Path {
    # winget añade las carpetas al PATH persistente, pero este proceso conserva
    # el que tenía al arrancar. Sin esto, lo recién instalado no se encuentra.
    $env:PATH = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                [Environment]::GetEnvironmentVariable("Path", "User")
}

function Instalar-Winget($id, $nombre) {
    if ($SinHerramientas) {
        Falla "$nombre no está instalado (omitido por -SinHerramientas: winget install $id)"
        return $false
    }
    Nota "Instalando $nombre con winget…"
    winget install --id $id -e --accept-source-agreements --accept-package-agreements
    Refrescar-Path
    return $true
}

Write-Host "Chord Extractor — instalación del entorno" -ForegroundColor White
Nota "Proyecto : $Proyecto"
Nota "Entorno  : $VenvPath"

# ---------------------------------------------------------------- winget
Titulo "Herramientas del sistema"
if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
    if (-not $SinHerramientas) {
        Falla "winget no está disponible. Instala 'Instalador de aplicaciones' desde Microsoft Store, o usa -SinHerramientas."
    }
} else {
    Bien "winget disponible"
}

# ---------------------------------------------------------------- Python 3.12
function Hay-Python312 {
    if (-not (Get-Command py -ErrorAction SilentlyContinue)) { return $false }
    $salida = py -3.12 --version
    return ($LASTEXITCODE -eq 0) -and ($salida -match "3\.12")
}

$python = Hay-Python312
if (-not $python) {
    Nota "Python 3.12 no encontrado"
    if (Instalar-Winget "Python.Python.3.12" "Python 3.12") {
        $python = Hay-Python312
    }
}
if ($python) {
    Bien ((py -3.12 --version) + "  (madmom necesita numpy<2, sin ruedas para 3.13+)")
} else {
    Falla "Python 3.12"
}

# ---------------------------------------------------------------- git
if (Get-Command git -ErrorAction SilentlyContinue) {
    Bien ((git --version) -replace "git version ", "git ")
} else {
    Nota "git no encontrado (hace falta: madmom se instala desde su repositorio)"
    if (Instalar-Winget "Git.Git" "git") {
        if (Get-Command git -ErrorAction SilentlyContinue) { Bien "git instalado" }
        else { Falla "git" }
    }
}

# ---------------------------------------------------------------- compilador
$vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
$compilador = $null
if (Test-Path $vswhere) {
    $compilador = & $vswhere -latest -products * `
        -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 `
        -property displayName 2>$null
}
if ($compilador) {
    Bien "Compilador C++: $compilador"
    # vcvarsall.bat de VS 2026 invoca vswhere.exe sin ruta absoluta. Si no está
    # en el PATH devuelve un entorno vacío y setuptools concluye que no hay
    # compilador ("Unable to find a compatible Visual Studio installation"),
    # aunque cl.exe esté perfectamente instalado.
    $dirVswhere = Split-Path $vswhere
    if (($env:PATH -split ';') -notcontains $dirVswhere) {
        $env:PATH = $dirVswhere + ";" + $env:PATH
        Nota "vswhere añadido al PATH (lo necesita vcvarsall.bat para compilar)"
    }
} else {
    Falla ("Compilador de C++ (madmom trae 4 extensiones Cython que compilar).`n" +
           "            Instala las Build Tools marcando el componente de C++:`n" +
           "              winget install Microsoft.VisualStudio.2022.BuildTools`n" +
           "            Son varios GB, por eso este script no lo hace por su cuenta.")
}

# ---------------------------------------------------------------- ffmpeg
if (Get-Command ffmpeg -ErrorAction SilentlyContinue) {
    Bien "ffmpeg  (necesario para decodificar MP3/M4A; con WAV no hace falta)"
} else {
    Nota "ffmpeg no encontrado"
    if (Instalar-Winget "Gyan.FFmpeg" "ffmpeg") {
        if (Get-Command ffmpeg -ErrorAction SilentlyContinue) { Bien "ffmpeg instalado" }
        else { Aviso "ffmpeg instalado, pero requiere reabrir la terminal para verse en el PATH" }
    }
}

# ---------------------------------------------------------------- yt-dlp
if (Get-Command yt-dlp -ErrorAction SilentlyContinue) {
    Bien "yt-dlp  (opcional: habilita «Desde URL…»)"
} else {
    Nota "yt-dlp no encontrado (opcional)"
    if (-not $SinHerramientas) {
        winget install --id yt-dlp.yt-dlp -e --accept-source-agreements --accept-package-agreements
        Refrescar-Path
    }
}

if ($problemas.Count -gt 0) {
    Write-Host ""
    Write-Host "No se puede continuar. Resuelve primero:" -ForegroundColor Red
    $problemas | ForEach-Object { Write-Host "  - $_" -ForegroundColor Red }
    exit 1
}

# ---------------------------------------------------------------- venv
Titulo "Entorno virtual"
$pyExe = Join-Path $VenvPath "Scripts\python.exe"
if (Test-Path $pyExe) {
    Bien "ya existe en $VenvPath"
} else {
    Nota "Creando…"
    py -3.12 -m venv $VenvPath
    Comprobar "creación del entorno virtual"
    Bien "creado"
}
& $pyExe -m pip install --upgrade pip --quiet
Comprobar "actualización de pip"
Bien ("pip " + (& $pyExe -m pip --version).Split(" ")[1])

# ---------------------------------------------------------------- paquetes
Titulo "Dependencias de Python"
# El orden importa: madmom se compila contra numpy y Cython, así que tienen que
# estar antes de intentar instalarlo.
Nota "numpy<2, Cython, scipy  (deben ir ANTES que madmom)"
& $pyExe -m pip install "numpy<2" Cython scipy
Comprobar "instalación de numpy/Cython/scipy"
Bien "base instalada"

# Se compara la salida impresa, no $LASTEXITCODE: en PowerShell 5.1 el código de
# salida no es fiable aquí y un falso positivo se saltaría la instalación.
# -I aísla el intérprete: sin él, «python -c» mete el directorio actual en
# sys.path y bastaría ejecutar esto desde una carpeta que contenga un madmom
# para creer que ya está instalado.
$estaMadmom = & $pyExe -I -c "import importlib.util; print('SI' if importlib.util.find_spec('madmom') else 'NO')"
if ($estaMadmom -eq "SI") {
    Bien "madmom ya estaba instalado"
} else {
    Nota "madmom desde git (compila 4 extensiones Cython; tarda un poco)…"
    & $pyExe -m pip install "git+https://github.com/CPJKU/madmom.git"
    Comprobar "compilación de madmom"
    Bien "madmom instalado"
}

Nota "pygame, fastapi, uvicorn, python-multipart, pyinstaller"
& $pyExe -m pip install pygame fastapi "uvicorn[standard]" python-multipart pyinstaller
Comprobar "instalación del resto de dependencias"
Bien "resto de dependencias instaladas"

if ($ConDemucs) {
    Nota "demucs (arrastra PyTorch: varios GB)…"
    & $pyExe -m pip install demucs
    Comprobar "instalación de demucs"
    Bien "demucs instalado"
}

# ---------------------------------------------------------------- verificación
Titulo "Verificación"
$prueba = Join-Path $env:TEMP "verificar_chordextractor.py"
$codigo = @'
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
    import pygame; print("  pygame %s" % pygame.version.ver)
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
'@
Set-Content -Path $prueba -Value $codigo -Encoding utf8
& $pyExe $prueba $Proyecto
$okVerificacion = ($LASTEXITCODE -eq 0)
Remove-Item $prueba -ErrorAction SilentlyContinue

# ---------------------------------------------------------------- resumen
Titulo "Resumen"
if ($okVerificacion) {
    Bien "El entorno funciona de punta a punta."
    Write-Host ""
    Write-Host "  Interfaz de escritorio:" -ForegroundColor White
    Write-Host "    $pyExe `"$Proyecto\gui.py`""
    Write-Host "  Interfaz web:" -ForegroundColor White
    Write-Host "    $VenvPath\Scripts\uvicorn.exe server:app --port 8000"
    Write-Host "  Construir el ejecutable:" -ForegroundColor White
    Write-Host "    $VenvPath\Scripts\pyinstaller.exe `"$Proyecto\chordextractor.spec`" --noconfirm"
} else {
    Write-Host "  La verificación no pasó. Revisa los mensajes de arriba." -ForegroundColor Red
}
if ($avisos.Count -gt 0) {
    Write-Host ""
    Write-Host "  Avisos:" -ForegroundColor Yellow
    $avisos | ForEach-Object { Write-Host "    - $_" -ForegroundColor Yellow }
}
if (-not $okVerificacion) { exit 1 }
