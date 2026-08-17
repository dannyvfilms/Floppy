#!/bin/sh

set -eu

RUNTIME_DIR=/run/floppy
RUNTIME_PORT_FILE="${RUNTIME_DIR}/server-port"
NGINX_TEMPLATE=/etc/nginx/nginx.conf.template
NGINX_IPV4=/etc/nginx/nginx.conf
NGINX_IPV6=/etc/nginx/nginx.ipv6.conf

mkdir -p "$RUNTIME_DIR"

server_port=$(
    python -m config.server_port --prepare-runtime \
        "$NGINX_TEMPLATE" \
        "$NGINX_IPV4" \
        "$NGINX_IPV6" \
        "$RUNTIME_PORT_FILE"
)

if [ -z "${FLOPPY_URL+x}" ]; then
    FLOPPY_URL="http://127.0.0.1:${server_port}"
    export FLOPPY_URL
fi

echo "[runtime] Public HTTP port: ${server_port}" >&2
exec /entrypoint.sh "$server_port"
