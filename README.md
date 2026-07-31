# Prototipo: extractor de acordes desde MP3 (madmom)

Creado por **pepon** — pepon.cl

Backend que analiza un archivo de audio y devuelve los acordes con sus tiempos,
más una estimación de tonalidad y tempo. Pensado para vivir detrás de una API
(el cliente sube el audio, el servidor hace el trabajo pesado).

Probado y funcionando en Python 3.12. La progresión de prueba C → G → Am → F se
recupera con el acorde y los tiempos correctos por ambos métodos.

> **Python 3.12 como máximo.** madmom exige `numpy<2`, y numpy 1.x no publica
> wheels para Python 3.13+. Si lo instalas en 3.13/3.14, pip lo compila mal y
> *importar numpy* falla con `OverflowError: cannot convert longdouble infinity
> to integer` — antes siquiera de leer el audio. Crea el venv con 3.12.

## Contenido

- `chord_extractor.py` — módulo núcleo + CLI. La función `extract()` devuelve un
  objeto con `chords`, `key` y `tempo_bpm`.
- `gui.py` — interfaz gráfica de escritorio (Tkinter).
- `web/index.html` — interfaz web, servida por `server.py` en la raíz.
- `chordviz.py` — colores y etiquetas de acorde compartidos por ambas interfaces.
- `history.py` — historial y caché de análisis en SQLite.
- `ytaudio.py` — descarga de audio desde una URL con `yt-dlp` (opcional).
- `lyrics.py` — transcripción y alineamiento de la letra (opcional).
- `chordextractor.spec` + `packaging/` — receta de PyInstaller para distribuir la
  GUI como ejecutable autónomo.
- `server.py` — API FastAPI mínima (`POST /extract` con el archivo subido).
- `requirements.txt` — dependencias con la receta de instalación que funciona.
- `make_test_audio.py` — genera un WAV/MP3 sintético de acordes conocidos para
  validar la instalación.

## Cómo empezar — resumen

Tres caminos según lo que quieras hacer:

| Quiero… | Haz esto | Necesitas |
|---|---|---|
| **Solo usarlo** en Windows | Descarga la carpeta `ChordExtractor`, descomprime y ejecuta `ChordExtractor.exe` | Nada: ffmpeg y yt-dlp van dentro. Windows avisará: ver más abajo |
| **Ejecutarlo desde el código** en Windows | `.\packaging\instalar-entorno.ps1` | Compilador de C++ |
| **Ejecutarlo en Fedora** | `./packaging/instalar-entorno.sh` | Solo `sudo` para los paquetes |

Los dos scripts hacen lo mismo: comprueban las herramientas, instalan lo que
falte, crean el entorno virtual y verifican el resultado analizando un audio
sintético de acordes conocidos. Si terminan con `4 de 4`, funciona.

**Al ejecutar el `.exe`, Windows mostrará una advertencia** porque no está
firmado. En la mayoría de equipos aparece SmartScreen, que se salta con *Más
información → Ejecutar de todas formas*. En equipos con Smart App Control
activado no hay forma de saltarlo: ahí toca usar el código fuente.

Lo único que no se instala solo es el **compilador de C++** en Windows, porque
son varios GB. Hace falta porque madmom trae cuatro extensiones que se compilan
al instalarlo. En Fedora es `gcc` y sí lo instala el script.

Y ojo con la versión de Python: **3.12 como máximo**, nunca 3.13 o superior. El
motivo está explicado más abajo.

## Instalación — script automático (Windows)

```powershell
.\packaging\instalar-entorno.ps1
```

Comprueba e instala Python 3.12, git, ffmpeg y yt-dlp, crea el entorno virtual,
instala las dependencias en el orden correcto y verifica el resultado analizando
un audio sintético de acordes conocidos (`C → G → Am → F`). Es idempotente.

El único requisito que no instala solo es el **compilador de C++**, porque son
varios GB: si falta, te dice cómo obtenerlo. Hace falta porque madmom trae cuatro
extensiones Cython que se compilan al instalarlo.

Opciones: `-SinHerramientas` (sólo comprueba, no instala nada con winget),
`-ConDemucs`, `-VenvPath <ruta>`.

> Con Visual Studio 2026, su `vcvarsall.bat` invoca `vswhere.exe` sin ruta
> absoluta. Si no está en el PATH devuelve un entorno vacío y la compilación
> falla con «Unable to find a compatible Visual Studio installation», aunque
> `cl.exe` esté perfectamente instalado. El script lo añade al PATH por ti.

## Instalación — script automático (Fedora)

```bash
./packaging/instalar-entorno.sh
```

