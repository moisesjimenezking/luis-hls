#!/bin/bash

# Variables configurables
CONTAINER_NAME="flask_hls_streaming"
IMAGE_NAME="flask_hls_streaming"
HOST_VIDEO_DIR="/mnt/d/CuaimaTeam/videos"   # "/home/moises/Documentos/proyectos/trabajo/videos"    # Cambia esto a la ruta donde tienes tus videos en el host
HOST_HLS_OUTPUT_DIR="/mnt/d/CuaimaTeam/hls" # "/home/moises/Documentos/proyectos/trabajo/hls" # Cambia esto a la ruta donde deseas guardar los archivos HLS

# Verifica que los directorios existan
if [ ! -d "$HOST_VIDEO_DIR" ]; then
  echo "Error: El directorio de videos no existe en la ruta: $HOST_VIDEO_DIR"
  exit 1
fi

if [ ! -d "$HOST_HLS_OUTPUT_DIR" ]; then
  echo "Creando el directorio para la salida HLS: $HOST_HLS_OUTPUT_DIR"
  mkdir -p "$HOST_HLS_OUTPUT_DIR"
fi

docker build -t $IMAGE_NAME .

docker stop $IMAGE_NAME
docker remove $IMAGE_NAME

# Iniciar el contenedor
docker run -d \
  --name $CONTAINER_NAME \
  --network host \  # Cambia aquí para usar la red host
  -v "$HOST_VIDEO_DIR:/app/videos:rw" \
  -v "$HOST_HLS_OUTPUT_DIR:/app/hls_output:rw" \
  $IMAGE_NAME


# Confirmación
if [ $? -eq 0 ]; then
  echo "El contenedor '$CONTAINER_NAME' se inició correctamente."
  echo "Accede al servicio en: http://localhost:2001"
else
  echo "Error: No se pudo iniciar el contenedor."
fi
