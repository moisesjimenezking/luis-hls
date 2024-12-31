# Base de Python con herramientas multimedia
FROM python:3.10-slim

# Instalar FFmpeg, NGINX y dependencias
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg nginx && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Copiar archivos del proyecto
WORKDIR /app
COPY app/ /app
COPY nginx.conf /etc/nginx/nginx.conf

# Crear carpetas necesarias
RUN mkdir -p /app/videos /app/hls_output /run/nginx

# Instalar dependencias de Python
RUN pip install --no-cache-dir flask

# Exponer puertos para NGINX y Flask
# Exponer puertos para NGINX y Flask
EXPOSE 2001 5000

# Comando para iniciar NGINX y la app Flask
CMD ["sh", "-c", "nginx && python /app/main.py"]
