import os
import re
import json
import html
import time
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests
import google.generativeai as genai

from sources import HEADERS, FONTI_HTML, elimina_duplicati, pulisci_testo


# ============================================================
# CONFIGURAZIONE
# ============================================================

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GMAIL_USER = os.getenv("GMAIL_USER")
GMAIL_PASSWORD = os.getenv("GMAIL_PASSWORD")
DESTINATARIO = os.getenv("DESTINATARIO_EMAIL")

if not GEMINI_API_KEY:
    raise ValueError("Manca GEMINI_API_KEY nei Secrets di GitHub.")

if not GMAIL_USER or not GMAIL_PASSWORD or not DESTINATARIO:
    raise ValueError(
        "Mancano GMAIL_USER, GMAIL_PASSWORD o DESTINATARIO_EMAIL nei Secrets GitHub."
    )

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-2.5-flash")


# ============================================================
# DOWNLOAD
# ============================================================

def scarica_pagina(url):
    try:
        risposta = requests.get(
            url,
            headers=HEADERS,
            timeout=45,
            allow_redirects=True
        )
        risposta.raise_for_status()

        tipo = risposta.headers.get("Content-Type", "").lower()

        # Non inviamo PDF grezzi a Gemini in questa prima versione.
        if "application/pdf" in tipo or url.lower().endswith(".pdf"):
            return None, risposta.url, "Il dettaglio è un PDF"

        return risposta.text, risposta.url, None

    except requests.RequestException as errore:
        return None, url, str(errore)


def testo_da_html(html_pagina):
    """
    Versione semplice senza BeautifulSoup aggiuntivo:
    rimuove tag/script e compatta spazi.
    """
    testo = re.sub(r"<script.*?</script>", " ", html_pagina, flags=re.DOTALL | re.IGNORECASE)
    testo = re.sub(r"<style.*?</style>", " ", testo, flags=re.DOTALL | re.IGNORECASE)
    testo = re.sub(r"<[^>]+>", " ", testo)
    testo = re.sub(r"&nbsp;", " ", testo)
    testo = re.sub(r"&amp;", "&", testo)
    return pulisci_testo(testo)


# ============================================================
# GEMINI: ANALISI DEL SINGOLO BANDO
# ============================================================

