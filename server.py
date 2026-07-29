"""
server.py
---------
API HTTP mínima sobre chord_extractor. Arquitectura server-side:
el cliente (app Android, web, lo que sea) sube el audio y recibe JSON
con los acordes. El trabajo pesado (madmom + modelos) vive aquí.

Sirve además la interfaz web de web/index.html en la raíz: arrancas el server,
abres http://localhost:8000/ y arrastras el MP3.

Arrancar:
    uvicorn server:app --host 0.0.0.0 --port 8000

Probar:
    curl -F "file=@cancion.mp3" "http://localhost:8000/extract?method=deepchroma"

Notas de producción (para tu despliegue en AWS):
  - Los modelos de madmom se cargan por primera vez en cada proceso worker;
    para una API real conviene cargar los processors una sola vez al arrancar
    (aquí se hace de forma perezosa dentro de extract()).
  - El análisis es CPU-bound y tarda segundos; para tráfico real, en vez de
    procesar en el request, encola el trabajo (SQS + worker / Celery) y expón
    un endpoint de estado. Este server es el prototipo síncrono.
  - Limita el tamaño de subida y valida el tipo de archivo antes de procesar.
"""
from __future__ import annotations

import os
import tempfile

from fastapi import FastAPI, File, UploadFile, Query, HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from chord_extractor import extract

app = FastAPI(title="Chord Extractor API", version="0.1.0")

ALLOWED_EXT = {".mp3", ".wav", ".flac", ".ogg", ".opus", ".m4a", ".aac", ".wma"}
MAX_BYTES = 30 * 1024 * 1024  # 30 MB
WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/extract")
async def extract_endpoint(
    file: UploadFile = File(...),
    method: str = Query("deepchroma", pattern="^(deepchroma|cnn)$"),
    key: bool = Query(True),
    tempo: bool = Query(True),
    separate: bool = Query(False),
    device: str = Query("auto", pattern="^(auto|cuda|cpu)$"),
):
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(400, f"Extensión no soportada: {ext}")

    data = await file.read()
    if len(data) > MAX_BYTES:
        raise HTTPException(413, "Archivo demasiado grande")

    # madmom lee desde disco, así que escribimos un temporal
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
    try:
        tmp.write(data)
        tmp.close()
        result = extract(tmp.name, method=method, with_key=key, with_tempo=tempo,
                         separate=separate, device=device)
        payload = result.to_dict()
        payload["source"] = file.filename  # no filtrar la ruta temporal
        return JSONResponse(payload)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Error procesando audio: {e}")
    finally:
        os.unlink(tmp.name)


# La interfaz web se monta al final para que no eclipse a /extract ni /health.
app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
