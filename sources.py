import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup


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


def pulisci_testo(testo):
    return re.sub(r"\s+", " ", testo or "").strip()


def contiene_esclusioni(testo):
    testo = (testo or "").lower()
    return any(parola in testo for parola in PAROLE_ESCLUSE)


def riguarda_agricoltura(testo):
    testo = (testo or "").lower()
    return any(parola in testo for parola in PAROLE_AGRICOLTURA)


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
        flags=re.IGNORECASE,
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
    categoria="CSR / Sviluppo rurale",
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


def estrai_campania(html_pagina, url_base):
    """
    Campania:
    tenta prima la sezione id='csr'.
    Se non la trova, cerca qualsiasi tabella che contenga il codice SRD06
    oppure una riga con bando + scadenza + link.
    """
    soup = BeautifulSoup(html_pagina, "lxml")
    risultati = []

    sezioni_da_controllare = []

    sezione_csr = soup.find(id="csr")
    if sezione_csr:
        sezioni_da_controllare.append(sezione_csr)

    # Fallback: alcuni siti cambiano struttura o omettono l'id.
    for tabella in soup.find_all("table"):
        testo_tabella = pulisci_testo(tabella.get_text(" ", strip=True)).lower()

        if (
            "complemento di sviluppo rurale" in testo_tabella
            or "srd06" in testo_tabella
            or "csr 2023" in testo_tabella
        ):
            sezioni_da_controllare.append(tabella)

    visti_righe = set()

    for sezione in sezioni_da_controllare:
        for riga in sezione.find_all("tr"):
            celle = riga.find_all("td")

            if len(celle) < 3:
                continue

            titolo = pulisci_testo(celle[0].get_text(" ", strip=True))
            scadenza = pulisci_testo(celle[1].get_text(" ", strip=True))
            link = celle[-1].find("a", href=True)

            if not titolo or "nessun bando aperto" in titolo.lower():
                continue

            if not link:
                continue

            # Deve essere una misura specifica CSR/PSR/GAL.
            titolo_basso = titolo.lower()
            if not (
                re.search(r"\bSR[A-Z]?\d{2}\b", titolo, flags=re.IGNORECASE)
                or "bando" in titolo_basso
                or "avviso" in titolo_basso
                or "gal" in titolo_basso
            ):
                continue

            url = urljoin(url_base, link["href"])

            chiave = (titolo.lower(), url.lower())
            if chiave in visti_righe:
                continue

            visti_righe.add(chiave)

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

    print(f"      Campania: estratti {len(risultati)} bandi")
    return elimina_duplicati(risultati)


def estrai_basilicata(html_pagina, url_base):
    """
    Basilicata:
    legge solo i bandi pubblicati dopo 'Bandi in corso'.
    Ogni record deve avere un PDF o un pulsante data-url nello stesso blocco.
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
            elementi = nodo.find_all("li", recursive=False)

            if elementi:
                titolo = pulisci_testo(elementi[0].get_text(" ", strip=True))

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

                    for link in nodo.find_all("a", href=True):
                        href = link.get("href", "").lower()
                        testo_link = pulisci_testo(
                            link.get_text(" ", strip=True)
                        ).lower()

                        if "bando" in testo_link or "bando" in href:
                            link_scelto = link
                            break

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

                    if url:
                        risultati.append(
                            crea_record(
                                "Basilicata",
                                titolo,
                                url,
                                titolo,
                                stato="Aperto",
                                categoria="Agricoltura / Sviluppo rurale",
                            )
                        )

        nodo = nodo.find_next_sibling()

    print(f"      Basilicata: estratti {len(risultati)} bandi")
    return elimina_duplicati(risultati)


def estrai_piemonte(html_pagina, url_base):
    """
    Piemonte:
    estrae solo schede singole dal dominio bandi.regione.piemonte.it.
    """
    soup = BeautifulSoup(html_pagina, "lxml")
    risultati = []

    parole_agricole = (
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

        if not any(parola in titolo_basso for parola in parole_agricole):
            continue

        if (
            url.rstrip() == "https://bandi.regione.piemonte.it/contributi-finanziamenti"
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
                categoria="CSR / Agricoltura",
            )
        )

    return elimina_duplicati(risultati)


def estrai_puglia(html_pagina, url_base):
    """
    Puglia:
    ogni bando è una card <a class="as-card">.
    La funzione estrae lo stato, il codice SR*, il titolo e il link diretto.
    Rimuove i codici colore tecnici dei div nascosti.
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

        tag_categorie = []

        for tag in card.select(".category-tag"):
            copia_tag = BeautifulSoup(str(tag), "lxml")

            for elemento in copia_tag.select(".as-tag-to-get-color"):
                elemento.decompose()

            testo_tag = pulisci_testo(
                copia_tag.get_text(" ", strip=True)
            )

            if testo_tag:
                tag_categorie.append(testo_tag)

        codice = ""
        categoria = "CSR 2023-2027"

        for tag in tag_categorie:
            tag_pulito = re.sub(r"<[^>]+>", "", tag)
            tag_pulito = pulisci_testo(tag_pulito)

            if re.search(r"\bSR[A-Z]?\d{2}", tag_pulito, flags=re.IGNORECASE):
                codice = tag_pulito
            elif len(tag_pulito) > 3:
                categoria = f"CSR 2023-2027 – {tag_pulito}"

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
                categoria=categoria,
            )
        )

    print(f"      Puglia: estratti {len(risultati)} bandi")
    return elimina_duplicati(risultati)