Instala con `dnf` lo que falte —`python3.12`, `python3.12-devel`,
`python3.12-tkinter`, `gcc`, `gcc-c++`, `make`, `git`, `ffmpeg-free`, `yt-dlp`—,
crea el entorno virtual y verifica el resultado igual que su equivalente de
Windows.

Fedora reciente trae Python 3.13 por defecto, por eso instala 3.12 aparte: es el
máximo que admite `numpy<2`. El script aborta si el entorno no acaba siendo 3.12.

Opciones: `--sin-herramientas`, `--con-demucs`, `--venv <ruta>`.

## Instalación manual

El único punto delicado es **madmom**. La versión de PyPI (0.16.1) no compila en
Python 3.10+. Hay que instalar desde git y fijar numpy < 2:

```bash
# dependencia de sistema para decodificar MP3
sudo apt install ffmpeg          # o brew install ffmpeg en macOS

python3 -m venv venv && source venv/bin/activate
pip install "numpy<2" cython scipy
pip install "git+https://github.com/CPJKU/madmom.git"
pip install fastapi "uvicorn[standard]" python-multipart   # solo para la API
```

(La primera vez, madmom descarga/usa modelos preentrenados que ya vienen en el
paquete; no hay que bajar nada aparte.)

## Uso — interfaz gráfica de escritorio

```bash
dnf install python3-tkinter      # en Fedora Tkinter va aparte
pip install pygame               # opcional, solo para el reproductor

python gui.py                    # o: python gui.py cancion.mp3
```

Abres el archivo, eliges las opciones (método, tonalidad/tempo, `--separate` con
su dispositivo) y pulsas **Analizar**. El análisis corre en un hilo aparte, así
que la ventana no se congela. Verás:

- tonalidad, tempo, nº de acordes y método usado;
- una **línea de tiempo** con los acordes coloreados a escala, con regla de
  tiempos y control de **zoom** (1×–20×) — a 1× cabe la canción entera; con zoom
  la pista hace scroll y ya caben las etiquetas de los acordes cortos;
- la **tabla** de segmentos (inicio, fin, duración, acorde), teñida con el color
  de cada acorde;
- un **reproductor** cuyo cursor recorre la línea de tiempo, resalta la fila del
  acorde que suena y lo muestra en grande. Haz clic en la línea de tiempo o en
  una fila para saltar a ese punto;
- **audio desde una URL** (si tienes `yt-dlp` instalado): el botón «Desde URL…»
  descarga la pista, la deja lista para analizar y la trata igual que un archivo
  local. Ver la sección siguiente;
- **historial y caché**: cada análisis se guarda, y si vuelves a pulsar
  «Analizar» sobre un archivo ya procesado con las mismas opciones, el resultado
  aparece al instante en vez de reprocesarlo. El botón **Historial** abre la
  lista de análisis guardados para recargar cualquiera con un doble clic;
- botones para **exportar** el resultado a JSON, a `.lab` o a una **hoja de
  acordes** en formato ChordPro (`.cho`);
- un **tema claro y uno oscuro**, que se alternan con el botón de la barra
  superior. Arranca en oscuro y recuerda tu elección en
  `%LOCALAPPDATA%\ChordExtractor\config.json`. En Windows 10 2004+ y 11 la barra
  de título también se pone oscura.

Sin `pygame` todo lo demás funciona igual: solo se desactiva la reproducción.

En el ejecutable empaquetado no aparecen la casilla de Demucs ni el selector de
dispositivo: la separación no puede funcionar ahí (ver la sección de
distribución), así que no se construyen esos controles.

## Audio desde una URL (opcional)

