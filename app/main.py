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
SEGMENT_PATTERN = "segment_{index}_%05d.ts"

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
        os.system(f"cp '{input_path}' '{output_path}'")  # Copia sin modificar
        return True
    return False

def normalize_videos():
    """Normaliza todos los videos en el directorio y los agrega a la cola."""
    raw_videos = [os.path.join(VIDEOS_DIR, f) for f in os.listdir(VIDEOS_DIR) if f.endswith(".mp4")]

    for index, video in enumerate(raw_videos):
        filename = os.path.basename(video)
        filename_normal = re.sub(r'\s+', '', filename)
        normalized_path = os.path.join(NORMALIZE_DIR, filename_normal)

        if not os.path.exists(normalized_path):
            logging.info(f"Normalizando video: {filename_normal}")
            success = preprocess_video(video, normalized_path)
            if success:
                video_queue.append((index, filename_normal))
                logging.info(f"✅ Video normalizado: {filename_normal}")
            else:
                logging.warning(f"⚠️ Error al normalizar {filename_normal}")

def generate_hls_segments():
    """Genera segmentos HLS para todos los videos en la cola."""
    if not video_queue:
        logging.warning("⚠️ No hay videos en la cola para generar segmentos.")
        return

    playlist_path = os.path.join(HLS_OUTPUT_DIR, VIDEO_PLAYLIST)
    with open(playlist_path, "w") as playlist:
        playlist.write("#EXTM3U\n")
        playlist.write(f"#EXT-X-TARGETDURATION:{SEGMENT_DURATION}\n")
        playlist.write("#EXT-X-VERSION:3\n")
        playlist.write("#EXT-X-MEDIA-SEQUENCE:0\n")

        for index, filename in video_queue:
            video_path = os.path.join(NORMALIZE_DIR, filename)
            segment_pattern = os.path.join(HLS_OUTPUT_DIR, SEGMENT_PATTERN.format(index=index))

            pipeline_str = f"""
                filesrc location={video_path} ! decodebin name=dec \
                dec. ! queue ! videoconvert ! x264enc bitrate=1000 speed-preset=ultrafast ! mpegtsmux ! hlssink \
                playlist-location={HLS_OUTPUT_DIR}/temp_{index}.m3u8 \
                location={segment_pattern} \
                target-duration={SEGMENT_DURATION} \
                max-files=0
            """

            pipeline = Gst.parse_launch(pipeline_str)
            pipeline.set_state(Gst.State.PLAYING)

            # Esperar hasta que termine el procesamiento
            bus = pipeline.get_bus()
            msg = bus.timed_pop_filtered(Gst.CLOCK_TIME_NONE, Gst.MessageType.EOS | Gst.MessageType.ERROR)

            if msg.type == Gst.MessageType.ERROR:
                err, debug = msg.parse_error()
                logging.error(f"⚠️ Error procesando {filename}: {err}, Debug: {debug}")
            else:
                logging.info(f"✅ Segmentos generados para {filename}")

            pipeline.set_state(Gst.State.NULL)

            # Agregar los segmentos al playlist principal
            with open(f"{HLS_OUTPUT_DIR}/temp_{index}.m3u8", "r") as temp_playlist:
                for line in temp_playlist:
                    if not line.startswith("#EXT-X-TARGETDURATION") and not line.startswith("#EXT-X-VERSION"):
                        playlist.write(line)

    # Marcar el final de la lista de reproducción
    with open(playlist_path, "a") as playlist:
        playlist.write("#EXT-X-ENDLIST\n")

@app.route("/api/start", methods=["GET"])
def start_stream():
    """Procesa todos los videos y genera HLS."""
    normalize_videos()
    generate_hls_segments()
    return jsonify({"message": "Segmentos generados y HLS listo."})

@app.route("/api/videos", methods=["GET"])
def list_videos():
    """Devuelve la lista de videos normalizados disponibles."""
    return jsonify({"normalized_videos": [v[1] for v in video_queue]})

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
