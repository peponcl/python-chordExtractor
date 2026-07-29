@echo off
rem ---------------------------------------------------------------------------
rem sandbox-launch.cmd — arranca la aplicación dentro de Windows Sandbox.
rem
rem El sandbox es un Windows recién creado: no tiene yt-dlp ni winget, así que
rem «Desde URL…» avisaría de que falta. Como el .wsb monta la carpeta de yt-dlp
rem del anfitrión en C:\herramientas\yt-dlp, aquí sólo hay que añadirla al PATH
rem antes de lanzar la aplicación.
rem
rem ffmpeg no hace falta: va empaquetado dentro del propio ejecutable.
rem ---------------------------------------------------------------------------

if exist "C:\herramientas\yt-dlp\yt-dlp.exe" (
    set "PATH=C:\herramientas\yt-dlp;%PATH%"
    echo [sandbox] yt-dlp disponible en el PATH
) else (
    echo [sandbox] yt-dlp no montado: el boton «Desde URL...» avisara de que falta
)

start "" "C:\ChordExtractor\ChordExtractor.exe"
