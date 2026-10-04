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
scrivi
