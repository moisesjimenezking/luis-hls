import os
import threading
import time
import logging
import re
from flask import Flask, jsonify
import gi
import subprocess

gi.require_version("Gst", "1.0")
from gi.repository import Gst, GLib

logging.basicConfig(level=logging.DEBUG)

app = Flask(__name__)

# Directorios de configuración
VIDEOS_DIR = "./videos"
HLS_OUTPUT_DIR = "./hls_output"
NORMALIZE_DIR = "./videos/normalize"

# Configuración HLS
SEGMENT_DURATION = 5  # Duración de cada segmento HLS (en segundos)
VIDEO_PLAYLIST = "cuaima-tv.m3u8"
SEGMENT_PATTERN = "segment_%05d.ts"

os.makedirs(NORMALIZE_DIR, exist_ok=True)
os.makedirs(HLS_OUTPUT_DIR, exist_ok=True)

video_queue = []  # Cola de videos normalizados
processed_videos = set()  # Videos ya agregados al HLS
current_video_index = 0  # Índice del video en reproducción

# Inicializar GStreamer
Gst.init(None)


def is_valid_mp4(file_path):
    """
    Verifica si un archivo MP4 es válido y está codificado en H.264 y AAC.
    """
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=codec_name",
                "-of", "default=noprint_wrappers=1:nokey=1",
                file_path,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        video_codec = result.stdout.strip()
        if video_codec != "h264":
            logging.warning(f"⚠️ El archivo {file_path} no está codificado en H.264 (códec: {video_codec})")
            return False

        result = subprocess.run(
            [
                "ffprobe",
                "-v", "error",
                "-select_streams", "a:0",
                "-show_entries", "stream=codec_name",
                "-of", "default=noprint_wrappers=1:nokey=1",
                file_path,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        audio_codec = result.stdout.strip()
        if audio_codec != "aac":
            logging.warning(f"⚠️ El archivo {file_path} no tiene audio codificado en AAC (códec: {audio_codec})")
            return False

        return True
    except Exception as e:
        logging.error(f"❌ Error verificando {file_path} con ffprobe: {e}")
        return False


def preprocess_video(input_path, output_path):
    """Verifica si el video es válido y lo copia sin recodificar."""
    if is_valid_mp4(input_path):
        os.system(f"cp '{input_path}' '{output_path}'")
        return True
    return False


def normalize_videos():
    while True:
        logging.debug("🔍 Buscando videos para normalizar...")
        raw_videos = [os.path.join(VIDEOS_DIR, f) for f in os.listdir(VIDEOS_DIR) if f.endswith(".mp4")]
        logging.debug(f"📂 Videos encontrados: {raw_videos}")

        for video in raw_videos:
            filename = os.path.basename(video)
            filename_normal = re.sub(r'\s+', '', filename)
            normalized_path = os.path.join(NORMALIZE_DIR, filename_normal)

            if filename_normal not in video_queue and filename_normal not in processed_videos:
                logging.info(f"⚙️ Normalizando video: {filename_normal}")
                success = preprocess_video(video, normalized_path)
                if success:
                    video_queue.append(filename_normal)
                    logging.info(f"✅ Video normalizado y agregado a la cola: {filename_normal}")
                else:
                    logging.warning(f"❌ Falló la normalización de {filename_normal}")

        time.sleep(10)



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
        src. ! queue ! videoconvert ! videoscale ! videorate ! capsfilter caps=video/x-raw,framerate=30/1 ! x264enc bitrate=2000 ! queue ! mux. \
        src. ! queue ! audioconvert ! audioresample ! avenc_aac bitrate=128000 ! queue ! mux. \
        mpegtsmux name=mux ! hlssink \
        playlist-location={HLS_OUTPUT_DIR}/{VIDEO_PLAYLIST} \
        location={HLS_OUTPUT_DIR}/{SEGMENT_PATTERN} \
        target-duration={SEGMENT_DURATION} \
        max-files=0
    """

    logging.info(f"🎥 Pipeline generado:\n{pipeline_str}")
    return Gst.parse_launch(pipeline_str)



def bus_call(bus, message, loop):
    """Maneja los mensajes del bus de GStreamer y reinicia desde el segmento 0 si es necesario."""
    global current_video_index
    if message.type == Gst.MessageType.ERROR:
        err, debug = message.parse_error()
        logging.error(f"⚠️ Error en la transmisión: {err}, Debug: {debug}")
        loop.quit()
    elif message.type == Gst.MessageType.EOS:
        logging.info("🎬 Fin del video. Marcando como procesado.")
        processed_videos.add(video_queue[current_video_index])  # Marcar como procesado

        # Avanzar al siguiente video o reiniciar desde el primero
        if current_video_index + 1 < len(video_queue):
            current_video_index += 1  # Siguiente video
        else:
            logging.info("🔄 Todos los videos han sido reproducidos. Reiniciando desde el primer segmento.")
            current_video_index = 0  # Reiniciar desde el primer video

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
            logging.info("🔄 Reiniciando transmisión en 5 segundos...")
            time.sleep(5)


@app.route("/api/start", methods=["GET"])
def start_stream():
    """Inicia la transmisión en un hilo separado."""
    logging.info("🚀 Iniciando normalización de videos...")
    normalize_thread = threading.Thread(target=normalize_videos, daemon=True)
    normalize_thread.start()

    logging.info("📡 Iniciando transmisión de videos...")
    stream_thread = threading.Thread(target=stream_videos, daemon=True)
    stream_thread.start()

    return jsonify({"message": "Streaming iniciado."})


@app.route("/api/videos", methods=["GET"])
def list_videos():
    """Devuelve la lista de videos normalizados disponibles para la transmisión."""
    return jsonify({"normalized_videos": video_queue})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
