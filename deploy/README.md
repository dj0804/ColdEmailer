# Deploying Applier (AWS Lightsail 512MB + Cloudflare Tunnel)

The box runs FastAPI + APScheduler bound to `127.0.0.1` only. Cloudflare Tunnel
dials **outbound** and publishes it at `applier.devj.in`, so **no inbound ports
are ever opened** — the Lightsail firewall can stay fully closed except SSH.

The dashboard has no built-in auth, so Cloudflare **Access** is what protects it.
Do not skip that step: without it, anyone with the URL could click
"Approve & send".

## 0. Prerequisites (one-time, on your side)

- **Publish the Google OAuth app to Production.** In Testing mode Google expires
  refresh tokens after 7 days and the server would silently stop sending.
  Google Auth Platform → Audience → **Publish app**.
- `devj.in` nameservers pointed at Cloudflare.

## 1. Provision the server

```bash
# from the repo root, first push the code up
bash deploy/push.sh <SERVER_IP> <key.pem>

# then on the server
ssh -i <key.pem> ubuntu@<SERVER_IP>
cd /home/ubuntu/applier && bash deploy/provision.sh
```

`provision.sh` installs Python, **creates a 1GB swapfile** (a 512MB box OOMs
without one), builds the venv, and installs the systemd unit + cloudflared.

## 2. Secrets (never in git — copy them up manually)

```bash
scp -i <key.pem> backend/.env         ubuntu@<SERVER_IP>:/home/ubuntu/applier/backend/.env
scp -i <key.pem> backend/credentials.json ubuntu@<SERVER_IP>:/home/ubuntu/applier/backend/
scp -i <key.pem> backend/token.json   ubuntu@<SERVER_IP>:/home/ubuntu/applier/backend/
ssh -i <key.pem> ubuntu@<SERVER_IP> 'chmod 600 /home/ubuntu/applier/backend/{.env,token.json,credentials.json}'
```

`token.json` is copied from your machine because the OAuth browser flow can't run
headless. It refreshes itself thereafter — provided the app is in Production.

Optionally copy `backend/applier.db` to carry over existing applications.

## 3. Cloudflare Tunnel

```bash
cloudflared tunnel login                 # opens a URL; authorize devj.in
cloudflared tunnel create applier
cloudflared tunnel route dns applier applier.devj.in

sudo mkdir -p /etc/cloudflared
sudo tee /etc/cloudflared/config.yml >/dev/null <<'YAML'
tunnel: applier
credentials-file: /home/ubuntu/.cloudflared/<TUNNEL_ID>.json
ingress:
  - hostname: applier.devj.in
    service: http://127.0.0.1:8000
  - service: http_status:404
YAML

sudo cloudflared service install
sudo systemctl restart cloudflared
```

## 4. Cloudflare Access (the auth layer — required)

Zero Trust dashboard → **Access → Applications → Add an application** →
*Self-hosted*:

- Application domain: `applier.devj.in`
- Policy: **Allow**, include → **Emails** → your address
- Save.

Now the dashboard demands a Google login before it will even render.

## 5. Verify

```bash
sudo systemctl status applier cloudflared
journalctl -u applier -n 50 --no-pager
curl -s localhost:8000/api/health
```

Then open `https://applier.devj.in` — expect a Cloudflare login, then the
dashboard.

## Routine behaviour

With `OUTREACH_ENABLED=true`, on **weekdays** at `OUTREACH_HOUR` (UTC) the
server works through the company queue: discover contact → draft with the
role-matched resume → **stage as pending approval**. It never sends. You approve
from the dashboard.

Scheduler jobs: `poll_replies` (15 min), `check_ghosting` (daily),
`daily_outreach` (weekdays).

## Redeploying after code changes

```bash
bash deploy/push.sh <SERVER_IP> <key.pem>
```
