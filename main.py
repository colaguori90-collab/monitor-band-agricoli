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
    raise ValueError("Manca GEMINI_API_KEY nei Secrets di GitHub.")

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-2.5-flash")

# Le pagine più vicine possibile a "bandi aperti" o "bandi in corso".
# Alcune regioni richiedono portali differenti: verranno perfezionate nel tempo.
REGIONI = {
    "Basilicata": "https://agricoltura.regione.basilicata.it/bandi-regionali/",
    "Campania": "https://agricoltura.regione.campania.it/bandi.html",
    "Emilia-Romagna": "https://agricoltura.regione.emilia-romagna.it/sviluppo-rurale-23-27/opportunita/bandi/bandi-aperti",
    "Friuli-Venezia Giulia": "https://www.opr.fvg.it/it/bandi-e-scadenze-per-la-presentazione-delle-domande-86876/bandi-aperti-72911",
    "Lazio": "https://www.regione.lazio.it/imprese/agricoltura",
    "Liguria": "https://www.siarliguria.it/web/Public/Bandi.aspx",
    "Lombardia": "https://www.bandi.regione.lombardia.it/servizi/servizio/bandi/agricoltura",
    "Piemonte": "https://bandi.regione.piemonte.it/contributi-finanziamenti",
    "Sicilia": "https://www.psrsicilia.it/bandi-aperti/",
    "Toscana": "https://www.regione.toscana.it/sviluppo-rurale-2023-2027/bandi",
    "Umbria": "https://applicazioni.regione.umbria.it/widget/bandi1/-/bandi_WAR_bandiportlet",
    "Veneto": "https://www.regione.veneto.it/web/agricoltura-e-foreste/bandi-finanziamenti",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "it-IT,it;q=0.9",
}


# ============================================================
# DOWNLOAD E PULIZIA TESTO
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
    except Exception as errore:
        return None, url, str(errore)


def testo_pagina(pagina_html):
    soup = BeautifulSoup(pagina_html, "lxml")

    for tag in soup(["script", "style", "noscript", "svg", "nav", "footer"]):
        tag.decompose()

    testo = soup.get_text(" ", strip=True)
    return re.sub(r"\s+", " ", testo).strip()


def estrai_blocchi_rilevanti(testo):
    """
    Divide il testo in blocchi. Mantiene solo le parti che contengono
    parole tipiche di un bando agricolo.
    """
    parole = (
        "bando", "avviso", "contribut", "finanzi", "domande",
        "agricolt", "rurale", "csr", "psr", "srd", "sra",
        "sre", "srg", "feasr", "pac", "scadenza"
    )

    blocchi = []
    dimensione = 4000

    for inizio in range(0, min(len(testo), 30000), dimensione):
        blocco = testo[inizio:inizio + dimensione]
        if any(parola in blocco.lower() for parola in parole):
            blocchi.append(blocco)

    return blocchi[:6]


# ============================================================
# GEMINI: ESTRAZIONE, NON DECISIONE
# ============================================================

def estrai_bandi_con_gemini(regione, url_fonte, testo):
    """
    Gemini deve estrarre i bandi presenti nel testo.
    Non gli chiediamo di escludere automaticamente tutto ciò che
    non riesce a classificare in modo certo.
    """
    prompt = f"""
Sei un assistente che estrae dati da siti ufficiali regionali italiani.

Analizza il testo seguente, proveniente da una pagina di bandi/avvisi
agricoli della Regione {regione}.

Estrai i bandi, avvisi, misure o opportunità finanziarie che riguardano:
agricoltura, sviluppo rurale, agricoltori, aziende agricole, foreste,
agroalimentare, zootecnia, pesca o filiere rurali.

Non inventare nulla. Se un dato non appare nel testo, scrivi
"non specificato".

Restituisci ESCLUSIVAMENTE un array JSON valido.
Non inserire testo prima o dopo l'array.

Ogni elemento deve avere ESATTAMENTE queste chiavi:
{{
  "titolo": "titolo del bando o avviso",
  "scadenza": "data o non specificata",
  "descrizione": "massimo 45 parole",
  "importo": "importo o non specificato",
  "aliquota": "aliquota/percentuale o non specificata",
  "stato": "da verificare",
  "fonte": "{url_fonte}"
}}

Se non ci sono misure agricole nel testo, restituisci [].

TESTO DA ANALIZZARE:
{testo[:11000]}
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
        if not isinstance(dati, list):
            return []

        risultati = []
        for bando in dati:
            if not isinstance(bando, dict):
                continue

            titolo = str(bando.get("titolo", "")).strip()
            if len(titolo) < 8:
                continue

            bando["regione"] = regione
            bando["fonte"] = url_fonte
            bando["stato"] = "da verificare"
            risultati.append(bando)

        return risultati

    except Exception as errore:
        print(f"   ⚠️ Errore Gemini in {regione}: {errore}")
        return []


# ============================================================
# PULIZIA E REPORT
# ============================================================

def elimina_duplicati(bandi):
    risultati = []
    visti = set()

    for bando in bandi:
        chiave = (
            bando.get("regione", "").strip().lower(),
            bando.get("titolo", "").strip().lower()
        )

        if chiave in visti:
            continue

        visti.add(chiave)
        risultati.append(bando)

    return risultati


def escape(testo):
    return html.escape(str(testo or "non specificato"))


def genera_report_html(bandi, errori):
    data = datetime.now().strftime("%d/%m/%Y")
    righe = ""

    if bandi:
        for bando in bandi:
            url = escape(bando.get("fonte", ""))
            link = f'<a href="{url}" target="_blank">Fonte ufficiale</a>' if url else "non disponibile"

            righe += f"""
            <tr>
                <td>{escape(bando.get("regione"))}</td>
                <td><strong>{escape(bando.get("titolo"))}</strong><br>{link}</td>
                <td>{escape(bando.get("scadenza"))}</td>
                <td>{escape(bando.get("descrizione"))}</td>
                <td>{escape(bando.get("importo"))}</td>
                <td>{escape(bando.get("aliquota"))}</td>
                <td>Da verificare</td>
            </tr>
            """
    else:
        righe = """
        <tr>
            <td colspan="7" style="text-align:center;padding:30px">
                Nessun bando estratto automaticamente in questa esecuzione.
            </td>
        </tr>
        """

    errori_html = ""
    if errori:
        elenco = "".join(
            f"<li><strong>{escape(regione)}</strong>: {escape(messaggio)}</li>"
            for regione, messaggio in errori
        )
        errori_html = f"""
        <h2>Fonti non raggiunte</h2>
        <ul>{elenco}</ul>
        """

    return f"""<!DOCTYPE html>
