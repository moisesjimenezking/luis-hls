import os
import subprocess
from flask import Flask, jsonify

app = Flask(__name__)

VIDEOS_DIR = "/app/videos"
HLS_OUTPUT_DIR = "/app/hls_output"

SEGMENT_DURATION = 5  # Duración en segundos
PLAYLIST_LENGTH = 3  # Número de segmentos en la lista

@app.route("/start/<video_name>", methods=["GET"])
def start_stream(video_name):
    video_path = os.path.join(VIDEOS_DIR, video_name)
    if not os.path.exists(video_path):
        return jsonify({"error": f"Video {video_name} not found."}), 404

    # FFmpeg pipeline
    pipeline = [
        "ffmpeg", "-re", "-i", video_path,
        "-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency", "-b:v", "3000k",
        "-maxrate", "3000k", "-bufsize", "6000k",
        "-c:a", "aac", "-b:a", "128k",
        "-f", "hls", "-hls_time", str(SEGMENT_DURATION),
        "-hls_list_size", str(PLAYLIST_LENGTH),
        "-hls_flags", "delete_segments",
        "-hls_segment_filename", os.path.join(HLS_OUTPUT_DIR, "segment_%03d.ts"),
        os.path.join(HLS_OUTPUT_DIR, "playlist.m3u8")
    ]

    # Ejecutar FFmpeg
    subprocess.Popen(pipeline)
    return jsonify({"message": f"Streaming started for {video_name}."})

@app.route("/videos", methods=["GET"])
def list_videos():
    videos = [f for f in os.listdir(VIDEOS_DIR) if f.endswith(".mp4")]
    return jsonify(videos)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
