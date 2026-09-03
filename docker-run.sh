#!/usr/bin/env bash
set -euo pipefail

IMAGE_NAME="${IMAGE_NAME:-ghcr.io/wolf575/tg-forward-hub:latest}"
CONTAINER_NAME="${CONTAINER_NAME:-tg-forward-hub}"
HOST_PORT="${HOST_PORT:-10000}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-$ROOT_DIR/data}"
DOWNLOADS_DIR="${DOWNLOADS_DIR:-$ROOT_DIR/downloads}"

mkdir -p "$DATA_DIR" "$DOWNLOADS_DIR"

docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true

docker run -d \
    --name "$CONTAINER_NAME" \
    --restart unless-stopped \
    -p "${HOST_PORT}:10000" \
    -v "${DATA_DIR}:/app/data" \
    -v "${DOWNLOADS_DIR}:/app/downloads" \
    -e DATA_DIR=/app/data \
    -e PORT=10000 \
    -e TZ=Asia/Shanghai \
    "$IMAGE_NAME"

echo "TG Forward Hub is running at http://localhost:${HOST_PORT}"
echo "Open the page and finish Telegram setup in the web UI."
echo "Use 'docker logs -f ${CONTAINER_NAME}' to view logs."
