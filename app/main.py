import os
import subprocess
import threading
import time
import logging
import json
import requests
import xml.etree.ElementTree as ET
import re
import shutil
from flask import Flask, Response, request, jsonify, send_from_directory, send_file
from flask_cors import CORS

logging.basicConfig(level=logging.DEBUG)

app = Flask(__name__)

# Directorios de configuración
VIDEOS_DIR = "./videos"
HLS_OUTPUT_DIR = "./hls_output"

# Configuración HLS
SEGMENT_DURATION = 10  # Duración de cada segmento HLS (en segundos)
PLAYLIST_LENGTH = 5   # Número de segmentos en la lista de reproducción

# Cola de reproducción
video_queue = []

# Ruta del archivo XML dentro de 'app/public/'
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
XML_FILE = os.path.join(BASE_DIR, "app", "public", "epg.xml")
JSON_FILE = os.path.join(BASE_DIR, "app", "public", "cuaimaTeam.json")
INSERTED_VIDEO_PATH = os.path.join(VIDEOS_DIR, "inserted_video.mp4")
OUTPUT_VIDEO_PATH = os.path.join(VIDEOS_DIR, "inserted_video_fixed.mp4")

PUBLIC_DIR = "./public"

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
        print(f"Error obteniendo el VAST tag: {e}")
        return None

def generate_concat_file(video_queue):
    """ Crea un archivo temporal con la lista de videos a concatenar """
    concat_file = os.path.join(VIDEOS_DIR, "concat_list.txt")
    
    try:
        with open(concat_file, "w") as f:
            for video in video_queue:
                video_path = os.path.join(VIDEOS_DIR, video)
                logging.debug(str(video_path))
                if os.path.exists(video_path):  # Verifica que el archivo existe
                    f.write(f"file '{video}'\n")  # Formato compatible con FFmpeg

        return concat_file
    except Exception as e:
        print(f"Error al generar concat_list.txt: {e}")
        return None

def stream_videos():
    # global video_queue
    # original_sequence = video_queue[:]  # Guardamos la secuencia original        
    while True:
        concat_file = generate_concat_file(video_queue)
        if not concat_file:
            print("No se pudo generar el archivo de concatenación. Esperando 10 segundos...")
            time.sleep(10)
        # if not video_queue:
        #     video_queue = original_sequence[:]

        # Genera un archivo con la lista de videos concatenados
        

        pipeline = [
            "ffmpeg", "-re", "-f", "concat", "-safe", "0", "-i", concat_file,
            "-c:v", "libx264", "-preset", "faster", "-tune", "zerolatency", "-b:v", "2000k",
            "-maxrate", "2000k", "-bufsize", "4000k",
            "-g", "48", "-sc_threshold", "0",
            "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2",  # Asegurar audio
            "-err_detect", "ignore_err", "-ignore_unknown",  # Omitir errores de archivos corruptos
            "-f", "hls", "-hls_time", str(SEGMENT_DURATION),
            "-hls_list_size", str(PLAYLIST_LENGTH),
            "-hls_flags", "independent_segments+delete_segments",
            "-hls_segment_filename", os.path.join(HLS_OUTPUT_DIR, "segment_%03d.ts"),
            os.path.join(HLS_OUTPUT_DIR, "cuaima-tv.m3u8")
        ]
        print("Iniciando transmisión con concatenación de videos...")
        try:
            process = subprocess.Popen(pipeline)
            process.wait()  # Espera a que FFmpeg termine antes de reiniciar la lista
        except Exception as e:
            print(f"Error en FFmpeg: {e}")
        finally:
            if process.poll() is None:
                process.terminate()  # Asegura que el proceso de FFmpeg se cierre correctamente

        print("Transmisión finalizada, reiniciando en 5 segundos...")
        time.sleep(5)
        
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

