import os
import re
import json
import time
import html
import smtplib
from datetime import datetime
from urllib.parse import urljoin, urlparse
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
    raise ValueError("Manca il segreto GEMINI_API_KEY.")
if not GMAIL_USER or not GMAIL_PASSWORD or not DESTINATARIO:
    raise ValueError("Mancano uno o più segreti Gmail.")

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-2.5-flash")

REGIONI = {
    "Abruzzo": "https://www.regione.abruzzo.it/bandi-e-avvisi/agricoltura",

    "Basilicata": "https://agricoltura.regione.basilicata.it/bandi-regionali/",

    "Calabria": "https://www.regione.calabria.it/website/",

    "Campania": "https://agricoltura.regione.campania.it/bandi.html",

    "Emilia-Romagna": "https://agricoltura.regione.emilia-romagna.it/sviluppo-rurale-23-27/opportunita/bandi/bandi-aperti",

    "Friuli-Venezia Giulia": "https://www.opr.fvg.it/it/bandi-e-scadenze-per-la-presentazione-delle-domande-86876/bandi-aperti-72911",

    "Lazio": "https://www.regione.lazio.it/imprese/agricoltura",

    "Liguria": "https://www.siarliguria.it/web/Public/Bandi.aspx",

    "Lombardia": "https://www.bandi.regione.lombardia.it/servizi/servizio/bandi/agricoltura",

    "Marche": "https://siar.regione.marche.it/SiarWeb/Public/Bandi.aspx",

    "Molise": "https://www.regione.molise.it/",

    "Piemonte": "https://bandi.regione.piemonte.it/contributi-finanziamenti",

    "Puglia": "https://www.regione.puglia.it/web/agricoltura/bandi",

    "Sardegna": "https://www.sardegnaagricoltura.it/it/bandi/",

    "Sicilia": "https://www.psrsicilia.it/bandi-aperti/",

    "Toscana": "https://www.regione.toscana.it/sviluppo-rurale-2023-2027/bandi",

    "Trentino-Alto Adige": "https://www.provincia.bz.it/agricoltura/bandi.asp",

    "Umbria": "https://applicazioni.regione.umbria.it/widget/bandi1/-/bandi_WAR_bandiportlet",

    "Valle d'Aosta": "https://www.regione.vda.it/agricoltura/bandi_i.asp",

    "Veneto": "https://www.regione.veneto.it/web/agricoltura-e-foreste/bandi-finanziamenti",
}

PAROLE_CHIAVE = (
    "bando", "bandi", "avviso", "avvisi", "contribut", "finanzi",
    "agricolt", "rurale", "feasr", "csr", "psr", "sra", "srd",
    "sre", "srg", "pac", "aiuto", "sostegno"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "it-IT,it;q=0.9,en;q=0.8",
}


# ============================================================
# 2. DOWNLOAD ED ESTRAZIONE
# ============================================================

def scarica_pagina(url):
    try:
        risposta = requests.get(
            url,
            headers=HEADERS,
            timeout=35,
            allow_redirects=True
        )
        risposta.raise_for_status()
        return risposta.text, risposta.url
    except Exception as errore:
        print(f"   ⚠️ Download non riuscito: {errore}")
        return None, url


def pulisci_testo(testo):
    testo = re.sub(r"\s+", " ", testo or "")
    return testo.strip()


def testo_pagina(html_pagina):
    soup = BeautifulSoup(html_pagina, "lxml")

    for elemento in soup(["script", "style", "noscript", "svg", "nav", "footer", "header"]):
        elemento.decompose()

    return pulisci_testo(soup.get_text(" ", strip=True))


def estrai_link_bandi(html_pagina, url_base):
    soup = BeautifulSoup(html_pagina, "lxml")
    risultati = []
    visti = set()

    for link in soup.find_all("a", href=True):
        titolo = pulisci_testo(link.get_text(" ", strip=True))
        href = urljoin(url_base, link["href"])

        if not titolo or len(titolo) < 12:
            continue

        testo_da_valutare = f"{titolo} {href}".lower()
        if not any(parola in testo_da_valutare for parola in PAROLE_CHIAVE):
            continue

        if href.startswith(("mailto:", "tel:", "javascript:")):
            continue

        if href in visti:
            continue

        visti.add(href)
        risultati.append({
            "titolo_pagina_elenco": titolo[:350],
            "url": href
        })

    return risultati[:8]


