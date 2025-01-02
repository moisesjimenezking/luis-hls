import os
import subprocess
import threading
import time
from flask import Flask, jsonify

app = Flask(__name__)

# Directorios de configuración
VIDEOS_DIR = "./app/videos"
HLS_OUTPUT_DIR = "./app/hls_output"

# Configuración HLS
SEGMENT_DURATION = 4  # Duración de cada segmento HLS (en segundos)
PLAYLIST_LENGTH = 10   # Número de segmentos en la lista de reproducción

# Cola de reproducción
video_queue = []

def stream_videos():
    """Función para reproducir videos en cola secuencialmente."""
    while True:
        if video_queue:
            current_video = video_queue.pop(0)
            video_path = os.path.join(VIDEOS_DIR, current_video)

            if os.path.exists(video_path):
                # Configuración del pipeline FFmpeg
                pipeline = [
                    "ffmpeg", "-re", "-i", video_path,
                    "-c:v", "libx264", "-preset", "faster", "-tune", "zerolatency", "-b:v", "2000k",
                    "-maxrate", "2000k", "-bufsize", "4000k",
                    "-g", "48",  # GOP size para mejorar la latencia
                    "-sc_threshold", "0",  # Desactiva el threshold de corte de escenas
                    "-c:a", "aac", "-b:a", "128k",
                    "-f", "hls", "-hls_time", str(SEGMENT_DURATION),
                    "-hls_list_size", str(PLAYLIST_LENGTH),
                    "-hls_flags", "independent_segments+delete_segments",
                    "-hls_segment_filename", os.path.join(HLS_OUTPUT_DIR, "segment_%03d.ts"),
                    os.path.join(HLS_OUTPUT_DIR, "playlist.m3u8")
                ]

                # Ejecutar FFmpeg
                process = subprocess.Popen(pipeline)
                process.wait()  # Esperar a que FFmpeg termine antes de pasar al siguiente video
            else:
                print(f"Video {current_video} no encontrado.")
        else:
            time.sleep(1)  # Esperar un segundo antes de verificar la cola nuevamente

@app.route("/start", methods=["GET"])
def start_stream():
    """Inicia la transmisión al llenar la cola con todos los videos disponibles."""
    global video_queue

    # Obtener todos los videos disponibles
    videos = [f for f in os.listdir(VIDEOS_DIR) if f.endswith(".mp4")]
    if not videos:
        return jsonify({"error": "No videos found in the directory."}), 404

    # Agregar los videos a la cola
    video_queue.extend(videos)
    return jsonify({"message": "Streaming started for all videos in the queue."})

@app.route("/videos", methods=["GET"])
def list_videos():
    """Devuelve la lista de videos disponibles en el directorio."""
    videos = [f for f in os.listdir(VIDEOS_DIR) if f.endswith(".mp4")]
    return jsonify(videos)

if __name__ == "__main__":
    # Iniciar el hilo para manejar la cola de reproducción
    threading.Thread(target=stream_videos, daemon=True).start()
    app.run(host="0.0.0.0", port=5000)