def download_video():
    """Descarga y convierte el video para que sea compatible con la transmisión."""
    while True:
        try:
            url = get_vast_ad_url()
            if url is None:
                return False

            # Descargar el video crudo
            response = requests.get(url, stream=True)
            response.raise_for_status()
            with open(INSERTED_VIDEO_PATH, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

            logging.debug(f"Video descargado: {INSERTED_VIDEO_PATH}")

            # Convertirlo a un formato compatible
            convert_video(INSERTED_VIDEO_PATH, OUTPUT_VIDEO_PATH)

            os.chmod(OUTPUT_VIDEO_PATH, 0o777)
            logging.debug("Video convertido y guardado en: inserted_video_fixed.mp4")

            time.sleep(450)
        except Exception as e:
            logging.debug(f"Error al descargar el video: {e}")
            time.sleep(20)

def convert_video(input_path, output_path):
    """Convierte el video descargado para que sea compatible con la transmisión."""
    try:
        ffmpeg_command = [
            "ffmpeg", "-y", "-i", input_path,
            "-c:v", "libx264", "-profile:v", "high", "-preset", "fast",
            "-b:v", "2000k", "-maxrate", "2000k", "-bufsize", "4000k",
            "-r", "29.97", "-g", "48", "-sc_threshold", "0",
            "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2",
            "-movflags", "+faststart",
            "-f", "mp4", output_path
        ]
        subprocess.run(ffmpeg_command, check=True)
        logging.debug(f"Conversión exitosa: {output_path}")
    except Exception as e:
        logging.debug(f"Error en la conversión con FFmpeg: {e}")
        
# @app.route("/api/start", methods=["GET"])
# def start_stream():
#     """Inicia la transmisión siguiendo la secuencia predefinida."""
#     global video_queue
#     # threading.Thread(target=download_video, daemon=True).start()
    
#     especial = 'inserted_video_fixed.mp4'
    
#     # Obtener todos los videos disponibles
#     secuencia = ['CC T1 EP 1.mp4', '1AV.MP4', 'CC T2 EP 1.mp4', '40BB', 'C PE 1.mp4', '1BINT', 'CC T1 EP 2.mp4', '2AV.MP4', 'CC T2 EP 2.mp4', '3BB', 'C PE 2.mp4', '32FIT.mp4', '2FIT.mp4', '17FIT.mp4', 'CC T1 EP 3.mp4', '3AV.MP4', 'CC T2 EP 3.mp4', '4BB', 'C PE 3.mp4', '3BINT', 'MC3', '3FIT.mp4', '33FIT.mp4', '18FIT.mp4', 'CC T1 EP 4.mp4', '4AV.MP4', 'CC T2 EP 4.mp4', '5BB', '4FIT.mp4', '54BINT', '19FIT.mp4', '4BINT', 'CC T1 EP 5.mp4', '5AV.MP4', 'CC T2 EP 5.mp4', '8BB', '5FIT.mp4', '55BINT', '35FIT.mp4', '28BB', 'CC T1 EP 6.mp4', '6AV.MP4', 'CC T2 EP 6.mp4', '9BB', '6FIT.mp4', '56BINT', '36FIT.mp4', '21FIT.mp4', '8BINT', 'CC T1 EP 7.mp4', '7AV.MP4', 'CC T2 EP 7.mp4', '12BB', '1OFEC', '22FIT.mp4', '37FIT.mp4', '57BINT', 'CC T1 EP 8.mp4', '8AV.MP4', 'CC T2 EP 8.mp4', '13BB', '8FIT.mp4', '38FIT.mp4', '58BINT', '23FIT.mp4', '10BINT', 'CC T1 EP 9.mp4', '1AV.MP4', 'CC T2 EP 9.mp4', '16BB', '39FIT.mp4', '59BINT', '9FIT.mp4', '24FIT.mp4', 'CC T1 EP 10.mp4', '2AV.MP4', 'CC T2 EP 10.mp4', '2BB', '10FIT.mp4', '60BINT', '25FIT.mp4', '20BB', 'CC T1 EP 11.mp4', '3AV.MP4', 'CC T2 EP 11.mp4', '22BB', '11FIT.mp4', '41FIT.mp4', '61BINT', '26FIT.mp4', '39BB', 'CC T1 EP 12.mp4', 'CC T2 EP 12.mp4', '4AV.MP4', '50BB', '12FIT.mp4', '62BINT', 'MC1', '27FIT.mp4', '23BB', 'CC T1 EP 13.mp4', '5AV.MP4', 'CC T2 EP 13.mp4', '24BB', '13FIT.mp4', '43FIT.mp4', '28FIT.mp4', '63BINT', 'MC2', '16BINT', 'CC T1 EP 14.mp4', '6AV.MP4', 'CC T2 EP 14.mp4', '28BB', '64BINT', '44FIT.mp4', '1OFEC', 'MC3', '17BINT', 'CC T1 EP 15 .mp4', '7AV.MP4', 'CC T2 EP 15.mp4', '30BB', '65BINT', '30FIT.mp4', '21BINT', 'CC T1 EP 16 .mp4', '8AV.MP4', 'CC T2 EP 15.mp4', '31BB', '16FIT.mp4', '51BINT', '1FIT.mp4', '22BINT', 'CC T1 EP 1.mp4', '1AV.MP4', 'CC T2 EP 1.mp4', '31FIT.mp4', '34BB', '17FIT.mp4', '52BINT', '2FIT.mp4', '32FIT.mp4', 'CC T1 EP 2.mp4', '2AV.MP4', 'CC T2 EP 2.mp4', '18FIT.mp4', '37BB', '3FIT.mp4', '53BINT', '33FIT.mp4', '24BINT', 'CC T1 EP 3.mp4', '3AV.MP4', 'CC T2 EP 3.mp4', '2BB', '4FIT.mp4', '54BINT', '34FIT.mp4', '19FIT.mp4', '45FIT.mp4', 'CC T1 EP 4.mp4', '4AV.MP4', 'CC T2 EP 4.mp4', '5FIT.mp4', '39BB', '35FIT.mp4', '55BINT', '20FIT.mp4', '14FIT.mp4', '44FIT.mp4', 'MC3', 'CC T1 EP 5.mp4', '5AV.MP4', 'CC T2 EP 5.mp4', '21FIT.mp4', '50BB', '1OFEC', 'MC1', '6FIT.mp4', '56BINT', '24BINT', '36FIT.mp4', '2OFEC', 'CC T1 EP 6.mp4', '6AV.MP4', 'CC T2 EP 6.mp4', '22FIT.mp4', '40BB', 'MC2', '2BINT', '7FIT.mp4', '37FIT.mp4', '30FIT.mp4', '29FIT.mp4', 'CC T1 EP 7.mp4', '7AV.MP4', 'CC T2 EP 7.mp4', '23FIT.mp4', 'MC3', '3BINT', '8FIT.mp4', '58BINT', '38FIT.mp4', 'CC T1 EP 8.mp4', '8AV.MP4', 'CC T2 EP 8.mp4', '24FIT.mp4', '4BB', '9FIT.mp4', '4BINT', '59BINT', 'CC T1 EP 9.mp4', '1AV.MP4', 'CC T2 EP 9.mp4', '60BINT', '39FIT.mp4', '10FIT.mp4', '40FIT.mp4', '5BINT', 'CC T1 EP 10.mp4', '2AV.MP4', 'CC T2 EP 10.mp4', '25FIT.mp4', '8BB', '26FIT.mp4', '8BINT', '11FIT.mp4', '61BINT', '41FIT.mp4', 'CC T1 EP 11.mp4', '3AV.MP4', 'CC T2 EP 11.mp4', '27FIT.mp4', '9BB', '9BINT', '62BINT', '42FIT.mp4', 'CC T1 EP 12.mp4', '4AV.MP4', 'CC T2 EP 12.mp4', '28FIT.mp4', '12BB', 'MC2', '43FIT.mp4', 'MC1', '13FIT.mp4', '63BINT', '12FIT.mp4', '1OFEC', '2OFEC', 'CC T1 EP 13.mp4', '6AV.MP4', 'CC T1 EP 14.mp4', 'CC T2 EP 13.mp4', '13BB', '5AV.MP4', 'CC T1 EP 15 .mp4', '7AV.MP4', 'CC T1 EP 16 .mp4', 'CC T2 EP 14.mp4', '16BB', '8AV.MP4']
    
#     # Eliminar la extensión .mp4 de cada elemento en la lista de secuencias
#     secuencia_sin_ext = [re.sub(r'\.mp4$', '', elem, flags=re.IGNORECASE) for elem in secuencia]
#     archivos_videos = sorted(os.listdir(VIDEOS_DIR))
#     video_queue = []
    
#     for elemento in secuencia_sin_ext:
#         # Buscar los segmentos pertenecientes al elemento en la carpeta de videos
#         segmentos = sorted(
#             [archivo for archivo in archivos_videos if re.match(rf'^{re.escape(elemento)}_\d+\.mp4$', archivo, re.IGNORECASE)]
#         )

#         if len(segmentos) > 0:
#             for x in range(len(segmentos)):
#                 searchSegment = f'{elemento}_{x}.mp4'
#                 if searchSegment in segmentos:
#                     video_queue.append(searchSegment)
#                     # video_queue.append(especial)
    
#     # video_queue = [video for video in secuencia if video in videos_disponibles]
#     threading.Thread(target=stream_videos, daemon=True).start()
    
#     if not video_queue:
#         return jsonify({"error": "No videos found matching the predefined sequence."}), 404

#     return jsonify({"message": "Streaming started following the predefined sequence.", "videos": video_queue})

@app.route("/api/start", methods=["GET"])
def start_stream():
    """Inicia la transmisión siguiendo la secuencia predefinida."""
    global video_queue
    
    # Obtener todos los videos disponibles
    secuencia = ['CC T1 EP 1.mp4', '1AV.MP4', 'CC T2 EP 1.mp4', '40BB', 'C PE 1.mp4', '1BINT', 'CC T1 EP 2.mp4', '2AV.MP4', 'CC T2 EP 2.mp4', '3BB', 'C PE 2.mp4', '32FIT.mp4', '2FIT.mp4', '17FIT.mp4', 'CC T1 EP 3.mp4', '3AV.MP4', 'CC T2 EP 3.mp4', '4BB', 'C PE 3.mp4', '3BINT', 'MC3', '3FIT.mp4', '33FIT.mp4', '18FIT.mp4', 'CC T1 EP 4.mp4', '4AV.MP4', 'CC T2 EP 4.mp4', '5BB', '4FIT.mp4', '54BINT', '19FIT.mp4', '4BINT', 'CC T1 EP 5.mp4', '5AV.MP4', 'CC T2 EP 5.mp4', '8BB', '5FIT.mp4', '55BINT', '35FIT.mp4', '28BB', 'CC T1 EP 6.mp4', '6AV.MP4', 'CC T2 EP 6.mp4', '9BB', '6FIT.mp4', '56BINT', '36FIT.mp4', '21FIT.mp4', '8BINT', 'CC T1 EP 7.mp4', '7AV.MP4', 'CC T2 EP 7.mp4', '12BB', '1OFEC', '22FIT.mp4', '37FIT.mp4', '57BINT', 'CC T1 EP 8.mp4', '8AV.MP4', 'CC T2 EP 8.mp4', '13BB', '8FIT.mp4', '38FIT.mp4', '58BINT', '23FIT.mp4', '10BINT', 'CC T1 EP 9.mp4', '1AV.MP4', 'CC T2 EP 9.mp4', '16BB', '39FIT.mp4', '59BINT', '9FIT.mp4', '24FIT.mp4', 'CC T1 EP 10.mp4', '2AV.MP4', 'CC T2 EP 10.mp4', '2BB', '10FIT.mp4', '60BINT', '25FIT.mp4', '20BB', 'CC T1 EP 11.mp4', '3AV.MP4', 'CC T2 EP 11.mp4', '22BB', '11FIT.mp4', '41FIT.mp4', '61BINT', '26FIT.mp4', '39BB', 'CC T1 EP 12.mp4', 'CC T2 EP 12.mp4', '4AV.MP4', '50BB', '12FIT.mp4', '62BINT', 'MC1', '27FIT.mp4', '23BB', 'CC T1 EP 13.mp4', '5AV.MP4', 'CC T2 EP 13.mp4', '24BB', '13FIT.mp4', '43FIT.mp4', '28FIT.mp4', '63BINT', 'MC2', '16BINT', 'CC T1 EP 14.mp4', '6AV.MP4', 'CC T2 EP 14.mp4', '28BB', '64BINT', '44FIT.mp4', '1OFEC', 'MC3', '17BINT', 'CC T1 EP 15 .mp4', '7AV.MP4', 'CC T2 EP 15.mp4', '30BB', '65BINT', '30FIT.mp4', '21BINT', 'CC T1 EP 16 .mp4', '8AV.MP4', 'CC T2 EP 15.mp4', '31BB', '16FIT.mp4', '51BINT', '1FIT.mp4', '22BINT', 'CC T1 EP 1.mp4', '1AV.MP4', 'CC T2 EP 1.mp4', '31FIT.mp4', '34BB', '17FIT.mp4', '52BINT', '2FIT.mp4', '32FIT.mp4', 'CC T1 EP 2.mp4', '2AV.MP4', 'CC T2 EP 2.mp4', '18FIT.mp4', '37BB', '3FIT.mp4', '53BINT', '33FIT.mp4', '24BINT', 'CC T1 EP 3.mp4', '3AV.MP4', 'CC T2 EP 3.mp4', '2BB', '4FIT.mp4', '54BINT', '34FIT.mp4', '19FIT.mp4', '45FIT.mp4', 'CC T1 EP 4.mp4', '4AV.MP4', 'CC T2 EP 4.mp4', '5FIT.mp4', '39BB', '35FIT.mp4', '55BINT', '20FIT.mp4', '14FIT.mp4', '44FIT.mp4', 'MC3', 'CC T1 EP 5.mp4', '5AV.MP4', 'CC T2 EP 5.mp4', '21FIT.mp4', '50BB', '1OFEC', 'MC1', '6FIT.mp4', '56BINT', '24BINT', '36FIT.mp4', '2OFEC', 'CC T1 EP 6.mp4', '6AV.MP4', 'CC T2 EP 6.mp4', '22FIT.mp4', '40BB', 'MC2', '2BINT', '7FIT.mp4', '37FIT.mp4', '30FIT.mp4', '29FIT.mp4', 'CC T1 EP 7.mp4', '7AV.MP4', 'CC T2 EP 7.mp4', '23FIT.mp4', 'MC3', '3BINT', '8FIT.mp4', '58BINT', '38FIT.mp4', 'CC T1 EP 8.mp4', '8AV.MP4', 'CC T2 EP 8.mp4', '24FIT.mp4', '4BB', '9FIT.mp4', '4BINT', '59BINT', 'CC T1 EP 9.mp4', '1AV.MP4', 'CC T2 EP 9.mp4', '60BINT', '39FIT.mp4', '10FIT.mp4', '40FIT.mp4', '5BINT', 'CC T1 EP 10.mp4', '2AV.MP4', 'CC T2 EP 10.mp4', '25FIT.mp4', '8BB', '26FIT.mp4', '8BINT', '11FIT.mp4', '61BINT', '41FIT.mp4', 'CC T1 EP 11.mp4', '3AV.MP4', 'CC T2 EP 11.mp4', '27FIT.mp4', '9BB', '9BINT', '62BINT', '42FIT.mp4', 'CC T1 EP 12.mp4', '4AV.MP4', 'CC T2 EP 12.mp4', '28FIT.mp4', '12BB', 'MC2', '43FIT.mp4', 'MC1', '13FIT.mp4', '63BINT', '12FIT.mp4', '1OFEC', '2OFEC', 'CC T1 EP 13.mp4', '6AV.MP4', 'CC T1 EP 14.mp4', 'CC T2 EP 13.mp4', '13BB', '5AV.MP4', 'CC T1 EP 15 .mp4', '7AV.MP4', 'CC T1 EP 16 .mp4', 'CC T2 EP 14.mp4', '16BB', '8AV.MP4']
    
    # Obtener los videos realmente disponibles en el directorio
    videos_disponibles = set(f for f in os.listdir(VIDEOS_DIR) if f.endswith(".mp4"))

    # Crear una lista ordenada solo con los archivos que existen en la carpeta
    video_queue = [video for video in secuencia if video in videos_disponibles]

    threading.Thread(target=stream_videos, daemon=True).start()
    
    if not video_queue:
        return jsonify({"error": "No videos found matching the predefined sequence."}), 404

    return jsonify({"message": "Streaming started following the predefined sequence.", "videos": video_queue})


@app.route("/api/clear", methods=["GET"])
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
        return jsonify({"message": f"Not exits dir {HLS_OUTPUT_DIR}"}),400
    
    return jsonify({"message": f"clear output directory {HLS_OUTPUT_DIR}"})

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
    # Iniciar el hilo para manejar la cola de reproducción
    # threading.Thread(target=stream_videos, daemon=True).start()
    app.run(host="0.0.0.0", port=5000)
