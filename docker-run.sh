#!/usr/bin/env bash
set -euo pipefail

IMAGE_NAME="${IMAGE_NAME:-tg-forward-hub}"
CONTAINER_NAME="${CONTAINER_NAME:-tg-forward-hub}"
HOST_PORT="${HOST_PORT:-10000}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-$ROOT_DIR/data}"
DOWNLOADS_DIR="${DOWNLOADS_DIR:-$ROOT_DIR/downloads}"

if [[ ! -f "$ROOT_DIR/.env" ]]; then
    echo "Missing .env file. Copy .env.example to .env and fill in your Telegram credentials first." >&2
    exit 1
fi

mkdir -p "$DATA_DIR" "$DOWNLOADS_DIR"

docker build -t "$IMAGE_NAME" "$ROOT_DIR"
docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true

docker run -d \
    --name "$CONTAINER_NAME" \
    --restart unless-stopped \
    -p "${HOST_PORT}:10000" \
    -v "${DATA_DIR}:/app/data" \
    -v "${DOWNLOADS_DIR}:/app/downloads" \
    --env-file "$ROOT_DIR/.env" \
    -e DATA_DIR=/app/data \
    -e PORT=10000 \
    -e TZ=Asia/Shanghai \
    "$IMAGE_NAME"

echo "TG Forward Hub is running at http://localhost:${HOST_PORT}"
echo "Use 'docker logs -f ${CONTAINER_NAME}' to view logs."
