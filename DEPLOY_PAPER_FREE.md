# Full guide — free paper deployment (24/7)

Deploy ScalpBot on a **free Linux VPS** for paper trading (XAUUSDT, no MT5). Monitor from your phone or Mac anytime.

```
Your Mac  →  push code to GitHub
     ↓
Oracle Cloud VPS (free)  →  autopilot 24/7 + dashboard
     ↓
Binance/Yahoo prices  →  paper trades  →  logs you can pull
```

---

## What runs where

| Component | Where | Purpose |
|-----------|--------|---------|
| `autopilot.py` | VPS (systemd) | Scans, opens/closes paper baskets |
| `dashboard.py` | VPS port 8501 | Live UI on phone/browser |
| `data/status.json` | VPS | Quick snapshot (balance, P/L, price) |
| `npm run pull-logs` | Your Mac | Download all logs locally |

**Paper mode does not need** MT5 login, AWS Windows, or your Mac running.

---

## Part A — Push code from your Mac

### A1. Confirm secrets are not committed

```bash
cd ~/Desktop/tarding_bot
git status
```

`.env` must **not** appear (only `.env.example` is tracked).

### A2. Push to GitHub (private repo recommended)

```bash
git add .
git commit -m "Paper deploy ready"
git remote add origin git@github.com:YOUR_USER/YOUR_REPO.git   # if not set
git push -u origin main
```

Use HTTPS + personal access token if you prefer.

---

## Part B — Create free Oracle Cloud VPS

### B1. Sign up

