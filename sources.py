import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup


# ============================================================
# IMPOSTAZIONI GENERALI
# ============================================================

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "it-IT,it;q=0.9,en;q=0.8",
}

PAROLE_ESCLUSE = (
    "graduatoria",
    "graduatorie",
    "esito",
    "esiti",
    "ammessi",
    "ammissibili",
    "finanziati",
    "finanziabili",
    "pagamento",
    "pagamenti",
    "liquidazione",
    "liquidazioni",
    "rendicontazione",
    "rettifica",
    "revoca",
    "gara",
    "gare",
    "concorso",
    "concorsi",
    "selezione del personale",
    "assistenza tecnica",
    "fiera",
    "fiere",
    "evento",
    "eventi",
    "manifestazione",
    "feampa",
    "pesca",
    "acquacoltura",
)

PAROLE_AGRICOLTURA = (
    "agricolt",
    "rurale",
    "forest",
    "zootecn",
    "agroaliment",
    "agricol",
    "psr",
    "csr",
    "feasr",
    "pac",
    "leader",
    "gal",
    "srd",
    "sra",
    "srb",
    "sre",
    "srg",
    "srh",
)

STATI_AMMESSI = (
    "aperto",
    "aperti",
    "in corso",
    "in apertura",
    "prossima apertura",
    "sportello aperto",
)


# ============================================================
# FUNZIONI DI SUPPORTO
# ============================================================

def pulisci_testo(testo):
    return re.sub(r"\s+", " ", testo or "").strip()


def contiene_esclusioni(testo):
    testo = (testo or "").lower()
    return any(parola in testo for parola in PAROLE_ESCLUSE)


def riguarda_agricoltura(testo):
    testo = (testo or "").lower()
    return any(parola in testo for parola in PAROLE_AGRICOLTURA)


def stato_ammesso(testo):
    testo = (testo or "").lower()
    return any(stato in testo for stato in STATI_AMMESSI)


def cerca_scadenza(testo):
    testo = pulisci_testo(testo)

    mesi = (
        "gennaio|febbraio|marzo|aprile|maggio|giugno|"
        "luglio|agosto|settembre|ottobre|novembre|dicembre"
    )

    pattern_num = r"\b\d{1,2}[/-]\d{1,2}[/-]\d{4}\b"
    pattern_testo = rf"\b\d{{1,2}}\s+({mesi})\s+\d{{4}}\b"

    # Cerca prima una data associata a "scadenza", "entro", "chiude".
    match = re.search(
        rf"(scadenza|entro|chiude|termine).{{0,100}}?({pattern_num}|{pattern_testo})",
        testo,
        flags=re.IGNORECASE
    )

    if match:
        return match.group(2)

    match = re.search(pattern_num, testo)
    if match:
        return match.group(0)

    match = re.search(pattern_testo, testo, flags=re.IGNORECASE)
    if match:
        return match.group(0)

    return "non specificata"


def crea_record(regione, titolo, url, testo="", stato="Aperto", categoria="CSR / Sviluppo rurale"):
    return {
        "regione": regione,
        "stato": stato,
        "titolo": pulisci_testo(titolo)[:500],
        "scadenza": cerca_scadenza(testo),
        "url": url,
        "categoria": categoria,
    }


def elimina_duplicati(bandi):
    risultati = []
    visti = set()

    for bando in bandi:
        chiave = (
            bando["regione"].lower(),
            bando["titolo"].lower(),
            bando["url"].lower(),
        )

        if chiave not in visti:
            visti.add(chiave)
            risultati.append(bando)

    return risultati


# ============================================================
# CAMPANIA
# ============================================================

def estrai_campania(html_pagina, url_base):
    """
    Include solamente:
    - CSR 2023-2027
    - PSR 2014-2022, se la riga è ancora aperta
    - GAL

    Esclude FEAMPA/pesca, manifestazioni, eventi e comunicazioni.
    """
    soup = BeautifulSoup(html_pagina, "lxml")
    risultati = []

    for riga in soup.find_all("tr"):
        testo = pulisci_testo(riga.get_text(" ", strip=True))
        testo_basso = testo.lower()

        if len(testo) < 20:
            continue

        if contiene_esclusioni(testo):
            continue

        # Ammessi: CSR/PSR o GAL.
        if not (
            "csr" in testo_basso
            or "psr" in testo_basso
            or "gal" in testo_basso
            or any(codice in testo_basso for codice in ("srd", "sra", "srb", "sre", "srg", "srh"))
        ):
            continue

        # Evita righe che non sono bandi/misure.
        if not (
            "bando" in testo_basso
            or "avviso" in testo_basso
            or "intervento" in testo_basso
            or "gal" in testo_basso
        ):
            continue

        link = riga.find("a", href=True)
        if not link:
            continue

        url = urljoin(url_base, link["href"])

        if url.rstrip("/") == url_base.rstrip("/"):
            continue

        titolo = re.sub(
            r"\b(vai alla pagina|dettaglio|apri)\b.*$",
            "",
            testo,
            flags=re.IGNORECASE
        ).strip()

        risultati.append(
            crea_record(
                "Campania",
                titolo,
                url,
                testo,
                stato="Aperto",
                categoria="CSR / PSR / GAL"
            )
        )

    return elimina_duplicati(risultati)


