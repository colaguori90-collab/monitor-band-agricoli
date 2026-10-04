import os
import re
import json
import html
import time
import smtplib
from datetime import datetime
from urllib.parse import urljoin
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests
from bs4 import BeautifulSoup
import google.generativeai as genai


# ============================================================
# CONFIGURAZIONE
# ============================================================

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GMAIL_USER = os.getenv("GMAIL_USER")
GMAIL_PASSWORD = os.getenv("GMAIL_PASSWORD")
DESTINATARIO = os.getenv("DESTINATARIO_EMAIL")

if not GEMINI_API_KEY:
    raise ValueError("Manca GEMINI_API_KEY nei Secrets GitHub.")

if not GMAIL_USER or not GMAIL_PASSWORD or not DESTINATARIO:
    raise ValueError("Mancano i Secrets Gmail.")

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-2.5-flash")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "it-IT,it;q=0.9,en;q=0.8",
}

# Per verificare che il nuovo metodo funzioni, manteniamo due fonti.
# Quando l'email sarà corretta, aggiungeremo una regione alla volta.
REGIONI = {
    "Campania": "https://agricoltura.regione.campania.it/bandi.html",
    "Emilia-Romagna": "https://agricoltura.regione.emilia-romagna.it/sviluppo-rurale-23-27/opportunita/bandi/bandi-aperti",
}

PAROLE_BANDO = (
    "bando", "avviso", "intervento",
    "srd", "sra", "sre", "srg", "srh", "srb",
    "agricolt", "rurale", "forest", "zootecn",
    "contribut", "finanzi", "sostegno",
    "psr", "csr", "feasr", "pac",
)


# ============================================================
# DOWNLOAD E TESTO
# ============================================================

def scarica_pagina(url):
    try:
        risposta = requests.get(
            url,
            headers=HEADERS,
            timeout=40,
            allow_redirects=True
        )
        risposta.raise_for_status()
        return risposta.text, risposta.url, None
    except requests.RequestException as errore:
        return None, url, str(errore)


def pulisci_testo(testo):
    return re.sub(r"\s+", " ", testo or "").strip()


def testo_pagina(html_pagina):
    soup = BeautifulSoup(html_pagina, "lxml")

    for tag in soup(["script", "style", "noscript", "svg", "nav", "footer", "header"]):
        tag.decompose()

    return pulisci_testo(soup.get_text(" ", strip=True))


def contiene_parola_bando(testo):
    testo = (testo or "").lower()
    return any(parola in testo for parola in PAROLE_BANDO)


# ============================================================
# ESTRAZIONE BANDI DA TABELLE E SCHEDE
# ============================================================

def estrai_da_tabelle(soup, url_base):
    """
    Per siti come Campania:
    legge una tabella riga per riga e associa titolo/scadenza
    al link 'Vai alla pagina' presente nella stessa riga.
    """
    risultati = []

    for tabella in soup.find_all("table"):
        for riga in tabella.find_all("tr"):
            testo_riga = pulisci_testo(riga.get_text(" ", strip=True))

            if len(testo_riga) < 20:
                continue

            if "nessun bando aperto" in testo_riga.lower():
                continue

            if not contiene_parola_bando(testo_riga):
                continue

            link = riga.find("a", href=True)
            if not link:
                continue

            url = urljoin(url_base, link["href"])

            # Nel caso "Vai alla pagina", il titolo è il testo della riga
            # meno il testo generico del pulsante.
            titolo = testo_riga
            titolo = re.sub(
                r"\b(vai alla pagina|dettaglio|apri|azioni?)\b.*$",
                "",
                titolo,
                flags=re.IGNORECASE
            ).strip()

            risultati.append({
                "titolo": titolo[:500],
                "scadenza": cerca_scadenza(testo_riga),
                "url": url,
                "origine": "tabella"
            })

    return risultati


