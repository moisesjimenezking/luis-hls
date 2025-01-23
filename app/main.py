import os
import threading
import time
import logging
import re
from flask import Flask, jsonify, Response, send_file, request, send_from_directory
import gi
import subprocess
import json

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

PUBLIC_DIR='./public'
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
    """Hilo en segundo plano para normalizar videos automáticamente."""
    while True:
        raw_videos = [os.path.join(VIDEOS_DIR, f) for f in os.listdir(VIDEOS_DIR) if f.endswith(".mp4")]

        for video in raw_videos:
            filename = os.path.basename(video)
            filename_normal = re.sub(r'\s+', '', filename)
            normalized_path = os.path.join(NORMALIZE_DIR, filename_normal)

            if filename_normal not in video_queue and filename_normal not in processed_videos:
                logging.info(f"Normalizando video: {filename_normal}")
                success = preprocess_video(video, normalized_path)
                if success:
                    video_queue.append(filename_normal)
                    logging.info(f"✅ Video normalizado: {filename_normal}")
                else:
                    logging.warning(f"⚠️ Error al normalizar {filename_normal}")

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
        max-files=0 append=true
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
    threading.Thread(target=normalize_videos, daemon=True).start()
    threading.Thread(target=stream_videos, daemon=True).start()
    return jsonify({"message": "Streaming iniciado."})

@app.route("/api/videos", methods=["GET"])
def list_videos():
    """Devuelve la lista de videos normalizados disponibles para la transmisión."""
    return jsonify({"normalized_videos": video_queue})

@app.route("/api/view_epg")
def view_epg():
    file_xlm = os.path.join(PUBLIC_DIR, "epg.xml")
    """Devuelve el XML para verlo en el navegador."""
    with open(file_xlm, "r", encoding="utf-8") as f:
        xml_content = f.read()
    return Response(xml_content, mimetype="application/xml")

@app.route("/api/download_epg")
def download_epg():
    file_xlm = os.path.join(PUBLIC_DIR, "epg.xml")
    """Permite descargar el archivo XML."""
    return send_file(file_xlm, as_attachment=True)

@app.route("/api/preview", methods=["GET"])
def preview_video():
    """Devuelve los primeros 30 segundos del video especificado."""
    video_name = request.args.get("name")
    
    if not video_name:
        return jsonify({"error": "Debe proporcionar el nombre del video."}), 400

    video_path = os.path.join(VIDEOS_DIR, video_name)

    if not os.path.exists(video_path):
        return jsonify({"error": "El archivo no existe."}), 404

    # Comando FFmpeg para extraer los primeros 30 segundos del video
    try:
        preview_path = os.path.join(HLS_OUTPUT_DIR, f"preview_{video_name}")

        if not os.path.exists(preview_path):  # Evita regenerar la vista previa si ya existe
            cmd = [
                "ffmpeg", "-i", video_path, "-t", "30", "-c:v", "libx264",
                "-preset", "ultrafast", "-c:a", "aac", "-b:a", "128k", preview_path, "-y"
            ]
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except:
        return jsonify({"error": "El archivo no puede ser formateado."}), 404 
    
    return send_from_directory(HLS_OUTPUT_DIR, f"preview_{video_name}")


@app.route("/api/json", methods=["GET"])
def view_json():
    json_file = os.path.join(PUBLIC_DIR, "cuaimaTeam.json")
    """Devuelve el contenido del JSON en la respuesta (visualización en navegador)."""
    if not os.path.exists(json_file):
        return jsonify({"error": "El archivo JSON no existe"}), 404

    with open(json_file, "r", encoding="utf-8") as f:
        json_content = json.load(f)  # 🔹 Convertir a diccionario
        
    result = dict()

    for secuencia, lista_videos in json_content.items():  # 🔹 Recorrer correctamente

        if isinstance(lista_videos, list):  # 🔹 Verifica que sea una lista
            result[secuencia] = []  # Crear una nueva lista en el resultado

            for obj in lista_videos:
                if "file" in obj:  # 🔹 Verifica que "file" exista en el objeto
                    if ".MP4" not in obj["file"].upper():
                        obj["file"] = f"{obj['file']}.MP4"

                    obj["file"] = f"https://cuaimateam.online/api/preview?name={obj['file'].replace('MP4', 'mp4')}"

                result[secuencia].append(obj)
                
        
    return jsonify({"data": result})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
