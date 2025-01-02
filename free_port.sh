#!/bin/bash

PORT=2001

echo "Verificando si el puerto $PORT está en uso..."
while lsof -i :$PORT &>/dev/null; do
    PID=$(lsof -t -i:$PORT)
    echo "El puerto $PORT está en uso por el proceso $PID. Deteniéndolo..."
    kill -9 $PID
    sleep 1
done

echo "El puerto $PORT está libre."
