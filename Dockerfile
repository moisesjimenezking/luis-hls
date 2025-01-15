# Base de Python con herramientas multimedia
FROM python:3.10

# Instalar dependencias necesarias y GStreamer
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    gstreamer1.0-tools \
    gstreamer1.0-plugins-base \
    gstreamer1.0-plugins-good \
    gstreamer1.0-plugins-bad \
    gstreamer1.0-plugins-ugly \
    gstreamer1.0-libav \
    python3-gi \
    gir1.2-gstreamer-1.0 \
    gobject-introspection \
    libgirepository1.0-dev \
    build-essential \
    meson \
    pkg-config && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Crear directorio de trabajo
WORKDIR /app

# Copiar archivos de la aplicación
COPY app/ /app

# Instalar dependencias de Python
COPY requirements.txt /app/requirements.txt

# Instalar paquetes Python, incluyendo PyGObject
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r /app/requirements.txt && \
    pip install --no-cache-dir PyGObject

# Exponer solo el puerto de Flask
EXPOSE 5000

# Comando para iniciar la aplicación
CMD ["python", "/app/main.py"]
