# Exness MT5 Scalp Bot — Full AWS Deployment Guide

Automated micro-scalping bot for **Exness + MetaTrader 5**, designed to run 24/7 on **AWS Windows**. Starts on **demo**; switch to live only after proven results.

---

## What the bot does

| Feature | Detail |
|--------|--------|
| **Style** | 5–10 tiny trades (0.01 lot), close each ASAP when profit beats spread |
| **Edge** | M15 trend filter + M1 RSI pullback (no random entries) |
| **Sessions** | London + NY hours (UTC) — best Exness liquidity |
| **Safety** | Daily loss cap, 3-loss pause, spread filter, demo-only guard |
| **Broker** | Exness MT5 (demo first) |

### Honest expectation

No bot **guarantees** profit. This design avoids the mistakes that killed your Binance bot (random entries, fees eating tiny wins, no trend filter). You must:

1. Run **demo for at least 2–4 weeks**
2. Track win rate and net P/L in `data/trades.jsonl`
3. Only go live if demo is **consistently green after spread**

Target on demo: **>55% win rate** and **positive daily P/L** over 20+ trading days before real money.

---

## Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  AWS Windows    │     │  Exness MT5      │     │  Exness servers │
│  EC2 instance   │────▶│  terminal64.exe  │────▶│  (demo/live)    │
│  Python bot.py  │     │  (must be open)  │     │                 │
└─────────────────┘     └──────────────────┘     └─────────────────┘
```

**Important:** MetaTrader’s Python API only works on **Windows** with the **MT5 terminal running**. Linux/Mac AWS instances will **not** work.

---

## Part 1 — Exness demo account

### 1.1 Create demo account

1. Go to [Exness Personal Area](https://my.exness.com)
2. **My accounts** → **Open account** → **Demo**
3. Choose **MT5**, set balance (e.g. $500–$10,000), create password

### 1.2 Copy credentials (exact strings)

1. **My accounts** → switch to **Demo**
2. Click the **dropdown (▼)** on your MT5 demo card
3. Copy:
   - **MT5 login** (number)
   - **Server** (e.g. `Exness-MT5Trial9` — **yours may differ**)
   - **Trading password** (you set this; not your website login)

> Server names are assigned per account. Never guess — always copy from Personal Area.

### 1.3 Install Exness MT5 on your PC (test first)

1. Download: [Exness MetaTrader 5](https://www.exness.com/metatrader-5/)
2. Install and log in with demo credentials
3. **View → Market Watch** → find symbol (often `EURUSDm` or `XAUUSDm`)
4. Enable **Algo Trading** (button in toolbar must be green)
5. **Tools → Options → Expert Advisors** → allow algo trading

---

## Part 2 — AWS Windows server

### 2.1 Launch EC2 instance

| Setting | Recommendation |
|---------|----------------|
| **OS** | Microsoft Windows Server 2022 Base |
| **Instance** | `t3.small` or `t3.medium` (2 GB+ RAM) |
| **Storage** | 30 GB gp3 |
| **Region** | Close to Exness servers (e.g. `eu-west-1`, `ap-southeast-1`) |

### 2.2 Security group

| Type | Port | Source |
|------|------|--------|
| RDP | 3389 | **Your IP only** (not 0.0.0.0/0) |

### 2.3 Connect via RDP

1. AWS Console → EC2 → instance → **Connect** → **RDP client**
2. Download remote desktop file, connect with Administrator password

### 2.4 Install on the server

1. **Exness MT5** — same installer as desktop
2. Log into **demo account**, enable **Algo Trading**
3. Leave MT5 running (minimized is fine)

---

## Part 3 — Deploy the bot

### 3.1 Copy project to server

Option A — zip from your Mac and upload via RDP  
Option B — git clone if repo is on GitHub:

```powershell
cd C:\
git clone <your-repo-url> tarding_bot
cd tarding_bot
```

### 3.2 Run setup script

Open **PowerShell** in the project folder:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\setup_aws.ps1
```

### 3.3 Configure `.env`

Edit `C:\tarding_bot\.env`:

```env
MT5_LOGIN=YOUR_DEMO_LOGIN
MT5_PASSWORD=YOUR_TRADING_PASSWORD
MT5_SERVER=Exness-MT5Trial9
MT5_SYMBOL=EURUSDm
MT5_LOT=0.01
MT5_DEMO_ONLY=true
```

Use **exact** server and symbol from MT5 Market Watch.

### 3.4 Test connection

```powershell
cd C:\tarding_bot
.\.venv\Scripts\python.exe test_connection.py
```

Expected output:

```
Symbol:        EURUSDm
Spread:        12 points
Spread cost:   $0.0240 per round-trip
Min profit:    $0.1200
M15 trend:     buy (45%)
In session:    True
OK — ready to run bot.py
```

Fix any errors before running the bot.

