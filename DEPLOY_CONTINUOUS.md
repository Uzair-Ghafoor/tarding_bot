# Run ScalpBot 24/7 (Step 2 tuned)

Mac paper mode is for testing only. For **continuous trading**, use **AWS Windows + Exness MT5**.

## Step 2 filters (already in code)

| Setting | Value | Effect |
|---------|-------|--------|
| `MT5_ZSCORE_MAX_SELL` | 1.8 | No shorts when Z &lt; −1.8 (less chasing) |
| `MT5_M5_SELL_RELAX_Z_FLOOR` | −2.0 | No relaxed M5 sell when oversold |
| `MT5_POST_SL_COOLDOWN` | 75s | Same-side re-entry blocked after stop |
| `MT5_STARTUP_WARMUP_SCANS` | 3 | No trade on first 3 scans after start |
| `MT5_ATR_SL_VOL_BOOST` | 1.25× | Wider SL when ATR ratio ≥ 1.75 |

Copy `.env.example` → `.env` on the server and fill Exness demo credentials.

---

## Production: AWS Windows + MT5 (recommended)

### 1. Launch EC2

- **OS:** Windows Server 2022
- **Size:** `t3.small` or larger
- **Storage:** 30 GB+
- Full click-by-click: [GUIDE.md](GUIDE.md)

### 2. On the server

```powershell
git clone YOUR_PRIVATE_REPO C:\Users\Administrator\trading_bot
cd C:\Users\Administrator\trading_bot
.\setup_aws.ps1
notepad .env   # MT5 login, password, server, XAUUSDT
.\.venv\Scripts\python.exe test_connection.py
```

### 3. MT5 terminal

1. Install **Exness MT5** and log into **demo**
2. Enable **Algo Trading** (toolbar button)
3. Add **XAUUSDT** to Market Watch
4. Leave MT5 running (minimized is OK)

### 4. Start bot manually (test)

```powershell
.\run_bot.ps1
```

Logs: `logs\bot.log` and `logs\live_run.log`

### 5. Auto-start on boot

```powershell
# PowerShell as Administrator
.\install_scheduled_task.ps1
```

Task **ExnessMT5ScalpBot** runs `run_bot.ps1` at Windows logon.  
Keep an RDP session logged in or use a always-on user so MT5 stays connected.

### 6. After code updates

```powershell
cd C:\Users\Administrator\trading_bot
git pull
.\.venv\Scripts\pip.exe install -r requirements.txt
# Restart: Task Scheduler → ExnessMT5ScalpBot → End → Run
```

---

## Paper 24/7 on Linux VPS (optional, no real MT5)

For signal testing only (Binance/Yahoo feed, no broker orders):

```bash
# On Ubuntu VPS
git clone YOUR_REPO ~/scalpbot && cd ~/scalpbot
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env   # no MT5 login needed for paper

# systemd user service
sudo cp scripts/scalpbot-paper.service /etc/systemd/system/
sudo systemctl enable --now scalpbot-paper
journalctl -u scalpbot-paper -f
```

Dashboard (optional): `streamlit run dashboard.py --server.port 8501` behind a firewall.

---

## Mac (not 24/7)

```bash
npm run dev    # paper + dashboard while Mac is awake
npm run stop
```

---

## Checklist before live demo

- [ ] `test_connection.py` OK on AWS
- [ ] `.env` has `MT5_DEMO_ONLY=true`
- [ ] Symbol **XAUUSDT** visible in MT5
- [ ] Step 2 vars in `.env` (see `.env.example`)
- [ ] Scheduled task or `run_bot.ps1` running
- [ ] First trades appear in MT5 **Toolbox → Trade**
