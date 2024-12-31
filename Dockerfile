FROM python:3.9-slim

WORKDIR /app

ENV FLASK_ENV=development

# Instalar GStreamer
RUN apt-get update && apt-get install -y gstreamer1.0-tools gstreamer1.0-plugins-good \
    gstreamer1.0-plugins-bad gstreamer1.0-plugins-ugly gstreamer1.0-libav && \
    apt-get clean

# Copiar el proyecto
COPY app /app

# Instalar dependencias
RUN pip install -r requirements.txt

# Exponer el puerto
# EXPOSE 2001

# Comando de inicio
CMD ["sh", "-c", "python app.py & python schedule.py"]