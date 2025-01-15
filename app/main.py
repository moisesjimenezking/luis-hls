import os
import threading
import time
import logging
from flask import Flask, jsonify
import gi
import re

gi.require_version("Gst", "1.0")
from gi.repository import Gst

logging.basicConfig(level=logging.DEBUG)

app = Flask(__name__)

# Directorios de configuración
VIDEOS_DIR = "./videos"
HLS_OUTPUT_DIR = "./hls_output"
NORMALIZE_DIR = "./videos/normalize"

# Configuración HLS
SEGMENT_DURATION = 5  # Duración de cada segmento HLS (en segundos)
PLAYLIST_LENGTH = 20  # Número de segmentos en la lista de reproducción

os.makedirs(NORMALIZE_DIR, exist_ok=True)
os.makedirs(HLS_OUTPUT_DIR, exist_ok=True)

video_queue = []  # Cola de videos normalizados

# Inicializar GStreamer
Gst.init(None)


def is_valid_mp4(file_path):
    """Verifica si un archivo MP4 tiene códec H.264."""
    return file_path.endswith(".mp4")  # Solo revisamos la extensión


def preprocess_video(input_path, output_path):
    """Verifica si el video es válido y lo copia sin recodificar."""
    if is_valid_mp4(input_path):
        os.system(f"cp '{input_path}' '{output_path}'")  # Copia sin modificar
        return True
    return False


def normalize_videos():
    """Hilo en segundo plano para normalizar videos automáticamente."""
    while True:
        raw_videos = [os.path.join(VIDEOS_DIR, f) for f in os.listdir(VIDEOS_DIR) if f.endswith(".mp4")]

        for video in raw_videos:
            filename = os.path.basename(video)
            filenameNormal = cadena_sin_espacios = re.sub(r'\s+', '', filename)
            normalized_path = os.path.join(NORMALIZE_DIR, filenameNormal)

            if not os.path.exists(normalized_path):
                logging.info(f"Normalizando video: {filenameNormal}")
                success = preprocess_video(video, normalized_path)
                if success:
                    video_queue.append(filenameNormal)
                    logging.info(f"✅ Video normalizado: {filenameNormal}")
                else:
                    logging.warning(f"⚠️ Error al normalizar {filenameNormal}")

        time.sleep(10)  # Verifica nuevos videos cada 10 segundos


def create_gstreamer_pipeline():
    """Genera la tubería de GStreamer para transmitir múltiples videos en HLS."""
    if not video_queue:
        logging.warning("⚠️ No hay videos en la cola para transmitir.")
        return None

    uris = " ".join([f"file://{os.path.abspath(os.path.join(NORMALIZE_DIR, f))}" for f in video_queue])
    logging.info(f"🎥 Transmitiendo videos: {uris}")

    pipeline_str = f"""
        uridecodebin uri={uris} name=decoder
        decoder. ! videoconvert ! x264enc bitrate=2000 ! mpegtsmux ! hlssink 
        playlist-location={HLS_OUTPUT_DIR}/playlist.m3u8 
        location={HLS_OUTPUT_DIR}/segment_%05d.ts 
        target-duration={SEGMENT_DURATION} max-files={PLAYLIST_LENGTH}
    """

    return Gst.parse_launch(pipeline_str)



def stream_videos():
    """Inicia el pipeline de GStreamer."""
    while True:
        if not video_queue:
            logging.info("⚠️ No hay videos listos para transmitir. Esperando...")
            time.sleep(10)
            continue

        pipeline = create_gstreamer_pipeline()
        if not pipeline:
            time.sleep(10)
            continue

        logging.info("🎥 Iniciando transmisión con GStreamer...")
        pipeline.set_state(Gst.State.PLAYING)

        bus = pipeline.get_bus()
        msg = bus.timed_pop_filtered(Gst.CLOCK_TIME_NONE, Gst.MessageType.ERROR | Gst.MessageType.EOS)

        if msg:
            logging.error(f"⚠️ Error en GStreamer: {msg}")

        pipeline.set_state(Gst.State.NULL)

        logging.info("🔄 Transmisión finalizada, reiniciando en 5 segundos...")
        time.sleep(5)


@app.route("/api/start", methods=["GET"])
def start_stream():
    """Inicia la transmisión en un hilo separado."""
    threading.Thread(target=normalize_videos, daemon=True).start()
    threading.Thread(target=stream_videos, daemon=True).start()
    return jsonify({"message": "Streaming iniciado."})


@app.route("/api/videos", methods=["GET"])
def list_videos():
    """Devuelve la lista de videos normalizados disponibles para la transmisión."""
    return jsonify({"normalized_videos": video_queue})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
