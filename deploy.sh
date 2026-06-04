#!/usr/bin/env bash
# Deploy paper-radar to a VPS via SSH + Docker Compose
#
# Usage:
#   ./deploy.sh user@your-server-ip
#   ./deploy.sh root@192.168.1.100
#
# Prerequisites on your local machine:
#   - docker (or podman) for building
#   - ssh access to the server
#   - rsync
#
# Prerequisites on the server:
#   - docker + docker compose (or podman + podman-compose)
#   - /opt/paper-radar directory (created automatically)

set -euo pipefail

REMOTE="${1:?Usage: $0 user@server-ip}"
REMOTE_DIR="/opt/paper-radar"
USE_PODMAN=false

# Detect podman vs docker
if command -v podman &>/dev/null && ! command -v docker &>/dev/null; then
    USE_PODMAN=true
fi

echo "=== Deploying paper-radar to ${REMOTE} ==="

# 1. Build image locally
echo "[1/4] Building image..."
if [ "$USE_PODMAN" = true ]; then
    podman build -t paper-radar:latest .
else
    docker build -t paper-radar:latest .
fi

# 2. Save image and transfer
echo "[2/4] Transferring image to server..."
if [ "$USE_PODMAN" = true ]; then
    podman save paper-radar:latest | ssh "${REMOTE}" "docker load" 2>/dev/null || \
    podman save paper-radar:latest | ssh "${REMOTE}" "podman load"
else
    docker save paper-radar:latest | ssh "${REMOTE}" "docker load"
fi

# 3. Sync project files
echo "[3/4] Syncing project files..."
ssh "${REMOTE}" "mkdir -p ${REMOTE_DIR}/data ${REMOTE_DIR}/digests"
rsync -az --delete \
    --exclude '.git' \
    --exclude '__pycache__' \
    --exclude '*.pyc' \
    --exclude 'data/' \
    --exclude 'digests/' \
    --exclude '.env' \
    --exclude 'node_modules' \
    ./ "${REMOTE}:${REMOTE_DIR}/"

# 4. Start services
echo "[4/4] Starting services..."
ssh "${REMOTE}" "cd ${REMOTE_DIR} && \
    test -f .env || cp .env.example .env && \
    echo '' && echo 'Edit .env on server:' && echo \"  ssh ${REMOTE} vim ${REMOTE_DIR}/config.yaml\" && \
    echo \"  ssh ${REMOTE} vim ${REMOTE_DIR}/.env\" && \
    echo '' && echo 'Then start:' && \
    echo \"  ssh ${REMOTE} 'cd ${REMOTE_DIR} && docker compose up -d'\""

echo ""
echo "=== Done ==="
echo "Image and files deployed to ${REMOTE}:${REMOTE_DIR}"
echo ""
echo "Next steps on server:"
echo "  1. Edit .env:  ssh ${REMOTE} vim ${REMOTE_DIR}/.env"
echo "  2. Edit config: ssh ${REMOTE} vim ${REMOTE_DIR}/config.yaml"
echo "  3. Start:       ssh ${REMOTE} 'cd ${REMOTE_DIR} && docker compose up -d'"
echo "  4. Logs:        ssh ${REMOTE} 'cd ${REMOTE_DIR} && docker compose logs -f'"