1. Go to [cloud.oracle.com](https://cloud.oracle.com)
2. Create account (Always Free tier — no charge if you stay in free limits)

### B2. Create a VM

1. Menu → **Compute** → **Instances** → **Create instance**
2. Settings:

| Field | Value |
|-------|--------|
| Name | `scalpbot-paper` |
| Image | **Ubuntu 22.04** (aarch64 for Ampere) |
| Shape | **Ampere A1** — 1 OCPU, 6 GB RAM (minimum) |
| Networking | Create new VCN (defaults OK) |
| SSH keys | **Generate** or upload your Mac public key |

3. Click **Create**
4. Wait until state = **Running**, copy **Public IP** (e.g. `123.45.67.89`)

### B3. Open firewall ports

1. Instance → **Subnet** → **Security List** → **Add ingress rules**

| Source | Protocol | Port | Description |
|--------|----------|------|-------------|
| `0.0.0.0/0` | TCP | 22 | SSH |
| `0.0.0.0/0` | TCP | 8501 | Dashboard |

> Restrict `8501` to your home IP later if you want more security.

### B4. SSH into the server

From your Mac:

```bash
ssh ubuntu@YOUR_VPS_IP
```

If Oracle created user `opc` instead of `ubuntu`:

```bash
ssh opc@YOUR_VPS_IP
```

---

## Part C — Deploy on the VPS

### C1. Clone your repo

```bash
git clone https://github.com/YOUR_USER/YOUR_REPO.git ~/scalpbot
cd ~/scalpbot
```

### C2. Run one-shot setup

```bash
bash scripts/setup-paper-vps.sh
```

This installs:

- Python venv + `requirements-paper.txt` (no MetaTrader5)
- `.env` from `.env.example` if missing
- **scalpbot-paper** — autopilot 24/7
- **scalpbot-dashboard** — Streamlit on port 8501
- Cron — log bundle every 6 hours

### C3. Edit config (paper — no MT5 password needed)

```bash
nano ~/scalpbot/.env
```

Minimum for paper:

```bash
MT5_SYMBOL=XAUUSDT
MT5_REFERENCE_BALANCE=30
MT5_BASKET_SIZE=10
MT5_LOT=0.01
MT5_BASKET_MIN_PROFIT=0.60
MT5_BASKET_MAX_LOSS=2.00

# Step 2 anti-whipsaw (recommended)
MT5_ZSCORE_MAX_SELL=1.8
MT5_M5_SELL_RELAX=1
MT5_M5_SELL_RELAX_Z_FLOOR=-2.0
MT5_POST_SL_COOLDOWN=75
MT5_STARTUP_WARMUP_SCANS=3

# Paper: scan 24/7 (no London/NY filter)
MT5_USE_SESSION=false
MT5_BASKET_PRICE_SEC=0.25
```

You can leave `MT5_LOGIN`, `MT5_PASSWORD`, `MT5_SERVER` blank for paper.

Restart after edits:

```bash
sudo systemctl restart scalpbot-paper scalpbot-dashboard
```

### C4. Verify bot is running

```bash
sudo systemctl status scalpbot-paper
sudo systemctl status scalpbot-dashboard
```

```bash
tail -f ~/scalpbot/logs/autopilot.log
```

You should see lines like:

```
AUTOPILOT | XAUUSDT | 8760.0h | brain=rules | mode=paper
SCAN #1 | XAUUSDT @ ...
```

Quick status file:

```bash
cat ~/scalpbot/data/status.json
```

---

## Part D — View on your phone / Mac (dashboard)

### Option 1 — Direct (easiest)

On phone or Mac browser:

```
http://YOUR_VPS_IP:8501
```

Bookmark it. Dashboard updates live (price, gates, P/L, trades).

### Option 2 — SSH tunnel (more private)

On your Mac:

```bash
ssh -L 8501:localhost:8501 ubuntu@YOUR_VPS_IP
```

Open: [http://localhost:8501](http://localhost:8501)

### Option 3 — Cloudflare quick tunnel (HTTPS on phone)

On VPS:

```bash
cd ~/scalpbot
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64 -o cloudflared
chmod +x cloudflared
./cloudflared tunnel --url http://localhost:8501
```

Use the `https://….trycloudflare.com` URL on your phone.

---

## Part E — Pull logs to your Mac (on the go)

### E1. Add VPS to Mac `.env`

```bash
# ~/Desktop/tarding_bot/.env
PAPER_HOST=ubuntu@YOUR_VPS_IP
PAPER_REMOTE_DIR=~/scalpbot
```

### E2. Pull everything

```bash
cd ~/Desktop/tarding_bot
npm run pull-logs
```

Downloads to `./pulled/data/` and `./pulled/logs/`.

### E3. Quick terminal summary

```bash
npm run paper-status
# or from pulled copy:
python3 scripts/paper-status.py pulled/data
```

### E4. What gets logged

| File | Contents |
|------|----------|
| `data/status.json` | Live: balance, P/L, price, in_basket, last signal |
| `data/events.jsonl` | Every open, close, heartbeat, session |
| `data/paper_trades.jsonl` | Trade journal |
| `data/agent_decisions.jsonl` | Every brain scan decision |
| `logs/autopilot.log` | Full text log (5 MB rotation) |
| `logs/bundle-latest.tar.gz` | Packed archive (auto every 6h) |

Manual bundle on VPS:

```bash
bash ~/scalpbot/scripts/bundle-logs.sh
scp ubuntu@YOUR_VPS_IP:~/scalpbot/logs/bundle-latest.tar.gz .
```

---

## Part F — Day-to-day commands

### On VPS

```bash
# Restart bot
sudo systemctl restart scalpbot-paper

# Restart dashboard
sudo systemctl restart scalpbot-dashboard

# Live log
tail -f ~/scalpbot/logs/autopilot.log

# Systemd journal
sudo journalctl -u scalpbot-paper -f

# Stop everything
sudo systemctl stop scalpbot-paper scalpbot-dashboard
```

### On Mac

```bash
npm run pull-logs       # download logs
npm run paper-status    # summary
npm run dev             # local paper test (Mac must stay on)
npm run stop            # stop local dev
```

### After code changes

**On VPS:**

```bash
cd ~/scalpbot
git pull
.venv/bin/pip install -r requirements-paper.txt
sudo systemctl restart scalpbot-paper scalpbot-dashboard
```

---

## Part G — Troubleshooting

### Bot not starting

```bash
sudo journalctl -u scalpbot-paper -n 50 --no-pager
```

Common fixes:

- `pip install -r requirements-paper.txt` again
- Check `.env` exists: `ls -la ~/scalpbot/.env`
- Run manually: `cd ~/scalpbot && .venv/bin/python3 autopilot.py --hours 1 --symbol XAUUSDT --no-session --no-sound`

### Dashboard not loading

- Confirm port **8501** open in Oracle security list
- `sudo systemctl status scalpbot-dashboard`
- `curl -I http://localhost:8501` on VPS

### No trades / only SKIP

Normal when filters block (e.g. `ATR_spike`, score &lt; 75). Read `logs/autopilot.log` for `SCAN #` lines and reasons.

### Dashboard shows OPEN BASKET but bot is flat

Restart both services after updating code (basket resume fix). Check `data/paper_trades.jsonl` for matching open/close pairs.

### `npm run pull-logs` fails

- Test SSH: `ssh ubuntu@YOUR_VPS_IP`
- Install rsync on Mac: `brew install rsync`
- Set `PAPER_HOST` in `.env`

---

## Part H — Local Mac testing (not 24/7)

When your Mac is on:

```bash
cd ~/Desktop/tarding_bot
pip install -r requirements-paper.txt   # or full requirements.txt
npm run dev
```

- Dashboard: [http://localhost:8501](http://localhost:8501)
- Logs: `logs/autopilot.log`
- Stops when you close terminal or Mac sleeps

---

## Part I — Later: real MT5 on AWS

Paper VPS ≠ live trading. For Exness demo/live on MT5:

- See [GUIDE.md](GUIDE.md) — AWS Windows + MT5 + `bot.py`
- See [DEPLOY_CONTINUOUS.md](DEPLOY_CONTINUOUS.md) — summary

---

## Checklist

- [ ] Code pushed to GitHub (`.env` not committed)
- [ ] Oracle VM running Ubuntu 22.04
- [ ] Ports 22 + 8501 open
- [ ] `bash scripts/setup-paper-vps.sh` completed
- [ ] `sudo systemctl status scalpbot-paper` = active
- [ ] `http://YOUR_VPS_IP:8501` loads dashboard
- [ ] `PAPER_HOST` set on Mac
- [ ] `npm run pull-logs` works
- [ ] `data/status.json` updating on VPS

**Cost: $0/month** on Oracle Always Free (within tier limits).
