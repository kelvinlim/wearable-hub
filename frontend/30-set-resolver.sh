#!/bin/sh
# Inject the container's DNS resolver (podman aardvark-dns) into nginx.conf so the
# reverse proxy re-resolves `backend` per request and survives backend restarts.
# Without this, nginx caches the IP at config-parse time and 502s after the backend
# container takes a new IP on the user-defined network.
set -e
RESOLVER=$(awk '/^nameserver / {print $2; exit}' /etc/resolv.conf)
sed -i "s|__DNS_RESOLVER__|${RESOLVER}|" /etc/nginx/conf.d/default.conf
echo "30-set-resolver: nginx using DNS resolver ${RESOLVER}"