# ============================================================
# 3. ANALISI CON GEMINI
# ============================================================

def analizza_con_gemini(regione, titolo, url_fonte, testo):
    testo = testo[:12000]

    prompt = f"""
Sei un analista scrupoloso di bandi pubblici italiani per il settore agricolo.

Data di oggi: {datetime.now().strftime("%d/%m/%Y")}

Analizza ESCLUSIVAMENTE le informazioni presenti nel testo fornito.
Non inventare mai scadenze, importi, aliquote, destinatari o stato del bando.

Un bando è "aperto" solo se il testo afferma chiaramente che:
- è aperto/in corso/attivo, oppure
- accetta domande fino a una data futura rispetto a oggi.

Escludi: bandi chiusi, graduatorie, esiti, proroghe di bandi già chiusi,
notizie generiche, gare non agricole, atti senza possibilità di domanda.

Restituisci SOLO un array JSON valido.
Se non ci sono bandi agricoli aperti, restituisci [].

Per ogni bando aperto restituisci:
{{
  "titolo": "titolo del bando",
  "scadenza": "GG/MM/AAAA oppure non specificata",
  "descrizione": "massimo 45 parole, solo dai dati disponibili",
  "importo": "dotazione/importo oppure non specificato",
  "aliquota": "percentuale/contributo oppure non specificata",
  "stato": "aperto",
  "fonte": "{url_fonte}"
}}

Regione: {regione}
Titolo visualizzato nell'elenco: {titolo}
URL fonte: {url_fonte}

TESTO:
{testo}
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

            if str(bando.get("stato", "")).lower() != "aperto":
                continue

            bando["regione"] = regione
            bando["fonte"] = bando.get("fonte") or url_fonte
            risultati.append(bando)

        return risultati

    except Exception as errore:
        print(f"   ⚠️ Errore Gemini: {errore}")
        return []


# ============================================================
# 4. ELIMINAZIONE DUPLICATI
# ============================================================

def rimuovi_duplicati(bandi):
    risultati = []
    chiavi_viste = set()

    for bando in bandi:
        chiave = (
            bando.get("regione", "").lower().strip(),
            bando.get("titolo", "").lower().strip()
        )

        if chiave in chiavi_viste:
            continue

        chiavi_viste.add(chiave)
        risultati.append(bando)

    return risultati


# ============================================================
# 5. REPORT HTML
# ============================================================

def h(valore):
    return html.escape(str(valore or "non specificato"))


def genera_report_html(bandi, errori_siti):
    data_oggi = datetime.now().strftime("%d/%m/%Y")
    regioni_con_bandi = len(set(b.get("regione", "") for b in bandi))

    righe = ""

    if bandi:
        for bando in bandi:
            link_fonte = h(bando.get("fonte", ""))
            fonte_html = (
                f'<a href="{link_fonte}" target="_blank">Apri fonte ufficiale</a>'
                if link_fonte else "non disponibile"
            )

            righe += f"""
            <tr>
              <td>{h(bando.get("regione"))}</td>
              <td><strong>{h(bando.get("titolo"))}</strong><br>{fonte_html}</td>
              <td class="scadenza">{h(bando.get("scadenza"))}</td>
              <td>{h(bando.get("descrizione"))}</td>
              <td>{h(bando.get("importo"))}</td>
              <td>{h(bando.get("aliquota"))}</td>
            </tr>
            """
    else:
        righe = """
        <tr>
          <td colspan="6" style="text-align:center;padding:28px">
            Nessun bando è stato identificato automaticamente.
            Questo risultato non certifica che non esistano bandi aperti:
            verifica le fonti ufficiali riportate più sotto.
          </td>
        </tr>
        """

    problemi_html = ""
    if errori_siti:
        elenco = "".join(f"<li>{h(regione)}: {h(errore)}</li>" for regione, errore in errori_siti)
        problemi_html = f"""
        <h2>Siti da verificare</h2>
        <p>Questi siti non sono stati letti correttamente durante questa esecuzione:</p>
        <ul>{elenco}</ul>
        """

    return f"""<!DOCTYPE html>
