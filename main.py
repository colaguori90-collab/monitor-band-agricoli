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
# 1. CONFIGURAZIONE
# ============================================================

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GMAIL_USER = os.getenv("GMAIL_USER")
GMAIL_PASSWORD = os.getenv("GMAIL_PASSWORD")
DESTINATARIO = os.getenv("DESTINATARIO_EMAIL")

if not GEMINI_API_KEY:
    raise ValueError("Manca GEMINI_API_KEY nei Secrets di GitHub.")

if not GMAIL_USER or not GMAIL_PASSWORD or not DESTINATARIO:
    raise ValueError("Mancano dati Gmail nei Secrets di GitHub.")

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

# Per iniziare usiamo solo due fonti con pagine dedicate ai bandi aperti.
# Quando il test produrrà correttamente il report, aggiungeremo le altre regioni.
REGIONI = {
    "Campania": "https://agricoltura.regione.campania.it/bandi.html",
    "Emilia-Romagna": "https://agricoltura.regione.emilia-romagna.it/sviluppo-rurale-23-27/opportunita/bandi/bandi-aperti",
}

PAROLE_CHIAVE = (
    "bando", "bandi", "avviso", "avvisi",
    "srd", "sra", "sre", "srg", "srh", "srb",
    "agricolt", "rurale", "forest", "zootecn",
    "contribut", "finanzi", "sostegno", "aiuto",
    "psr", "csr", "feasr", "pac",
)

VOCI_MENU_DA_ESCLUDERE = {
    "bando",
    "bandi",
    "bandi aperti",
    "bandi e avvisi",
    "tutti i bandi",
    "agricoltura",
    "sviluppo rurale",
    "contributi e finanziamenti",
    "home",
}


# ============================================================
# 2. SCARICAMENTO PAGINE
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


# ============================================================
# 3. RACCOLTA LINK BANDI
# ============================================================

def link_pertinente(titolo, url):
    testo = f"{titolo} {url}".lower()
    return any(parola in testo for parola in PAROLE_CHIAVE)


def e_voce_di_menu(titolo):
    titolo_normale = pulisci_testo(titolo).lower()
    return titolo_normale in VOCI_MENU_DA_ESCLUDERE


def estrai_link_bandi(html_pagina, url_base):
    soup = BeautifulSoup(html_pagina, "lxml")
    risultati = []
    visti = set()

    for link in soup.find_all("a", href=True):
        titolo = pulisci_testo(link.get_text(" ", strip=True))
        url = urljoin(url_base, link["href"])

        if not titolo or len(titolo) < 15:
            continue

        if url.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue

        if not url.startswith(("http://", "https://")):
            continue

        if e_voce_di_menu(titolo):
            continue

        if not link_pertinente(titolo, url):
            continue

        chiave = (titolo.lower(), url.lower())
        if chiave in visti:
            continue

        visti.add(chiave)

        risultati.append({
            "titolo": titolo[:350],
            "url": url
        })

    return risultati[:20]


# ============================================================
# 4. GEMINI: SINTESI DELLA PAGINA DI DETTAGLIO
# ============================================================

def dettagli_con_gemini(regione, titolo, url, testo):
    dettagli_base = {
        "scadenza": "non specificata",
        "descrizione": "Dettagli non estratti automaticamente: apri la fonte ufficiale.",
        "importo": "non specificato",
        "aliquota": "non specificata",
    }

    if len(testo) < 150:
        return dettagli_base

    prompt = f"""
Sei un assistente di supporto alla consulenza per bandi agricoli italiani.

Analizza il testo della pagina ufficiale di un singolo bando/avviso.

Regione: {regione}
Titolo del link: {titolo}
Fonte: {url}

Estrai solo informazioni presenti esplicitamente nel testo.
Non inventare dati. Se un dato non compare, usa esattamente la stringa:
"non specificato".

Restituisci ESCLUSIVAMENTE un JSON valido, senza Markdown e senza testo esterno,
con queste quattro chiavi:

{{
  "scadenza": "data o non specificato",
  "descrizione": "massimo 45 parole",
  "importo": "dotazione/importo o non specificato",
  "aliquota": "percentuale di contributo o non specificato"
}}

TESTO:
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
            return dettagli_base

        return {
            "scadenza": str(dati.get("scadenza", "non specificato")),
            "descrizione": str(dati.get(
                "descrizione",
                "Dettagli non estratti automaticamente: apri la fonte ufficiale."
            )),
            "importo": str(dati.get("importo", "non specificato")),
            "aliquota": str(dati.get("aliquota", "non specificata")),
        }

    except Exception as errore:
        print(f"   ⚠️ Gemini non ha elaborato il dettaglio: {errore}")
        return dettagli_base


# ============================================================
# 5. REPORT EMAIL
# ============================================================

def esc(valore):
    return html.escape(str(valore or "non specificato"))


def crea_report_html(bandi, errori):
    data = datetime.now().strftime("%d/%m/%Y")

    if bandi:
        righe = ""

        for bando in bandi:
            url = esc(bando["url"])

            righe += f"""
            <tr>
                <td>{esc(bando["regione"])}</td>
                <td>
                    <strong>{esc(bando["titolo"])}</strong><br>
                    <a href="{url}" target="_blank">Apri la fonte ufficiale</a>
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
            <td colspan="6" style="text-align:center;padding:30px">
                Nessun link specifico è stato trovato.
            </td>
        </tr>
        """

    blocco_errori = ""
    if errori:
        elementi = "".join(
            f"<li><strong>{esc(regione)}</strong>: {esc(messaggio)}</li>"
            for regione, messaggio in errori
        )

        blocco_errori = f"""
        <h2>Fonti da verificare</h2>
        <ul>{elementi}</ul>
        """

    return f"""<!DOCTYPE html>