def estrai_da_schede(soup, url_base):
    """
    Per siti come Emilia-Romagna:
    cerca titoli H2/H3 e trova il collegamento più vicino
    nella relativa scheda/contenitore HTML.
    """
    risultati = []

    for titolo_tag in soup.find_all(["h2", "h3", "h4"]):
        titolo = pulisci_testo(titolo_tag.get_text(" ", strip=True))

        if len(titolo) < 12 or not contiene_parola_bando(titolo):
            continue

        # Cerca prima un link dentro il titolo
        link = titolo_tag.find("a", href=True)

        # Altrimenti cerca nel contenitore vicino
        contenitore = titolo_tag.parent
        if not link and contenitore:
            link = contenitore.find("a", href=True)

        # Se ancora non c'è, cerca tra i fratelli successivi
        if not link:
            corrente = titolo_tag
            for _ in range(5):
                corrente = corrente.find_next_sibling()
                if not corrente:
                    break

                link = corrente.find("a", href=True)
                if link:
                    break

        if not link:
            continue

        url = urljoin(url_base, link["href"])

        # Prendiamo testo vicino al titolo per trovare la scadenza
        testo_vicino = titolo
        if contenitore:
            testo_vicino += " " + pulisci_testo(contenitore.get_text(" ", strip=True))

        risultati.append({
            "titolo": titolo[:500],
            "scadenza": cerca_scadenza(testo_vicino),
            "url": url,
            "origine": "scheda"
        })

    return risultati


def cerca_scadenza(testo):
    """
    Cerca date nel testo: es. 15-10-2026, 15/10/2026, 15 ottobre 2026.
    Se trova una voce 'Scadenza', privilegia la data vicina.
    """
    testo = pulisci_testo(testo)

    pattern_numerico = r"\b\d{1,2}[/-]\d{1,2}[/-]\d{4}\b"
    pattern_testuale = (
        r"\b\d{1,2}\s+"
        r"(gennaio|febbraio|marzo|aprile|maggio|giugno|"
        r"luglio|agosto|settembre|ottobre|novembre|dicembre)"
        r"\s+\d{4}\b"
    )

    # Prima cerca una data dopo la parola scadenza
    match_scadenza = re.search(
        r"scadenza.{0,100}?(" + pattern_numerico + "|" + pattern_testuale + ")",
        testo,
        flags=re.IGNORECASE
    )

    if match_scadenza:
        return match_scadenza.group(1)

    match = re.search(pattern_numerico, testo)
    if match:
        return match.group(0)

    match = re.search(pattern_testuale, testo, flags=re.IGNORECASE)
    if match:
        return match.group(0)

    return "non specificata"


def elimina_duplicati(bandi):
    risultati = []
    visti = set()

    for bando in bandi:
        chiave = (
            bando["titolo"].lower().strip(),
            bando["url"].lower().strip()
        )

        if chiave in visti:
            continue

        visti.add(chiave)
        risultati.append(bando)

    return risultati


def estrai_bandi_pagina_elenco(html_pagina, url_base):
    soup = BeautifulSoup(html_pagina, "lxml")

    bandi = []

    # Prima prova le tabelle: è la soluzione corretta per Campania.
    bandi.extend(estrai_da_tabelle(soup, url_base))

    # Poi prova schede/titoli: è adatta a Emilia-Romagna.
    bandi.extend(estrai_da_schede(soup, url_base))

    # Elimina link che riportano alla stessa pagina elenco.
    url_base_normale = url_base.rstrip("/")

    bandi_validi = []
    for bando in bandi:
        url_bando_normale = bando["url"].rstrip("/")

        if url_bando_normale == url_base_normale:
            continue

        if len(bando["titolo"]) < 12:
            continue

        bandi_validi.append(bando)

    return elimina_duplicati(bandi_validi)


# ============================================================
# GEMINI: SOLO DETTAGLI DAL SINGOLO BANDO
# ============================================================