# ============================================================
# FRIULI-VENEZIA GIULIA
# ============================================================

def estrai_fvg(html_pagina, url_base):
    """
    La pagina OPR FVG mostra singoli bandi aperti con
    il pulsante/collegamento 'Vai alla pagina'.
    """
    soup = BeautifulSoup(html_pagina, "lxml")
    risultati = []

    for link in soup.find_all("a", href=True):
        testo_link = pulisci_testo(link.get_text(" ", strip=True))
        href = link.get("href", "")

        if "vai alla pagina" not in testo_link.lower():
            continue

        contenitore = link.parent
        testo = ""

        for _ in range(4):
            if not contenitore:
                break

            testo = pulisci_testo(contenitore.get_text(" ", strip=True))

            if len(testo) > 20:
                break

            contenitore = contenitore.parent

        if contiene_esclusioni(testo):
            continue

        if not riguarda_agricoltura(testo):
            continue

        titolo = re.sub(
            r"\bvai alla pagina\b.*$",
            "",
            testo,
            flags=re.IGNORECASE
        ).strip()

        if len(titolo) < 10:
            continue

        risultati.append(
            crea_record(
                "Friuli-Venezia Giulia",
                titolo,
                urljoin(url_base, href),
                testo,
                stato="Aperto",
                categoria="CSR / Sviluppo rurale"
            )
        )

    return elimina_duplicati(risultati)


# ============================================================
# MOLISE
# ============================================================

def estrai_molise(html_pagina, url_base):
    """
    Pagina dedicata esclusivamente ai bandi aperti CSR 2023-2027.
    Inserisce tutte le voci SR... e cerca il relativo link.
    """
    soup = BeautifulSoup(html_pagina, "lxml")
    risultati = []

    for tag in soup.find_all(["h2", "h3", "h4", "li", "p", "a"]):
        testo = pulisci_testo(tag.get_text(" ", strip=True))

        if not re.search(r"\bSR[A-Z]?\d{2}\b", testo, flags=re.IGNORECASE):
            continue

        if contiene_esclusioni(testo):
            continue

        link = tag.find("a", href=True)

        if not link:
            contenitore = tag.parent
            if contenitore:
                link = contenitore.find("a", href=True)

        url = urljoin(url_base, link["href"]) if link else url_base

        risultati.append(
            crea_record(
                "Molise",
                testo,
                url,
                testo,
                stato="Aperto",
                categoria="CSR 2023-2027 / LEADER"
            )
        )

    return elimina_duplicati(risultati)


# ============================================================
# PIEMONTE
# ============================================================

def estrai_piemonte(html_pagina, url_base):
    """
    Calendario bandi Piemonte:
    ogni opportunità ha di norma titolo, scadenza e link diretto.
    """
    soup = BeautifulSoup(html_pagina, "lxml")
    risultati = []

    for titolo_tag in soup.find_all(["h2", "h3", "h4"]):
        titolo = pulisci_testo(titolo_tag.get_text(" ", strip=True))

        if len(titolo) < 12:
            continue

        if contiene_esclusioni(titolo):
            continue

        contenitore = titolo_tag.parent
        testo = pulisci_testo(contenitore.get_text(" ", strip=True)) if contenitore else titolo

        if not riguarda_agricoltura(f"{titolo} {testo}"):
            continue

        link = titolo_tag.find("a", href=True)

        if not link and contenitore:
            link = contenitore.find("a", href=True)

        if not link:
            continue

        url = urljoin(url_base, link["href"])

        if url.rstrip("/") == url_base.rstrip("/"):
            continue

        risultati.append(
            crea_record(
                "Piemonte",
                titolo,
                url,
                testo,
                stato="Aperto",
                categoria="CSR / Agricoltura"
            )
        )

    return elimina_duplicati(risultati)


# ============================================================
# SICILIA
# ============================================================

