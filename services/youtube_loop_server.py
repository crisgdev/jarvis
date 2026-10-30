"""Servidor Flask básico para controlar YouTube desde JARVIS.

Expone un endpoint HTTP que una extensión de Chrome (Manifest v3) consulta
para ejecutar document.querySelector('video').loop = true; en la pestaña
activa de YouTube.

Endpoints:
  POST /loop   - Activa el bucle en el video de YouTube actual.
                 Cuerpo JSON opcional: {"video_name": "..."} (informativo).
  GET  /status - Devuelve si el servidor está activo.

Ejecutar:  python services/youtube_loop_server.py
           (o desde la raíz: python -m services.youtube_loop_server)
"""

import logging
import os
import sys

from flask import Flask, request, jsonify

logger = logging.getLogger("jarvis.youtube_loop_server")

app = Flask(__name__)

# Último comando recibido (para debug / estado)
_LAST_COMMAND = {"video_name": None, "ts": None}


@app.route("/loop", methods=["POST"])
def loop():
    global _LAST_COMMAND
    import time as _t

    data = request.get_json(silent=True) or {}
    video_name = data.get("video_name")
    _LAST_COMMAND = {"video_name": video_name, "ts": _t.time()}

    logger.info("Solicitud de bucle recibida: video_name=%s", video_name)
    return jsonify({"status": "ok", "message": "Bucle activado en YouTube"})


@app.route("/status", methods=["GET"])
def status():
    return jsonify({"status": "ok", "last_command": _LAST_COMMAND})


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    host = os.environ.get("YOUTUBE_LOOP_HOST", "127.0.0.1")
    port = int(os.environ.get("YOUTUBE_LOOP_PORT", "5050"))
    logger.info("Iniciando servidor YouTube Loop en %s:%s", host, port)
    app.run(host=host, port=port, debug=False)


if __name__ == "__main__":
    main()
