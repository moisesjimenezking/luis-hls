#!/bin/bash

PORT=2001
PROCESS=$(lsof -t -i:$PORT)

if [ -z "$PROCESS" ]; then
  echo "El puerto $PORT está libre."
else
  echo "El puerto $PORT está en uso por el proceso $PROCESS. Deteniéndolo..."
  kill -9 $PROCESS
  if [ $? -eq 0 ]; then
    echo "Proceso detenido con éxito."
  else
    echo "Error al intentar detener el proceso."
  fi
fi
