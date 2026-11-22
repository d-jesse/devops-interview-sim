# Deploying to production

This runs the app on a small VPS, reachable at a real domain over
HTTPS, with grading proxied privately over Tailscale to a Mac Studio
(or any other machine) running Ollama. The VPS never talks to Ollama
over the public internet — only over the tailnet.

```
visitor --HTTPS--> Caddy (VPS, :443) --> uvicorn (127.0.0.1:8010) --Tailscale--> Ollama
```

## Prerequisites (you do these — they require an account/payment)

1. A domain name, DNS pointed at the VPS you're about to create.
2. A VPS running Ubuntu 22.04 or 24.04 (Hetzner CX22 or similar — this
   doesn't need much CPU/RAM, it's a thin proxy to Ollama, not the
   thing doing inference).
3. A Tailscale auth key: Tailscale admin console → Settings → Keys →
   Generate auth key. Reusable, short expiry is fine since you only
   need it once to join this VPS to the tailnet.

## 1. Join the VPS to your tailnet

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up --authkey=<AUTH_KEY> --hostname=devops-sim-vps
tailscale ip -4   # confirm it got a 100.x address
tailscale ping <ollama-host-tailscale-ip>   # confirm it can reach the Ollama host
```

## 2. Install dependencies

```bash
sudo apt update
sudo apt install -y python3.12-venv git ufw

# Caddy (official repo — gives automatic HTTPS for free)
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
  | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
  | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update
sudo apt install -y caddy
```

## 3. Deploy the app

```bash
sudo useradd --system --create-home --shell /bin/bash deploy
sudo -u deploy git clone https://github.com/<you>/devops-interview-sim.git /opt/devops-interview-sim
cd /opt/devops-interview-sim
sudo -u deploy python3 -m venv .venv
sudo -u deploy .venv/bin/pip install -r requirements.txt
```

The question bank is gitignored on purpose (it holds every rubric and
model answer) — copy it over directly, it's never in the repo:

```bash
scp data/question_bank.json deploy@<vps-ip>:/opt/devops-interview-sim/data/question_bank.json
```

Create `/opt/devops-interview-sim/.env` (copy `.env.example`, then fill
in real values — `OLLAMA_BASE_URL` is the Mac Studio's Tailscale
address, `ADMIN_PASSWORD` should be a real generated secret, not the
placeholder):

```bash
sudo -u deploy cp .env.example .env
sudo -u deploy nano .env
```

## 4. Run it as a service

```bash
sudo cp ops/devops-interview-sim.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now devops-interview-sim
sudo systemctl status devops-interview-sim   # should be active (running)
```

## 5. Front it with Caddy

Edit `ops/Caddyfile`, replacing `yourdomain.com` with the real domain,
then:

```bash
sudo cp ops/Caddyfile /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

Point the domain's DNS A record at the VPS's public IP before this
step — Caddy requests the Let's Encrypt cert on first request and
needs the domain to already resolve correctly.

## 6. Lock down the firewall

```bash
sudo ufw allow OpenSSH
sudo ufw allow 80,443/tcp
sudo ufw enable
```

## 7. Verify

```bash
curl -s https://yourdomain.com/api/healthz            # {"status":"ok"}
curl -s https://yourdomain.com/api/healthz/grading     # {"status":"ok"} if Ollama is reachable
```

Then in a browser: load the site, sign up, run a short interview,
confirm grading works, confirm the admin account can reach
`/admin.html` and a regular account can't even see a link to it.

## 8. Monitor it

Set up two free [UptimeRobot](https://uptimerobot.com) monitors:

- `https://yourdomain.com/api/healthz` — alerts if the VPS/app itself goes down.
- `https://yourdomain.com/api/healthz/grading` — alerts separately if
  the Mac Studio or the Tailscale link between it and the VPS goes
  down, even while the app itself is fine. This is the real single
  point of failure in this setup, worth watching on its own.

## Redeploying after a code change

```bash
cd /opt/devops-interview-sim
sudo -u deploy git pull
sudo -u deploy .venv/bin/pip install -r requirements.txt   # if deps changed
sudo systemctl restart devops-interview-sim
```

`data/app.db` and `data/question_bank.json` live outside git on the
server and are untouched by `git pull`.
