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

## Git

```bash
git add .
git status    # .env must NOT appear
git commit -m "Exness MT5 basket bot"
git push
```

**Never commit `.env`** — it holds your password.

## Binance bot

The old Binance bot lives at `~/Desktop/binance/` (separate folder).
