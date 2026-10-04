import os
import requests
from bs4 import BeautifulSoup
import google.generativeai as genai
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime
import json
import re

# Configurazione
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GMAIL_USER = os.getenv("GMAIL_USER")
GMAIL_PASSWORD = os.getenv("GMAIL_PASSWORD")
DESTINATARIO = os.getenv("DESTINATARIO_EMAIL")

# Configura Gemini
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-2.5-flash')

# SITI DI TUTTE LE REGIONI ITALIANE
REGIONI = {
    "Abruzzo": "https://www.regione.abruzzo.it/bandi-e-avvisi/agricoltura",
    "Basilicata": "https://www.regione.basilicata.it/page/bandi-agricoltura",
    "Calabria": "https://www.regione.calabria.it/dipartimento-agricoltura-risorse-agroalimentari-e-forestazione/",
    "Campania": "https://agricoltura.regione.campania.it/bandi-e-finanziamenti/",
    "Emilia-Romagna": "https://agricoltura.regione.emilia-romagna.it/sviluppo-rurale-23-27/opportunita/bandi",
    "Friuli-Venezia Giulia": "https://www.regione.fvg.it/rafvg/cms/RAFVG/economia-imprese/agricoltura-foreste/FOGLIA94/",
    "Lazio": "https://www.regione.lazio.it/imprese/agricoltura",
    "Liguria": "https://www.siarliguria.it/web/Public/Bandi.aspx",
    "Lombardia": "https://www.bandi.regione.lombardia.it/servizi/servizio/bandi/agricoltura",
    "Marche": "https://siar.regione.marche.it/SiarWeb/Public/Bandi.aspx",
    "Molise": "https://www.regione.molise.it/flex/cm/pages/ServBando.php",
    "Piemonte": "https://bandi.regione.piemonte.it/contributi-finanziamenti",
    "Puglia": "https://www.regione.puglia.it/web/agricoltura/bandi",
    "Sardegna": "https://www.sardegnaagricoltura.it/it/bandi/",
    "Sicilia": "https://www.psrsicilia.it/bandi-aperti/",
    "Toscana": "https://www.regione.toscana.it/sviluppo-rurale-2023-2027/bandi",
    "Trentino-Alto Adige": "https://www.provincia.bz.it/agricoltura/bandi.asp",
    "Umbria": "https://www.regione.umbria.it/la-regione/bandi",
    "Valle d'Aosta": "https://www.regione.vda.it/agricoltura/bandi_i.asp",
    "Veneto": "https://www.regione.veneto.it/web/agricoltura-e-foreste/bandi-finanziamenti"
}

def scarica_pagina(url):
    """Scarica il contenuto HTML di una pagina"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }
    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        return response.text
    except Exception as e:
        print(f"Errore download {url}: {e}")
        return None

def estrai_testo_bandi(html, regione):
    """Estrae il testo grezzo dei bandi dalla pagina HTML"""
    if not html:
        return []
    
    soup = BeautifulSoup(html, 'html.parser')
    
    # Rimuovi script e style
    for elemento in soup(['script', 'style', 'nav', 'footer']):
        elemento.decompose()
    
    # Cerca elementi con parole chiave
    bandi = []
    parole_chiave = ['bando', 'avviso', 'misura', 'azione', 'finanziamento', 'contributo', 'scadenza']
    
    # Cerca link e div che contengono testo sui bandi
    for elemento in soup.find_all(['a', 'div', 'li', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6']):
        testo = elemento.get_text(' ', strip=True)
        if testo and len(testo) > 30 and len(testo) < 2000:
            if any(parola in testo.lower() for parola in parole_chiave):
                bandi.append(f"[{regione}] {testo}")
    
    # Se non trova nulla, prendi sezioni di testo
    if not bandi:
        testo_completo = soup.get_text(separator=' ')
        chunk_size = 1500
        for i in range(0, min(len(testo_completo), 10000), chunk_size):
            chunk = testo_completo[i:i+chunk_size]
            if len(chunk.strip()) > 100:
                bandi.append(f"[{regione}] {chunk}")
    
    return bandi[:10]

def analizza_con_gemini(testo_bando):
    """Usa Gemini per estrarre i dettagli del bando"""
    prompt = f"""Sei un esperto di bandi agricoli italiani. Analizza questo testo e estrai SOLO i bandi APERTI (non scaduti).

Per ogni bando aperto trovato, crea un oggetto JSON con:
- "titolo": nome completo del bando
- "scadenza": data di scadenza (formato GG/MM/AAAA, o "non specificata")
- "descrizione": breve descrizione (max 40 parole)
- "importo": importo totale/budget (es. "50.000 €", "non specificato")
- "aliquota": percentuale contribuzione (es. "40%", "50%", "non specificata")

Testo da analizzare:
{text_bando}

IMPORTANTE: Rispondi SOLO con un array JSON valido. Esempio:
[{{"titolo": "...", "scadenza": "...", "descrizione": "...", "importo": "...", "aliquota": "..."}}]