El botón **«Desde URL…»** de la barra superior pide un enlace, consulta los
metadatos y, tras confirmar, descarga sólo la pista de audio a
`%LOCALAPPDATA%\ChordExtractor\downloads\`.

**El ejecutable ya trae yt-dlp incluido**, así que funciona sin instalar nada.
Ejecutando desde el código sí hace falta instalarlo:

```bash
winget install yt-dlp        # o: sudo dnf install yt-dlp
```

Aunque venga incluido, **siempre se prefiere el que esté instalado en el
sistema**. yt-dlp caduca —los sitios cambian cada pocas semanas y una versión
congelada deja de funcionar—, así que cuando el incluido se quede atrás basta
con instalar o actualizar yt-dlp por fuera: no hay que reconstruir ni volver a
repartir el ejecutable.

Ten en cuenta que descargar contenido de YouTube va contra sus Términos de
Servicio salvo con la descarga offline de Premium.

**Formato.** Si la pista viene en Opus —lo habitual— se **remuxea a `.opus`**:
sólo cambia el contenedor, el códec queda intacto, así que es instantáneo y sin
pérdida. Si viene en AAC hay que transcodificar a MP3, porque un contenedor Ogg
no admite AAC.

Dos detalles que costaron encontrarse y conviene no deshacer:

- La extensión **tiene que ser `.opus`, no `.ogg`**. SDL_mixer (pygame) elige el
  decodificador por la extensión, y ante un `.ogg` usa el de Vorbis, que falla
  con `VORBIS_invalid_first_page` aunque el Opus de dentro sea perfectamente
  válido.
- No sirve dejar el `.m4a`/`.webm` original: madmom los analiza sin problema,
  pero pygame no reproduce ni AAC ni WebM, y el reproductor quedaría inservible.

**Duración.** El análisis carga la señal entera en memoria y el consumo escala de
forma lineal: medido, 520 MB a 2 min, 1204 MB a 5 y 2344 MB a 10 (unos 3,8 MB por
segundo de audio). Un vídeo de una hora pediría ~13 GB. Por eso el diálogo estima
memoria y tiempo antes de descargar, y pide confirmación por encima de 10 minutos.

El audio descargado se cachea por id de vídeo, así que volver a pegar el mismo
enlace no vuelve a descargar nada. Y como el historial identifica los archivos
por el hash de su contenido, el análisis también se reutiliza.

## Uso — interfaz web

```bash
uvicorn server:app --port 8000
```

y abre <http://localhost:8000/>. Arrastras el MP3, eliges las opciones y pulsas
**Analizar**: el archivo se sube a `POST /extract` y la página pinta el mismo
conjunto de vistas que la de escritorio (línea de tiempo con zoom, tabla,
reproductor sincronizado y exportación a JSON/`.lab`). El audio se reproduce en
local con la etiqueta `<audio>` del navegador, no se vuelve a descargar del
servidor. La página se adapta al tema claro/oscuro del sistema.

Los colores de acorde son los mismos en las dos interfaces: el matiz sale de la
fundamental y la luminosidad de la calidad (mayor claro, menor oscuro), así que
un mismo acorde siempre se ve igual.

## Distribución — ejecutable autónomo (Windows)

`chordextractor.spec` empaqueta la GUI con PyInstaller en una aplicación que no
exige instalar Python, madmom ni ffmpeg en el equipo destino.

```bash
venv312\Scripts\pip install pyinstaller
```

```bash
venv312\Scripts\pyinstaller chordextractor.spec --noconfirm
```

Sale `dist/ChordExtractor/ChordExtractor.exe`. **Reparte la carpeta entera**
comprimida, no solo el `.exe`: el resto vive en `_internal/`.

Qué resuelve el spec (son las cuatro cosas que rompen si se empaqueta a lo bruto):

1. **Modelos de madmom.** `madmom.models` construye sus constantes con `glob()`
   sobre el directorio del paquete *en tiempo de importación*. Hay que incluir
   los 72 `.pkl` (~28 MB) conservando las subcarpetas (`chords/`, `chroma/`,
   `key/`…) o madmom se importa con las listas de modelos vacías.
2. **Importaciones perezosas.** `chord_extractor` importa los procesadores dentro
   de las funciones; `collect_submodules("madmom")` asegura que entren los 44
   submódulos y las 4 extensiones Cython (`.pyd`).
3. **ffmpeg y ffprobe.** madmom los llama por PATH. El spec los empaqueta y
   `packaging/runtime_hook_ffmpeg.py` antepone el directorio del bundle al PATH.
   Hacen falta **los dos**: se decodifica con ffmpeg, pero antes se consulta el
   sample rate con ffprobe (`get_file_info`).
4. **Demucs.** `separate_harmonic()` lanza `sys.executable -m demucs`; dentro del
   `.exe`, `sys.executable` es el propio ejecutable, así que eso relanzaría la
   GUI en bucle. La casilla se desactiva sola cuando detecta `sys.frozen`.

### Tamaño

El bundle completo son **~676 MB**, de los cuales ~462 MB son ffmpeg y ffprobe
(los binarios *full_build* de Gyan son estáticos, ~231 MB cada uno) y 17 MB
yt-dlp. Si prefieres un paquete ligero y asumes que el equipo destino tendrá
ffmpeg instalado:

```bash
set CHORDEXTRACTOR_BUNDLE_FFMPEG=0 && venv312\Scripts\pyinstaller chordextractor.spec --noconfirm
```

Baja a ~196 MB, pero sin ffmpeg en el PATH del destino solo se podrán abrir WAV.

### Windows bloquea el ejecutable

El `.exe` no está firmado, así que Windows desconfía. Hay dos protecciones
distintas y conviene no confundirlas:

- **SmartScreen** («Windows protegió su PC») es lo que verá la mayoría. Molesta,
  pero tiene salida: *Más información → Ejecutar de todas formas*.
- **Smart App Control** bloquea sin alternativa: no admite excepciones. Solo está
  activo en instalaciones limpias de Windows 11 22H2+, y se desactiva de forma
  permanente en cuanto alguien lo apaga.

El spec incrusta metadatos de versión (empresa, producto, descripción), que es lo
correcto y ayuda algo con las heurísticas, pero **no sustituye a una firma de
código**. La solución real es un certificado; existen programas de firma gratuita
para proyectos de código abierto que conviene mirar antes de pagar uno comercial.

Para probar el ejecutable como lo vería otra persona, sin tocar la seguridad de
tu equipo, usa `packaging/sandbox-test.wsb` con Windows Sandbox (requiere
Windows 11 Pro).

### Errores en el ejecutable

El build es *windowed* (sin consola), así que `sys.stderr` no existe: los fallos
se registran en `%LOCALAPPDATA%\ChordExtractor\error.log` y el diálogo de error
muestra esa ruta.

## Uso — CLI

```bash
python chord_extractor.py cancion.mp3
python chord_extractor.py cancion.mp3 --method cnn --json salida.json
python chord_extractor.py cancion.mp3 --lab salida.lab
python chord_extractor.py cancion.mp3 --chordpro cancion.cho --por-linea 8
```

## Hoja de acordes (ChordPro)

`--chordpro` genera un `.cho`, el formato estándar de las hojas de acordes: lo
leen ChordPro, Chordii, OnSong, SongBook y compañía, y de ahí se saca PDF o HTML
para imprimir o compartir. También está como botón «Hoja de acordes» en las dos
interfaces.

```
{title: rock_rodrigo_take1}
{subtitle: acordes extraídos automáticamente}
{key: D major}
{tempo: 128}
{comment: método deepchroma — sólo tríadas mayores y menores}