def analizza_dettaglio_con_gemini(regione, titolo, url, testo):
    base = {
        "descrizione": "Descrizione non estratta automaticamente: apri la fonte ufficiale.",
        "importo": "non specificato",
        "aliquota": "non specificata",
    }

    if len(testo) < 200:
        return base

    prompt = f"""
Sei un assistente per la consulenza su bandi agricoli italiani.

Leggi il testo della PAGINA DI DETTAGLIO di un singolo bando.
Fornisci soltanto dati esplicitamente presenti nel testo: non inventare nulla.

Regione: {regione}
Titolo: {titolo}
URL: {url}

Restituisci SOLO un JSON valido, senza Markdown, con queste chiavi:

{{
  "descrizione": "sintesi di massimo 40 parole oppure non specificato",
  "importo": "dotazione finanziaria/importo oppure non specificato",
  "aliquota": "percentuale di contribuzione oppure non specificata"
}}

Testo della pagina:
{testo[:12000]}
""".strip()

    try:
        risposta = model.generate_content(
            prompt,
            generation_config=genai.types.GenerationConfig(
                temperature=0,
                response_mime_type="application/json"
            )
        )

        dati = json.loads(risposta.text)

        if not isinstance(dati, dict):
            return base

        return {
            "descrizione": str(dati.get("descrizione", base["descrizione"])),
            "importo": str(dati.get("importo", base["importo"])),
            "aliquota": str(dati.get("aliquota", base["aliquota"])),
        }

    except Exception as errore:
        print(f"      ⚠️ Gemini: {errore}")
        return base


# ============================================================
# REPORT EMAIL
# ============================================================

def esc(valore):
    return html.escape(str(valore or "non specificato"))


def crea_report_html(bandi, errori):
    oggi = datetime.now().strftime("%d/%m/%Y")

    if bandi:
        righe = ""

        for bando in bandi:
            url = esc(bando["url"])

            righe += f"""
            <tr>
                <td>{esc(bando["regione"])}</td>
                <td>
                    <strong>{esc(bando["titolo"])}</strong><br>
                    <a href="{url}" target="_blank">Apri il singolo bando</a>
                </td>
                <td>{esc(bando["scadenza"])}</td>
                <td>{esc(bando["descrizione"])}</td>
                <td>{esc(bando["importo"])}</td>
                <td>{esc(bando["aliquota"])}</td>
            </tr>
            """
    else:
        righe = """
        <tr>
            <td colspan="6" style="text-align:center; padding:30px">
                Nessun link a singoli bandi è stato estratto.
            </td>
        </tr>
        """

    blocco_errori = ""
    if errori:
        elenco = "".join(
            f"<li><strong>{esc(regione)}</strong>: {esc(messaggio)}</li>"
            for regione, messaggio in errori
        )
        blocco_errori = f"<h2>Fonti da verificare</h2><ul>{elenco}</ul>"

    return f"""<!DOCTYPE html>
<html lang="it">
<head>
<meta charset="UTF-8">
<style>
body {{ font-family: Arial, sans-serif; margin: 20px; color: #222; line-height: 1.45; }}
h1, h2 {{ color: #246b36; }}
.riepilogo {{ background: #edf8ef; border-left: 5px solid #2d8a43; padding: 15px; margin-bottom: 20px; }}
table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
th {{ background: #287c3d; color: white; padding: 10px; text-align: left; }}
td {{ border: 1px solid #ddd; padding: 10px; vertical-align: top; }}
tr:nth-child(even) {{ background: #f8f8f8; }}
.nota {{ margin-top: 28px; color: #555; font-size: 12px; }}
</style>
</head>
<body>

<h1>Report settimanale – Bandi agricoli regionali</h1>

<div class="riepilogo">
<strong>Data elaborazione:</strong> {oggi}<br>
<strong>Singoli bandi trovati:</strong> {len(bandi)}<br>
<strong>Regioni esaminate:</strong> {len(REGIONI) - len(errori)} su {len(REGIONI)}
</div>

<table>
<thead>
<tr>
<th>Regione</th>
<th>Bando e link diretto</th>
<th>Scadenza</th>
<th>Di cosa si tratta</th>
<th>Importo</th>
<th>Aliquota</th>
</tr>
</thead>
<tbody>
{righe}
</tbody>
</table>

{blocco_errori}

<p class="nota">
I link devono aprire la scheda o la pagina del singolo bando, non l’elenco generale.
Le sintesi sono automatiche: verifica sempre requisiti, allegati, proroghe e scadenze dalla fonte ufficiale.
</p>

</body>
</html>
"""