Se non trovi bandi aperti, rispondi con: []"""

    try:
        response = model.generate_content(prompt)
        testo_risposta = response.text
        
        match = re.search(r'\[.*\]', testo_risposta, re.DOTALL)
        if match:
            return json.loads(match.group())
        return []
    except Exception as e:
        print(f"Errore Gemini: {e}")
        return []

def genera_report_html(bandi_trovati):
    """Genera un report HTML con tutti i bandi"""
    data_oggi = datetime.now().strftime("%d/%m/%Y")
    
    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; max-width: 1200px; margin: 0 auto; padding: 20px; }}
        h1 {{ color: #2e7d32; border-bottom: 3px solid #4caf50; padding-bottom: 10px; }}
        .meta {{ background: #e8f5e9; padding: 15px; border-radius: 5px; margin-bottom: 20px; }}
        table {{ border-collapse: collapse; width: 100%; margin-top: 20px; }}
        th, td {{ border: 1px solid #ddd; padding: 12px; text-align: left; vertical-align: top; }}
        th {{ background-color: #4caf50; color: white; font-weight: bold; }}
        tr:nth-child(even) {{ background-color: #f9f9f9; }}
        tr:hover {{ background-color: #f1f1f1; }}
        .scadenza {{ color: #d32f2f; font-weight: bold; }}
        .regione {{ background: #e3f2fd; font-weight: bold; }}
        .footer {{ margin-top: 30px; padding-top: 20px; border-top: 2px solid #ddd; font-size: 12px; color: #666; }}
    </style>
</head>
<body>
    <h1>📋 Report Settimanale Bandi Agricoli Aperti</h1>
    
    <div class="meta">
        <strong>Data generazione:</strong> {data_oggi}<br>
        <strong>Totale bandi trovati:</strong> {len(bandi_trovati)}<br>
        <strong>Regioni monitorate:</strong> {len(set(b['regione'] for b in bandi_trovati)) if bandi_trovati else 0}
    </div>
    
    <table>
        <thead>
            <tr>
                <th style="width: 12%;">Regione</th>
                <th style="width: 20%;">Titolo</th>
                <th style="width: 10%;">Scadenza</th>
                <th style="width: 28%;">Descrizione</th>
                <th style="width: 15%;">Importo</th>
                <th style="width: 15%;">Aliquota</th>
            </tr>
        </thead>
        <tbody>
"""
    
    if bandi_trovati:
        for bando in bandi_trovati:
            html += f"""
            <tr>
                <td class="regione">{bando.get('regione', 'N/A')}</td>
                <td><strong>{bando.get('titolo', 'N/A')}</strong></td>
                <td class="scadenza">{bando.get('scadenza', 'N/A')}</td>
                <td>{bando.get('descrizione', 'N/A')}</td>
                <td>{bando.get('importo', 'N/A')}</td>
                <td>{bando.get('aliquota', 'N/A')}</td>
            </tr>
"""
    else:
        html += """
            <tr>
                <td colspan="6" style="text-align: center; padding: 40px; color: #666;">
                    Nessun bando aperto trovato questa settimana. Riprova la prossima settimana.
                </td>
            </tr>
"""
    
    html += f"""
        </tbody>
    </table>
    
    <div class="footer">
        <p>⚠️ <strong>Nota importante:</strong> Questo report è generato automaticamente. Verifica sempre le informazioni sui siti ufficiali delle regioni prima di presentare domande.</p>
        <p>Report generato con sistema automatizzato open-source.</p>
    </div>
</body>
</html>
"""
    
    return html

def invia_email(contenuto_html):
    """Invia il report via email"""
    data_oggi = datetime.now().strftime("%d/%m/%Y")
    
    msg = MIMEMultipart('alternative')
    msg['Subject'] = f"📊 Report Bandi Agricoli Aperti - {data_oggi}"
    msg['From'] = GMAIL_USER
    msg['To'] = DESTINATARIO
    
    testo_semplice = f"""REPORT BANDI AGRICOLI - {data_oggi}

Apri questa email in formato HTML per visualizzare la tabella completa con tutti i dettagli dei bandi.

---
Report generato automaticamente. Verifica sui siti ufficiali.
"""
    msg.attach(MIMEText(testo_semplice, 'plain', 'utf-8'))
    msg.attach(MIMEText(contenuto_html, 'html', 'utf-8'))
    
    try:
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()
            server.login(GMAIL_USER, GMAIL_PASSWORD)
            server.send_message(msg)
        print("✅ Email inviata con successo!")
    except Exception as e:
        print(f"❌ Errore invio email: {e}")
        raise

def main():
    print("🚀 Avvio monitoraggio bandi agricoli...")
    print(f"Data: {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    print("-" * 60)
    
    tutti_i_bandi = []
    
    for regione, url in REGIONI.items():
        print(f"\n📍 Analisi {regione}...")
        
        html = scarica_pagina(url)
        if not html:
            print(f"   ⚠️ Saltata (pagina non raggiungibile)")
            continue
        
        testi_bandi = estrai_testo_bandi(html, regione)
        print(f"   Trovati {len(testi_bandi)} chunk di testo")
        
        for i, testo in enumerate(testi_bandi, 1):
            print(f"   Analisi chunk {i}/{len(testi_bandi)}...")
            bandi_json = analizza_con_gemini(testo)
            
            for bando in bandi_json:
                bando['regione'] = regione
                tutti_i_bandi.append(bando)
                print(f"   ✅ Bando: {bando.get('titolo', 'N/A')[:50]}...")
    
    print("\n" + "=" * 60)
    print(f"📊 Totale bandi aperti trovati: {len(tutti_i_bandi)}")
    
    if tutti_i_bandi:
        print("\n📧 Generazione report HTML...")
        html_report = genera_report_html(tutti_i_bandi)
        
        print("📧 Invio email...")
        invia_email(html_report)
        
        print("\n✅ Completato!")
    else:
        print("\n⚠️ Nessun bando trovato.")
        html_vuoto = genera_report_html([])
        invia_email(html_vuoto)
        print("✅ Email di notifica inviata (nessun bando)")

if __name__ == "__main__":
    main()
