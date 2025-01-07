import os
import subprocess
import threading
import time
import logging
import json
import shutil
import requests
import xml.etree.ElementTree as ET
import multiprocessing

from flask import Flask, Response, request, jsonify, send_from_directory, send_file
from flask_cors import CORS

logging.basicConfig(level=logging.DEBUG)

app = Flask(__name__)

# Directorios de configuración
VIDEOS_DIR = "./videos"
HLS_OUTPUT_DIR = "./hls_output"

# Configuración HLS
SEGMENT_DURATION = 480  # Duración de cada segmento HLS (en segundos)
PLAYLIST_LENGTH = 10   # Número de segmentos en la lista de reproducción

# Cola de reproducción
video_queue = []

# Ruta del archivo XML dentro de 'app/public/'
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
XML_FILE = os.path.join(BASE_DIR, "app", "public", "epg.xml")
JSON_FILE = os.path.join(BASE_DIR, "app", "public", "cuaimaTeam.json")

PUBLIC_DIR = "./public"

INSERTED_VIDEO_PATH = os.path.join(HLS_OUTPUT_DIR, "inserted_video.mp4")

def get_vast_ad_url():
    """Obtiene la URL del video del VAST tag."""
    try:
        # response = requests.get(vast_url, timeout=10)
        # response.raise_for_status()
        vast_xml = """
            <VAST version="3.0" xmlns:xs="http://www.w3.org/2001/XMLSchema">
                <Ad id="20001">
                    <InLine>
                        <AdSystem version="4.0">iabtechlab</AdSystem>
                        <AdTitle>iabtechlab video ad</AdTitle>
                        <Pricing model="cpm" currency="USD">
                            <![CDATA[ 25.00 ]]>
                        </Pricing>
                        <Error>http://example.com/error</Error>
                        <Impression id="Impression-ID">http://example.com/track/impression</Impression>
                        <Creatives>
                            <Creative id="5480" sequence="1">
                                <Linear>
                                    <Duration>00:00:16</Duration>
                                    <TrackingEvents>
                                        <Tracking event="start">http://example.com/tracking/start</Tracking>
                                        <Tracking event="firstQuartile">http://example.com/tracking/firstQuartile</Tracking>
                                        <Tracking event="midpoint">http://example.com/tracking/midpoint</Tracking>
                                        <Tracking event="thirdQuartile">http://example.com/tracking/thirdQuartile</Tracking>
                                        <Tracking event="complete">http://example.com/tracking/complete</Tracking>
                                        <Tracking event="progress" offset="00:00:10">http://example.com/tracking/progress-10</Tracking>
                                    </TrackingEvents>
                                    <VideoClicks>
                                        <ClickThrough id="blog">
                                            <![CDATA[https://iabtechlab.com]]>
                                        </ClickThrough>
                                    </VideoClicks>
                                    <MediaFiles>
                                        <MediaFile id="5241" delivery="progressive" type="video/mp4" bitrate="500" width="400" height="300" minBitrate="360" maxBitrate="1080" scalable="1" maintainAspectRatio="1" codec="0" apiFramework="VAST">
                                            <![CDATA[https://iab-publicfiles.s3.amazonaws.com/vast/VAST-4.0-Short-Intro.mp4]]>
                                        </MediaFile>
                                    </MediaFiles>


                                </Linear>
                            </Creative>
                        </Creatives>
                        <Extensions>
                            <Extension type="iab-Count">
                                <total_available>
                                    <![CDATA[ 2 ]]>
                                </total_available>
                            </Extension>
                        </Extensions>
                    </InLine>
                </Ad>
            </VAST>
        """
        
        # Parsear XML
        root = ET.fromstring(vast_xml)
        
        # Buscar la URL del archivo de video en el XML
        for media_file in root.findall(".//MediaFile"):
            video_url = media_file.text.strip()
            if video_url:
                return video_url

    except Exception as e:
        logging.debug(f"Error obteniendo el VAST tag: {e}")
        return None

