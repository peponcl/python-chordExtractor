"""
transcribe_worker.py
--------------------
Transcribe un audio con faster-whisper y escupe JSON por la salida estándar.

Corre como proceso aparte, en su propio entorno virtual, por dos razones: el
ejecutable empaquetado no tiene pip con el que instalar nada, y así la
dependencia (que pesa cientos de MB) no engorda el paquete ni se mezcla con él.

Uso:
    python transcribe_worker.py AUDIO MODELO IDIOMA
    # IDIOMA: código ISO ("es", "en") o "auto"

Salida (JSON):
    {"language": "es", "duration": 213.4,
     "words": [{"text": "hola", "start": 1.2, "end": 1.5}, ...]}
"""
import json
import os
import sys


def _habilitar_cuda():
    """
    CTranslate2 detecta la GPU y quiere usarla, pero no trae consigo el runtime
    de CUDA: necesita cublas64_12.dll y las de cuDNN, que NO están en el PATH.

    Si Demucs está instalado, PyTorch sí las trae en su carpeta lib, así que se
    registra ese directorio para que se encuentren. Sin esto, la transcripción
    falla con «Library cublas64_12.dll is not found or cannot be loaded».

    Devuelve una nota de lo ocurrido: si esto no funciona se acaba en CPU, y sin
    la nota no habría forma de saber por qué.
    """
    if sys.platform != "win32":
        return "no es Windows: no hace falta registrar DLL"
    try:
        import torch
    except Exception as exc:
        return f"torch no importable ({type(exc).__name__}), se usará CPU"
    lib = os.path.join(os.path.dirname(torch.__file__), "lib")
    if not os.path.isdir(lib):
        return f"no existe {lib}"
    if not os.path.isfile(os.path.join(lib, "cublas64_12.dll")):
        return f"cublas64_12.dll no está en {lib}"
    try:
        os.add_dll_directory(lib)
        # El PATH del proceso también, por si alguna dependencia se resuelve por
        # la vía clásica en vez de por los directorios registrados.
        os.environ["PATH"] = lib + os.pathsep + os.environ.get("PATH", "")
        return f"DLL de CUDA registradas desde {lib}"
    except Exception as exc:
        return f"no se pudieron registrar: {type(exc).__name__}: {exc}"


def main():
    if len(sys.argv) < 4:
        print(json.dumps({"error": "faltan argumentos"}))
        return 2

    audio, modelo, idioma = sys.argv[1], sys.argv[2], sys.argv[3]

    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        print(json.dumps({"error": f"faster-whisper no está instalado: {exc}"}))
        return 1

    def ejecutar(dispositivo):
        """
        Transcribe entera en el dispositivo dado.

        El generador de segmentos se consume AQUÍ dentro a propósito:
        model.transcribe() devuelve un iterador perezoso y CTranslate2 no toca
        CUDA hasta que se recorre, así que el fallo por librerías del runtime no
        aparece al construir el modelo sino al iterar. Si se dejara fuera, el
        repliegue a CPU no llegaría a activarse nunca.
        """
        model = WhisperModel(modelo, device=dispositivo, compute_type="int8")
        segments, info = model.transcribe(
            audio,
            language=None if idioma == "auto" else idioma,
            word_timestamps=True,          # imprescindible para colocar acordes
            vad_filter=True,               # descarta los tramos sin voz
        )
        palabras = []
        for segmento in segments:
            for w in (segmento.words or []):
                texto = w.word.strip()
                if texto:
                    palabras.append({"text": texto,
                                     "start": round(w.start, 3),
                                     "end": round(w.end, 3)})
        return palabras, info

    aviso_cuda = _habilitar_cuda()
    try:
        try:
            palabras, info = ejecutar("cuda")
            dispositivo, motivo = "cuda", ""
        except Exception as exc:
            # int8 en CPU es perfectamente utilizable, sólo más lento, y es
            # preferible a dejar al usuario sin transcripción.
            motivo = f"{type(exc).__name__}: {exc}"[:200]
            palabras, info = ejecutar("cpu")
            dispositivo = "cpu"

        # ensure_ascii=True a propósito: en Windows la salida estándar sale en
        # la página de códigos del sistema (cp1252), no en UTF-8, así que un
        # JSON con tildes y eñes llegaría corrompido al otro lado. Escapándolo
        # todo a \uXXXX el texto viaja en ASCII puro y json.loads lo reconstruye
        # intacto.
        print(json.dumps({"language": info.language,
                          "duration": round(info.duration, 2),
                          "device": dispositivo,
                          "cuda_aviso": aviso_cuda,
                          "cuda_motivo": motivo,
                          "words": palabras}, ensure_ascii=True))
        return 0
    except Exception as exc:
        print(json.dumps({"error": f"{type(exc).__name__}: {exc}",
                          "cuda_aviso": aviso_cuda}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
