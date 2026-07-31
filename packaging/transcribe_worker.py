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

    Si Demucs está instalado, PyTorch sí las trae en su carpeta lib, así que
    basta con registrar ese directorio para que se encuentren. Sin esto, el
    modelo falla con «Library cublas64_12.dll is not found or cannot be loaded».
    """
    if sys.platform != "win32":
        return
    try:
        import torch
        lib = os.path.join(os.path.dirname(torch.__file__), "lib")
        if os.path.isdir(lib):
            os.add_dll_directory(lib)
    except Exception:
        pass          # sin torch no hay GPU: se usará la CPU


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

    try:
        _habilitar_cuda()
        # Se intenta la GPU y, si el runtime de CUDA no carga, se sigue en CPU
        # en vez de abortar: int8 en CPU es perfectamente utilizable, sólo más
        # lento, y es preferible a dejar al usuario sin transcripción.
        try:
            model = WhisperModel(modelo, device="cuda", compute_type="int8")
            dispositivo = "cuda"
        except Exception:
            model = WhisperModel(modelo, device="cpu", compute_type="int8")
            dispositivo = "cpu"

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

        # ensure_ascii=True a propósito: en Windows la salida estándar sale en
        # la página de códigos del sistema (cp1252), no en UTF-8, así que un
        # JSON con tildes y eñes llegaría corrompido al otro lado. Escapándolo
        # todo a \uXXXX el texto viaja en ASCII puro y json.loads lo reconstruye
        # intacto.
        print(json.dumps({"language": info.language,
                          "duration": round(info.duration, 2),
                          "device": dispositivo,
                          "words": palabras}, ensure_ascii=True))
        return 0
    except Exception as exc:
        print(json.dumps({"error": f"{type(exc).__name__}: {exc}"}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
