"""
Gemeinsame Hilfsfunktionen für die Transfermarkt-Scraper.

Transfermarkt schützt seine Seiten mit einer AWS-WAF-JavaScript-Challenge.
Ein einfacher HTTP-Request (requests/urllib) bekommt deshalb nur eine leere
Zwischenseite zurück. Deshalb wird hier ein echter (headless) Browser über
Playwright genutzt, der die Challenge wie ein normaler Browser ausführt.
"""

import os
import time

from playwright.sync_api import sync_playwright

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Wie lange (Sekunden) wir maximal auf die Auflösung der AWS-WAF-Challenge warten
CHALLENGE_TIMEOUT = 30

# Textbausteine, die auf eine (noch) nicht aufgelöste Bot-Schutz-Seite hindeuten
BLOCK_MARKER = [
    "awswaf",
    "challenge-container",
    "captcha",
    "access denied",
    "zugriff verweigert",
    "just a moment",
    "attention required",
    "verify that you're not a robot",
]


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


def ist_blockiert(html):
    lower = html.lower()
    return any(marker in lower for marker in BLOCK_MARKER)


def warte_auf_echten_inhalt(page, timeout_seconds=CHALLENGE_TIMEOUT):
    """
    Wartet, bis die AWS-WAF-Challenge aufgelöst ist (die Seite lädt sich nach
    erfolgreicher Challenge selbst per JS neu) oder das Timeout erreicht ist.
    """
    start = time.time()
    content = ""
    while time.time() - start < timeout_seconds:
        try:
            content = page.content()
        except Exception:
            content = ""

        if content and not ist_blockiert(content) and len(content) > 2000:
            return content

        page.wait_for_timeout(1500)

    return content


def neuen_browser_kontext(p):
    """Startet einen headless Chromium-Browser mit einem realistischen Kontext."""
    browser = p.chromium.launch(
        headless=True,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
        ],
    )
    context = browser.new_context(
        user_agent=USER_AGENT,
        locale="de-DE",
        viewport={"width": 1280, "height": 900},
        extra_http_headers={
            "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
        },
    )
    # navigator.webdriver ist eines der einfachsten Signale, an denen
    # Bot-Schutz Automatisierung erkennt - hier wird es verschleiert.
    context.add_init_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
    )
    return browser, context


def seite_holen(context, url, debug_dir, debug, debug_name):
    """
    Lädt eine URL über einen echten Browser-Tab, wartet auf die Auflösung
    einer eventuellen Bot-Schutz-Challenge und gibt das finale HTML zurück.
    """
    print(f"[URL] {url}")

    page = context.new_page()
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        html = warte_auf_echten_inhalt(page)
    finally:
        page.close()

    geblockt = ist_blockiert(html)
    print(f"[INFO] {debug_name}: {len(html)} Zeichen, verdacht_auf_blockade={geblockt}")

    if debug:
        os.makedirs(debug_dir, exist_ok=True)
        pfad = os.path.join(debug_dir, f"{debug_name}.html")
        with open(pfad, "w", encoding="utf-8") as f:
            f.write(html)

    if geblockt:
        print(
            f"[WARN] {debug_name}: Auch nach {CHALLENGE_TIMEOUT}s noch "
            "Bot-Schutz-Seite, keine echten Daten erhalten."
        )

    return html
