#!/usr/bin/env bash
# Build the frontend locally and push code + static assets to the server.
# Run LOCALLY from the repo root:
#     bash deploy/push.sh [ssh-host]
#
# ssh-host defaults to `applier`, an ~/.ssh/config alias that reaches the box
# through the Cloudflare Tunnel (see README, "SSH access"), so no inbound port 22
# or IP whitelisting is needed. Any host ssh can reach works.
#
# Uses tar over ssh rather than rsync, which isn't available on Windows Git Bash.
# The frontend is built here on purpose — `npm build` would OOM on a 512MB box.
set -euo pipefail

HOST="${1:-applier}"
SSH="ssh ${HOST}"
APP=/home/ubuntu/applier

echo "==> Building frontend locally"
(cd frontend && npm run build)

echo "==> Syncing backend"
# app/ is replaced wholesale so deleted modules don't linger (rsync --delete
# did this before); .env, the DB, tokens and job state live outside app/ and
# are never touched.
tar -czf - -C backend \
  --exclude='__pycache__' \
  app evals requirements.txt authorize_gmail.py .env.example \
  | ${SSH} "rm -rf ${APP}/backend/app && mkdir -p ${APP}/backend && tar -xzf - -C ${APP}/backend"

echo "==> Syncing frontend, deploy scripts and resumes"
tar -czf - -C frontend dist \
  | ${SSH} "rm -rf ${APP}/frontend/dist && mkdir -p ${APP}/frontend && tar -xzf - -C ${APP}/frontend"
tar -czf - deploy assets | ${SSH} "tar -xzf - -C ${APP}"

echo "==> Restarting service"
${SSH} 'sudo systemctl restart applier && sleep 3 && curl -sf localhost:8000/api/health && echo'

echo "Deployed."
