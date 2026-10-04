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
    soup = BeautifulSoup(html_pagina, "lxml")
    risultati = []

    sezione_csr = soup.find(id="csr")

    if not sezione_csr:
        print("      Campania: sezione CSR non trovata")
        return risultati

    for riga in sezione_csr.find_all("tr"):
        celle = riga.find_all("td")

        if len(celle) != 3:
            continue

        titolo = pulisci_testo(celle[0].get_text(" ", strip=True))
        scadenza = pulisci_testo(celle[1].get_text(" ", strip=True))
        link = celle[2].find("a", href=True)

        if not titolo or "nessun bando aperto" in titolo.lower():
            continue

        if not link:
            continue

        url = urljoin(url_base, link["href"])

        record = crea_record(
            "Campania",
            titolo,
            url,
            scadenza,
            stato="Aperto",
            categoria="CSR 2023-2027"
        )

        record["scadenza"] = scadenza
        risultati.append(record)

    print(f"      Campania: estratti {len(risultati)} bandi CSR")
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
    soup = BeautifulSoup(html_pagina, "lxml")
    risultati = []

    punto_inizio = None

    for tag in soup.find_all(["p", "strong", "b", "h1", "h2", "h3", "h4"]):
        testo = pulisci_testo(tag.get_text(" ", strip=True)).lower()

        if "bandi in corso" in testo:
            punto_inizio = tag
            break

    if not punto_inizio:
        print("      Basilicata: sezione 'Bandi in corso' non trovata")
        return risultati

    nodo = punto_inizio.find_next_sibling()

    while nodo:
        testo_nodo = pulisci_testo(nodo.get_text(" ", strip=True))
        testo_basso = testo_nodo.lower()

        if "bandi scaduti" in testo_basso:
            break

        if nodo.name == "ul":
            elementi_principali = nodo.find_all("li", recursive=False)

            if elementi_principali:
                titolo = pulisci_testo(
                    elementi_principali[0].get_text(" ", strip=True)
                )

                if len(titolo) < 25:
                    titolo = testo_nodo

                titolo_basso = titolo.lower()

                if (
                    len(titolo) >= 25
                    and not contiene_esclusioni(titolo)
                    and any(
                        parola in titolo_basso
                        for parola in (
                            "avviso pubblico",
                            "bando",
                            "sostegno",
                            "allevamenti",
                            "zootecnico",
                            "biosicurezza",
                            "agricoltura",
                            "contributo",
                        )
                    )
                ):
                    link_scelto = None

                    # Cerca un link soltanto DENTRO questo stesso UL.
                    for link in nodo.find_all("a", href=True):
                        href = link.get("href", "").lower()
                        testo_link = pulisci_testo(
                            link.get_text(" ", strip=True)
                        ).lower()

                        if "bando" in testo_link or "bando" in href:
                            link_scelto = link
                            break

                    # Se manca il PDF chiamato bando, usa un PDF del blocco.
                    if not link_scelto:
                        for link in nodo.find_all("a", href=True):
                            href = link.get("href", "").lower()

                            if href.endswith(".pdf"):
                                link_scelto = link
                                break

                    # Per i pulsanti con attributo data-url.
                    url = None

                    if link_scelto:
                        url = urljoin(url_base, link_scelto["href"])
                    else:
                        bottone = nodo.find(attrs={"data-url": True})

                        if bottone:
                            url = urljoin(url_base, bottone["data-url"])

                    # Se non c'è un link nel blocco, NON inserire il bando:
                    # è meglio ometterlo che associargli una fonte sbagliata.
                    if url:
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

        nodo = nodo.find_next_sibling()

    print(f"      Basilicata: estratti {len(risultati)} bandi")
    return elimina_duplicati(risultati)
# ============================================================
# PUGLIA
# ============================================================