def analizza_bando_con_gemini(bando, testo_dettaglio):
    """
    Riceve solo la pagina del singolo bando già identificato.
    Se Gemini non estrae dati, il bando resta nel report con titolo/link.
    """
    valori_base = {
        "descrizione": "Apri il link ufficiale per leggere il dettaglio del bando.",
        "beneficiari": "non specificati",
        "importo": "non specificato",
        "aliquota": "non specificata",
    }

    if not testo_dettaglio or len(testo_dettaglio) < 250:
        return valori_base

    prompt = f"""
Sei un assistente esperto di bandi italiani in agricoltura e sviluppo rurale.

Analizza ESCLUSIVAMENTE il testo sotto, che proviene dalla pagina ufficiale
del singolo bando già identificato.

Regione: {bando["regione"]}
Stato rilevato: {bando["stato"]}
Titolo: {bando["titolo"]}
Link: {bando["url"]}

Non inventare alcuna informazione. Se un dato non è chiaramente presente,
scrivi esattamente "non specificato".

Restituisci SOLO un JSON valido, senza Markdown e senza altro testo,
con queste chiavi:

{{
  "descrizione": "Sintesi di massimo 45 parole",
  "beneficiari": "Beneficiari ammessi",
  "importo": "Dotazione finanziaria o importo",
  "aliquota": "Aliquota/intensità di aiuto"
}}

Testo della pagina:
{testo_dettaglio[:12000]}
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
            return valori_base

        return {
            "descrizione": str(dati.get("descrizione", valori_base["descrizione"])),
            "beneficiari": str(dati.get("beneficiari", valori_base["beneficiari"])),
            "importo": str(dati.get("importo", valori_base["importo"])),
            "aliquota": str(dati.get("aliquota", valori_base["aliquota"])),
        }

    except Exception as errore:
        print(f"      ⚠️ Gemini non ha estratto i dettagli: {errore}")
        return valori_base


# ============================================================
# REPORT HTML
# ============================================================

def esc(valore):
    return html.escape(str(valore or "non specificato"))


def crea_report_html(bandi, problemi):
    oggi = datetime.now().strftime("%d/%m/%Y")

    bandi_ordinati = sorted(
        bandi,
        key=lambda bando: (
            bando.get("regione", ""),
            bando.get("scadenza", ""),
            bando.get("titolo", ""),
        )
    )

    if bandi_ordinati:
        righe = ""

        for bando in bandi_ordinati:
            url = esc(bando["url"])

            righe += f"""
            <tr>
                <td>{esc(bando["regione"])}</td>
                <td>{esc(bando["stato"])}</td>
                <td>{esc(bando["categoria"])}</td>
                <td>
                    <strong>{esc(bando["titolo"])}</strong><br>
                    <a href="{url}" target="_blank">Apri il singolo bando</a>
                </td>
                <td>{esc(bando["scadenza"])}</td>
                <td>{esc(bando["descrizione"])}</td>
                <td>{esc(bando["beneficiari"])}</td>
                <td>{esc(bando["importo"])}</td>
                <td>{esc(bando["aliquota"])}</td>
            </tr>
            """
    else:
        righe = """
        <tr>
            <td colspan="9" style="text-align:center;padding:32px">
                Nessun singolo bando è stato estratto dalle fonti configurate.
            </td>
        </tr>
        """

    blocco_problemi = ""
    if problemi:
        elenco = "".join(
            f"<li><strong>{esc(regione)}</strong>: {esc(messaggio)}</li>"
            for regione, messaggio in problemi
        )

        blocco_problemi = f"""
        <h2>Fonti o dettagli da verificare</h2>
        <ul>{elenco}</ul>
        """

    return f"""<!DOCTYPE html>
<html lang="it">
<head>
<meta charset="UTF-8">
<style>
body {{
    font-family: Arial, sans-serif;
    margin: 18px;
    color: #222;
    line-height: 1.4;
}}
h1, h2 {{
    color: #236b36;
}}
.riepilogo {{
    background: #edf8ef;
    border-left: 5px solid #2d8a43;
    padding: 15px;
    margin-bottom: 18px;
}}
table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 12px;
}}
th {{
    background: #287c3d;
    color: #ffffff;
    padding: 9px;
    text-align: left;
}}
td {{
    border: 1px solid #d8d8d8;
    padding: 9px;
    vertical-align: top;
}}
tr:nth-child(even) {{
    background: #f7f7f7;
}}
a {{
    color: #125dc0;
}}
.nota {{
    margin-top: 28px;
    color: #555;
    font-size: 12px;
}}
</style>
</head>
<body>

<h1>Report settimanale – Bandi agricoltura e sviluppo rurale</h1>

<div class="riepilogo">
<strong>Data elaborazione:</strong> {oggi}<br>
<strong>Singoli bandi/avvisi inclusi:</strong> {len(bandi_ordinati)}<br>
<strong>Fonti regionali controllate:</strong> {len(FONTI_HTML)}<br>
<strong>Stati inclusi:</strong> Aperto, In corso, In apertura, Prossima apertura, Sportello aperto
</div>

<table>
<thead>
<tr>
<th>Regione</th>
<th>Stato</th>
<th>Area</th>
<th>Bando e link diretto</th>
<th>Scadenza</th>
<th>Di cosa si tratta</th>
<th>Beneficiari</th>
<th>Importo</th>
<th>Aliquota</th>
</tr>
</thead>
<tbody>
{righe}
</tbody>
</table>

{blocco_problemi}

