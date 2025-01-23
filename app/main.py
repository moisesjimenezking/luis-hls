import os
import threading
import time
import logging
import re
from flask import Flask, jsonify
import gi

gi.require_version("Gst", "1.0")
from gi.repository import Gst, GLib

logging.basicConfig(level=logging.DEBUG)

app = Flask(__name__)

# Directorios de configuración
VIDEOS_DIR = "./videos"
HLS_OUTPUT_DIR = "./hls_output"
NORMALIZE_DIR = "./videos/normalize"

# Configuración HLS
SEGMENT_DURATION = 10  # Duración de cada segmento HLS (en segundos)
VIDEO_PLAYLIST = "cuaima-tv.m3u8"
SEGMENT_PATTERN = "segment_%05d.ts"

os.makedirs(NORMALIZE_DIR, exist_ok=True)
os.makedirs(HLS_OUTPUT_DIR, exist_ok=True)

video_queue = []  # Cola de videos normalizados
current_video_index = 0  # Índice del video en reproducción

# Inicializar GStreamer
Gst.init(None)

def is_valid_mp4(file_path):
    """Verifica si un archivo MP4 tiene códec H.264."""
    if not file_path.endswith(".mp4"):
        return False
    # Verificar con ffprobe o gst-discoverer si es necesario
    return True

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
            filename_normal = re.sub(r'\s+', '', filename)
            normalized_path = os.path.join(NORMALIZE_DIR, filename_normal)

            if not os.path.exists(normalized_path):
                logging.info(f"Normalizando video: {filename_normal}")
                success = preprocess_video(video, normalized_path)
                if success:
                    video_queue.append(filename_normal)
                    logging.info(f"✅ Video normalizado: {filename_normal}")
                else:
                    logging.warning(f"⚠️ Error al normalizar {filename_normal}")

        time.sleep(10)  # Verifica nuevos videos cada 10 segundos

def create_gstreamer_pipeline():
    """Genera la tubería de GStreamer para transmitir en HLS."""
    global current_video_index
    if not video_queue:
        logging.warning("⚠️ No hay videos en la cola para transmitir.")
        return None

    filename = video_queue[current_video_index]
    uri = f"file://{os.path.abspath(os.path.join(NORMALIZE_DIR, filename))}"

    pipeline_str = f"""
        uridecodebin uri="{uri}" name=src \
        src. ! queue max-size-bytes=10485760 max-size-buffers=0 max-size-time=0 ! videoconvert ! videoscale ! videorate ! capsfilter caps=video/x-raw,framerate=30/1 ! x264enc speed-preset=ultrafast bitrate=1000 ! queue ! mux. \
        src. ! queue max-size-bytes=10485760 max-size-buffers=0 max-size-time=0 ! audioconvert ! audioresample ! avenc_aac bitrate=128000 ! queue ! mux. \
        mpegtsmux name=mux ! hlssink \
        playlist-location={HLS_OUTPUT_DIR}/{VIDEO_PLAYLIST} \
        location={HLS_OUTPUT_DIR}/{SEGMENT_PATTERN} \
        target-duration={SEGMENT_DURATION} \
        max-files=5 append=true
    """

    logging.info(f"🎥 Pipeline generado:\n{pipeline_str}")
    return Gst.parse_launch(pipeline_str)

def bus_call(bus, message, loop):
    """Maneja los mensajes del bus de GStreamer y cambia al siguiente video en la cola."""
    global current_video_index
    if message.type == Gst.MessageType.ERROR:
        err, debug = message.parse_error()
        logging.error(f"⚠️ Error en la transmisión: {err}, Debug: {debug}")
        current_video_index = (current_video_index + 1) % len(video_queue)
        pipeline.set_state(Gst.State.NULL)
        loop.quit()
    elif message.type == Gst.MessageType.WARNING:
        err, debug = message.parse_warning()
        logging.warning(f"⚠️ Advertencia en la transmisión: {err}, Debug: {debug}")
    elif message.type == Gst.MessageType.EOS:
        logging.info("🎬 Fin del video. Cargando el siguiente...")
        current_video_index = (current_video_index + 1) % len(video_queue)
        pipeline.set_state(Gst.State.NULL)
        loop.quit()
    return True

def stream_videos():
    """Inicia el pipeline de GStreamer y maneja errores."""
    global current_video_index
    while True:
        if not video_queue:
            logging.info("⚠️ No hay videos listos para transmitir. Esperando...")
            time.sleep(10)
            continue

        pipeline = create_gstreamer_pipeline()
        if not pipeline:
            time.sleep(10)
            continue

        loop = GLib.MainLoop()
        bus = pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message", bus_call, loop)

        pipeline.set_state(Gst.State.PLAYING)
        try:
            loop.run()
        except KeyboardInterrupt:
            logging.info("🛑 Transmisión detenida manualmente.")
            break
        finally:
            pipeline.set_state(Gst.State.NULL)
            logging.info("🔄 Cargando el siguiente video en 5 segundos...")
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