<html lang="it">
<head>
  <meta charset="UTF-8">
  <style>
    body {{ font-family: Arial, sans-serif; color:#222; line-height:1.45; margin:20px; }}
    h1 {{ color:#1f6b32; }}
    h2 {{ color:#1f6b32; margin-top:30px; }}
    .riepilogo {{ background:#eef8ef; border-left:5px solid #2d8a43; padding:14px; }}
    table {{ width:100%; border-collapse:collapse; margin-top:18px; font-size:14px; }}
    th {{ background:#287a3a; color:white; padding:10px; text-align:left; }}
    td {{ border:1px solid #d5d5d5; padding:10px; vertical-align:top; }}
    tr:nth-child(even) {{ background:#f7f7f7; }}
    .scadenza {{ color:#a11717; font-weight:bold; }}
    .nota {{ margin-top:25px; font-size:12px; color:#555; }}
  </style>
</head>
<body>
  <h1>Report settimanale – Bandi agricoli regionali</h1>

  <div class="riepilogo">
    <strong>Data elaborazione:</strong> {data_oggi}<br>
    <strong>Bandi aperti identificati:</strong> {len(bandi)}<br>
    <strong>Regioni con almeno un bando identificato:</strong> {regioni_con_bandi}<br>
    <strong>Regioni controllate:</strong> {len(REGIONI)}
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
      </tr>
    </thead>
    <tbody>
      {righe}
    </tbody>
  </table>

  {problemi_html}

  <p class="nota">
    Report automatico: prima di usare una misura in consulenza o presentare una domanda,
    verifica sempre bando, allegati, requisiti, proroghe e scadenza nel sito ufficiale.
  </p>
</body>
</html>
"""


# ============================================================
# 6. INVIO EMAIL
# ============================================================

def invia_email(report_html, numero_bandi):
    data_oggi = datetime.now().strftime("%d/%m/%Y")

    messaggio = MIMEMultipart("alternative")
    messaggio["Subject"] = f"Report bandi agricoli – {numero_bandi} bandi identificati – {data_oggi}"
    messaggio["From"] = GMAIL_USER
    messaggio["To"] = DESTINATARIO

    testo_semplice = (
        f"Report bandi agricoli del {data_oggi}.\n"
        f"Bandi identificati: {numero_bandi}.\n"
        "Apri l'email in HTML per visualizzare tabella e fonti ufficiali."
    )

    messaggio.attach(MIMEText(testo_semplice, "plain", "utf-8"))
    messaggio.attach(MIMEText(report_html, "html", "utf-8"))

    with smtplib.SMTP("smtp.gmail.com", 587, timeout=40) as server:
        server.starttls()
        server.login(GMAIL_USER, GMAIL_PASSWORD)
        server.send_message(messaggio)


# ============================================================
# 7. AVVIO
# ============================================================

def main():
    print("🚀 Avvio monitoraggio bandi agricoli regionali")
    tutti_i_bandi = []
    errori_siti = []

    for regione, url_elenco in REGIONI.items():
        print(f"\n📍 {regione}")

        pagina_elenco, url_effettivo = scarica_pagina(url_elenco)
        if not pagina_elenco:
            errori_siti.append((regione, "pagina elenco non raggiungibile"))
            continue

        link_bandi = estrai_link_bandi(pagina_elenco, url_effettivo)

        if not link_bandi:
            print("   Nessun link specifico rilevato: analizzo la pagina elenco.")
            testo = testo_pagina(pagina_elenco)
            bandi = analizza_con_gemini(regione, "Pagina elenco bandi", url_effettivo, testo)
            tutti_i_bandi.extend(bandi)
            time.sleep(1)
            continue

        print(f"   Link pertinenti trovati: {len(link_bandi)}")

        for indice, voce in enumerate(link_bandi, start=1):
            print(f"   Analizzo {indice}/{len(link_bandi)}: {voce['titolo_pagina_elenco'][:70]}")

            pagina_bando, url_bando_effettivo = scarica_pagina(voce["url"])
            if not pagina_bando:
                continue

            testo = testo_pagina(pagina_bando)
            bandi = analizza_con_gemini(
                regione,
                voce["titolo_pagina_elenco"],
                url_bando_effettivo,
                testo
            )
            tutti_i_bandi.extend(bandi)
            time.sleep(1)

    tutti_i_bandi = rimuovi_duplicati(tutti_i_bandi)

    print("\n" + "=" * 60)
    print(f"✅ Bandi identificati: {len(tutti_i_bandi)}")

    report = genera_report_html(tutti_i_bandi, errori_siti)
    invia_email(report, len(tutti_i_bandi))
    print("📧 Email inviata con successo.")


if __name__ == "__main__":
    main()
