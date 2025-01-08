#!/bin/bash

# Definir directorios
ORIGEN="./videos-originales"
DESTINO="./videos"

# Eliminar y recrear el directorio de salida
rm -rf "$DESTINO"
mkdir -p "$DESTINO"
chmod 777 "$DESTINO"

# Procesar cada archivo de video en el directorio de origen
for video in "$ORIGEN"/*.mp4; do
    # Verifica si hay archivos que coincidan con el patrón
    if [[ ! -f "$video" ]]; then
        echo "No se encontraron archivos .mkv en $ORIGEN"
        exit 1
    fi

    # Obtener el nombre base del archivo sin la extensión
    nombre_base=$(basename "$video")
    nombre_sin_ext="${nombre_base%.*}"
    extension="${nombre_base##*.}"

    # Ejecutar FFmpeg para dividir el video en segmentos de 8 minutos (480 segundos)
    ffmpeg -i "$video" -c copy -map 0 -segment_time 480 -f segment -reset_timestamps 1 "$DESTINO/${nombre_sin_ext}_%d.$extension"
done
chmod -R 777 "$DESTINO"
echo "Segmentación completada. Archivos guardados en $DESTINO"
