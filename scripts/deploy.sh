#!/usr/bin/env bash
# Deploy wearable-hub on the prod host (lnpitask, Podman Quadlets).
#
# Run this ON the host, after checking out the commit/tag you want to ship. It rebuilds the
# images (code is baked in), restarts the services (the backend's startup runs
# `alembic upgrade head` against the external DB), and health-checks. Data backfills, if any,
# are run separately (see README).
#
# Usage: scripts/deploy.sh [backend|frontend|all]   (default: all)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
TARGET="${1:-all}"

# `sudo` strips proxy env on lnpitask; re-export the proxy from .env so the base-image and
# dependency pulls during the build can reach out (sudo -E then inherits these).
for v in HTTP_PROXY HTTPS_PROXY NO_PROXY; do
  val="$(sed -nE "s/^$v=(.*)/\1/p" .env | head -1)"
  if [ -n "$val" ]; then
    export "$v=$val"
    export "$(printf '%s' "$v" | tr '[:upper:]' '[:lower:]')=$val"
  fi
done

build() {
  echo "==> Building $1 image"
  sudo -E podman build -t "localhost/wearable-$1:latest" "./$1"
}

case "$TARGET" in
  backend)
    build backend
    echo "==> Restarting services"
    sudo systemctl restart wearable-backend.service wearable-scheduler.service ;;
  frontend)
    build frontend
    echo "==> Restarting services"
    sudo systemctl restart wearable-frontend.service ;;
  all)
    build backend
    build frontend
    echo "==> Restarting services"
    sudo systemctl restart wearable-backend.service wearable-scheduler.service wearable-frontend.service ;;
  *)
    echo "usage: $0 [backend|frontend|all]" >&2; exit 1 ;;
esac

echo "==> Waiting for backend (migrations run on startup)"
for _ in $(seq 1 30); do
  code="$(curl -s --noproxy '*' -o /dev/null -w '%{http_code}' http://localhost:8010/health || true)"
  [ "$code" = "200" ] && break
  sleep 2
done
curl -s --noproxy '*' http://localhost:8010/health \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print('backend /health: version', d.get('version'), '| db', d.get('db'))" \
  2>/dev/null || echo "backend /health: not OK"
curl -s --noproxy '*' -o /dev/null -w 'frontend: HTTP %{http_code}\n' http://localhost:8020/wearable/
echo "==> Done"
