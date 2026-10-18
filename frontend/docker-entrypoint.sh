#!/bin/sh
set -eu

: "${BASIC_AUTH_USER:?Set BASIC_AUTH_USER for the deployment}"
: "${BASIC_AUTH_PASSWORD:?Set BASIC_AUTH_PASSWORD for the deployment}"

printf '%s\n' "$BASIC_AUTH_PASSWORD" | htpasswd -iB -c /etc/nginx/.htpasswd "$BASIC_AUTH_USER"
exec nginx -g 'daemon off;'
