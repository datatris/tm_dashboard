"""
Transfermarkt-Scraper (Ersatz für die PowerQuery-Abfrage).

Holt für die Wettbewerbe L1 (Bundesliga), L2 (2. Bundesliga) und L3 (3. Liga)
jeweils bis zu 20 Seiten der "neueste Transfers"-Statistik und speichert das
Ergebnis als data.json.

Die CSS-Selektoren entsprechen 1:1 denen aus der ursprünglichen
Html.Table(...)-Abfrage in Power Query, damit die Spaltenlogik identisch bleibt.
"""

import json
import time
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.transfermarkt.de"
WETTBEWERBE = ["L1", "L2", "L3"]
MAX_SEITEN = 20
OUTPUT_FILE = "transfers.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}


def get_attr(el, attr):
    """Hilfsfunktion: Attribut eines Tags sicher auslesen (oder None)."""
    if el is None:
        return None
    return el.get(attr)


def get_text(el):
    if el is None:
        return None
    text = el.get_text(strip=True)
    return text if text else None


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
    # Fallback: manche Layouts haben "Alter" direkt als zentrierte Zelle in der Zeile
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


def fetch_page(wettbewerb, seite):
    url = f"{BASE_URL}/transfers/neuestetransfers/statistik"
    params = {
        "wettbewerb_id": wettbewerb,
        "minMarktwert": 0,
        "plus": 1,
        "page": seite,
    }
    resp = requests.get(url, headers=HEADERS, params=params, timeout=30)
    resp.raise_for_status()
    return resp.text


def parse_transfers(html):
    soup = BeautifulSoup(html, "html.parser")
    rows = soup.select("tr")

    # RowSelector-Äquivalent: nur Zeilen behalten, die tatsächlich einen
    # Spielernamen im ersten TD enthalten (Header-/Trennzeilen fallen raus).
    treffer = []
    for row in rows:
        if row.select_one("td:nth-child(1) .hauptlink"):
            treffer.append(parse_row(row))
    return treffer


def scrape():
    alle_transfers = []

    for wettbewerb in WETTBEWERBE:
        leere_seiten_in_folge = 0
        for seite in range(1, MAX_SEITEN + 1):
            try:
                html = fetch_page(wettbewerb, seite)
                daten = parse_transfers(html)
            except requests.RequestException as exc:
                print(f"[WARN] {wettbewerb} Seite {seite}: {exc}")
                daten = []

            if not daten:
                leere_seiten_in_folge += 1
                # Wie im Original werden Fehler-/leere Seiten übersprungen
                # (entspricht Table.RemoveRowsWithErrors). Nach 2 leeren
                # Seiten in Folge brechen wir früh ab, um Requests zu sparen.
                if leere_seiten_in_folge >= 2:
                    break
                continue

            leere_seiten_in_folge = 0
            for eintrag in daten:
                eintrag["Column1"] = wettbewerb
                eintrag["Seite"] = seite
                alle_transfers.append(eintrag)

            time.sleep(1)  # kurze Pause, um transfermarkt.de nicht zu überlasten

    return alle_transfers


def main():
    transfers = scrape()
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