### 3.5 Start the bot

```powershell
.\run_bot.ps1
```

Logs:

- `logs/bot.log` — main log
- `logs/live_run.log` — console output
- `data/trades.jsonl` — every open/close event

### 3.6 Run 24/7 after reboot

```powershell
.\install_scheduled_task.ps1
```

Also configure MT5 to **auto-start at Windows login** and stay logged in. The bot needs an active MT5 session.

---

## Part 4 — Settings tuned for Exness

| Variable | Default | Meaning |
|----------|---------|---------|
| `MT5_SYMBOL` | `EURUSDm` | Low spread on Exness Standard |
| `MT5_LOT` | `0.01` | Micro size (~$0.10/pip on EUR) |
| `MT5_MIN_TRADES` | `5` | Minimum concurrent positions |
| `MT5_MAX_TRADES` | `10` | Maximum concurrent positions |
| `MT5_MIN_PROFIT_CLOSE` | `0.12` | Close when profit ≥ $0.12 |
| `MT5_SPREAD_PROFIT_MULT` | `2.5` | Auto-raise target if spread is wide |
| `MT5_STOP_LOSS_POINTS` | `120` | ~12 pips on 5-digit EUR |
| `MT5_MAX_DAILY_LOSS` | `3.0` | Stop new entries after −$3 day |
| `MT5_MAX_CONSEC_LOSSES` | `3` | Pause after 3 losses in a row |
| `MT5_USE_SESSION` | `true` | Trade London + NY only |

### Gold vs EUR

For **XAUUSDm** (gold), widen settings:

```env
MT5_SYMBOL=XAUUSDm
MT5_MIN_PROFIT_CLOSE=0.25
MT5_STOP_LOSS_POINTS=300
MT5_MAX_SPREAD_POINTS=40
```

---

## Part 5 — Demo validation checklist

Run demo until **all** are true:

- [ ] Bot runs 24h without crashes (`logs/bot.log` no repeated errors)
- [ ] Trades only open **with** M15 trend (check logs: `trend=buy` or `trend=sell`)
- [ ] Closes happen at profit, not random timeouts
- [ ] **20+ trading days** of data in `data/trades.jsonl`
- [ ] Win rate **≥ 55%**
- [ ] Net P/L **positive** after all closes (sum profits in jsonl)
- [ ] Max drawdown acceptable (never hit daily loss limit daily)

### Quick P/L check (PowerShell)

```powershell
Get-Content data\trades.jsonl | Select-String "close_profit" | Measure-Object
Get-Content data\trades.jsonl | Select-String "close_sl"
```

---

## Part 6 — Go live (only after demo success)

1. Open **live** MT5 account in Exness (minimum deposit per Exness rules)
2. Copy **live** login, server, password to `.env`
3. Set `MT5_DEMO_ONLY=false`
4. Start with **same 0.01 lot** — do not scale until live matches demo
5. Set `MT5_MAX_DAILY_LOSS=2.0` or lower for small accounts

**Never skip demo.** Live spreads, slippage, and psychology differ.

---

## Part 7 — Troubleshooting

| Problem | Fix |
|---------|-----|
| `MT5 initialize failed` | MT5 not installed or wrong `MT5_PATH` |
| `account is not demo` | `.env` has live login but `MT5_DEMO_ONLY=true` |
| `Symbol not found` | Copy exact name from Market Watch (`EURUSDm` vs `EURUSD`) |
| `Open failed ret=10027` | Enable **Algo Trading** in MT5 |
| `Open failed ret=10016` | Invalid stops — increase `MT5_STOP_LOSS_POINTS` |
| Bot stops when RDP closes | Use Task Scheduler + keep session alive, or EC2 "Keep alive" RDP |
| No trades for hours | Normal — waits for trend + session + pullback |
| Spread too high | Bot skips entry; try EURUSDm during London session |

---

## Part 8 — AWS cost estimate

| Resource | ~Monthly |
|----------|----------|
| t3.small Windows | $25–35 |
| 30 GB storage | $3 |
| Data transfer | $1–5 |
| **Total** | **~$30–45/mo** |

Stop the instance when not testing to save money.

---

## File reference

```
bot.py                  # Main loop
config.py               # Settings
mt5_client.py           # MT5 orders
strategy.py             # M1 entries
trend.py                # M15 trend filter
session.py              # Trading hours
risk.py                 # Loss pause
test_connection.py      # Pre-flight check
setup_aws.ps1           # One-time install
run_bot.ps1             # Start bot
install_scheduled_task.ps1
.env.example            # Template
GUIDE.md                # This file
logs/
data/trades.jsonl
```

---

## Support checklist before asking for help

1. Output of `test_connection.py`
2. Last 50 lines of `logs/bot.log`
3. Your `.env` **without** password (login + server + symbol only)
4. Screenshot of MT5 Market Watch showing symbol name