def estrai_puglia(html_pagina, url_base):
    """
    CSR Puglia:
    prende solo card con stato 'Aperto' o 'Prossima apertura'.
    Ogni card deve avere un titolo e un link individuale.
    """
    soup = BeautifulSoup(html_pagina, "lxml")
    risultati = []

    stati_validi = ("aperto", "prossima apertura", "in apertura")

    # Cerca i titoli delle card: nella pagina sono H3.
    for titolo_tag in soup.find_all(["h2", "h3", "h4"]):
        titolo = pulisci_testo(titolo_tag.get_text(" ", strip=True))

        if len(titolo) < 15:
            continue

        # Cerca un contenitore vicino che includa stato e contenuto card.
        contenitore = titolo_tag.parent
        card = None

        for _ in range(6):
            if not contenitore:
                break

            testo_card = pulisci_testo(contenitore.get_text(" ", strip=True))
            testo_basso = testo_card.lower()

            if any(stato in testo_basso for stato in stati_validi):
                card = contenitore
                break

            contenitore = contenitore.parent

        if not card:
            continue

        testo_card = pulisci_testo(card.get_text(" ", strip=True))
        testo_basso = testo_card.lower()

        if "chiuso" in testo_basso:
            continue

        if not any(stato in testo_basso for stato in stati_validi):
            continue

        if contiene_esclusioni(f"{titolo} {testo_card}"):
            continue

        if not riguarda_agricoltura(f"{titolo} {testo_card}"):
            continue

        # Cerca prima il link del titolo, poi un link della card.
        link = titolo_tag.find("a", href=True)

        if not link:
            for candidato in card.find_all("a", href=True):
                href = candidato.get("href", "").lower()
                testo_link = pulisci_testo(
                    candidato.get_text(" ", strip=True)
                ).lower()

                # Evita link di navigazione, preferisce il dettaglio bando.
                if (
                    len(testo_link) > 5
                    and "bandi" not in href.rstrip("/").split("/")[-1]
                    and "homepage" not in href
                ):
                    link = candidato
                    break

        if not link:
            continue

        url = urljoin(url_base, link["href"])

        if url.rstrip("/") == url_base.rstrip("/"):
            continue

        stato = "Aperto"
        if "prossima apertura" in testo_basso:
            stato = "Prossima apertura"
        elif "in apertura" in testo_basso:
            stato = "In apertura"

        risultati.append(
            crea_record(
                "Puglia",
                titolo,
                url,
                testo_card,
                stato=stato,
                categoria="CSR 2023-2027"
            )
        )

    return elimina_duplicati(risultati)


# ============================================================
# LOMBARDIA
# ============================================================

def estrai_lombardia(html_pagina, url_base):
    """
    Bandi e Servizi Lombardia:
    estrae i blocchi con stato 'Aperto' oppure 'In apertura'.
    Filtra espressamente pesca/FEAMPA/acquacoltura e voci estranee.
    """
    soup = BeautifulSoup(html_pagina, "lxml")
    risultati = []

    esclusioni_lombardia = (
        "feampa",
        "pesca",
        "acquacoltura",
        "studio legale",
        "studi legali",
        "denunce sinistri",
        "rivalse",
        "assicurazioni",
        "concorso",
        "gara",
    )

    # Ogni titolo di bando è visibile come H4.
    for titolo_tag in soup.find_all(["h3", "h4"]):
        titolo = pulisci_testo(titolo_tag.get_text(" ", strip=True))

        if len(titolo) < 15:
            continue

        contenitore = titolo_tag.parent
        card = None

        for _ in range(6):
            if not contenitore:
                break

            testo_card = pulisci_testo(contenitore.get_text(" ", strip=True))
            testo_basso = testo_card.lower()

            if "aperto" in testo_basso or "in apertura" in testo_basso:
                card = contenitore
                break

            contenitore = contenitore.parent

        if not card:
            continue

        testo_card = pulisci_testo(card.get_text(" ", strip=True))
        testo_basso = testo_card.lower()

        if not ("aperto" in testo_basso or "in apertura" in testo_basso):
            continue

        if any(parola in testo_basso for parola in esclusioni_lombardia):
            continue

        if contiene_esclusioni(f"{titolo} {testo_card}"):
            continue

        # Mantieni solo ciò che è almeno agricolo/rurale/forestale/zootecnico.
        if not riguarda_agricoltura(f"{titolo} {testo_card}"):
            continue

        link = titolo_tag.find("a", href=True)

        if not link:
            for candidato in card.find_all("a", href=True):
                href = candidato.get("href", "")

                if "/dettaglio/" in href or "/bando/" in href:
                    link = candidato
                    break

        if not link:
            continue

        url = urljoin(url_base, link["href"])

        if url.rstrip("/") == url_base.rstrip("/"):
            continue

        stato = "Aperto"
        if "in apertura" in testo_basso:
            stato = "In apertura"

        risultati.append(
            crea_record(
                "Lombardia",
                titolo,
                url,
                testo_card,
                stato=stato,
                categoria="Agricoltura / PAC / Sviluppo rurale"
            )
        )

    return elimina_duplicati(risultati)


