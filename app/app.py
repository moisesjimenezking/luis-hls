from flask import Flask, jsonify, send_from_directory
import os

app = Flask(__name__)
app.config["FLASK_DEBUG"] = True

HLS_DIR = "hls_output"

@app.route("/hls/<path:filename>")
def serve_hls(filename):
    """Servir segmentos HLS y listas de reproducción"""
    return send_from_directory(HLS_DIR, filename)

@app.route("/epg")
def serve_epg():
    """Servir archivo EPG.xml"""
    return send_from_directory(".", "epg.xml")

@app.route("/")
def home():
    return jsonify({
        "message": "HLS Streaming Server",
        "hls_url": "/hls/playlist.m3u8",
        "epg_url": "/epg"
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