# ============================================================
# INVIO EMAIL
# ============================================================

def invia_email(report_html, quanti_bandi):
    oggi = datetime.now().strftime("%d/%m/%Y")

    messaggio = MIMEMultipart("alternative")
    messaggio["From"] = GMAIL_USER
    messaggio["To"] = DESTINATARIO
    messaggio["Subject"] = f"Report bandi agricoli – {quanti_bandi} bandi – {oggi}"

    testo = (
        f"Report bandi agricoli del {oggi}. "
        f"Singoli bandi trovati: {quanti_bandi}. "
        "Apri la versione HTML per consultare i link diretti."
    )

    messaggio.attach(MIMEText(testo, "plain", "utf-8"))
    messaggio.attach(MIMEText(report_html, "html", "utf-8"))

    with smtplib.SMTP("smtp.gmail.com", 587, timeout=40) as server:
        server.starttls()
        server.login(GMAIL_USER, GMAIL_PASSWORD)
        server.send_message(messaggio)


# ============================================================
# PROGRAMMA PRINCIPALE
# ============================================================

def main():
    print("🚀 Avvio ricerca dei singoli bandi agricoli")

    tutti_i_bandi = []
    errori = []

    for regione, url_elenco in REGIONI.items():
        print(f"\n📍 Regione: {regione}")

        html_elenco, url_effettivo, errore = scarica_pagina(url_elenco)

        if errore:
            print(f"   ⚠️ Elenco non raggiungibile: {errore}")
            errori.append((regione, "pagina elenco non raggiungibile"))
            continue

        bandi_trovati = estrai_bandi_pagina_elenco(html_elenco, url_effettivo)
        print(f"   Singoli bandi estratti: {len(bandi_trovati)}")

        for numero, bando in enumerate(bandi_trovati, start=1):
            print(f"   {numero}/{len(bandi_trovati)} - {bando['titolo'][:90]}")

            dettagli = {
                "descrizione": "Descrizione non estratta automaticamente: apri la fonte ufficiale.",
                "importo": "non specificato",
                "aliquota": "non specificata",
            }

            html_dettaglio, url_dettaglio, errore_dettaglio = scarica_pagina(bando["url"])

            if not errore_dettaglio and html_dettaglio:
                testo_dettaglio = testo_pagina(html_dettaglio)
                dettagli = analizza_dettaglio_con_gemini(
                    regione,
                    bando["titolo"],
                    url_dettaglio,
                    testo_dettaglio
                )
            else:
                print("      ⚠️ Pagina di dettaglio non leggibile: mantengo titolo/link.")

            tutti_i_bandi.append({
                "regione": regione,
                "titolo": bando["titolo"],
                "url": bando["url"],
                "scadenza": bando["scadenza"],
                "descrizione": dettagli["descrizione"],
                "importo": dettagli["importo"],
                "aliquota": dettagli["aliquota"],
            })

            time.sleep(1)

    # Rimuove duplicati finali
    risultati_finali = []
    visti = set()

    for bando in tutti_i_bandi:
        chiave = (bando["regione"], bando["url"])

        if chiave in visti:
            continue

        visti.add(chiave)
        risultati_finali.append(bando)

    print("\n" + "=" * 60)
    print(f"✅ Singoli bandi nel report: {len(risultati_finali)}")

    report_html = crea_report_html(risultati_finali, errori)
    invia_email(report_html, len(risultati_finali))

    print("📧 Email inviata.")


if __name__ == "__main__":
    main()
