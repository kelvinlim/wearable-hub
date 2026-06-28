#!/usr/bin/env bash
#
# Verify the frontend compiles exactly as the production image does — same node:20-alpine base
# and `npm ci` against the committed package-lock.json — without installing Node on the host or
# writing node_modules into the working tree.
#
# Why a container (not host Node): the prod image is built this way, so a green run here means the
# image build is green; a host Node of a different version can pass or fail differently (a flaky
# install once silently dropped a dep — see CLAUDE.md).
#
# Why `sudo -E podman`: this host's rootless podman has no subuid/subgid range, so image unpack
# fails ("insufficient UIDs/GIDs"); the project already builds images with `sudo -E podman`. `-E`
# preserves http_proxy/https_proxy for the registry pull + npm. The source is mounted READ-ONLY
# and copied to a throwaway dir inside the container, so nothing is written back to the repo.
#
# Usage:
#   frontend/build-check.sh
#   PODMAN="podman" frontend/build-check.sh        # if you have rootless podman working
#   NODE_IMAGE="node:20-alpine" frontend/build-check.sh
#
set -euo pipefail

FE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PODMAN="${PODMAN:-sudo -E podman}"
NODE_IMAGE="${NODE_IMAGE:-node:20-alpine}"

echo "Building frontend in ${NODE_IMAGE} (source read-only; no host writes)…"
# shellcheck disable=SC2086  # $PODMAN may be "sudo -E podman" and must word-split.
$PODMAN run --rm \
  -e http_proxy -e https_proxy -e no_proxy \
  -v "${FE_DIR}":/src:ro \
  "${NODE_IMAGE}" \
  sh -c "cp -r /src /build && cd /build && npm ci && npm run build && echo BUILD_OK"
