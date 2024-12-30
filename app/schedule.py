import os
import shutil
import subprocess
import logging

logging.basicConfig(level=logging.DEBUG)

VIDEOS_DIR = "/app/videos"
HLS_OUTPUT_DIR = "/app/hls_output"
SEGMENT_COUNTER = 0  # Contador global para los segmentos
PLAYLIST_SEQUENCE = 0  # Secuencia global para mantener la lista sincronizada


import os
import subprocess
import logging
import shutil

logging.basicConfig(level=logging.DEBUG)

VIDEOS_DIR = "/app/videos"
HLS_OUTPUT_DIR = "/app/hls_output"
SEGMENT_COUNTER = 0  # Contador para mantener continuidad en los segmentos


def process_video(video_path):
    """Procesar un video con GStreamer para generar HLS"""
    global SEGMENT_COUNTER

    # Nombre base para los segmentos
    segment_base_name = f"segment_%05d.ts"
    playlist_aux_path = os.path.join(HLS_OUTPUT_DIR, "playlist-aux.m3u8")
    playlist_path = os.path.join(HLS_OUTPUT_DIR, "playlist.m3u8")

    # Configuración del pipeline
    pipeline = (
        f"gst-launch-1.0 filesrc location={video_path} ! decodebin name=dec "
        f"dec. ! queue ! audioconvert ! audioresample ! avenc_aac ! queue ! mux. "
        f"dec. ! queue ! videoconvert ! x264enc bitrate=5000 speed-preset=veryfast tune=zerolatency ! mux. "
        f"mpegtsmux name=mux ! hlssink location={HLS_OUTPUT_DIR}/{segment_base_name} "
        f"playlist-location={playlist_aux_path} target-duration=10 max-files=0 playlist-length=0"
    )

    logging.debug(f"Ejecutando pipeline: {pipeline}")
    process = subprocess.Popen(pipeline, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout, stderr = process.communicate()
    logging.debug(f"Pipeline stdout: {stdout.decode()}")
    logging.error(f"Pipeline stderr: {stderr.decode()}")

    # Fusionar la lista de reproducción auxiliar con la principal
    if process.returncode == 0 and os.path.exists(playlist_aux_path):
        merge_playlists(playlist_aux_path, playlist_path)


def merge_playlists(aux_playlist_path, global_playlist_path):
    """Combinar listas de reproducción y renombrar segmentos para continuidad"""
    global SEGMENT_COUNTER

    if not os.path.exists(aux_playlist_path):
        logging.error(f"No se encontró la lista auxiliar: {aux_playlist_path}")
        return

    # Crear la lista global si no existe
    if not os.path.exists(global_playlist_path):
        with open(global_playlist_path, "w") as global_playlist:
            global_playlist.write("#EXTM3U\n")
            global_playlist.write("#EXT-X-VERSION:3\n")
            global_playlist.write("#EXT-X-TARGETDURATION:10\n")
            global_playlist.write("#EXT-X-MEDIA-SEQUENCE:0\n")

    with open(aux_playlist_path, "r") as aux_playlist, open(global_playlist_path, "a") as global_playlist:
        for line in aux_playlist:
            if line.startswith("#EXTINF") or line.startswith("#EXT-X-ENDLIST"):
                global_playlist.write(line)
            elif not line.startswith("#") and line.strip():
                segment_name = line.strip()
                new_segment_name = f"segment_{SEGMENT_COUNTER:05d}.ts"
                segment_path = os.path.join(HLS_OUTPUT_DIR, segment_name)
                new_segment_path = os.path.join(HLS_OUTPUT_DIR, new_segment_name)

                # Renombrar el segmento
                if os.path.exists(segment_path):
                    shutil.move(segment_path, new_segment_path)
                    global_playlist.write(new_segment_name + "\n")
                    SEGMENT_COUNTER += 1



def play_videos_in_order():
    """Reproducir los videos en el orden definido de forma continua"""
    video_playlist = [
        "11FIT.mp4",
        "12FIT.mp4",
    ]
    os.makedirs(HLS_OUTPUT_DIR, exist_ok=True)

    while True:
        for video_file in video_playlist:
            video_path = os.path.join(VIDEOS_DIR, video_file)
            if os.path.exists(video_path):
                logging.debug(f"Procesando video: {video_file}")
                process_video(video_path)
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
