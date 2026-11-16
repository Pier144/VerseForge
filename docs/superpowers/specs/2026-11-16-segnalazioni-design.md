# Segnalazioni dall'app (issues su GitHub): progetto

Data: 16/11/2026 · Stato: approvato a voce dall'utente, da rileggere

## Scopo

Chi usa VerseForge può mandare una segnalazione (bug o idea) senza uscire dal programma e senza un account
GitHub. La segnalazione diventa una issue pubblica su `Pier144/VerseForge`, tracciabile (numero, stato, commenti).
Chi l'ha inviata ne vede lo stato da dentro l'app.

Scelte fissate con l'utente:
- servizio intermedio su **Vercel** (account `pier144s-projects`, già collegato);
- le issues sono aperte da una **GitHub App dedicata** ("VerseForge Reports"), non dall'account Pier144;
- issues **pubbliche** sul repo VerseForge.

Fuori da questo lavoro: segnalazione automatica dei crash (Sentry o simili), traduzioni dell'interfaccia,
risposte dello sviluppatore mostrate dentro l'app (si apre la issue su GitHub).

## Architettura

```
VerseForge (finestra) ─► server locale FastAPI ─POST JSON─► verseforge-reports.vercel.app/api/report
                                 │                                 ├─► immagine su Vercel Blob (pubblica)
                                 │                                 └─► issue su Pier144/VerseForge (token della GitHub App)
                                 └─GET anonimo─► api.github.com/repos/Pier144/VerseForge/issues/N   (stato)
```

Tre pezzi indipendenti, ognuno con un compito solo:

