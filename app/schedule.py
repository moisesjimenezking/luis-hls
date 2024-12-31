import os
import subprocess
import logging
import time

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# Configuración de rutas
VIDEOS_DIR = "/app/videos"
HLS_OUTPUT_DIR = "/app/hls_output"

# Configuración de HLS
SEGMENT_DURATION = 5  # Duración de cada segmento (segundos)
PLAYLIST_LENGTH = 3  # Número de segmentos a mantener en la lista de reproducción
WAIT_TIME = 3  # Tiempo de espera entre segmentos para sincronizar con la duración

def get_video_id(video_path):
    """
    Genera un identificador único basado en el nombre del archivo de video.
    """
    return os.path.splitext(os.path.basename(video_path))[0]

def video_segments_exist(video_id):
    """
    Comprueba si los segmentos para un video ya existen.
    """
    playlist_path = os.path.join(HLS_OUTPUT_DIR, f"{video_id}.m3u8")
    return os.path.exists(playlist_path)

def process_video_in_real_time(video_path):
    """
    Procesa un video con GStreamer para generar HLS de forma continua en tiempo real.
    """
    video_id = get_video_id(video_path)
    segment_base_name = f"{video_id}_segment_%05d.ts"
    playlist_path = os.path.join(HLS_OUTPUT_DIR, f"{video_id}.m3u8")

    # Configuración del pipeline de GStreamer
    pipeline = (
        f"gst-launch-1.0 filesrc location={video_path} ! decodebin name=dec "
        f"dec. ! queue max-size-buffers=0 max-size-time=0 max-size-bytes=0 ! audioconvert ! audioresample ! "
        f"avenc_aac ! queue max-size-buffers=0 max-size-time=0 max-size-bytes=0 ! mux. "
        f"dec. ! queue max-size-buffers=0 max-size-time=0 max-size-bytes=0 ! videoconvert ! x264enc bitrate=3000 "
        f"speed-preset=ultrafast tune=zerolatency key-int-max=30 ! mux. "
        f"mpegtsmux name=mux ! hlssink location={HLS_OUTPUT_DIR}/{segment_base_name} "
        f"playlist-location={playlist_path} "
        f"target-duration={SEGMENT_DURATION} max-files={PLAYLIST_LENGTH} playlist-length={PLAYLIST_LENGTH}"
    )

    logging.debug(f"Ejecutando pipeline: {pipeline}")
    process = subprocess.Popen(pipeline, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    # Monitoriza el pipeline en tiempo real
    try:
        while process.poll() is None:  # Mientras el proceso siga corriendo
            logging.debug("Esperando a que se generen nuevos segmentos...")
            time.sleep(WAIT_TIME)  # Sincronización con la duración de los segmentos
    except KeyboardInterrupt:
        logging.info("Deteniendo el pipeline por interrupción del usuario.")
        process.terminate()
    finally:
        process.wait()  # Asegúrate de que el proceso termine correctamente

    if process.returncode != 0:
        logging.error(f"Error en el pipeline de GStreamer: {process.stderr.read().decode()}")
    else:
        logging.debug("Pipeline completado con éxito.")


def cleanup_old_segments():
    """
    Elimina fragmentos antiguos que no están en la lista de reproducción actual.
    """
    for playlist_file in os.listdir(HLS_OUTPUT_DIR):
        if playlist_file.endswith(".m3u8"):
            video_id = playlist_file.split(".")[0]
            playlist_path = os.path.join(HLS_OUTPUT_DIR, playlist_file)

            # Leer los segmentos actuales en la lista de reproducción
            with open(playlist_path, "r") as playlist:
                lines = playlist.readlines()
                current_segments = [
                    line.strip() for line in lines if not line.startswith("#") and line.strip()
                ]

            # Eliminar segmentos que no estén en la lista actual
            for file in os.listdir(HLS_OUTPUT_DIR):
                if file.endswith(".ts") and file.startswith(video_id) and file not in current_segments:
                    file_path = os.path.join(HLS_OUTPUT_DIR, file)
                    try:
                        os.remove(file_path)
                        logging.debug(f"Eliminado segmento obsoleto: {file_path}")
                    except Exception as e:
                        logging.error(f"No se pudo eliminar el archivo {file_path}: {e}")


def play_videos_in_order():
    """
    Procesa videos en orden continuo y genera HLS en tiempo real.
    """
    video_playlist = [
        "11FIT.mp4",
        "12FIT.mp4",
    ]
    os.makedirs(HLS_OUTPUT_DIR, exist_ok=True)

    for video_file in video_playlist:
        video_path = os.path.join(VIDEOS_DIR, video_file)
        if os.path.exists(video_path):
            video_id = get_video_id(video_path)

            if video_segments_exist(video_id):
                logging.debug(f"Segmentos para {video_file} ya existen. Saltando procesamiento.")
            else:
                logging.debug(f"Iniciando procesamiento en tiempo real para: {video_file}")
                process_video_in_real_time(video_path)
            cleanup_old_segments()
        else:
            logging.error(f"El archivo {video_file} no existe en {VIDEOS_DIR}.")
    
    logging.debug("Lista de reproducción completa. Reiniciando ciclo...")


if __name__ == "__main__":
    logging.debug("Iniciando transmisión continua...")
    logging.debug(f"Directorio de videos: {VIDEOS_DIR}")
    logging.debug(f"Directorio de salida HLS: {HLS_OUTPUT_DIR}")

    try:
        while True:
            play_videos_in_order()
    except KeyboardInterrupt:
        logging.debug("Transmisión detenida por el usuario.")
