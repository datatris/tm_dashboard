"""
Transfermarkt-Scraper: Gerüchteküche (Ersatz für die PowerQuery-Abfrage).

Holt die Seiten 1 bis 15 der Gerüchteküche (nationale Wettbewerbe) und
speichert das Ergebnis als datageruechte.json.

Die CSS-Selektoren entsprechen 1:1 denen aus der ursprünglichen
Html.Table(...)-Abfrage in Power Query, damit die Spaltenlogik identisch
bleibt. RowSelector war dort
".threaduebersicht-threads.geruechtekueche > .thread" - jede so gefundene
".thread"-Box entspricht hier einer Zeile, innerhalb derer die einzelnen
Felder gesucht werden.
"""

import json
import os
from datetime import datetime, timezone

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

from browser_common import get_attr, get_text, neuen_browser_kontext, seite_holen

BASE_URL = "https://www.transfermarkt.de"
MAX_SEITEN = 15
OUTPUT_FILE = "datageruechte.json"
DEBUG_DIR = "debug"
DEBUG = os.environ.get("SCRAPER_DEBUG", "1") != "0"  # standardmäßig an


def parse_row(row):
    """Extrahiert aus einer ".thread"-Box dieselben Felder wie die PowerQuery-Abfrage."""

    spieler = get_text(
        row.select_one(
            ".spielergeruechte-reihe-offset:nth-last-child(2) "
            "> div.row.geruecht-kasten:nth-child(1):nth-last-child(1) "
            "> :nth-child(1) > .spielername"
        )
    )

    profilbild_el = row.select_one(
        '.gk-spieler-bild:nth-last-child(1) > a > img.bilderrahmen-fixed[itemprop="image"]'
        ":nth-child(1):nth-last-child(1)"
    )
    profilbild = get_attr(profilbild_el, "src")

    link_spieler_el = row.select_one(".gk-spieler-bild:nth-last-child(1) > a")
    link_spieler = get_attr(link_spieler_el, "href")

    marktwert = get_text(row.select_one(".large-push-2.large-2:nth-last-child(3)"))

    aktueller_verein = get_text(row.select_one(".vereinname"))

    link_aktueller_verein_el = row.select_one(".vereinname > a:nth-child(1):nth-last-child(1)")
    link_aktueller_verein = get_attr(link_aktueller_verein_el, "href")

    wappen_aktueller_verein_el = row.select_one(
        ".gk-wappen:nth-child(1) > a:nth-child(1):nth-last-child(1) "
        "> img:nth-child(1):nth-last-child(1)"
    )
    wappen_aktueller_verein = get_attr(wappen_aktueller_verein_el, "src")

    potenzieller_verein = get_text(
        row.select_one(
            ".spielergeruechte-reihe-offset:nth-last-child(2) "
            "> div.row.geruecht-kasten:nth-child(1):nth-last-child(1) "
            "> .threadtext-zelle > .show-for-small > .wechsel-verein-name-kurz"
        )
    )

    link_potenzieller_verein_el = row.select_one(
        ".gk-wappen:nth-child(3) > a:nth-child(1):nth-last-child(1)"
    )
    link_potenzieller_verein = get_attr(link_potenzieller_verein_el, "href")

    wappen_potenzieller_verein_el = row.select_one(
        ".gk-wappen:nth-child(3) > a:nth-child(1):nth-last-child(1) "
        "> img:nth-child(1):nth-last-child(1)"
    )
    wappen_potenzieller_verein = get_attr(wappen_potenzieller_verein_el, "src")

    wahrscheinlichkeit = get_text(row.select_one(".geruecht-zahl"))

    letzter_stand = get_text(
        row.select_one(
            ".large-5:nth-last-child(1):nth-child(2) > div.row:nth-child(1):nth-last-child(1) "
            "> .small-6.large-4 > a:nth-child(1):nth-last-child(1) > .post-datum"
        )
    )

    return {
        "Spieler": spieler,
        "Profilbild": profilbild,
        "Link Spieler": link_spieler,
        "Marktwert": marktwert,
        "Aktueller Verein": aktueller_verein,
        "Link aktueller Verein": link_aktueller_verein,
        "Wappen aktueller Verein": wappen_aktueller_verein,
        "Potenzieller Verein": potenzieller_verein,
        "Link potenzieller Verein": link_potenzieller_verein,
        "Wappen potenzieller Verein": wappen_potenzieller_verein,
        "Wahrscheinlichkeit": wahrscheinlichkeit,
        "Letzter Stand": letzter_stand,
    }


def fetch_page(context, seite):
    url = f"{BASE_URL}/geruchtekuche/detail/forum/154/gk_group/nationalCompetitions/page/{seite}"
    return seite_holen(context, url, DEBUG_DIR, DEBUG, debug_name=f"geruechte_seite{seite}")


def parse_geruechte(html):
    soup = BeautifulSoup(html, "html.parser")
    rows = soup.select(".threaduebersicht-threads.geruechtekueche > .thread")

    treffer = []
    for row in rows:
        eintrag = parse_row(row)
        # Entspricht Table.SelectRows(..., each ([Spieler] <> null)) im Original
        if eintrag["Spieler"] is not None:
            treffer.append(eintrag)

    if DEBUG and not rows:
        anzahl_container = len(soup.select(".threaduebersicht-threads.geruechtekueche"))
        print(
            f"[DEBUG] 0 .thread-Elemente gefunden "
            f"({anzahl_container} Container '.threaduebersicht-threads.geruechtekueche')."
        )

    return treffer


def scrape(context):
    alle_geruechte = []
    leere_seiten_in_folge = 0

    for seite in range(1, MAX_SEITEN + 1):
        try:
            html = fetch_page(context, seite)
            daten = parse_geruechte(html)
        except Exception as exc:
            print(f"[WARN] Seite {seite}: {type(exc).__name__}: {exc}")
            daten = []

        if not daten:
            leere_seiten_in_folge += 1
            if leere_seiten_in_folge >= 2:
                break
            continue

        leere_seiten_in_folge = 0
        alle_geruechte.extend(daten)

    return alle_geruechte


def main():
    with sync_playwright() as p:
        browser, context = neuen_browser_kontext(p)
        geruechte = scrape(context)
        browser.close()

    ausgabe = {
        "letzte_aktualisierung": datetime.now(timezone.utc).isoformat(),
        "anzahl": len(geruechte),
        "geruechte": geruechte,
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(ausgabe, f, ensure_ascii=False, indent=2)

    print(f"{len(geruechte)} Gerüchte gespeichert in {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
