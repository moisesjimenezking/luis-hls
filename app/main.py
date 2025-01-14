import os
import subprocess
import threading
import time
import logging
from flask import Flask, jsonify

logging.basicConfig(level=logging.DEBUG)

app = Flask(__name__)

# Directorios de configuración
VIDEOS_DIR = "./videos"
HLS_OUTPUT_DIR = "./hls_output"
NORMALIZE_DIR = "./videos/normalize"

# Configuración HLS
SEGMENT_DURATION = 10  # Duración de cada segmento HLS (en segundos)
PLAYLIST_LENGTH = 5  # Número de segmentos en la lista de reproducción

os.makedirs(NORMALIZE_DIR, exist_ok=True)
os.makedirs(HLS_OUTPUT_DIR, exist_ok=True)

video_queue = []  # Cola de videos normalizados

def preprocess_video(input_path, output_path):
    """Convierte un video a formato compatible para HLS."""
    pipeline = [
        "ffmpeg", "-y", "-fflags", "+genpts", "-i", input_path,  # <--- Añadido aquí
        "-c:v", "libx264", "-preset", "fast", "-tune", "zerolatency",
        "-b:v", "2000k", "-maxrate", "2000k", "-bufsize", "4000k",
        "-g", "48", "-sc_threshold", "0",
        "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2",
        "-movflags", "+faststart",
        output_path
    ]
    result = subprocess.run(pipeline, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return result.returncode == 0 # Retorna True si la conversión fue exitosa

def normalize_videos():
    """Hilo en segundo plano para normalizar videos automáticamente."""
    while True:
        raw_videos = [os.path.join(VIDEOS_DIR, f) for f in os.listdir(VIDEOS_DIR) if f.endswith(".mp4")]
        
        for video in raw_videos:
            filename = os.path.basename(video)
            normalized_path = os.path.join(NORMALIZE_DIR, filename)

            if not os.path.exists(normalized_path):
                logging.info(f"Normalizando video: {filename}")
                success = preprocess_video(video, normalized_path)
                if success:
                    video_queue.append(filename)
                    logging.info(f"✅ Video normalizado: {filename}")
                else:
                    logging.warning(f"⚠️ Error al normalizar {filename}")
        
        time.sleep(10)  # Verifica nuevos videos cada 10 segundos

def generate_concat_file():
    """Genera un archivo de concatenación con los videos normalizados."""
    concat_path = os.path.join(NORMALIZE_DIR, "concat_list.txt")
    
    if not video_queue:
        return None  # No hay videos disponibles

    with open(concat_path, "w") as f:
        for video in video_queue:
            f.write(f"file '{video}'\n")
    
    return concat_path

def stream_videos():
    """Ciclo de transmisión de videos normalizados."""
    while True:
        if not video_queue:
            logging.info("⚠️ No hay videos listos para transmitir. Esperando...")
            time.sleep(10)
            continue

        concat_file = generate_concat_file()
        if not concat_file:
            logging.warning("⚠️ No se pudo generar el archivo de concatenación.")
            time.sleep(10)
            continue

        pipeline = [
            "ffmpeg", "-re", "-fflags", "+genpts",  # <--- Añadido aquí
            "-f", "concat", "-safe", "0", "-i", concat_file,
            "-c:v", "libx264", "-preset", "faster", "-tune", "zerolatency",
            "-b:v", "2000k", "-maxrate", "2000k", "-bufsize", "4000k",
            "-g", "48", "-sc_threshold", "0",
            "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2",
            "-err_detect", "ignore_err", "-ignore_unknown",
            "-f", "hls", "-hls_time", str(SEGMENT_DURATION),
            "-hls_list_size", str(PLAYLIST_LENGTH),
            "-hls_flags", "independent_segments+delete_segments",
            "-hls_segment_filename", os.path.join(HLS_OUTPUT_DIR, "segment_%03d.ts"),
            os.path.join(HLS_OUTPUT_DIR, "cuaima-tv.m3u8")
        ]

        logging.info("🎥 Iniciando transmisión con videos normalizados...")
        try:
            process = subprocess.Popen(pipeline)
            process.wait()
        except Exception as e:
            logging.error(f"⚠️ Error en FFmpeg: {e}")
        finally:
            if process.poll() is None:
                process.terminate()

        logging.info("🔄 Transmisión finalizada, reiniciando en 5 segundos...")
        time.sleep(5)

@app.route("/api/start", methods=["GET"])
def start_stream():
    threading.Thread(target=normalize_videos, daemon=True).start()
    """Inicia la transmisión en un hilo separado."""
    threading.Thread(target=stream_videos, daemon=True).start()
    return jsonify({"message": "Streaming iniciado."})

@app.route("/api/videos", methods=["GET"])
def list_videos():
    """Devuelve la lista de videos normalizados disponibles para la transmisión."""
    return jsonify({"normalized_videos": video_queue})

# Iniciar el hilo de normalización en segundo plano


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
