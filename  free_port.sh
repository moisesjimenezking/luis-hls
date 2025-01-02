#!/bin/bash

PORT=2001

# Buscar el proceso que está usando el puerto
PID=$(lsof -t -i:$PORT)

if [ -n "$PID" ]; then
  echo "El puerto $PORT está en uso por el proceso $PID. Deteniéndolo..."
  kill -9 $PID
  echo "Puerto $PORT liberado."
else
  echo "El puerto $PORT está libre."
fi
