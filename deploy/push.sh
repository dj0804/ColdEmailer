#!/usr/bin/env bash
# Build the frontend locally and push code + static assets to the server.
# Run LOCALLY from the repo root:
#     bash deploy/push.sh <server-ip> <path-to-key.pem>
#
# The frontend is built here on purpose — `npm build` would OOM on a 512MB box.
set -euo pipefail

HOST="${1:?usage: push.sh <server-ip> <key.pem>}"
KEY="${2:?usage: push.sh <server-ip> <key.pem>}"
REMOTE="ubuntu@${HOST}"
SSH="ssh -i ${KEY} -o StrictHostKeyChecking=accept-new"

echo "==> Building frontend locally"
(cd frontend && npm run build)

echo "==> Syncing code"
rsync -az --delete -e "${SSH}" \
  --exclude '.venv' --exclude '__pycache__' --exclude 'node_modules' \
  --exclude '*.db' --exclude '.env' --exclude 'token.json' \
  --exclude 'credentials.json' --exclude '.git' \
  backend/ "${REMOTE}:/home/ubuntu/applier/backend/"

rsync -az --delete -e "${SSH}" frontend/dist/ "${REMOTE}:/home/ubuntu/applier/frontend/dist/"
rsync -az -e "${SSH}" deploy/ "${REMOTE}:/home/ubuntu/applier/deploy/"
rsync -az -e "${SSH}" assets/ "${REMOTE}:/home/ubuntu/applier/assets/"

echo "==> Restarting service"
${SSH} "${REMOTE}" 'sudo systemctl restart applier && sleep 2 && curl -sf localhost:8000/api/health && echo'

echo "Deployed."
