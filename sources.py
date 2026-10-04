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
    "privacy",
    "informazioni legali",
    "note legali",
    "newsletter",
    "categorie di articoli",
    "categorie di articoli",
    "altre pagine",
    "anagrafe agricola",
    "servizi forestali",
    "servizi per l’agricoltura",
    "griglie di riduzione",
    "riduzione/esclusione",
    "riduzione ed esclusione",
    "approvate le griglie",
    "bando scaduto",
    "bandi chiusi",)

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
    Campania:
    - cerca le righe delle tabelle CSR/PSR e le righe GAL;
    - esclude le pagine-indice generiche tipo 'Bandi CSR a cura dei GAL';
    - conserva solo righe con un singolo intervento/bando.
    """
    soup = BeautifulSoup(html_pagina, "lxml")
    risultati = []

    parole_bando = (
        "srd", "sra", "srb", "sre", "srg", "srh",
        "bando", "avviso pubblico", "intervento"
    )

    parole_da_escludere = (
        "bandi csr a cura dei gal",
        "bandi psr a cura dei gal",
        "archivio",
        "calendario",
        "elenco",
        "modulistica",
        "fiera",
        "evento",
        "feampa",
        "pesca",
    )

    for riga in soup.find_all("tr"):
        testo = pulisci_testo(riga.get_text(" ", strip=True))
        testo_basso = testo.lower()

        if len(testo) < 25:
            continue

        if contiene_esclusioni(testo):
            continue

        if any(parola in testo_basso for parola in parole_da_escludere):
            continue

        if not any(parola in testo_basso for parola in parole_bando):
            continue

        # Una riga utile deve avere il link della sua pagina di dettaglio.
        candidati = riga.find_all("a", href=True)

        if not candidati:
            continue

        link = None

        for candidato in candidati:
            testo_link = pulisci_testo(candidato.get_text(" ", strip=True)).lower()
            href = candidato.get("href", "").lower()

            # Preferisce il pulsante di dettaglio presente nella riga.
            if (
                "vai alla pagina" in testo_link
                or "dettaglio" in testo_link
                or "bando" in href
                or "comunicato" in href
            ):
                link = candidato
                break

        if not link:
            link = candidati[-1]

        url = urljoin(url_base, link["href"])

        if url.rstrip("/") == url_base.rstrip("/"):
            continue

        # Deve essere una misura specifica, non un indice.
        if not re.search(
            r"\b(SRD|SRA|SRB|SRE|SRG|SRH)\s*\d{2}\b",
            testo,
            flags=re.IGNORECASE
        ) and "bando" not in testo_basso:
            continue

        titolo = re.sub(
            r"\b(vai alla pagina|dettaglio|apri)\b.*$",
            "",
            testo,
            flags=re.IGNORECASE
        ).strip()

        if len(titolo) < 20:
            continue

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
    Piemonte:
    prende esclusivamente le card del calendario bandi.
    Ignora titoli generici dell'header, footer, menu e pagine editoriali.
    """
    soup = BeautifulSoup(html_pagina, "lxml")
    risultati = []

    parole_agricole_specifiche = (
        "csr", "psr", "srd", "sra", "srb", "sre",
        "srg", "srh", "agricol", "cooperative agricole",
        "imprenditori agricoli", "agroalimentare", "rurale"
    )

    for link in soup.find_all("a", href=True):
        titolo = pulisci_testo(link.get_text(" ", strip=True))
        href = link.get("href", "")
        url = urljoin(url_base, href)

        titolo_basso = titolo.lower()

        if len(titolo) < 25:
            continue

        if contiene_esclusioni(titolo):
            continue

        # Solo URL del portale ufficiale bandi Piemonte.
        if "bandi.regione.piemonte.it" not in url:
            continue

        # Il titolo deve riferirsi in modo esplicito ad agricoltura/CSR.
        if not any(parola in titolo_basso for parola in parole_agricole_specifiche):
            continue

        # Esclude pagina listing, search e navigazione.
        if (
            url.rstrip("/") == "https://bandi.regione.piemonte.it/contributi-finanziamenti"
            or "archivio" in url.lower()
            or "categorie" in url.lower()
        ):
            continue

        contenitore = link.parent
        testo_vicino = titolo

        for _ in range(4):
            if not contenitore:
                break

            testo_temp = pulisci_testo(contenitore.get_text(" ", strip=True))

            if "scadenza" in testo_temp.lower():
                testo_vicino = testo_temp
                break

            contenitore = contenitore.parent

        risultati.append(
            crea_record(
                "Piemonte",
                titolo,
                url,
                testo_vicino,
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
    Sicilia:
    usa la categoria ufficiale 'Bandi aperti', ma elimina atti
    successivi come griglie, rettifiche, proroghe e graduatorie.
    """
    soup = BeautifulSoup(html_pagina, "lxml")
    risultati = []

    parole_necessarie = (
        "bando",
        "bando attuativo",
        "avviso pubblico",
    )

    parole_scarto = (
        "griglie",
        "riduzione",
        "esclusione",
        "rettifica",
        "proroga",
        "graduatoria",
        "elenco",
        "ammissibili",
        "non ammissibili",
        "pagamento",
        "istruzioni",
        "faq",
    )

    for titolo_tag in soup.find_all(["h2", "h3", "h4"]):
        titolo = pulisci_testo(titolo_tag.get_text(" ", strip=True))
        titolo_basso = titolo.lower()

        if len(titolo) < 18:
            continue

        if contiene_esclusioni(titolo):
            continue

        if any(parola in titolo_basso for parola in parole_scarto):
            continue

        # È ammesso se parla di bando/avviso oppure di un intervento SR*
        if not (
            any(parola in titolo_basso for parola in parole_necessarie)
            or re.search(r"\bSR[A-Z]?\d{2}\b", titolo, flags=re.IGNORECASE)
        ):
            continue

        link = titolo_tag.find("a", href=True)
        if not link:
            continue

        url = urljoin(url_base, link["href"])

        risultati.append(
            crea_record(
                "Sicilia",
                titolo,
                url,
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
    Basilicata:
    estrae soltanto i link situati nella sezione 'Bandi in corso'.
    Non prende menu come Anagrafe, Servizi forestali o Servizi agricoltura.
    """
    soup = BeautifulSoup(html_pagina, "lxml")
    risultati = []

    in_corso = False

    for elemento in soup.find_all(["h1", "h2", "h3", "h4", "a", "li", "p"]):
        testo = pulisci_testo(elemento.get_text(" ", strip=True))
        testo_basso = testo.lower()

        if elemento.name in ("h1", "h2", "h3", "h4"):
            if "bandi in corso" in testo_basso:
                in_corso = True
                continue

            if (
                "bandi scaduti" in testo_basso
                or "bandi regionali scaduti" in testo_basso
                or "archivio" in testo_basso
            ):
                in_corso = False
                continue

        if not in_corso or elemento.name != "a":
            continue

        titolo = testo

        if len(titolo) < 30:
            continue

        if contiene_esclusioni(titolo):
            continue

        # Deve essere effettivamente un bando/avviso/contributo,
        # non un collegamento ai servizi generali.
        titolo_basso = titolo.lower()
        if not any(
            parola in titolo_basso
            for parola in (
                "bando",
                "avviso",
                "contribut",
                "sostegno",
                "aiuto",
                "allev",
                "agricolt",
                "zootecn",
                "forest",
                "csr",
                "psr",
            )
        ):
            continue

        href = elemento.get("href", "")
        if not href:
            continue

        url = urljoin(url_base, href)

        if url.rstrip("/") == url_base.rstrip("/"):
            continue

        risultati.append(
            crea_record(
                "Basilicata",
                titolo,
                url,
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
    "Basilicata": {
        "url": "https://agricoltura.regione.basilicata.it/bandi-regionali/",
        "estrattore": estrai_basilicata,
    
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
