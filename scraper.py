"""
Transfermarkt-Scraper: neueste Transfers (Ersatz für die PowerQuery-Abfrage).

Holt für die Wettbewerbe L1 (Bundesliga), L2 (2. Bundesliga) und L3 (3. Liga)
jeweils bis zu 20 Seiten der "neueste Transfers"-Statistik und speichert das
Ergebnis als data.json.

Die CSS-Selektoren entsprechen 1:1 denen aus der ursprünglichen
Html.Table(...)-Abfrage in Power Query, damit die Spaltenlogik identisch bleibt.
"""

import json
import os
import re
import time
import urllib.parse
from datetime import datetime, timezone

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

from browser_common import get_attr, get_text, neuen_browser_kontext, seite_holen

BASE_URL = "https://www.transfermarkt.de"
WETTBEWERBE = ["L1", "L2", "L3"]
MAX_SEITEN = 20
OUTPUT_FILE = "data.json"
DEBUG_DIR = "debug"
DEBUG = os.environ.get("SCRAPER_DEBUG", "1") != "0"  # standardmäßig an

# --- Für die Vereinsanreicherung (Wappen/Link "Neuer Verein") ---
CREST_BASE = "https://tmssl.akamaized.net//images/wappen/medium/"
ALTER_VEREIN_TINY_PREFIX = "https://tmssl.akamaized.net//images/wappen/tiny/"
KARRIEREENDE_ID = "123"


def parse_row(row):
    """Extrahiert aus einer <tr>-Zeile dieselben Felder wie die PowerQuery-Abfrage."""

    spieler = get_text(row.select_one("td:nth-child(1) .hauptlink"))

    spielerprofil_el = row.select_one(
        ".hauptlink:nth-child(2) > a:nth-child(1):nth-last-child(1)"
    )
    spielerprofil = get_attr(spielerprofil_el, "href")

    position = get_text(
        row.select_one(
            "td:nth-last-child(8) > table.inline-table:nth-child(1):nth-last-child(1) "
            "> tbody:nth-child(1):nth-last-child(1) > :nth-child(2)"
        )
    )

    alter = get_text(row.select_one("tbody .zentriert:nth-child(2)"))
    if alter is None:
        alter = get_text(row.select_one(".zentriert:nth-child(2)"))

    nation_el = row.select_one("td.zentriert:nth-child(3) > img.flaggenrahmen:nth-child(1)")
    nation = get_attr(nation_el, "src")

    nation2_el = row.select_one(".flaggenrahmen:nth-child(3)")
    nation2 = get_attr(nation2_el, "src")

    alter_verein = get_text(row.select_one("td:nth-child(4) .hauptlink"))

    link_alter_verein_el = row.select_one('[rowspan="2"] > a')
    link_alter_verein = get_attr(link_alter_verein_el, "href")

    wappen_alter_verein_el = row.select_one(
        '[rowspan="2"] > a > img.tiny_wappen:nth-child(1):nth-last-child(1)'
    )
    wappen_alter_verein = get_attr(wappen_alter_verein_el, "src")

    neuer_verein = get_text(row.select_one("td:nth-child(5) .hauptlink"))
    transferdatum = get_text(row.select_one("td:nth-child(6)"))
    marktwert = get_text(row.select_one("td:nth-child(7)"))
    abloese = get_text(row.select_one(".rechts.hauptlink"))

    return {
        "Spieler": spieler,
        "Spielerprofil": spielerprofil,
        "Position": position,
        "Alter": alter,
        "Nation": nation,
        "Nation 2": nation2,
        "Alter Verein": alter_verein,
        "Link alter Verein": link_alter_verein,
        "Wappen alter Verein": wappen_alter_verein,
        "Neuer Verein": neuer_verein,
        "Transferdatum": transferdatum,
        "Marktwert": marktwert,
        "Ablöse": abloese,
    }


def fetch_page(context, wettbewerb, seite):
    url = (
        f"{BASE_URL}/transfers/neuestetransfers/statistik"
        f"?wettbewerb_id={wettbewerb}&minMarktwert=0&plus=1&page={seite}"
    )
    return seite_holen(
        context, url, DEBUG_DIR, DEBUG, debug_name=f"{wettbewerb}_seite{seite}"
    )


def parse_transfers(html):
    soup = BeautifulSoup(html, "html.parser")
    rows = soup.select("tr")

    # Transfermarkt rendert pro Transfer zwei <tr>: eine Hauptzeile mit allen
    # Daten und eine zusätzliche Layout-Zeile, die nur den Spielernamen erneut
    # enthält (alle anderen Felder wären dort None). Damit diese Zusatzzeile
    # nicht als eigener (fast leerer) Eintrag durchrutscht, verlangen wir,
    # dass sowohl der alte als auch der neue Verein vorhanden sind.
    treffer = []
    for row in rows:
        hat_spieler = row.select_one("td:nth-child(1) .hauptlink")
        hat_neuer_verein = row.select_one("td:nth-child(5) .hauptlink")
        if hat_spieler and hat_neuer_verein:
            treffer.append(parse_row(row))

    if DEBUG and not treffer:
        anzahl_tabellen = len(soup.select("table"))
        anzahl_hauptlink = len(soup.select(".hauptlink"))
        print(
            f"[DEBUG] 0 Treffer. Gefunden: {len(rows)} <tr>, "
            f"{anzahl_tabellen} <table>, {anzahl_hauptlink} .hauptlink-Elemente."
        )

    return treffer