def download_video(output_path):
    """Descarga un video desde una URL y lo guarda en output_path."""
    try:
        url = get_vast_ad_url()
        if url is None:
            return False
        
        response = requests.get(url, stream=True)
        response.raise_for_status()
        with open(output_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        logging.debug(f"Video descargado exitosamente: {output_path}")
        return True
    except Exception as e:
        logging.debug(f"Error al descargar el video: {e}")
        return False
      
def download_video_in_thread(output_path):
    download_thread = threading.Thread(target=download_video, args=(output_path,))
    download_thread.start()
      
def stream_videos():
    """Reproduce videos en segmentos de 480s, insertando un video específico entre cada porción."""
    global video_queue
    original_sequence = video_queue[:]  # Guardamos la secuencia original
    segmentNumber = 0

    while True:
        if not video_queue:  # Reiniciar la cola si se vacía
            video_queue = original_sequence[:]

        if video_queue:
            current_video = video_queue.pop(0)
            video_path = os.path.join(VIDEOS_DIR, current_video)

            if os.path.exists(video_path):
                logging.debug(f"Procesando: {current_video}")

                # Obtener la duración del video
                try:
                    result = subprocess.run(
                        [
                            "ffprobe", "-v", "error", "-select_streams", "v:0",
                            "-show_entries", "format=duration",
                            "-of", "default=noprint_wrappers=1:nokey=1", video_path
                        ],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
                    )
                    video_duration = float(result.stdout.strip()) if result.stdout else None
                    if video_duration is None:
                        logging.error(f"Duración de {video_path} no encontrada")
                        continue
                except Exception as e:
                    logging.error(f"Error obteniendo duración de {video_path}: {e}")
                    continue

                # Procesar el video en segmentos de 480s
                start_time = 0

                while start_time < video_duration:
                    download_video_in_thread(INSERTED_VIDEO_PATH)
                    logging.debug(f"Reproduciendo segmento desde {start_time} segundos de {current_video}")

                    segment_filename = os.path.join(HLS_OUTPUT_DIR, f"segment_{segmentNumber}.ts")

                    segment_pipeline = [
                        "ffmpeg", "-re", "-ss", str(start_time), "-i", video_path,
                        "-t", str(SEGMENT_DURATION),
                        "-c:v", "libx264", "-preset", "faster", "-tune", "zerolatency", "-b:v", "2000k",
                        "-maxrate", "2000k", "-bufsize", "4000k",
                        "-g", "48", "-sc_threshold", "0",
                        "-c:a", "aac", "-b:a", "128k",
                        "-f", "hls",
                        "-hls_time", str(SEGMENT_DURATION),
                        "-hls_list_size", "0",
                        "-hls_flags", "independent_segments+append_list",
                        "-hls_segment_filename", os.path.join(HLS_OUTPUT_DIR, "segment_%03d.ts"),
                        "-start_number", str(segmentNumber),
                        os.path.join(HLS_OUTPUT_DIR, "cuaima-tv.m3u8")
                    ]

                    try:
                        process = subprocess.Popen(segment_pipeline, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                        stdout, stderr = process.communicate()

                        if process.returncode != 0:
                            logging.error(f"FFmpeg error: {stderr}")
                        else:
                            logging.debug(stdout)
                    except Exception as e:
                        logging.error(f"Error al procesar segmento de {current_video}: {e}")
                        break

                    start_time += SEGMENT_DURATION
                    segmentNumber += 1

                    # Insertar propaganda después de cada segmento
                    if start_time % 480 == 0 or start_time >= video_duration:
                        if os.path.exists(INSERTED_VIDEO_PATH):
                            logging.debug(f"Insertando {INSERTED_VIDEO_PATH} después del segmento {segmentNumber}")

                            insert_pipeline = [
                                "ffmpeg", "-re", "-i", INSERTED_VIDEO_PATH,
                                "-c:v", "libx264", "-preset", "faster", "-tune", "zerolatency", "-b:v", "2000k",
                                "-maxrate", "2000k", "-bufsize", "4000k",
                                "-g", "48", "-sc_threshold", "0",
                                "-c:a", "aac", "-b:a", "128k",
                                "-f", "hls",
                                "-hls_time", str(SEGMENT_DURATION),
                                "-hls_list_size", "0",
                                "-hls_flags", "independent_segments+append_list",
                                "-hls_segment_filename", os.path.join(HLS_OUTPUT_DIR, f"segment_{segmentNumber}_ad.ts"),
                                "-start_number", str(segmentNumber),
                                os.path.join(HLS_OUTPUT_DIR, "cuaima-tv.m3u8")
                            ]

                            try:
                                process = subprocess.Popen(insert_pipeline, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                                stdout, stderr = process.communicate()

                                if process.returncode != 0:
                                    logging.error(f"FFmpeg error while inserting ad: {stderr}")
                                else:
                                    logging.debug(stdout)
                                segmentNumber += 1
                            except Exception as e:
                                logging.error(f"Error al procesar la propaganda {INSERTED_VIDEO_PATH}: {e}")

            else:
                logging.debug(f"Video no encontrado: {current_video}")
        else:
            logging.debug("Esperando videos...")
            time.sleep(1)  # Espera breve para evitar uso excesivo de CPU

def cleanHlsDir():
    # Limpiar la carpeta HLS_OUTPUT_DIR
    if os.path.exists(HLS_OUTPUT_DIR):
        for filename in os.listdir(HLS_OUTPUT_DIR):
            file_path = os.path.join(HLS_OUTPUT_DIR, filename)
            try:
                if os.path.isfile(file_path) or os.path.islink(file_path):
                    os.unlink(file_path)  # Elimina archivos y enlaces simbólicos
                elif os.path.isdir(file_path):
                    shutil.rmtree(file_path)  # Elimina carpetas completas
            except Exception as e:
                return jsonify({"error": f"Error cleaning HLS output directory: {e}"}), 500
    else:
        return False
    
    return True

@app.route("/api/start", methods=["GET"])
def start_stream():
    """Inicia la transmisión siguiendo la secuencia predefinida."""
    global video_queue
    
    # cleanHlsDir()
    # Obtener todos los videos disponibles
    secuencia = ['CC T1 EP 1.mp4', '1AV.MP4', 'CC T2 EP 1.mp4', '40BB', 'C PE 1.mp4', '1BINT', 'CC T1 EP 2.mp4', '2AV.MP4', 'CC T2 EP 2.mp4', '3BB', 'C PE 2.mp4', '32FIT.mp4', '2FIT.mp4', '17FIT.mp4', 'CC T1 EP 3.mp4', '3AV.MP4', 'CC T2 EP 3.mp4', '4BB', 'C PE 3.mp4', '3BINT', 'MC3', '3FIT.mp4', '33FIT.mp4', '18FIT.mp4', 'CC T1 EP 4.mp4', '4AV.MP4', 'CC T2 EP 4.mp4', '5BB', '4FIT.mp4', '54BINT', '19FIT.mp4', '4BINT', 'CC T1 EP 5.mp4', '5AV.MP4', 'CC T2 EP 5.mp4', '8BB', '5FIT.mp4', '55BINT', '35FIT.mp4', '28BB', 'CC T1 EP 6.mp4', '6AV.MP4', 'CC T2 EP 6.mp4', '9BB', '6FIT.mp4', '56BINT', '36FIT.mp4', '21FIT.mp4', '8BINT', 'CC T1 EP 7.mp4', '7AV.MP4', 'CC T2 EP 7.mp4', '12BB', '1OFEC', '22FIT.mp4', '37FIT.mp4', '57BINT', 'CC T1 EP 8.mp4', '8AV.MP4', 'CC T2 EP 8.mp4', '13BB', '8FIT.mp4', '38FIT.mp4', '58BINT', '23FIT.mp4', '10BINT', 'CC T1 EP 9.mp4', '1AV.MP4', 'CC T2 EP 9.mp4', '16BB', '39FIT.mp4', '59BINT', '9FIT.mp4', '24FIT.mp4', 'CC T1 EP 10.mp4', '2AV.MP4', 'CC T2 EP 10.mp4', '2BB', '10FIT.mp4', '60BINT', '25FIT.mp4', '20BB', 'CC T1 EP 11.mp4', '3AV.MP4', 'CC T2 EP 11.mp4', '22BB', '11FIT.mp4', '41FIT.mp4', '61BINT', '26FIT.mp4', '39BB', 'CC T1 EP 12.mp4', 'CC T2 EP 12.mp4', '4AV.MP4', '50BB', '12FIT.mp4', '62BINT', 'MC1', '27FIT.mp4', '23BB', 'CC T1 EP 13.mp4', '5AV.MP4', 'CC T2 EP 13.mp4', '24BB', '13FIT.mp4', '43FIT.mp4', '28FIT.mp4', '63BINT', 'MC2', '16BINT', 'CC T1 EP 14.mp4', '6AV.MP4', 'CC T2 EP 14.mp4', '28BB', '64BINT', '44FIT.mp4', '1OFEC', 'MC3', '17BINT', 'CC T1 EP 15 .mp4', '7AV.MP4', 'CC T2 EP 15.mp4', '30BB', '65BINT', '30FIT.mp4', '21BINT', 'CC T1 EP 16 .mp4', '8AV.MP4', 'CC T2 EP 15.mp4', '31BB', '16FIT.mp4', '51BINT', '1FIT.mp4', '22BINT', 'CC T1 EP 1.mp4', '1AV.MP4', 'CC T2 EP 1.mp4', '31FIT.mp4', '34BB', '17FIT.mp4', '52BINT', '2FIT.mp4', '32FIT.mp4', 'CC T1 EP 2.mp4', '2AV.MP4', 'CC T2 EP 2.mp4', '18FIT.mp4', '37BB', '3FIT.mp4', '53BINT', '33FIT.mp4', '24BINT', 'CC T1 EP 3.mp4', '3AV.MP4', 'CC T2 EP 3.mp4', '2BB', '4FIT.mp4', '54BINT', '34FIT.mp4', '19FIT.mp4', '45FIT.mp4', 'CC T1 EP 4.mp4', '4AV.MP4', 'CC T2 EP 4.mp4', '5FIT.mp4', '39BB', '35FIT.mp4', '55BINT', '20FIT.mp4', '14FIT.mp4', '44FIT.mp4', 'MC3', 'CC T1 EP 5.mp4', '5AV.MP4', 'CC T2 EP 5.mp4', '21FIT.mp4', '50BB', '1OFEC', 'MC1', '6FIT.mp4', '56BINT', '24BINT', '36FIT.mp4', '2OFEC', 'CC T1 EP 6.mp4', '6AV.MP4', 'CC T2 EP 6.mp4', '22FIT.mp4', '40BB', 'MC2', '2BINT', '7FIT.mp4', '37FIT.mp4', '30FIT.mp4', '29FIT.mp4', 'CC T1 EP 7.mp4', '7AV.MP4', 'CC T2 EP 7.mp4', '23FIT.mp4', 'MC3', '3BINT', '8FIT.mp4', '58BINT', '38FIT.mp4', 'CC T1 EP 8.mp4', '8AV.MP4', 'CC T2 EP 8.mp4', '24FIT.mp4', '4BB', '9FIT.mp4', '4BINT', '59BINT', 'CC T1 EP 9.mp4', '1AV.MP4', 'CC T2 EP 9.mp4', '60BINT', '39FIT.mp4', '10FIT.mp4', '40FIT.mp4', '5BINT', 'CC T1 EP 10.mp4', '2AV.MP4', 'CC T2 EP 10.mp4', '25FIT.mp4', '8BB', '26FIT.mp4', '8BINT', '11FIT.mp4', '61BINT', '41FIT.mp4', 'CC T1 EP 11.mp4', '3AV.MP4', 'CC T2 EP 11.mp4', '27FIT.mp4', '9BB', '9BINT', '62BINT', '42FIT.mp4', 'CC T1 EP 12.mp4', '4AV.MP4', 'CC T2 EP 12.mp4', '28FIT.mp4', '12BB', 'MC2', '43FIT.mp4', 'MC1', '13FIT.mp4', '63BINT', '12FIT.mp4', '1OFEC', '2OFEC', 'CC T1 EP 13.mp4', '6AV.MP4', 'CC T1 EP 14.mp4', 'CC T2 EP 13.mp4', '13BB', '5AV.MP4', 'CC T1 EP 15 .mp4', '7AV.MP4', 'CC T1 EP 16 .mp4', 'CC T2 EP 14.mp4', '16BB', '8AV.MP4']
    
    # Obtener los videos realmente disponibles en el directorio
    videos_disponibles = set(f for f in os.listdir(VIDEOS_DIR) if f.endswith(".mp4"))

    # Crear una lista ordenada solo con los archivos que existen en la carpeta
    video_queue = [video for video in secuencia if video in videos_disponibles]

    if not video_queue:
        return jsonify({"error": "No videos found matching the predefined sequence."}), 404

    return jsonify({"message": "Streaming started following the predefined sequence.", "videos": video_queue})


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

@app.route("/api/videos", methods=["GET"])
def list_videos():
    """Devuelve la lista de videos disponibles en el directorio."""
    videos = [f for f in os.listdir(VIDEOS_DIR) if f.endswith(".mp4")]
    return jsonify(videos)

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
    # Iniciar el proceso para manejar la cola de reproducción
    process = multiprocessing.Process(target=stream_videos)
    process.start()

    # Iniciar el servidor Flask
    app.run(host="0.0.0.0", port=5000)
