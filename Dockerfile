# Base de Python con herramientas multimedia
FROM python:3.10-slim

# Instalar FFmpeg y dependencias necesarias
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Crear directorio de trabajo
WORKDIR /app

# Copiar archivos de la aplicación (sin los videos)
COPY app/ /app

# Instalar dependencias de Python
RUN pip install --no-cache-dir flask

# Exponer solo el puerto de Flask
EXPOSE 5000

# Comando para iniciar la aplicación
CMD ["python", "/app/main.py"]