<p class="nota">
Il report include esclusivamente fonti configurate per agricoltura e sviluppo rurale,
comprese le misure LEADER/GAL quando presenti. Sono esclusi, per regola, graduatorie,
esiti, pagamenti, gare, concorsi, pesca/FEAMPA, fiere, eventi e comunicazioni non
riconducibili a un bando attivo o in apertura. Prima di usare i dati professionalmente,
verifica sempre bando, allegati, beneficiari, requisiti, scadenza ed eventuali proroghe
nella pagina ufficiale collegata.
</p>

</body>
</html>
"""


# ============================================================
# EMAIL
# ============================================================

def invia_email(report_html, numero_bandi):
    oggi = datetime.now().strftime("%d/%m/%Y")

    messaggio = MIMEMultipart("alternative")
    messaggio["From"] = GMAIL_USER
    messaggio["To"] = DESTINATARIO
    messaggio["Subject"] = (
        f"Report bandi agricoltura – {numero_bandi} misure – {oggi}"
    )

    testo = (
        f"Report bandi agricoltura e sviluppo rurale del {oggi}. "
        f"Misure incluse: {numero_bandi}. "
        "Apri l'email in formato HTML per consultare i link diretti e i dettagli."
    )

    messaggio.attach(MIMEText(testo, "plain", "utf-8"))
    messaggio.attach(MIMEText(report_html, "html", "utf-8"))

    with smtplib.SMTP("smtp.gmail.com", 587, timeout=45) as server:
        server.starttls()
        server.login(GMAIL_USER, GMAIL_PASSWORD)
        server.send_message(messaggio)


# ============================================================
# PROGRAMMA PRINCIPALE
# ============================================================

def main():
    print("🚀 Avvio monitoraggio bandi – fonti HTML configurate")

    tutti_i_bandi = []
    problemi = []

    for regione, configurazione in FONTI_HTML.items():
        url = configurazione["url"]
        estrattore = configurazione["estrattore"]

        print(f"\n📍 Regione: {regione}")
        print(f"   Fonte: {url}")

        pagina, url_effettivo, errore = scarica_pagina(url)

        if errore:
            print(f"   ⚠️ Fonte non letta: {errore}")
            problemi.append((regione, f"pagina fonte non leggibile: {errore}"))
            continue

        try:
            bandi = estrattore(pagina, url_effettivo)
        except Exception as errore_estrazione:
            print(f"   ⚠️ Errore estrattore: {errore_estrazione}")
            problemi.append((regione, "errore durante estrazione dei bandi"))
            continue

        print(f"   Bandi individuati: {len(bandi)}")

        if not bandi:
            problemi.append((
                regione,
                "nessun bando individuato: verificare la struttura della fonte"
            ))
            continue

        for indice, bando in enumerate(bandi, start=1):
            print(f"   {indice}/{len(bandi)} - {bando['titolo'][:95]}")

            bando["descrizione"] = (
                "Apri il link ufficiale per leggere il dettaglio del bando."
            )
            bando["beneficiari"] = "non specificati"
            bando["importo"] = "non specificato"
            bando["aliquota"] = "non specificata"

            pagina_dettaglio, url_dettaglio, errore_dettaglio = scarica_pagina(
                bando["url"]
            )

            if errore_dettaglio:
                print(f"      Dettaglio non analizzato: {errore_dettaglio}")
                continue

            testo_dettaglio = testo_da_html(pagina_dettaglio)

            dettagli = analizza_bando_con_gemini(bando, testo_dettaglio)

            bando["descrizione"] = dettagli["descrizione"]
            bando["beneficiari"] = dettagli["beneficiari"]
            bando["importo"] = dettagli["importo"]
            bando["aliquota"] = dettagli["aliquota"]

            time.sleep(1)

        tutti_i_bandi.extend(bandi)

    risultati_finali = elimina_duplicati(tutti_i_bandi)

    print("\n" + "=" * 65)
    print(f"✅ Totale bandi nel report: {len(risultati_finali)}")

    report_html = crea_report_html(risultati_finali, problemi)
    invia_email(report_html, len(risultati_finali))

    print("📧 Email inviata con successo.")


if __name__ == "__main__":
    main()
