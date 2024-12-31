import os
import subprocess
import logging
import time

logging.basicConfig(level=logging.DEBUG)

VIDEOS_DIR = "/app/videos"
HLS_OUTPUT_DIR = "/app/hls_output"

# Configuración de segmentos (ajustables)
SEGMENT_DURATION = 10
PLAYLIST_LENGTH = 5  # Mantener los últimos 5 segmentos en memoria


def process_video(video_path):
    """Procesa un video con GStreamer para generar HLS sin acumulación de fragmentos."""
    segment_base_name = "segment_%05d.ts"
    playlist_path = os.path.join(HLS_OUTPUT_DIR, "cuaima_tv.m3u8")

    # Configuración del pipeline
    pipeline = (
        f"gst-launch-1.0 filesrc location={video_path} ! decodebin name=dec "
        f"dec. ! queue ! audioconvert ! audioresample ! avenc_aac ! queue ! mux. "
        f"dec. ! queue ! videoconvert ! x264enc bitrate=5000 speed-preset=veryfast tune=zerolatency ! mux. "
        f"mpegtsmux name=mux ! hlssink location={HLS_OUTPUT_DIR}/{segment_base_name} "
        f"playlist-location={playlist_path} "
        f"target-duration={SEGMENT_DURATION} max-files={PLAYLIST_LENGTH} playlist-length={PLAYLIST_LENGTH}"
    )

    logging.debug(f"Ejecutando pipeline: {pipeline}")
    process = subprocess.Popen(pipeline, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout, stderr = process.communicate()
    if process.returncode != 0:
        logging.error(f"Error en el pipeline de GStreamer: {stderr.decode()}")
    else:
        logging.debug(f"Pipeline completado: {stdout.decode()}")


def cleanup_old_segments():
    """Elimina fragmentos antiguos que no están en la lista de reproducción."""
    playlist_path = os.path.join(HLS_OUTPUT_DIR, "cuaima_tv.m3u8")
    if not os.path.exists(playlist_path):
        logging.warning("No se encontró la lista de reproducción para limpiar.")
        return

    # Leer segmentos actuales en la lista de reproducción
    with open(playlist_path, "r") as playlist:
        lines = playlist.readlines()
        current_segments = [
            line.strip() for line in lines if not line.startswith("#") and line.strip()
        ]

    # Eliminar segmentos que no estén en la lista actual
    for file in os.listdir(HLS_OUTPUT_DIR):
        if file.endswith(".ts") and file not in current_segments:
            file_path = os.path.join(HLS_OUTPUT_DIR, file)
            try:
                os.remove(file_path)
                logging.debug(f"Eliminado segmento obsoleto: {file_path}")
            except Exception as e:
                logging.error(f"No se pudo eliminar el archivo {file_path}: {e}")


def play_videos_in_order():
    """Procesa videos en orden continuo y mantiene la limpieza de fragmentos."""
    video_playlist = [
        "11FIT.mp4",
        "12FIT.mp4",
    ]
    os.makedirs(HLS_OUTPUT_DIR, exist_ok=True)

    while True:
        time.sleep(3)
        for video_file in video_playlist:
            video_path = os.path.join(VIDEOS_DIR, video_file)
            if os.path.exists(video_path):
                logging.debug(f"Procesando video: {video_file}")
                process_video(video_path)
                cleanup_old_segments()
            else:
                logging.error(f"El archivo {video_file} no existe en {VIDEOS_DIR}.")
        logging.debug("Lista de reproducción completa. Reiniciando ciclo.")


if __name__ == "__main__":
    logging.debug("Iniciando transmisión continua...")
    logging.debug(f"Directorio de videos: {VIDEOS_DIR}")
    logging.debug(f"Directorio de salida HLS: {HLS_OUTPUT_DIR}")

    try:
        play_videos_in_order()
    except KeyboardInterrupt:
        logging.debug("Transmisión detenida por el usuario.")