def estrai_lombardia(html_pagina, url_base):
    """
    Lombardia:
    estrae card aperte/in apertura, relative ad agricoltura e sviluppo rurale.
    Esclude FEAMPA, pesca, acquacoltura, gare e temi non pertinenti.
    """
    soup = BeautifulSoup(html_pagina, "lxml")
    risultati = []

    esclusioni = (
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

        if any(parola in testo_basso for parola in esclusioni):
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
                categoria="Agricoltura / PAC / Sviluppo rurale",
            )
        )

    return elimina_duplicati(risultati)


def estrai_sicilia(html_pagina, url_base):
    """
    Sicilia:
    usa la categoria ufficiale Bandi aperti.
    Esclude griglie, rettifiche, proroghe, graduatorie, FAQ e atti successivi.
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
                categoria="CSR / Sviluppo rurale",
            )
        )

    return elimina_duplicati(risultati)
def estrai_marche(html_pagina, url_base):
    """
    Marche: versione diagnostica temporanea.
    Stampa cosa vede lo script nella pagina per capire perché non estrae bandi.
    """
    soup = BeautifulSoup(html_pagina, "lxml")
    risultati = []

    testo_pagina = pulisci_testo(soup.get_text(" ", strip=True))
    testo_pagina_basso = testo_pagina.lower()

    print("      Marche: lunghezza HTML:", len(html_pagina))
    print("      Marche: lunghezza testo:", len(testo_pagina))
    print("      Marche: numero link:", len(soup.find_all("a")))
    print("      Marche: contiene 'Scadenza':", "scadenza" in testo_pagina_basso)
    print("      Marche: contiene 'CSR':", "csr" in testo_pagina_basso)
    print("      Marche: contiene 'SRD':", "srd" in testo_pagina_basso)
    print("      Marche: contiene 'GAL':", "gal" in testo_pagina_basso)

    # Stampa i primi 600 caratteri del testo visibile.
    print("      Marche: inizio testo pagina:")
    print("      " + testo_pagina[:600].replace("\n", " "))

    # Cerca tutte le occorrenze di 'Scadenza' e stampa il contesto.
    posizioni = [
        match.start()
        for match in re.finditer(r"scadenza", testo_pagina_basso)
    ]

    print("      Marche: occorrenze 'Scadenza':", len(posizioni))

    for indice, posizione in enumerate(posizioni[:5], start=1):
        contesto = testo_pagina[
            max(0, posizione - 150): posizione + 250
        ]

        print(f"      Marche: contesto scadenza {indice}:")
        print("      " + pulisci_testo(contesto))

    # Stampa i primi 20 link non di navigazione.
    print("      Marche: primi link trovati:")

    for indice, link in enumerate(soup.find_all("a", href=True)[:20], start=1):
        testo_link = pulisci_testo(link.get_text(" ", strip=True))
        href = link.get("href", "")

        print(
            f"      {indice}. testo='{testo_link[:100]}' | href='{href[:180]}'"
        )

    return risultati


def estrai_valle_daosta(html_pagina, url_base):
    """
    Valle d'Aosta:
    estrae solo interventi CSR con 'SPORTELLO APERTO'
    oppure scadenza nel futuro.
    """
    soup = BeautifulSoup(html_pagina, "lxml")
    risultati = []

    for elemento in soup.find_all(["li", "p", "div"]):
        testo = pulisci_testo(elemento.get_text(" ", strip=True))
        testo_basso = testo.lower()

        if len(testo) < 30:
            continue

        aperto = "sportello aperto" in testo_basso
        scadenza_futura = False
        scadenza = "non specificata"

        match = re.search(
            r"scadenza\s+([0-9]{1,2}\s+[a-zàèéìòù]+\s+[0-9]{4})",
            testo_basso,
        )

        if not match:
            match = re.search(
                r"scadenza\s+([0-9]{1,2}\s+[a-zàèéìòù]+\s+[0-9]{4})",
                testo,
                flags=re.IGNORECASE,
            )

        if match:
            scadenza = pulisci_testo(match.group(1)).title()

            try:
                data_scadenza = datetime.strptime(
                    scadenza,
                    "%d %B %Y"
                )
                scadenza_futura = data_scadenza >= datetime.now()
            except Exception:
                scadenza_futura = False

        if not aperto and not scadenza_futura:
            continue

        if contiene_esclusioni(testo):
            continue

        if not riguarda_agricoltura(testo):
            continue

        link = elemento.find("a", href=True)
        url = url_base

        if link:
            url = urljoin(url_base, link["href"])

        stato = "Sportello aperto" if aperto else "Aperto"

        risultati.append(
            crea_record(
                "Valle d'Aosta",
                testo,
                url,
                testo,
                stato=stato,
                categoria="CSR 2023-2027 / Agricoltura",
            )
        )

    print(f"      Valle d'Aosta: estratti {len(risultati)} bandi")
    return elimina_duplicati(risultati)

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
    "Marche": {
        "url": "https://www.regione.marche.it/Regione-Utile/Agricoltura-Sviluppo-Rurale-e-Pesca/Bandi-di-finanziamento",
        "estrattore": estrai_marche,
    },
    "Valle d'Aosta": {
        "url": "https://www.regione.vda.it/agricoltura/CSR_2023_2027/bandi_interventi_strutturali/default_i.aspx",
        "estrattore": estrai_valle_daosta,
    },
}