def estrai_sicilia(html_pagina, url_base):
    """
    Categoria WordPress 'Bandi aperti'.
    Inserisce solo veri bandi/interventi e scarta rettifiche,
    graduatorie, griglie di riduzione e comunicazioni successive.
    """
    soup = BeautifulSoup(html_pagina, "lxml")
    risultati = []

    parole_necessarie = (
        "bando",
        "intervento srd",
        "intervento sra",
        "intervento srb",
        "intervento sre",
        "intervento srg",
        "intervento srh",
        "avviso pubblico",
    )

    for titolo_tag in soup.find_all(["h2", "h3", "h4"]):
        titolo = pulisci_testo(titolo_tag.get_text(" ", strip=True))
        titolo_basso = titolo.lower()

        if len(titolo) < 12:
            continue

        if contiene_esclusioni(titolo):
            continue

        if not any(parola in titolo_basso for parola in parole_necessarie):
            continue

        link = titolo_tag.find("a", href=True)

        if not link:
            continue

        risultati.append(
            crea_record(
                "Sicilia",
                titolo,
                urljoin(url_base, link["href"]),
                titolo,
                stato="Aperto",
                categoria="CSR / Sviluppo rurale"
            )
        )

    return elimina_duplicati(risultati)


# ============================================================
# VALLE D'AOSTA
# ============================================================

def estrai_valle_aosta(html_pagina, url_base):
    """
    Pagina FEASR Bandi aperti. Le card iniziano spesso con 'SCADE IL'.
    """
    soup = BeautifulSoup(html_pagina, "lxml")
    risultati = []

    for titolo_tag in soup.find_all(["h2", "h3", "h4"]):
        titolo = pulisci_testo(titolo_tag.get_text(" ", strip=True))

        if len(titolo) < 12:
            continue

        contenitore = titolo_tag.parent
        testo = pulisci_testo(contenitore.get_text(" ", strip=True)) if contenitore else titolo

        if contiene_esclusioni(f"{titolo} {testo}"):
            continue

        if not riguarda_agricoltura(f"{titolo} {testo}"):
            continue

        if "scade" not in testo.lower() and "aperto" not in testo.lower():
            continue

        link = titolo_tag.find("a", href=True)

        if not link and contenitore:
            link = contenitore.find("a", href=True)

        if not link:
            continue

        risultati.append(
            crea_record(
                "Valle d'Aosta",
                titolo,
                urljoin(url_base, link["href"]),
                testo,
                stato="Aperto",
                categoria="FEASR / CSR"
            )
        )

    return elimina_duplicati(risultati)


# ============================================================
# BASILICATA
# ============================================================

def estrai_basilicata(html_pagina, url_base):
    """
    SIA-RB:
    mantiene i link contenuti nella sezione 'Bandi in corso'
    ed esclude quelli che seguono 'Bandi Regionali scaduti'.
    """
    soup = BeautifulSoup(html_pagina, "lxml")
    risultati = []
    in_corso = False

    for elemento in soup.find_all(["h1", "h2", "h3", "h4", "a", "li", "p", "div"]):
        testo = pulisci_testo(elemento.get_text(" ", strip=True))
        testo_basso = testo.lower()

        if "bandi in corso" in testo_basso:
            in_corso = True
            continue

        if "bandi regionali scaduti" in testo_basso or "bandi scaduti" in testo_basso:
            in_corso = False

        if not in_corso:
            continue

        if elemento.name != "a":
            continue

        titolo = testo

        if len(titolo) < 15:
            continue

        if contiene_esclusioni(titolo):
            continue

        if not riguarda_agricoltura(titolo):
            continue

        href = elemento.get("href", "")
        if not href:
            continue

        risultati.append(
            crea_record(
                "Basilicata",
                titolo,
                urljoin(url_base, href),
                titolo,
                stato="Aperto",
                categoria="Agricoltura / Sviluppo rurale"
            )
        )

    return elimina_duplicati(risultati)


# ============================================================
# FONTI ESTRATTORE
# ============================================================

FONTI_HTML = {
    "Campania": {
        "url": "https://agricoltura.regione.campania.it/bandi.html",
        "estrattore": estrai_campania,
    },
    "Friuli-Venezia Giulia": {
        "url": "https://www.opr.fvg.it/it/bandi-e-scadenze-per-la-presentazione-delle-domande-86876/bandi-aperti-72911",
        "estrattore": estrai_fvg,
    },
    "Basilicata": {
        "url": "https://agricoltura.regione.basilicata.it/bandi-regionali/",
        "estrattore": estrai_basilicata,
    },
    "Molise": {
        "url": "https://psr.regione.molise.it/aperti23-27",
        "estrattore": estrai_molise,
    },
    "Piemonte": {
        "url": "https://quaderniagricoltura.regione.piemonte.it/calendario-bandi/",
        "estrattore": estrai_piemonte,
    },
    "Sicilia": {
        "url": "https://svilupporurale.regione.sicilia.it/categoria/news/bandi-aperti/",
        "estrattore": estrai_sicilia,
    },
    "Valle d'Aosta": {
        "url": "https://new.regione.vda.it/europa/fondi-e-programmi/fondo-europeo-agricolo-per-lo-sviluppo-rurale/bandi-aperti",
        "estrattore": estrai_valle_aosta,
    },
      }