- **A. Servizio** `reports-service/` (cartella nuova nel repo, progetto Vercel con root directory lì). Node 20,
  nessun framework, una sola dipendenza (`@vercel/blob`). Moduli: `api/report.js` (ingresso), `lib/validate.js`
  (controllo del messaggio), `lib/github.js` (token dell'App e chiamate REST), `lib/limits.js` (tetto globale).
  Prove con `node --test` e `fetch` finto.
- **B. Modulo Python** `sc_explorer/reports.py`: **unico proprietario del testo della issue** (titolo e corpo),
  pulizia dei dati personali, invio, indirizzo di riserva, stato delle segnalazioni. Non conosce FastAPI: lo usa
  `server.py`.
- **C. Interfaccia** in `web/`: pulsante nella barra in alto e finestra `#reportDlg`.

Il testo della issue nasce in un posto solo (B): l'anteprima "What will be sent", l'invio e l'indirizzo di riserva
usano la stessa funzione, quindi quello che l'utente vede è quello che parte. Il servizio non riscrive il testo:
lo controlla, sostituisce il segnaposto dell'immagine e lo pubblica.

## A. Servizio online

`POST /api/report`, corpo JSON (massimo 4 MB):

| campo | regole |
|---|---|
| `kind` | `"bug"` o `"idea"` (decide l'etichetta: `bug` o `enhancement`) |
| `title` | al massimo 130 caratteri, già con il prefisso `[Bug] ` / `[Idea] ` messo da B; dopo il prefisso almeno 4 caratteri che non siano spazi |
| `body` | 10–20000 caratteri, Markdown costruito da B |
| `version` | forma `1.2.3`, obbligatorio |
| `screenshot` | JPEG in base64, facoltativo, ≤ 2 MB decodificato, deve iniziare con i byte `FF D8 FF` |

Risposte: `201 {"number": 42, "url": "https://github.com/Pier144/VerseForge/issues/42"}`;
`400 {"error": "<motivo leggibile>"}` per dati non validi; `503 {"error": …}` se il servizio è spento, se è
stato raggiunto il tetto globale o se GitHub rifiuta o non risponde (anche 403/422 di GitHub diventano 503);
`429` dal firewall.

Funzionamento, in ordine:
1. interruttore: `REPORTS_ENABLED` diverso da `1` → 503;
2. `User-Agent` deve iniziare con `VerseForge/` (filtro debole contro i robot generici, non una protezione);
3. validazione dei campi; nel corpo le menzioni `@nome` vengono spezzate (`@` + spazio di larghezza zero) anche
   qui, per sicurezza (B lo fa già, l'operazione è idempotente);
4. token: JWT RS256 firmato con `node:crypto` (`iat` = adesso − 60 s, `exp` = adesso + 9 min) →
   `POST /app/installations/{id}/access_tokens`; il token d'installazione resta in memoria fino a 5 minuti prima
   della scadenza; se GitHub risponde 401 a una chiamata successiva si rifà il token una volta e si riprova;
5. tetto globale: al massimo `REPORTS_PER_HOUR` (20) issue con etichetta `from-app` create nell'ultima ora,
   contate con la ricerca di GitHub autenticata col token (`repo:… label:from-app created:>=<ora-1h>`, limite 30
   ricerche al minuto); oltre → 503. Il conteggio è approssimato (l'indice di ricerca di GitHub può essere
   indietro di qualche minuto) e va bene così. Se la ricerca fallisce si lascia passare (si scrive nel log di
   Vercel): il limite per IP resta comunque;
6. immagine: caricata su Vercel Blob come `reports/AAAA-MM/<uuid>.jpg` (pubblica); l'**ultimo** segnaposto
   `<!-- screenshot -->` nel corpo diventa `![3D view](<url>)`. Se il caricamento fallisce diventa
   `_(the picture could not be uploaded)_` e la issue parte lo stesso;
7. crea la issue con etichette `from-app` più `bug` o `enhancement`; scrive nel log di Vercel il numero della
   issue accanto al nome del file dell'immagine (serve alla procedura d'emergenza).

Variabili su Vercel: `GH_APP_ID`, `GH_APP_INSTALLATION_ID`, `GH_APP_PRIVATE_KEY` (le inserisce l'utente),
`BLOB_READ_WRITE_TOKEN` (messa da Vercel quando si collega l'archivio Blob al progetto),
`REPORTS_REPO=Pier144/VerseForge`, `REPORTS_ENABLED=1`, `REPORTS_PER_HOUR=20`.

Protezione dallo spam, a tre livelli:
- firewall Vercel su `/api/report`: 5 richieste ogni 10 minuti per IP, poi `deny` (429). Prima di contarci si
  controlla che il piano Hobby includa la regola di limite; se non la include, il limite per IP si fa nella
  funzione con un contatore in memoria (per istanza, quindi indicativo) e l'IP non viene salvato da nessuna parte;
- tetto globale per ora (punto 4), che limita anche un attacco da molti IP;
- procedura d'emergenza (scritta nel README del servizio): `REPORTS_ENABLED=0` su Vercel, poi chiudere in blocco
  le issue `from-app` sbagliate e cancellare le immagini dalla pagina Blob di Vercel (cancellazione vera, non
  resta storia).

## Passi dell'utente (guidati)

- GitHub App "VerseForge Reports": nessun webhook; permessi del repository Issues: read & write e Metadata: read
  (niente Contents, le immagini non vanno su GitHub); installata solo su `Pier144/VerseForge`. L'utente genera la
  chiave privata e la incolla su Vercel (le chiavi non le maneggia l'assistente).
- Archivio Vercel Blob creato e collegato al progetto (può farlo l'assistente con il connettore, chiedendo prima).
- Etichetta `from-app` creata sul repo VerseForge.
- Per rimuovere una segnalazione offensiva: cancellare la issue su GitHub (da proprietario del repo) e il file
  dalla pagina Blob.

## B. App: `sc_explorer/reports.py`

Funzioni (argomenti espliciti, niente stato globale):
- `diagnostics(version, model=None, variant=None, gpu=None, log_path=None, log_lines=80)` → testo: versione,
  sistema (`platform`), scheda video (passata dall'interfaccia), modello aperto e variante (passati
  dall'interfaccia nel corpo della richiesta), ultime righe di `verseforge.log` in `paths.cache_dir()`.
  Il log viene riscritto a ogni avvio, quindi contiene solo la sessione in corso; se si lancia dal sorgente
  non c'è e la sezione manca.
- `anonymize(text, *, home, user, machine, folders)` → testo con: cartella utente → `<home>`; ogni cartella in
  `folders` (cartella del Data.p4k → `<game>`, cartella delle esportazioni → `<exports>`, cartella di Blender →
  `<blender>`, quando sono fuori dalla cartella utente) sostituita; nome del PC → `<pc>`; nome utente → `<user>`.
  Confronto senza badare a maiuscole, con `\` e `/`. Il nome utente si sostituisce solo come parola intera e solo
  se ha almeno 3 caratteri; per nomi comuni ("admin", "user") la sostituzione di parole intere nel testo
  normale è accettata. Vale per titolo, descrizione e dati tecnici.
- `compose(kind, title, description, details, has_picture, version)` → `{title, body}`: riceve testi già passati
  da `anonymize` (così l'anteprima mostra il testo pulito); titolo con prefisso; corpo =
  descrizione dell'utente (con `</details>`, `<details` e `<!-- screenshot -->` resi innocui e menzioni spezzate), poi
  `<!-- screenshot -->` se c'è l'immagine, poi `<details><summary>Technical details</summary>` con i dati dentro
  un blocco di codice recintato ```` ```text ```` (le eventuali ``` nei dati vengono spezzate), poi
  "Sent from VerseForge x.y.z". È la stessa funzione per anteprima, invio e riserva.
- `send(payload, screenshot_b64=None, timeout=25)`: `urllib` come `updates.py`, `User-Agent: VerseForge/<versione>`;
  ritorna `{number, url}` o alza `ReportError(kind, message)` con `kind` in `network`, `rate`, `unavailable`,
  `invalid` (più il testo del 400).
- `fallback_url(composed)`: `https://github.com/Pier144/VerseForge/issues/new?title=…&body=…`, corpo tagliato
  perché l'indirizzo resti sotto ~7000 caratteri, senza immagine (al posto del segnaposto: "please attach a
  screenshot here"). Le etichette nell'indirizzo GitHub le ignora per chi non ha permessi sul repo: le issue di
  riserva arrivano senza etichette, va bene.
- `remember(cfg, number, title)` / `mine(cfg)`: elenco in `config.json` → `reports: [{number, title, date}]`
  (ultime 50).
- `statuses(numbers)`: `GET api.github.com/repos/Pier144/VerseForge/issues/{n}` senza token per le 20 più recenti,
  risultato in memoria 5 minuti. 404 e 410 → "Removed"; per un'issue trasferita (301, seguito da `urllib`) si
  ha lo stato dell'issue spostata; il link resta su `issues/<n>` di VerseForge, che GitHub reindirizza. Si chiede solo quando l'utente apre "My reports", così
  non consuma il limite pubblico (60 richieste/ora per IP) che serve al controllo degli aggiornamenti; se il
  limite è finito si mostra l'elenco senza stato e "Status unavailable right now".

Nuovi indirizzi in `server.py`:
- `POST /api/report/preview` (JSON: kind, title, description, picture, details, model, variant, gpu) → `{title, body}`;
- `POST /api/report` (stesso JSON più `screenshot` in base64) → `{number, url}` e salva in config; errori con il
  `kind` di `ReportError`;
- `GET /api/report/mine` → elenco con stato;
- `POST /api/report/open` con `{number}` (apre `https://github.com/Pier144/VerseForge/issues/<n>`, `n` intero) o
  con `{fallback: {...stesso JSON...}}` (costruisce l'indirizzo di riserva sul server). Nessun indirizzo arriva
  già fatto dall'interfaccia.

## C. App: interfaccia

- Pulsante con icona a fumetto nella barra in alto, prima di quello della luna, titolo "Report a problem or
  suggest an idea".
- Finestra `#reportDlg` con due schede:
  - **New report**: scelta Bug / Idea (pillole come quelle esistenti), titolo, descrizione, due interruttori già
    accesi "Attach a picture of the 3D view" e "Attach technical details", sezione apribile "What will be sent"
    (chiede `/api/report/preview` mentre si scrive, al massimo ogni 400 ms), avviso "Reports and pictures are
    public on GitHub. Personal folders and names are removed.", pulsanti Cancel / Send.
  - **My reports**: elenco con numero, titolo, stato (Open / Closed / Removed), commenti, data; clic → apre la issue.
- Immagine: `renderer.domElement` (ha già `preserveDrawingBuffer: true`) ridotta a 1600 px di lato lungo, JPEG
  qualità 0.85; se supera 2 MB si riduce ancora (1200 px, 0.75).
- Scheda video: `WEBGL_debug_renderer_info` dal contesto WebGL della vista.
- Dopo l'invio: messaggio "Report #42 sent" con link, modulo svuotato, passa a My reports.
- Errori, mostrati sotto il modulo senza perdere la bozza:
  - `rate` (429) → "Too many reports from this connection, try again in a few minutes";
  - `invalid` (400) → il motivo dato dal servizio (es. "Title is too short");
  - `network` o `unavailable` (503) → messaggio e pulsante "Open on GitHub instead" (riserva, senza immagine).
- La bozza non inviata resta se si chiude la finestra (in memoria, finché l'app è aperta).

## Prove

- `tests/test_reports.py`: pulizia dei dati personali (percorsi Windows e Linux, cartella di Wine nel log,
  maiuscole, cartelle fuori dalla home, nome utente dentro altre parole non toccato, nomi di 1–2 lettere
  ignorati), `compose` (segnaposto, `</details>` e ``` nel testo, menzioni), taglio dell'indirizzo di riserva,
  elenco in config, `send` con server finto (`http.server` locale) per 201/400/429/503 e rete giù, `statuses`
  con 200/404/410.
- `reports-service/test/*.test.js` con `node --test`: validazione, menzioni idempotenti, JWT ben formato e con i
  tempi giusti, tetto globale, rinnovo del token dopo 401, flusso completo con `fetch` e Blob finti (immagine
  riuscita e fallita), interruttore spento, 403/422 di GitHub → 503.
- Prova vera alla fine: una segnalazione inviata dall'app di sviluppo, **solo dopo il permesso dell'utente**
  (diventa pubblica), poi chiusa con un commento e immagine cancellata.
- Anteprima nella finestra di sviluppo (`verseforge-dev`) per l'aspetto in chiaro e scuro.

## Rilascio

Uscirà come VerseForge 1.14.0 quando l'utente lo chiede (stesso procedimento delle release precedenti). Il
servizio va pubblicato e provato prima della release, perché le versioni nuove lo usano subito.