<html lang="it">
<head>
<meta charset="UTF-8">
<style>
body {{
    font-family: Arial, sans-serif;
    margin: 20px;
    color: #222;
    line-height: 1.45;
}}
h1, h2 {{
    color: #246b36;
}}
.riepilogo {{
    background: #edf8ef;
    border-left: 5px solid #2d8a43;
    padding: 15px;
    margin-bottom: 20px;
}}
table {{
    border-collapse: collapse;
    width: 100%;
    font-size: 13px;
}}
th {{
    background: #287c3d;
    color: white;
    text-align: left;
    padding: 10px;
}}
td {{
    border: 1px solid #ddd;
    padding: 10px;
    vertical-align: top;
}}
tr:nth-child(even) {{
    background: #f8f8f8;
}}
.nota {{
    margin-top: 30px;
    color: #555;
    font-size: 12px;
}}
</style>
</head>
<body>

<h1>Report settimanale – Bandi agricoli regionali</h1>

<div class="riepilogo">
<strong>Data elaborazione:</strong> {data}<br>
<strong>Link a bandi/avvisi trovati:</strong> {len(bandi)}<br>
<strong>Regioni esaminate:</strong> {len(REGIONI) - len(errori)} su {len(REGIONI)}
</div>

<table>
<thead>
<tr>
<th>Regione</th>
<th>Bando e link ufficiale</th>
<th>Scadenza</th>
<th>Descrizione</th>
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
Il titolo e il link sono raccolti dalle pagine ufficiali regionali dedicate a bandi aperti/in corso.
Le informazioni riassuntive sono generate automaticamente: verifica sempre testo del bando,
allegati, requisiti, proroghe e scadenza nella fonte ufficiale.
</p>

</body>
</html>
"""


# ============================================================
# 6. INVIO EMAIL
# ============================================================

def invia_email(report_html, numero_bandi):
    data = datetime.now().strftime("%d/%m/%Y")

    messaggio = MIMEMultipart("alternative")
    messaggio["From"] = GMAIL_USER
    messaggio["To"] = DESTINATARIO
    messaggio["Subject"] = (
        f"Report bandi agricoli – {numero_bandi} link trovati – {data}"
    )

    testo = (
        f"Report bandi agricoli del {data}. "
        f"Link trovati: {numero_bandi}. "
        "Apri l'email in HTML per vedere dettagli e fonti."
    )

    messaggio.attach(MIMEText(testo, "plain", "utf-8"))
    messaggio.attach(MIMEText(report_html, "html", "utf-8"))

    with smtplib.SMTP("smtp.gmail.com", 587, timeout=40) as server:
        server.starttls()
        server.login(GMAIL_USER, GMAIL_PASSWORD)
        server.send_message(messaggio)


# ============================================================
# 7. AVVIO PROGRAMMA
# ============================================================

def main():
    print("🚀 Avvio monitoraggio bandi agricoli")

    tutti_i_bandi = []
    errori = []

    for regione, url_elenco in REGIONI.items():
        print(f"\n📍 Analisi: {regione}")

        pagina_elenco, url_effettivo, errore = scarica_pagina(url_elenco)

        if errore:
            print(f"   ⚠️ Pagina non raggiunta: {errore}")
            errori.append((regione, "pagina elenco non raggiungibile"))
            continue

        link_bandi = estrai_link_bandi(pagina_elenco, url_effettivo)
        print(f"   Link pertinenti trovati: {len(link_bandi)}")

        for numero, link in enumerate(link_bandi, start=1):
            print(f"   {numero}/{len(link_bandi)} - {link['titolo'][:70]}")

            dettagli = {
                "scadenza": "non specificata",
                "descrizione": "Dettagli non estratti automaticamente: apri la fonte ufficiale.",
                "importo": "non specificato",
                "aliquota": "non specificata",
            }

            pagina_dettaglio, url_dettaglio, errore_dettaglio = scarica_pagina(link["url"])

            if not errore_dettaglio and pagina_dettaglio:
                testo = testo_pagina(pagina_dettaglio)
                dettagli = dettagli_con_gemini(
                    regione,
                    link["titolo"],
                    url_dettaglio,
                    testo
                )
            else:
                print("      Dettaglio non leggibile: mantengo titolo e link.")

            tutti_i_bandi.append({
                "regione": regione,
                "titolo": link["titolo"],
                "url": link["url"],
                "scadenza": dettagli["scadenza"],
                "descrizione": dettagli["descrizione"],
                "importo": dettagli["importo"],
                "aliquota": dettagli["aliquota"],
            })

            time.sleep(1)

    # Elimina eventuali duplicati: stessa regione + stesso link
    bandi_unici = []
    visti = set()

    for bando in tutti_i_bandi:
        chiave = (bando["regione"], bando["url"])

        if chiave in visti:
            continue

        visti.add(chiave)
        bandi_unici.append(bando)

    print("\n" + "=" * 60)
    print(f"✅ Link/bandi totali trovati: {len(bandi_unici)}")

    report_html = crea_report_html(bandi_unici, errori)
    invia_email(report_html, len(bandi_unici))

    print("📧 Report inviato con successo.")


if __name__ == "__main__":
    main()
