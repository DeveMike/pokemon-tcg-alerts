#!/usr/bin/env python3
"""
Pokémon-uutuusvahti: Prisma + Verkkokauppa.com + Kärkkäinen
Hälyttää puhelimeen (ntfy) linkin kanssa, kun kaupan listaan ilmestyy UUSI tuote.

Ajo:  python3 monitor.py           (pyörii jatkuvasti)
      python3 monitor.py --test    (testi-ilmoitus)
"""
import json, os, random, re, sys, time
from pathlib import Path
from urllib.parse import quote

import requests


def load_dotenv(path=Path(__file__).with_name(".env")):
    """Lukee .env-tiedoston ympäristömuuttujiksi (ei vaadi ylimääräisiä kirjastoja)."""
    if path.exists():
        for line in path.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


load_dotenv()

# ================= ASETUKSET =================
NTFY_TOPIC = os.getenv("NTFY_TOPIC")
if not NTFY_TOPIC:
    sys.exit("NTFY_TOPIC puuttuu. Kopioi .env.example -> .env ja aseta oma topic.")
INTERVAL = int(os.getenv("INTERVAL", "180"))            # sekuntia kierrosten välillä
QUERY = os.getenv("QUERY", "pokemon kortit 30th")        # Prisman hakusana
VK_QUERY = os.getenv("VK_QUERY", "pokemon kortit 30th")  # Verkkokaupan hakusana

PRISMA_URL = f"https://www.prisma.fi/haku?search={quote(QUERY)}"
VK_URL = f"https://www.verkkokauppa.com/fi/search?query={quote(VK_QUERY)}"
KARKK_URL = ("https://www.karkkainen.com/verkkokauppa/kerailykortit?offset=0"
             "&facet=attributes.Ker%C3%A4ilykortin+sarja%3APokemon+ker%C3%A4ilykortit")

# Hakutuloksista pois (vaatteet, lelut, tarvikkeet)
EXCLUDE = re.compile(r"paita|sukat|pyyhekumi|puzzle|kansio|portfolio|album|pehmo|plush|figuuri|"
                     r"kalenteri|switch|muki|reppu|sleeves|suojat|squishmallow", re.I)
# =============================================

STATE_FILE = Path(__file__).with_name("state.json")
S = requests.Session()
S.headers.update({
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/129.0 Safari/537.36",
    "Accept-Language": "fi-FI,fi;q=0.9,en;q=0.8",
})


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def ok(name):
    return "pok" in name.lower() and not EXCLUDE.search(name)


def slug_name(slug):
    return re.sub(r"-?\d{6,}$", "", slug).replace("-", " ").strip().capitalize()


# ---------- KAUPAT: palauttaa {id: (nimi, linkki)} tai None jos haku ei toimi ----------
def prisma():
    html = S.get(PRISMA_URL, timeout=20).text
    out = {}
    for path, pid, slug in re.findall(r'href="(?:https://www\.prisma\.fi)?(/tuotteet/(\d+)/([a-z0-9-]+))"', html):
        name = slug_name(slug)
        if ok(name):
            out[f"prisma:{pid}"] = (name, "https://www.prisma.fi" + path)
    return out


_vk_warned = False


def verkkokauppa():
    """Verkkokaupan haku-API ei vastaa skripteille -> renderöidään hakusivu oikealla selaimella."""
    global _vk_warned
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        if not _vk_warned:
            log("!! Verkkokauppa vaatii Playwrightin: pip install playwright && playwright install chromium")
            _vk_warned = True
        return None
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(user_agent=S.headers["User-Agent"], locale="fi-FI")
        page.goto(VK_URL, timeout=45000)
        page.wait_for_selector('a[href*="/fi/product/"]', timeout=30000)
        page.wait_for_timeout(2000)  # annetaan listan latautua loppuun
        hrefs = page.eval_on_selector_all('a[href*="/fi/product/"]', "els => els.map(e => e.getAttribute('href'))")
        browser.close()
    out = {}
    for href in hrefs:
        m = re.search(r"/fi/product/(\d+)/([A-Za-z0-9-]+)", href or "")
        if not m:
            continue
        name = m.group(2).replace("-", " ")
        if ok(name):
            out[f"vk:{m.group(1)}"] = (name, f"https://www.verkkokauppa.com/fi/product/{m.group(1)}/{m.group(2)}")
    return out


def karkkainen():
    html = S.get(KARKK_URL, timeout=20).text
    out = {}
    for path, slug in re.findall(r'href="(?:https://www\.karkkainen\.com)?(/verkkokauppa/([a-z0-9-]+))"', html):
        name = slug_name(slug)
        if ok(name):
            out[f"karkk:{slug}"] = (name, "https://www.karkkainen.com" + path)
    return out


SHOPS = [  # (nimi, funktio, hälytä myös kun tuote palaa listalle)
    ("Prisma", prisma, False),
    ("Verkkokauppa", verkkokauppa, False),
    ("Kärkkäinen", karkkainen, True),  # Kärkkäisen lista näyttää vain saatavilla olevat
]


# ---------- ILMOITUS ----------
def notify(title, msg, url, priority=5, tag="rotating_light"):
    try:
        S.post("https://ntfy.sh", timeout=10, json={
            "topic": NTFY_TOPIC, "title": title, "message": msg, "click": url,
            "priority": priority, "tags": [tag],
            "actions": [{"action": "view", "label": "Avaa kauppa", "url": url}],
        }).raise_for_status()
    except Exception as e:
        log("ntfy epäonnistui:", e)


# ---------- PÄÄLOGIIKKA ----------
def load():
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {}


def run_once(state):
    for shop, fn, alert_on_return in SHOPS:
        try:
            items = fn()
        except Exception as e:
            log(f"{shop}: haku epäonnistui ({e})")
            continue
        if items is None:
            continue
        first = shop not in state  # kaupan ensimmäinen kierros: tallennetaan nykyiset, ei hälytetä
        seen = state.setdefault(shop, {"ever": [], "last": []})
        ever, last = set(seen["ever"]), set(seen["last"])
        log(f"{shop}: {len(items)} tuotetta listalla")

        for key, (name, url) in items.items():
            is_new = key not in ever
            came_back = alert_on_return and key in ever and key not in last
            if not first and (is_new or came_back):
                label = "🆕 UUSI" if is_new else "🔥 TAKAISIN MYYNNISSÄ"
                notify(f"{label}: {shop}", name, url)
                log(f"HÄLYTYS {label} {shop}: {name}")

        seen["ever"] = sorted(ever | set(items))
        seen["last"] = sorted(items)
        if first:
            notify(f"Vahti päällä: {shop}", f"{len(items)} nykyistä tuotetta tallennettu. "
                   "Hälytys tulee, kun uusia ilmestyy.",
                   {"Prisma": PRISMA_URL, "Verkkokauppa": VK_URL, "Kärkkäinen": KARKK_URL}[shop],
                   priority=2, tag="white_check_mark")
        time.sleep(random.uniform(1, 3))

    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=1))


def main():
    if "--test" in sys.argv:
        notify("🆕 UUSI: Testi", "Ilmoitukset toimii", PRISMA_URL)
        return
    state = load()
    while True:
        run_once(state)
        time.sleep(INTERVAL + random.uniform(-20, 20))


if __name__ == "__main__":
    main()