def scrape(context):
    alle_transfers = []

    for wettbewerb in WETTBEWERBE:
        leere_seiten_in_folge = 0
        for seite in range(1, MAX_SEITEN + 1):
            try:
                html = fetch_page(context, wettbewerb, seite)
                daten = parse_transfers(html)
            except Exception as exc:
                print(f"[WARN] {wettbewerb} Seite {seite}: {type(exc).__name__}: {exc}")
                daten = []

            if not daten:
                leere_seiten_in_folge += 1
                if leere_seiten_in_folge >= 2:
                    break
                continue

            leere_seiten_in_folge = 0
            alle_transfers.extend(daten)

            time.sleep(1.5)  # kurze Pause, um transfermarkt.de nicht zu überlasten

    return alle_transfers


def alte_vereins_id(wappen_alter_verein):
    """
    Entspricht der M-Formel für 'AlterVereinsId': die Vereins-ID steckt
    bereits im vorhandenen Wappen-Link ("Wappen alter Verein"), es ist also
    kein zusätzlicher Request nötig - nur reines String-Parsing.
    Die echten URLs enden mit ".png?lm=<timestamp>", daher wird (wie im
    Original) am ersten ".png" abgeschnitten statt nur auf das Suffix zu prüfen.
    """
    if not wappen_alter_verein or ALTER_VEREIN_TINY_PREFIX not in wappen_alter_verein:
        return None
    rest = wappen_alter_verein.split(ALTER_VEREIN_TINY_PREFIX, 1)[1]
    verein_id = rest.split(".png", 1)[0]
    return verein_id or None


def _debug_name_fuer_verein(name):
    kurz = re.sub(r"[^a-zA-Z0-9]+", "_", name).strip("_")[:40]
    return f"verein_suche_{kurz or 'unbekannt'}"


def suche_verein(context, name):
    """
    Entspricht Suchanfrage -> ErsetzterWertWappen -> Suchdaten -> NeueVereinsId:
    sucht einen Verein über die Transfermarkt-Schnellsuche und liest aus dem
    ersten Treffer mit '.../startseite/verein/...' im Link die Vereins-ID,
    daraus lassen sich Wappen-URL und voller Vereinslink ableiten.
    """
    if name == "Karriereende":
        return {
            "Link neuer Verein": None,
            "Wappen neuer Verein": f"{CREST_BASE}{KARRIEREENDE_ID}.png",
            "NeuerVereinId": KARRIEREENDE_ID,
        }

    query = urllib.parse.quote_plus(name)
    url = f"{BASE_URL}/schnellsuche/ergebnis/schnellsuche?query={query}"

    leer = {"Link neuer Verein": None, "Wappen neuer Verein": None, "NeuerVereinId": None}

    try:
        html = seite_holen(context, url, DEBUG_DIR, DEBUG, debug_name=_debug_name_fuer_verein(name))
    except Exception as exc:
        print(f"[WARN] Vereinssuche '{name}': {type(exc).__name__}: {exc}")
        return leer

    soup = BeautifulSoup(html, "html.parser")

    href_treffer = None
    for kandidat in soup.select(".inline-table .hauptlink"):
        a_tag = kandidat if kandidat.name == "a" else kandidat.find("a")
        href = get_attr(a_tag, "href")
        if href and "startseite/verein" in href:
            href_treffer = href
            break

    if not href_treffer:
        print(f"[WARN] Vereinssuche '{name}': kein Treffer mit 'startseite/verein' gefunden.")
        return leer

    verein_id = href_treffer.rstrip("/").split("/")[-1]
    return {
        "Link neuer Verein": BASE_URL + href_treffer,
        "Wappen neuer Verein": f"{CREST_BASE}{verein_id}.png",
        "NeuerVereinId": verein_id,
    }


def vereinsdaten_anreichern(context, transfers):
    """
    Entspricht dem Block ab 'Abfrage Vereinswappen Neuer Verein' bis zum
    NestedJoin zurück in die Haupttabelle: für jeden eindeutigen "Neuer
    Verein"-Namen wird einmal gesucht (statt pro Transfer-Zeile), das
    Ergebnis wird anschließend allen passenden Zeilen zugeordnet.
    """
    distinct_vereine = sorted({t["Neuer Verein"] for t in transfers if t.get("Neuer Verein")})
    print(f"[INFO] Vereinssuche für {len(distinct_vereine)} unterschiedliche neue Vereine ...")

    cache = {}
    for i, name in enumerate(distinct_vereine, start=1):
        cache[name] = suche_verein(context, name)
        if i % 25 == 0:
            print(f"[INFO] Vereinssuche: {i}/{len(distinct_vereine)} erledigt")
        time.sleep(1)

    for t in transfers:
        info = cache.get(t.get("Neuer Verein"), {})
        t["Link neuer Verein"] = info.get("Link neuer Verein")
        t["Wappen neuer Verein"] = info.get("Wappen neuer Verein")
        t["NeuerVereinId"] = info.get("NeuerVereinId")
        t["AlterVereinsId"] = alte_vereins_id(t.get("Wappen alter Verein"))

    return transfers


def main():
    with sync_playwright() as p:
        browser, context = neuen_browser_kontext(p)
        transfers = scrape(context)
        transfers = vereinsdaten_anreichern(context, transfers)
        browser.close()

    ausgabe = {
        "letzte_aktualisierung": datetime.now(timezone.utc).isoformat(),
        "anzahl": len(transfers),
        "transfers": transfers,
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(ausgabe, f, ensure_ascii=False, indent=2)

    print(f"{len(transfers)} Transfers gespeichert in {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
