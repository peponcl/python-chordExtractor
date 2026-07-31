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
import sys


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
        # int8 sobre CPU: es lo que hace esto viable sin GPU.
        model = WhisperModel(modelo, device="auto", compute_type="int8")
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
                          "words": palabras}, ensure_ascii=True))
        return 0
    except Exception as exc:
        print(json.dumps({"error": f"{type(exc).__name__}: {exc}"}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
