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
    "altre pagine",
    "anagrafe agricola",
    "servizi forestali",
    "servizi per l’agricoltura",
    "griglie di riduzione",
    "riduzione/esclusione",
    "riduzione ed esclusione",
    "approvate le griglie",
    "bando scaduto",
    "bandi chiusi",
)

PAROLE_AGRICOLTURA = (
    "agricolt",
    "rurale",
    "forest",
    "zootecn",
    "agroaliment",
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


def crea_record(
    regione,
    titolo,
    url,
    testo="",
    stato="Aperto",
    categoria="CSR / Sviluppo rurale"
):
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
    Legge solo la tabella nella sezione id="csr".
    Ogni riga contiene:
    - cella 1: titolo bando;
    - cella 2: scadenza;
    - cella 3: link "Vai alla pagina".
    """
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

        if not titolo:
            continue

        if "nessun bando aperto" in titolo.lower():
            continue

        if contiene_esclusioni(titolo):
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

        record["scadenza"] = scadenza or "non specificata"
        risultati.append(record)

    print(f"      Campania: estratti {len(risultati)} bandi CSR")
    return elimina_duplicati(risultati)


# ============================================================
# BASILICATA
# ============================================================

def estrai_basilicata(html_pagina, url_base):
    """
    Cerca esclusivamente i bandi pubblicati dopo la dicitura
    'Bandi in corso'. I bandi sono spesso scritti in un <li>,
    mentre il relativo link è un PDF oppure un pulsante data-url.

    Non cerca link nel blocco successivo: in questo modo non associa
    mai un bando ad una pagina errata.
    """
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

                parole_richieste = (
                    "avviso pubblico",
                    "bando",
                    "sostegno",
                    "allevamenti",
                    "zootecnico",
                    "biosicurezza",
                    "agricoltura",
                    "contributo",
                )

                if (
                    len(titolo) >= 25
                    and not contiene_esclusioni(titolo)
                    and any(parola in titolo_basso for parola in parole_richieste)
                ):
                    link_scelto = None

                    # Prima scelta: link/PDF chiamato Bando.
                    for link in nodo.find_all("a", href=True):
                        href = link.get("href", "").lower()
                        testo_link = pulisci_testo(
                            link.get_text(" ", strip=True)
                        ).lower()

                        if "bando" in testo_link or "bando" in href:
                            link_scelto = link
                            break

                    # Seconda scelta: il primo PDF nel medesimo blocco.
                    if not link_scelto:
                        for link in nodo.find_all("a", href=True):
                            href = link.get("href", "").lower()

                            if href.endswith(".pdf"):
                                link_scelto = link
                                break

                    url = None

                    if link_scelto:
                        url = urljoin(url_base, link_scelto["href"])
                    else:
                        bottone = nodo.find(attrs={"data-url": True})

                        if bottone:
                            url = urljoin(url_base, bottone["data-url"])

                    # Se manca un collegamento nello stesso blocco,
                    # il record non viene inserito.
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
# PIEMONTE
# ============================================================

def estrai_piemonte(html_pagina, url_base):
    """
    Prende solo link alle singole schede ufficiali
    bandi.regione.piemonte.it, con titolo agricolo/CSR.
    """
    soup = BeautifulSoup(html_pagina, "lxml")
    risultati = []

    parole_agricole_specifiche = (
        "csr",
        "psr",
        "srd",
        "sra",
        "srb",
        "sre",
        "srg",
        "srh",
        "agricol",
        "cooperative agricole",
        "imprenditori agricoli",
        "agroalimentare",
        "rurale",
    )

    for link in soup.find_all("a", href=True):
        titolo = pulisci_testo(link.get_text(" ", strip=True))
        url = urljoin(url_base, link.get("href", ""))
        titolo_basso = titolo.lower()

        if len(titolo) < 25:
            continue

        if contiene_esclusioni(titolo):
            continue

        if "bandi.regione.piemonte.it" not in url:
            continue

        if not any(parola in titolo_basso for parola in parole_agricole_specifiche):
            continue

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

            testo_temp = pulisci_testo(
                contenitore.get_text(" ", strip=True)
            )

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
# PUGLIA
# ============================================================

def estrai_puglia(html_pagina, url_base):
    """
    CSR Puglia:
    ogni singolo bando è un tag <a class="as-card">.
    La card contiene stato, categoria, codice, titolo e descrizione.
    Include solo Aperto, In apertura e Prossima apertura.
    """
    soup = BeautifulSoup(html_pagina, "lxml")
    risultati = []

    for card in soup.select("a.as-card[href]"):
        testo_card = pulisci_testo(card.get_text(" ", strip=True))
        testo_basso = testo_card.lower()

        stato_tag = card.select_one(".status-bandi-pill")

        if not stato_tag:
            continue

        stato_pagina = pulisci_testo(
            stato_tag.get_text(" ", strip=True)
        ).lower()

        if stato_pagina not in (
            "aperto",
            "in apertura",
            "prossima apertura",
        ):
            continue

        if "chiuso" in testo_basso:
            continue

        if contiene_esclusioni(testo_card):
            continue

        titolo_tag = card.select_one("h3.as-title")

        if not titolo_tag:
            continue

        titolo = pulisci_testo(titolo_tag.get_text(" ", strip=True))

        if len(titolo) < 15:
            continue

        tag_categorie = [
            pulisci_testo(tag.get_text(" ", strip=True))
            for tag in card.select(".category-tag")
        ]

        codice = ""
        categoria = "CSR 2023-2027"

        for tag in tag_categorie:
            if re.search(r"\bSR[A-Z]?\d{2}", tag, flags=re.IGNORECASE):
                codice = tag
            elif len(tag) > 3:
                categoria = f"CSR 2023-2027 – {tag}"

        if codice and codice.lower() not in titolo.lower():
            titolo = f"{codice} – {titolo}"

        url = urljoin(url_base, card["href"])

        if url.rstrip("/") == url_base.rstrip("/"):
            continue

        stato = "Aperto"

        if stato_pagina == "in apertura":
            stato = "In apertura"
        elif stato_pagina == "prossima apertura":
            stato = "Prossima apertura"

        risultati.append(
            crea_record(
                "Puglia",
                titolo,
                url,
                testo_card,
                stato=stato,
                categoria=categoria
            )
        )

    print(f"      Puglia: estratti {len(risultati)} bandi")
    return elimina_duplicati(risultati)


# ============================================================
# LOMBARDIA
# ============================================================

def estrai_lombardia(html_pagina, url_base):
    """
    Estrae le schede Lombardia con stato Aperto o In apertura.
    Esclude pesca, FEAMPA, acquacoltura, gare e altre voci non pertinenti.
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

    for titolo_tag in soup.find_all(["h3", "h4"]):
        titolo = pulisci_testo(titolo_tag.get_text(" ", strip=True))

        if len(titolo) < 15:
            continue

        contenitore = titolo_tag.parent
        card = None

        for _ in range(6):
            if not contenitore:
                break

            testo_card = pulisci_testo(
                contenitore.get_text(" ", strip=True)
            ).lower()

            if "aperto" in testo_card or "in apertura" in testo_card:
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
# SICILIA
# ============================================================

def estrai_sicilia(html_pagina, url_base):
    """
    Categoria ufficiale 'Bandi aperti' Sicilia.
    Esclude griglie, riduzioni, rettifiche, proroghe, graduatorie,
    FAQ e altri atti successivi al bando originale.
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
# FONTI ATTIVE
# ============================================================

FONTI_HTML = {
    "Basilicata": {
        "url": "https://agricoltura.regione.basilicata.it/bandi-regionali/",
        "estrattore": estrai_basilicata,
    },
    "Campania": {
        "url": "https://agricoltura.regione.campania.it/bandi.html",
        "estrattore": estrai_campania,
    },
    "Lombardia": {
        "url": "https://www.bandi.regione.lombardia.it/servizi/servizio/bandi/agricoltura-pesca",
        "estrattore": estrai_lombardia,
    },
    "Piemonte": {
        "url": "https://quaderniagricoltura.regione.piemonte.it/calendario-bandi/",
        "estrattore": estrai_piemonte,
    },
    "Puglia": {
        "url": "https://csr.regione.puglia.it/bandi",
        "estrattore": estrai_puglia,
    },
    "Sicilia": {
        "url": "https://svilupporurale.regione.sicilia.it/categoria/news/bandi-aperti/",
        "estrattore": estrai_sicilia,
    },
}