{comment: 0:00}
[D] [G] [Dm] [D]

{comment: 0:10}
[G] [D] [Gm] [A#]
```

Los acordes se agrupan de cuatro en cuatro (ajustable con `--por-linea`), y cada
grupo lleva el minuto en que empieza para poder seguir la canción mientras suena.

### Con letra

El botón **«Con letra…»** añade la letra debajo de los acordes. Dos modos, según
lo que tengas:

- **Pegas la letra** → sólo se usa el reconocedor para *situarla* en el tiempo.
  Las palabras son las tuyas y el resultado es bastante fiable, porque el
  problema pasa de «adivinar qué dice» a «encontrar dónde lo dice». Es el modo
  recomendado para tus propias canciones.
- **Dejas la caja vacía** → transcripción automática. Cómodo para canciones
  ajenas, pero el reconocimiento sobre voz *cantada* es notablemente peor que
  sobre voz hablada, y con mezclas densas o voz agresiva la calidad cae mucho.

```
{comment: 0:12}
[D]Bajo el cielo [G]gris
[G]caminas sin [Am]mirar atras
```

Cada acorde se coloca delante de la palabra que suena cuando entra, no en una
posición calculada por regla de tres: partir una palabra por la mitad se lee
peor.

**La dependencia se instala desde la propia aplicación.** Se usa
[faster-whisper](https://github.com/SYSTRAN/faster-whisper), que corre sobre
CTranslate2 y **no arrastra PyTorch**: misma calidad que Whisper por una fracción
del tamaño. Se instala en un entorno virtual aparte, dentro de
`%LOCALAPPDATA%\ChordExtractor\transcripcion\`, no dentro del programa — así se
puede actualizar o borrar sin tocar la aplicación, y el ejecutable no engorda.

Modelos disponibles: `tiny` (~75 MB) a `large-v3` (~3 GB); `small` (~480 MB) es
el equilibrio razonable, porque `tiny` y `base` van demasiado justos cantando. El
modelo se descarga la primera vez que se usa.

En el ejecutable empaquetado hace falta que haya **Python instalado en el
sistema** para poder montar ese entorno, porque el `.exe` no lleva pip. Si no lo
hay, la aplicación lo dice y explica cómo instalarlo.

> Sobre publicar: los acordes no son problema, una progresión no es material
> protegible. Las letras sí lo son, y publicar la de una canción ajena requiere
> licencia. Para uso propio, o para tus propias canciones, no hay inconveniente.

El formato `.lab` es el estándar de anotación de acordes (MIREX): una línea por
segmento, `inicio<TAB>fin<TAB>etiqueta` en segundos, con `N` para los tramos sin
acorde. Lo leen directamente Sonic Visualiser, mir_eval y las herramientas tipo
Chordino, así que sirve para visualizar, comparar contra un ground truth o
importar en otro flujo.

Salida:

```
Archivo : cancion.mp3
Método  : deepchroma
Tonalidad estimada : C major
Tempo estimado     : 120.0 BPM

  inicio      fin   acorde
--------------------------------
    0.00     2.00   C:maj
    2.00     4.00   G:maj
    ...
```

## Uso — como módulo

```python
from chord_extractor import extract

result = extract("cancion.mp3", method="deepchroma")
print(result.key, result.tempo_bpm)
for c in result.chords:
    print(c.start, c.end, c.chord)
print(result.to_json(indent=2))
```

## Uso — API

```bash
uvicorn server:app --host 0.0.0.0 --port 8000
curl -F "file=@cancion.mp3" "http://localhost:8000/extract?method=deepchroma"
```

Parámetros de query: `method` (`deepchroma`|`cnn`), `key`, `tempo`, `separate` y
`device` (`auto`|`cuda`|`cpu`). La raíz `/` sirve la interfaz web de `web/`.

Respuesta JSON:

```json
{
  "source": "cancion.mp3",
  "method": "deepchroma",
  "key": "C major",
  "tempo_bpm": 120.0,
  "chords": [
    { "start": 0.0, "end": 2.0, "chord": "C:maj" },
    { "start": 2.0, "end": 4.0, "chord": "G:maj" }
  ]
}
```

## Dos métodos de acordes

- `deepchroma` (por defecto): DeepChroma + decoder. Rápido.
- `cnn`: CNNChordFeature + CRF. En el audio de prueba clavó los tiempos exactos;
  suele ir bien en audio real. Pruébalos y quédate con el que mejor te dé.

## Separación con Demucs (opcional, `--separate`)

Para mejorar los acordes en mezclas densas (guitarras distorsionadas, batería y
voz fuertes), puedes separar la canción con Demucs y analizar solo la parte
armónica (`bass` + `other`, sin batería ni voz) antes de pasarla a madmom.

```bash
pip install demucs        # arrastra PyTorch
python chord_extractor.py cancion.mp3 --separate            # GPU auto
python chord_extractor.py cancion.mp3 --separate --device cpu
```

Cómo funciona el flag:

```
MP3 → Demucs (htdemucs, 4 stems) → bass + other → madmom → acordes
```

- La detección de **acordes** y **tonalidad** se hace sobre la parte armónica.
- El **tempo** se estima siempre sobre el audio original (necesita la batería).
- `--device auto` (por defecto) usa la GPU si hay CUDA disponible; si no, CPU.
- Con GPU la separación tarda segundos; en CPU, varios minutos por canción.

Nota GPU Blackwell (RTX 50xx): si torch no reconoce la tarjeta, instala el build
CUDA 12.8: `pip install torch --index-url https://download.pytorch.org/whl/cu128`

Probado: la lógica de combinación de stems + análisis está validada con stems
sintéticos (recupera C-G-Am-F). La separación Demucs en sí se ejecuta en tu
equipo (requiere los pesos del modelo, que se descargan la primera vez).

## Limitaciones honestas

- **Solo tríadas mayores/menores** (24 clases). No detecta séptimas, sus, add9,
  acordes de jazz ni inversiones. Para eso se necesita otro modelo (p. ej.
  entrenar/usar uno sobre un vocabulario de acordes más amplio).
- **La tonalidad es poco fiable en clips cortos o sin melodía.** En la prueba
  sintética dio "G major" cuando la progresión está en Do mayor. Con canciones
  reales completas mejora, pero tómala como orientativa.
- **Mezclas densas bajan la precisión.** Si vas a por calidad, separa primero las
  pistas con Demucs y corre el extractor sobre la parte armónica (sin batería ni
  voz). Eso sube bastante el acierto.
- El análisis es **CPU-bound** y tarda unos segundos por canción.

## Notas para llevarlo a producción (AWS)

- `server.py` procesa dentro del request (síncrono). Para tráfico real, encola el
  trabajo (SQS + worker, o Celery) y expón un endpoint de estado/resultado.
- Carga los *processors* de madmom una sola vez al arrancar el worker en lugar de
  por request (aquí se cargan de forma perezosa para mantener el prototipo simple).
- Valida tipo y tamaño del archivo antes de procesar (el server ya limita a 30 MB
  y a extensiones de audio conocidas).
- Para una app Android: este es exactamente el backend que consumiría el cliente
  subiendo el MP3 y pintando la línea de acordes con el JSON de vuelta.
```