<html lang="it">
<head>
<meta charset="UTF-8">
<style>
body {{ font-family: Arial, sans-serif; margin: 20px; color: #222; }}
h1, h2 {{ color: #246b36; }}
.box {{ background: #eef8f0; padding: 15px; border-left: 5px solid #2f8a43; }}
table {{ width: 100%; border-collapse: collapse; margin-top: 18px; font-size: 13px; }}
th {{ background: #287c3d; color: white; text-align: left; padding: 10px; }}
td {{ border: 1px solid #ddd; padding: 10px; vertical-align: top; }}
tr:nth-child(even) {{ background: #f8f8f8; }}
.note {{ margin-top: 25px; font-size: 12px; color: #555; }}
</style>
</head>
<body>
<h1>Report settimanale – Bandi agricoli regionali</h1>

<div class="box">
<strong>Data elaborazione:</strong> {data}<br>
<strong>Bandi/avvisi estratti:</strong> {len(bandi)}<br>
<strong>Regioni lette:</strong> {len(REGIONI) - len(errori)} su {len(REGIONI)}<br>
<strong>Stato dati:</strong> da verificare sulle fonti ufficiali
</div>

<table>
<thead>
<tr>
<th>Regione</th>
<th>Bando e fonte</th>
<th>Scadenza</th>
<th>Descrizione</th>
<th>Importo</th>
<th>Aliquota</th>
<th>Stato</th>
</tr>
</thead>
<tbody>
{righe}
</tbody>
</table>

{errori_html}

<p class="note">
Questo report individua opportunità pubblicate nelle pagine regionali.
Verifica sempre data di scadenza, allegati, requisiti, importo e aliquota
nella fonte ufficiale prima di utilizzarlo in attività di consulenza.
</p>
</body>
</html>
"""


# ============================================================
# INVIO MAIL
# ============================================================

def invia_email(report_html, quanti_bandi):
    oggi = datetime.now().strftime("%d/%m/%Y")

    messaggio = MIMEMultipart("alternative")
    messaggio["From"] = GMAIL_USER
    messaggio["To"] = DESTINATARIO
    messaggio["Subject"] = f"Report bandi agricoli – {quanti_bandi} opportunità estratte – {oggi}"

    testo = (
        f"Report bandi agricoli del {oggi}. "
        f"Opportunità estratte: {quanti_bandi}. "
        "Apri questa email in formato HTML per il dettaglio."
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
    print("🚀 Avvio del monitoraggio bandi agricoli")
    tutti_i_bandi = []
    errori = []

    for regione, url in REGIONI.items():
        print(f"\n📍 Regione: {regione}")

        pagina, url_effettivo, errore = scarica_pagina(url)

        if errore:
            print(f"   ⚠️ Non raggiunta: {errore}")
            errori.append((regione, "pagina elenco non raggiungibile"))
            continue

        testo = testo_pagina(pagina)
        blocchi = estrai_blocchi_rilevanti(testo)

        print(f"   Blocchi rilevanti trovati: {len(blocchi)}")

        if not blocchi:
            errori.append((regione, "nessun testo utile estratto dalla pagina"))
            continue

        for numero, blocco in enumerate(blocchi, start=1):
            print(f"   Analisi blocco {numero}/{len(blocchi)}")
            bandi = estrai_bandi_con_gemini(regione, url_effettivo, blocco)
            tutti_i_bandi.extend(bandi)
            time.sleep(1)

    tutti_i_bandi = elimina_duplicati(tutti_i_bandi)

    print("\n" + "=" * 60)
    print(f"✅ Opportunità estratte: {len(tutti_i_bandi)}")

    report = genera_report_html(tutti_i_bandi, errori)
    invia_email(report, len(tutti_i_bandi))

    print("📧 Report inviato.")


if __name__ == "__main__":
    main()