# ============================================================
# MARCHE
# ============================================================

def estrai_marche(html_pagina, url_base):
    """
    Marche:
    ogni bando è presentato con:
    - titolo H4;
    - identificativo bando e scadenza;
    - link sulla scheda/titolo o nell'area vicina.
    Include i GAL e gli interventi CSR.
    Esclude bandi faunistico-venatori.
    """
    soup = BeautifulSoup(html_pagina, "lxml")
    risultati = []

    esclusioni_marche = (
        "faunistico",
        "venatorio",
        "caccia",
        "pesca",
        "feampa",
        "acquacoltura",
        "gara",
        "concorso",
    )

    for titolo_tag in soup.find_all(["h3", "h4"]):
        titolo = pulisci_testo(titolo_tag.get_text(" ", strip=True))

        if len(titolo) < 20:
            continue

        titolo_basso = titolo.lower()

        if any(parola in titolo_basso for parola in esclusioni_marche):
            continue

        # Trova il contenitore che ha anche Identificativo e Scadenza.
        contenitore = titolo_tag.parent
        card = None

        for _ in range(6):
            if not contenitore:
                break

            testo_card = pulisci_testo(contenitore.get_text(" ", strip=True))

            if "identificativo bando" in testo_card.lower():
                card = contenitore
                break

            contenitore = contenitore.parent

        if not card:
            continue

        testo_card = pulisci_testo(card.get_text(" ", strip=True))
        testo_basso = testo_card.lower()

        if any(parola in testo_basso for parola in esclusioni_marche):
            continue

        # Deve essere sviluppo rurale/agricoltura/CSR oppure GAL.
        if not riguarda_agricoltura(f"{titolo} {testo_card}"):
            continue

        link = titolo_tag.find("a", href=True)

        if not link:
            for candidato in card.find_all("a", href=True):
                href = candidato.get("href", "")

                if (
                    "Bandi" in href
                    or "bando" in href.lower()
                    or "id_" in href.lower()
                    or "Dettaglio" in href
                ):
                    link = candidato
                    break

        if not link:
            continue

        url = urljoin(url_base, link["href"])

        if url.rstrip("/") == url_base.rstrip("/"):
            continue

        risultati.append(
            crea_record(
                "Marche",
                titolo,
                url,
                testo_card,
                stato="Aperto",
                categoria="CSR / Sviluppo rurale / GAL"
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
      "Puglia": {
        "url": "https://csr.regione.puglia.it/bandi",
        "estrattore": estrai_puglia,
    },
    "Lombardia": {
        "url": "https://www.bandi.regione.lombardia.it/servizi/servizio/bandi/agricoltura-pesca",
        "estrattore": estrai_lombardia,
    },
    "Marche": {
        "url": "https://www.regione.marche.it/Entra-in-Regione/Bandi-e-opportunita/Bandi-attivi?p=1&t=103",
        "estrattore": estrai_marche,
    },
      }
