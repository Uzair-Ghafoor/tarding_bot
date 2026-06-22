# Full AWS Setup Guide — Exness MT5 Bot (Private GitHub)

Complete click-by-click guide: push your code to **private GitHub**, launch **AWS Windows**, clone the repo, run the bot, and see **demo trades in MT5**.

---

## What you are building

```
Your Mac  →  push code to private GitHub
     ↓
AWS Windows EC2  →  clone repo  →  install MT5 + Python  →  run bot.py
     ↓
Exness MT5 demo  →  10 trades open  →  close all when profit hit  →  repeat
```

Trades appear in MT5 under **Toolbox → Trade** and **History** on your **demo account** (fake money).

---

## Before you start — checklist

| Item           | You need                                                                |
| -------------- | ----------------------------------------------------------------------- |
| AWS account    | [aws.amazon.com](https://aws.amazon.com) (credit card for verification) |
| GitHub account | Repo already private ✓                                                  |
| Exness demo    | Login, password, server from [my.exness.com](https://my.exness.com)     |
| Your Mac       | Code lives in `~/Desktop/tarding_bot`                                   |
| Budget         | ~$30–45/month while EC2 runs (stop instance when not testing)           |

---

# PART A — Push code to private GitHub (on your Mac)

### A1. Commit and push

Open **Terminal** on your Mac:

```bash
cd ~/Desktop/tarding_bot
git status
```

Confirm **`.env` is NOT listed** (only `.env.example` should be tracked).

```bash
git commit -m "Exness MT5 basket bot"
git remote add origin git@github.com:YOUR_USERNAME/YOUR_REPO_NAME.git
git push -u origin main
```

Replace `YOUR_USERNAME` and `YOUR_REPO_NAME` with your actual private repo.

> **HTTPS alternative:** `https://github.com/YOUR_USERNAME/YOUR_REPO_NAME.git`  
> GitHub will ask for a **Personal Access Token** (not your password).  
> Create one: GitHub → **Settings** → **Developer settings** → **Personal access tokens** → **Tokens (classic)** → Generate → tick **`repo`**.

---

# PART B — Create AWS Windows server

### B1. Log into AWS

1. Go to **[https://console.aws.amazon.com](https://console.aws.amazon.com)**
2. Sign in
3. Top-right: pick a **Region** close to you (e.g. **Europe (London) `eu-west-2`** or **Asia Pacific (Singapore)**)

### B2. Open EC2

1. Top search bar → type **`EC2`** → click **EC2**
2. Left sidebar → **Instances**
3. Click orange **Launch instance** button

### B3. Name and OS

| Field                         | Choose                                 |
| ----------------------------- | -------------------------------------- |
| **Name**                      | `exness-mt5-bot`                       |
| **Application and OS Images** | **Microsoft Windows Server 2022 Base** |
| **Architecture**              | 64-bit (x86)                           |

### B4. Instance type

| Field             | Choose                                                   |
| ----------------- | -------------------------------------------------------- |
| **Instance type** | **`t3.small`** (2 vCPU, 2 GB RAM) — enough for MT5 + bot |

### B5. Key pair (login)

1. **Key pair** → **Create new key pair**
2. Name: `exness-bot-key`
3. Type: **RSA**
4. Format: **`.pem`** (for reference; Windows uses password login)
5. Click **Create** — `.pem` file downloads to your Mac (keep it safe)

### B6. Network settings (IMPORTANT)

1. Click **Edit** on Network settings
2. **Allow RDP traffic from:**
   - Choose **My IP** (NOT "Anywhere" — that is insecure)
3. Leave SSH unchecked (Windows uses RDP, not SSH)

### B7. Storage

| Field    | Choose                           |
| -------- | -------------------------------- |
| **Size** | **30 GiB** gp3 (default is fine) |

### B8. Launch

1. Click **Launch instance**
2. Click **View all instances**
3. Wait until **Instance state** = **Running** (green)
4. Wait until **Status check** = **2/2 checks passed** (~5–10 min)

### B9. Get Windows password

1. Select your instance (checkbox)
2. Click **Connect** (top right)
3. Tab: **RDP client**
4. Click **Get password**
5. Click **Browse** → upload the `.pem` key file you downloaded
6. Click **Decrypt password**
7. **Copy and save** the Administrator password (you need it once)

### B10. Copy your connection address (DNS or IP)

Back on **EC2 → Instances** → click your instance. In the details panel below, find **either**:

| Field                   | Example                                           | Use for RDP?                                 |
| ----------------------- | ------------------------------------------------- | -------------------------------------------- |
| **Public IPv4 address** | `3.120.45.67`                                     | ✅ Yes                                       |
| **Public IPv4 DNS**     | `ec2-3-120-45-67.eu-west-2.compute.amazonaws.com` | ✅ Yes — **use this if you don't see an IP** |

**Both work the same** in Microsoft Remote Desktop — paste whichever AWS shows you.

> **Only see Public DNS, no IPv4?** That's normal on many AWS accounts. Use the **Public IPv4 DNS** hostname — it resolves to your server. You do **not** need a separate IP.

> **See neither DNS nor IP?** Your instance may have no public access. EC2 → instance → **Actions → Networking → Manage IP addresses** → assign an **Elastic IP** or enable **Auto-assign public IPv4** on the subnet, then stop/start the instance.

---

# PART C — Connect to AWS (Remote Desktop)

### C1. On your Mac — Microsoft Remote Desktop

1. Install **Microsoft Remote Desktop** from Mac App Store (free)
2. Open it → **Add PC**
3. **PC name:** paste your **Public IPv4 DNS** from AWS (e.g. `ec2-12-34-56-78.eu-west-2.compute.amazonaws.com`)  
   — or use **Public IPv4 address** if you have one (e.g. `12.34.56.78`)
4. **User account:** Add User Account
   - Username: `Administrator`
   - Password: paste the decrypted password from B9
5. Click **Add** → double-click the PC to connect

You should see the **Windows Server desktop**.

### C2. First-time Windows setup on the server

1. Close any popups (Server Manager is fine to minimize)
2. Open **Microsoft Edge** on the server (for downloads)

---

# PART D — Install software on AWS

Do all of this **inside the Windows RDP session**.

### D1. Install Git (to clone private repo)

1. Edge → go to **[https://git-scm.com/download/win](https://git-scm.com/download/win)**
2. Download **64-bit Git for Windows Setup**
3. Run installer → click **Next** through defaults → **Install**
4. Close installer

### D2. Install Exness MetaTrader 5

1. Edge → **[https://www.exness.com/metatrader-5/](https://www.exness.com/metatrader-5/)**
2. Download MT5 for Windows
3. Run installer → install to default path:
   ```
   C:\Program Files\MetaTrader 5\terminal64.exe
   ```
4. Open **MetaTrader 5** after install

### D3. Log into Exness DEMO in MT5

1. MT5 opens → **File → Login to Trade Account**
2. Enter from [my.exness.com](https://my.exness.com) → **My accounts** → expand demo card:
   - **Login:** your MT5 number (e.g. `108654774`)
   - **Password:** your **trading** password
   - **Server:** exact string (e.g. `Exness-MT5Trial9`)
3. Click **OK** — bottom-right should show connection bars (connected)

### D4. Enable algo trading in MT5

1. Toolbar → click **Algo Trading** button until it is **GREEN**
2. **Tools → Options → Expert Advisors** tab:
   - ✅ Allow algorithmic trading
   - ✅ Allow DLL imports (if shown)
3. Click **OK**

### D5. Find your symbol name

1. **View → Market Watch** (Ctrl+M)
2. Right-click → **Show All**
3. Find gold — note **exact** name: `XAUUSD`, `XAUUSDm`, etc.
4. Double-click it so it appears in Market Watch

---

# PART E — Clone your PRIVATE GitHub repo

### E1. Create GitHub token (for private repo clone)

On your **Mac** (or any browser):

1. GitHub.com → profile photo → **Settings**
2. Left sidebar bottom → **Developer settings**
3. **Personal access tokens** → **Tokens (classic)** → **Generate new token (classic)**
4. Note: `AWS clone token`
5. Expiration: 90 days (or your choice)
6. Scopes: tick **`repo`** (full control of private repositories)
7. **Generate token** → **copy the token** (starts with `ghp_...`) — you won't see it again

### E2. Clone on AWS Windows

**What this means:** open a command window on your AWS server (the Windows desktop you see after Remote Desktop), then paste the git commands.

1. On the AWS Windows desktop, click the **Start** button (Windows icon, bottom-left).
2. Type **`PowerShell`** on the keyboard.
3. You will see **Windows PowerShell** in the list → **right-click** it → click **Run as administrator**.
4. If a popup asks “Do you want to allow…?” → click **Yes**.
5. A **blue window** opens — that is PowerShell. Click inside it and paste the commands below.

Run these commands (one block, press Enter after each line):

```powershell
cd C:\
git clone https://github.com/YOUR_USERNAME/YOUR_REPO_NAME.git tarding_bot
```

When Git asks for login:
   - **Username:** your GitHub username
   - **Password:** paste the **`ghp_...` token** (NOT your GitHub password)

```powershell
cd C:\Users\Administrator\trading_bot
dir
```

You should see: `bot.py`, `config.py`, `setup_aws.ps1`, `.env.example`, etc.

> **If clone fails:** check repo name, token has `repo` scope, and repo is shared with your GitHub user.

---

# PART F — Configure `.env` (your secrets)

`.env` is **not in GitHub** (private, local only). You create it on the server.

```powershell
cd C:\Users\Administrator\trading_bot
copy .env.example .env
notepad .env
```

Fill in your real values:

```env
MT5_LOGIN=108654774
MT5_PASSWORD=your_trading_password
MT5_SERVER=Exness-MT5Trial9

MT5_PATH=C:\Program Files\MetaTrader 5\terminal64.exe

MT5_SYMBOL=XAUUSDm
MT5_SYMBOL_FALLBACKS=XAUUSD,XAUUSDm

MT5_LOT=0.01
MT5_BASKET_SIZE=10
MT5_BASKET_MIN_PROFIT=0.60
MT5_BASKET_MAX_LOSS=2.00
MT5_MAX_DAILY_LOSS=5.0
MT5_DEMO_ONLY=true
```

**Save** and close Notepad.

---

# PART G — Install Python + bot dependencies

In the same **Administrator PowerShell**:

```powershell
cd C:\Users\Administrator\trading_bot
Set-ExecutionPolicy -Scope Process Bypass
.\setup_aws.ps1
```

This installs Python 3.12 (if missing), creates `.venv`, and installs `MetaTrader5` package.

Wait until it finishes with green **Next steps** message.

---

# PART H — Test before trading

**MT5 must be open and logged into demo.**

```powershell
cd C:\Users\Administrator\trading_bot
.\.venv\Scripts\python.exe test_connection.py
```

**Good output:**

```
Symbol:        XAUUSDm
Spread:        ...
Connected | login=... | demo=True
OK — ready to run bot.py
```

**If it fails:**

| Error                   | Fix                                            |
| ----------------------- | ---------------------------------------------- |
| `MT5 initialize failed` | Open MT5 first, check `MT5_PATH` in `.env`     |
| `Symbol not found`      | Fix `MT5_SYMBOL` to match Market Watch exactly |
| `account is not demo`   | Using live login with `MT5_DEMO_ONLY=true`     |

---

# PART I — Start the bot (places demo trades)

```powershell
cd C:\Users\Administrator\trading_bot
.\run_bot.ps1
```

### What you should see

**In PowerShell / log:**

```
Exness basket scalp | XAUUSDm | batch=10 | close all at +$0.60
trend=buy (40%) | open=0/10 | basket P/L=$0.00
BASKET OPEN | 10 × 0.01 BUY | trend=buy
trend=buy | open=10/10 | basket P/L=$0.35 | target=+$0.60
BASKET CLOSE (profit) | 10/10 tickets | total P/L $0.68
```

**In MT5:**

1. **Toolbox → Trade** — up to 10 open positions
2. When basket closes — they disappear from Trade
3. **Toolbox → History** — closed trades with profit/loss

### Log files

| File                               | What                   |
| ---------------------------------- | ---------------------- |
| `C:\Users\Administrator\trading_bot\logs\bot.log`      | Main log               |
| `C:\Users\Administrator\trading_bot\logs\live_run.log` | Console output         |
| `C:\Users\Administrator\trading_bot\data\trades.jsonl` | Every open/close event |

---

# PART J — Run 24/7 (keep bot alive after reboot)

### J1. Schedule bot at Windows login

```powershell
cd C:\Users\Administrator\trading_bot
Set-ExecutionPolicy -Scope Process Bypass
.\install_scheduled_task.ps1
```

### J2. Auto-start MT5

1. Press **Win+R** → type `shell:startup` → Enter
2. Right-click → **New → Shortcut**
3. Target:
   ```
   C:\Program Files\MetaTrader 5\terminal64.exe
   ```
4. Name: `MT5` → Finish

### J3. Keep session alive when you disconnect RDP

When you close Remote Desktop, Windows may pause apps. On AWS this is usually OK if the instance keeps running, but if the bot stops:

1. **Start** → **Settings** → **System** → **Power & sleep**
2. Set sleep to **Never** (plugged in and on battery)

---

# PART K — Update code later (private repo)

When you change code on Mac and push:

**On Mac:**

```bash
cd ~/Desktop/tarding_bot
git add .
git commit -m "Update strategy"
git push
```

**On AWS (PowerShell):**

```powershell
cd C:\Users\Administrator\trading_bot
git pull
.\run_bot.ps1
```

Your `.env` on AWS is **not touched** by `git pull`.

---

# PART L — Stop AWS charges when not testing

1. AWS Console → **EC2** → **Instances**
2. Select instance → **Instance state** → **Stop instance**

Stopped = no compute charges (small storage fee only).  
**Start instance** again when you want to test.

To delete completely: **Terminate instance** (cannot undo).

---

# PART M — Bot settings ($30 demo, 10-trade basket)

| Setting                 | Value  | Meaning                                       |
| ----------------------- | ------ | --------------------------------------------- |
| `MT5_BASKET_SIZE`       | `10`   | Open 10 trades at once                        |
| `MT5_BASKET_MIN_PROFIT` | `0.60` | Close **all 10** when combined profit ≥ $0.60 |
| `MT5_BASKET_MAX_LOSS`   | `2.00` | Close all if combined loss hits −$2           |
| `MT5_LOT`               | `0.01` | Tiny size per trade                           |
| `MT5_MAX_DAILY_LOSS`    | `5.00` | Stop new batches after −$5 day                |
| `MT5_DEMO_ONLY`         | `true` | Refuses live account                          |

Lower profit target (faster cycles):

```env
MT5_BASKET_MIN_PROFIT=0.40
```

---

# PART N — Troubleshooting

| Problem                           | Fix                                                                                  |
| --------------------------------- | ------------------------------------------------------------------------------------ |
| Can't RDP                         | Use **Public IPv4 DNS** (not only IP); security group must allow **your IP** on 3389 |
| No Public IPv4, only DNS          | Normal — paste DNS into Remote Desktop **PC name** field                             |
| `git clone` asks password forever | Use `ghp_` token, not GitHub password                                                |
| Bot runs but no trades            | Normal outside London/NY hours; wait for `trend=buy/sell` in log                     |
| `Open failed ret=10027`           | Algo Trading not green in MT5                                                        |
| `Not enough money`                | Reduce `MT5_BASKET_SIZE` to 5 or lower lot                                           |
| Bot died after closing RDP        | Run `install_scheduled_task.ps1`, keep MT5 open                                      |
| Wrong symbol                      | Match Market Watch exactly in `.env`                                                 |

---

# PART O — Go live (ONLY after demo success)

1. Demo profitable for **2–4 weeks**
2. Change `.env`: live login, live server, `MT5_DEMO_ONLY=false`
3. Start with same **0.01 lot**
4. Never risk money you can't afford to lose

---

# Quick reference — copy/paste order on AWS

```powershell
# 1. Clone (once)
cd C:\
git clone https://github.com/YOUR_USERNAME/YOUR_REPO_NAME.git tarding_bot

# 2. Config (once)
cd C:\Users\Administrator\trading_bot
copy .env.example .env
notepad .env

# 3. Setup (once)
Set-ExecutionPolicy -Scope Process Bypass
.\setup_aws.ps1

# 4. Every time (MT5 must be open + demo logged in)
cd C:\Users\Administrator\trading_bot
.\.venv\Scripts\python.exe test_connection.py
.\run_bot.ps1
```

---

## File map

```
C:\Users\Administrator\trading_bot\
├── bot.py              ← main bot
├── .env                ← YOUR secrets (never in GitHub)
├── .env.example        ← template (in GitHub)
├── setup_aws.ps1       ← one-time install
├── run_bot.ps1         ← start bot
├── test_connection.py  ← test MT5 connection
├── logs\bot.log
└── data\trades.jsonl
```
