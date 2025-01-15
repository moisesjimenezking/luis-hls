# Base de Python con herramientas multimedia
FROM python:3.10-slim

# Instalar FFmpeg, GStreamer y dependencias necesarias
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    gstreamer1.0-tools \
    gstreamer1.0-plugins-base \
    gstreamer1.0-plugins-good \
    gstreamer1.0-plugins-bad \
    gstreamer1.0-plugins-ugly \
    gstreamer1.0-libav && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Crear directorio de trabajo
WORKDIR /app

# Copiar archivos de la aplicación (sin los videos)
COPY app/ /app

# Instalar dependencias de Python
COPY requirements.txt /app/requirements.txt

# Instalar paquetes Python
RUN pip install --no-cache-dir -r /app/requirements.txt

# Exponer solo el puerto de Flask
EXPOSE 5000

# Comando para iniciar la aplicación
CMD ["python", "/app/main.py"]
