from flask import (
    Flask, 
    jsonify, 
    send_file, 
    Response,
    send_from_directory,
    request
)

from gi.repository import Gst, GLib
import os
import threading
import time
import logging
import re
import gi
import json
import subprocess

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
current_video_index = 0  # Índice del video en reproducción
all_segments = []  # Lista de todos los segmentos generados
PUBLIC_DIR = "./public"

AD_INTERVAL = 480  # Intervalo de inserción de anuncios (8 minutos)
AD_VIDEO = "ad.mp4"  # Ruta al video de publicidad
AD_SCTE35_MARKER = "#EXT-SCTE35:/DYNAMIC/PLACEMENT\n"  # Ejemplo de marcador SCTE-35


# Inicializar GStreamer
Gst.init(None)


def create_gstreamer_pipeline_for_ad(ad_path):
    """Crea un pipeline para reproducir el anuncio publicitario."""
    uri = f"file://{os.path.abspath(ad_path)}"
    segment_path = os.path.join(HLS_OUTPUT_DIR, SEGMENT_PATTERN)

    pipeline_str = f"""
        uridecodebin uri="{uri}" name=src \
        src. ! queue ! videoconvert ! videoscale ! videorate ! capsfilter caps=video/x-raw,framerate=30/1 ! x264enc bitrate=2000 ! queue ! mux. \
        src. ! queue ! audioconvert ! audioresample ! avenc_aac bitrate=128000 ! queue ! mux. \
        mpegtsmux name=mux ! hlssink \
        playlist-location={os.path.join(HLS_OUTPUT_DIR, VIDEO_PLAYLIST)} \
        location={segment_path} \
        target-duration={SEGMENT_DURATION} \
        max-files=0
    """
    return Gst.parse_launch(pipeline_str)


def insert_advertisement(pipeline, loop):
    """Inserta un video publicitario y agrega un marcador SCTE-35 en la lista."""
    global all_segments

    ad_path = os.path.join(PUBLIC_DIR, AD_VIDEO)
    if not os.path.exists(ad_path):
        logging.error("⚠️ No se encontró el video de publicidad.")
        return

    pipeline.set_state(Gst.State.NULL)
    ad_pipeline = create_gstreamer_pipeline_for_ad(ad_path)
    ad_pipeline.set_state(Gst.State.PLAYING)
    time.sleep(120)
    ad_pipeline.set_state(Gst.State.NULL)

    all_segments.append(AD_SCTE35_MARKER)
    regenerate_playlist()
    loop.quit()
    
def is_valid_mp4(file_path):
    """Verifica si un archivo MP4 es válido y está codificado en H.264 y AAC."""
    return file_path.endswith(".mp4")


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
    global current_video_index, all_segments
    if not video_queue:
        logging.warning("⚠️ No hay videos en la cola para transmitir.")
        return None

    filename = video_queue[current_video_index]
    uri = f"file://{os.path.abspath(os.path.join(NORMALIZE_DIR, filename))}"

    playlist_path = os.path.join(HLS_OUTPUT_DIR, VIDEO_PLAYLIST)
    segment_path = os.path.join(HLS_OUTPUT_DIR, SEGMENT_PATTERN)

    pipeline_str = f"""
        uridecodebin uri="{uri}" name=src \
        src. ! queue ! videoconvert ! videoscale ! videorate ! capsfilter caps=video/x-raw,framerate=30/1 ! x264enc bitrate=2000 ! queue ! mux. \
        src. ! queue ! audioconvert ! audioresample ! avenc_aac bitrate=128000 ! queue ! mux. \
        mpegtsmux name=mux ! hlssink \
        playlist-location={playlist_path} \
        location={segment_path} \
        target-duration={SEGMENT_DURATION} \
        max-files=0
    """

    logging.info(f"🎥 Pipeline generado:\n{pipeline_str}")
    return Gst.parse_launch(pipeline_str)


def bus_call(bus, message, loop):
    """Maneja los mensajes del bus de GStreamer y cambia al siguiente video en la cola."""
    global current_video_index, all_segments

    if message.type == Gst.MessageType.ERROR:
        err, debug = message.parse_error()
        logging.error(f"⚠️ Error en la transmisión: {err}, Debug: {debug}")
        loop.quit()
    elif message.type == Gst.MessageType.EOS:
        logging.info("🎬 Fin del video. Cargando el siguiente...")
        current_video_index = (current_video_index + 1) % len(video_queue)
        loop.quit()
    return True


def regenerate_playlist():
    """Regenera el playlist con todos los segmentos generados."""
    playlist_path = os.path.join(HLS_OUTPUT_DIR, VIDEO_PLAYLIST)
    with open(playlist_path, "w") as playlist_file:
        playlist_file.write("#EXTM3U\n")
        playlist_file.write("#EXT-X-VERSION:3\n")
        playlist_file.write("#EXT-X-MEDIA-SEQUENCE:0\n")
        playlist_file.write(f"#EXT-X-TARGETDURATION:{SEGMENT_DURATION}\n")
        for segment in all_segments:
            playlist_file.write(f"#EXTINF:{SEGMENT_DURATION},\n{segment}\n")


def stream_videos():
    """Inicia el pipeline de GStreamer y maneja errores."""
    global current_video_index, all_segments
    last_ad_time = time.time()

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
            while True:
                if time.time() - last_ad_time >= AD_INTERVAL:
                    insert_advertisement(pipeline, loop)
                    last_ad_time = time.time()
                if not loop.is_running():
                    break
                
                loop.run()
        except KeyboardInterrupt:
            logging.info("🛑 Transmisión detenida manualmente.")
            break
        finally:
            pipeline.set_state(Gst.State.NULL)

        # Agregar los nuevos segmentos a la lista global y regenerar la playlist
        new_segments = sorted(f for f in os.listdir(HLS_OUTPUT_DIR) if f.endswith(".ts"))
        all_segments.extend(new_segments)
        all_segments = list(dict.fromkeys(all_segments))  # Eliminar duplicados
        regenerate_playlist()

        logging.info("🔄 Reiniciando la transmisión desde el siguiente video...")


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
