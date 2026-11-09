#!/usr/bin/env bash
# Start the local pika server (127.0.0.1:7171, data in ~/pika-data) unless it is already up.
set -euo pipefail
PIKA_BIN="${PIKA_BIN:-/root/pika-build/bin/pika}"
PIKA_DATA="${PIKA_DATA:-/root/pika-data}"
if curl -fsS --noproxy "*" -m 3 http://127.0.0.1:7171/api/health >/dev/null 2>&1; then exit 0; fi
mkdir -p "$PIKA_DATA"
nohup "$PIKA_BIN" --data-dir "$PIKA_DATA" serve --bind 127.0.0.1:7171 --auth none --visitor-analytics off \
  >> "$PIKA_DATA/serve.log" 2>&1 < /dev/null &
for _ in $(seq 20); do
  curl -fsS --noproxy "*" -m 2 http://127.0.0.1:7171/api/health >/dev/null 2>&1 && { echo "pika up"; exit 0; }
  sleep 0.5
done
echo "pika failed to start; see $PIKA_DATA/serve.log" >&2; exit 1
