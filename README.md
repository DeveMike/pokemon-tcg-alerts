# Pokémon TCG New-Product Alerts 🇫🇮

Watches Finnish online stores for **new Pokémon TCG products** and sends an instant push notification with a direct product link to your phone (iOS / Android) via [ntfy](https://ntfy.sh).

Built for big releases (e.g. *Pokémon TCG: 30th Celebration*), where products sell out within minutes of appearing.

> 🤖 **Built with AI:** all code in this repository was written by **Claude Opus 5.5** (Anthropic) through conversational, AI-assisted development. My part was defining the requirements, testing against the live stores, and iterating on the results.

```
Prisma.fi ─────────┐  server-rendered search page → regex
Verkkokauppa.com ──┼─ JS-rendered search page    → headless Chromium (Playwright)
Kärkkäinen ────────┘  server-rendered listing     → regex
          │
          ▼
   diff vs. state.json  ──►  new product?  ──►  ntfy push  ──►  📱 banner + "open store" button
```

## Features

- **Three stores**, each scraped with the approach its frontend requires
  - **Prisma**: search results are server-rendered, parsed straight from HTML
  - **Verkkokauppa.com**: the search API rejects non-browser clients, so the search page is rendered in headless Chromium
  - **Kärkkäinen**: the category listing only shows in-stock items, so a product *returning* to the list also triggers an alert
- **Alerts only on real changes**: the first run silently stores a baseline, after that only new products trigger an alert
- **Survives restarts**: state is persisted, so products that appeared while the script was offline are caught on the next start
- **Push with a direct link** (priority 5 → banner + sound), tap to open the product page
- Polite polling: randomized interval and delays, junk filter (clothing, plushies, accessories)

## Setup

```bash
git clone https://github.com/<your-username>/pokemon-tcg-alerts.git
cd pokemon-tcg-alerts
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium

cp .env.example .env   # set your own NTFY_TOPIC
```

On your phone: install **ntfy** (App Store / Google Play) → **+** → subscribe to the same topic.

```bash
python3 monitor.py --test   # sends a test notification
python3 monitor.py          # starts watching (every ~3 min)
```

On macOS, `caffeinate -i python3 monitor.py` keeps the machine awake while the script runs.

## Configuration (`.env`)

| Variable | Default | Description |
|---|---|---|
| `NTFY_TOPIC` | *(required)* | Your ntfy topic. Treat it like a password, since anyone who knows it can read and post. |
| `INTERVAL` | `180` | Seconds between rounds |
| `QUERY` | `pokemon kortit 30th` | Prisma search term |
| `VK_QUERY` | `pokemon kortit 30th` | Verkkokauppa.com search term |

## Testing an alert

Remove one product from the saved state, and it will be detected as "new" on the next run:

```bash
python3 -c "
import json; s=json.load(open('state.json')); k=s['Prisma']['ever'][0]
s['Prisma']['ever'].remove(k); s['Prisma']['last'].remove(k)
json.dump(s,open('state.json','w'),indent=1); print('Removed:',k)"
python3 monitor.py
```

## Tech

Python · requests · Playwright (headless Chromium) · ntfy (HTTP pub/sub push)

## Roadmap

- [ ] Run 24/7 on a cloud VM (systemd service)
- [ ] More stores (Gigantti, Power, Puolenkuun Pelit)
- [ ] Discord webhook output
- [ ] Price-change alerts

---
*Personal project. Polls public pages at a low rate. Respect the stores' terms of use.*
