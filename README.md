# Exness MT5 Basket Scalp Bot

Automated bot for **Exness + MetaTrader 5** on a **demo account**.

- Opens **10 tiny trades** at once (0.01 lot)
- When **combined profit** hits target → **closes all 10** → opens a fresh batch
- **M15 trend + M1 pullback** entries
- Runs on **Windows AWS** with MT5 terminal open

> Trades show in your **MT5 demo** (Toolbox → Trade / History).

**Full step-by-step AWS guide:** [GUIDE.md](GUIDE.md) — EC2, RDP, private GitHub clone, MT5, run bot.

## Setup

```bash
cp .env.example .env    # fill in your Exness demo credentials
```

## AWS Windows

```powershell
git clone https://github.com/YOUR_USER/exness-mt5-bot.git
cd exness-mt5-bot
copy .env.example .env
notepad .env
.\setup_aws.ps1
.\.venv\Scripts\python.exe test_connection.py
.\run_bot.ps1
```

## Backtest + interactive charts (Plotly, not PNG)

```bash
pip install -r requirements.txt
python run_backtest.py                  # opens charts in browser + loss analysis
python run_backtest.py --no-show          # tables only (headless)
python run_backtest.py --pair EURUSD      # single-pair deep-dive
```

Run in background:  nohup python paper_bot.py --hours 48 &

## Mac paper trading (no MT5)

Test locally with **live Yahoo/Binance data** (~15 min delay on forex):

```bash
pip install -r requirements.txt

# Terminal 1 — run the bot (logs + sounds in this window)
python paper_bot.py --hours 48 --symbol EURUSD

# Terminal 2 — live watcher (extra SCAN/HOLD lines + sounds if bot runs in background)
python paper_watch.py

# Background bot + foreground watcher:
nohup python paper_bot.py --hours 48 > logs/paper.out 2>&1 &
python paper_watch.py

python paper_stats.py
```

**Sounds (Mac):** Glass = basket open | Hero = win close | Basso = loss close  
Disable: `--no-sound` on either script.

Logs: `data/paper_trades.jsonl` | `logs/paper_bot.log`


```bash
git add .
git status    # .env must NOT appear
git commit -m "Exness MT5 basket bot"
git push
```

**Never commit `.env`** — it holds your password.

## Binance bot

The old Binance bot lives at `~/Desktop/binance/` (separate folder).
