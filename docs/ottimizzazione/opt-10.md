# Ottimizzazione 10 — budget di memoria del server

**Consiglio: TENERE.** Con le impostazioni normali (cache su disco accesa) il server usa 200–750 MB in meno e il
primo caricamento delle navi grandi è più veloce del 30–55 %. Le riaperture restano veloci come prima.

## Cosa è cambiato

1. **Budget in MB invece di "ultimi 8 modelli"** (`sc_explorer/modelcache.py`). Prima il server teneva gli ultimi 8
   pezzi costruiti, che fossero un'arma da 2 MB o il Polaris con interni da 750 MB. Ora tiene i modelli finché il
   loro peso stimato sta in **1,5 GB**, e butta via per primi quelli usati meno di recente. Il peso si conta da
   vertici, facce, UV e indici delle ossa, più quello che il modello tiene da parte (GLB, animazioni). I dati
   condivisi si contano una volta sola: una nave con interni sono 3 voci (base, vernice, interni) che condividono
   quasi tutto, e la stima lo sa (Polaris: 3 voci = 754 MB, non 1,7 GB).
2. **Niente copia del GLB in memoria se è già sulla cache su disco**: le richieste successive lo leggono comunque dal
   disco, quindi la copia in memoria non serviva mai (Polaris: 300 MB, Perseus: 180 MB).
3. **Una sola costruzione per modello alla volta.** Il visore chiede insieme la descrizione del modello e il GLB; le
   due richieste costruivano la stessa nave due volte in parallelo, contendendosi il processore. Ora la seconda
   aspetta la prima. È da qui che viene il guadagno sul primo caricamento.
4. `/api/status` riporta anche la memoria stimata (`memory`: modelli tenuti, MB stimati, MB di texture, budget).

Il budget delle texture (400 MB di immagini decodificate) è stato controllato: viene rispettato (397–400 MB in tutte
le prove). Il budget si può cambiare per le prove con la variabile `VERSEFORGE_MODEL_MB`.

## Come è stato misurato

`python tools/bench_memory.py` (nuovo): avvia un server suo, apre in fila Polaris con interni, Perseus con interni,
Carrack con interni, Gladius completa, Quartz, poi riapre Quartz, Gladius e le prime tre navi. Per ogni modello chiede
quello che chiede il visore (descrizione + GLB leggero + tutte le texture, 6 alla volta) e legge la memoria del
processo (memoria privata = quella che il server occupa davvero). "Prima" = `main` 7370733, "dopo" = questo ramo.
Con `--disk-cache` la cache su disco è accesa, in una cartella temporanea (quella vera dell'utente non viene toccata).

Altre sessioni giravano in parallelo sullo stesso PC, quindi i tempi hanno un po' di rumore; il guadagno sul primo
caricamento si è visto uguale in tutte e quattro le prove "dopo".

## Risultati

### Cache su disco accesa (impostazione normale)

| | prima | dopo |
|---|---|---|
| memoria privata a server pronto | 776 MB | 776 MB |
| memoria privata dopo i 5 modelli | 2647 MB | **2442 MB** |
| memoria privata massima a riposo | 3355 MB | **2590 MB** |
| picco durante le costruzioni | 4266 MB | **3786 MB** |
| primo caricamento Polaris con interni | 26,9 s | **16,0 s** |
| primo caricamento Perseus con interni | 12,8 s | **9,7 s** |
| primo caricamento Carrack con interni | 22,2 s | **9,5 s** |
| primo caricamento Gladius completa | 5,8 s | **3,4 s** |
| riapertura Quartz (appena usata) | 0,10 s | 0,10 s |
| riapertura Gladius / Polaris / Perseus / Carrack | 0,67 / 0,79 / 0,66 / 1,35 s | 0,63 / 0,73 / 0,63 / 1,36 s |

Con la cache su disco le riaperture vengono dal disco in ogni caso; la memoria ora si ferma attorno a 2,4 GB invece di
salire a 3,4 GB.

### Cache su disco spenta (`start.py --no-disk-cache`)

| | prima | dopo, budget 1,5 GB | dopo, budget 3 GB (prova) |
|---|---|---|---|
| memoria privata dopo i 5 modelli | 2210 MB | 2411–2422 MB | 3050 MB |
| memoria privata massima a riposo | 3219 MB | 3199–3260 MB | 3072 MB |
| picco durante le costruzioni | 5117 MB | 5189 MB | **3862 MB** |
| primo caricamento Polaris con interni | 24,1 s | **13,2–16,0 s** | 14,9 s |
| primo caricamento Perseus con interni | 13,6 s | **8,9–9,7 s** | 10,5 s |
| primo caricamento Carrack con interni | 17,9 s | **12,8–15,6 s** | 12,8 s |
| riapertura Quartz (appena usata) | 0,18 s | 0,15–0,17 s | 0,16 s |
| riapertura Gladius (usata 1 modello fa) | 4,0 s | **2,3–2,8 s** | 2,5 s |
| riapertura Polaris (dopo altre 4 navi) | 23,8 s | 15,7–16,7 s | **3,7 s** |

Senza cache su disco la memoria resta quella di prima, ma ora è legata ai MB e non al numero di pezzi. Con 1,5 GB ci
stanno 2–3 navi grandi con interni; il giro di prova ne apre 3 più due piccole, quindi il Polaris esce e va
ricostruito (ma in metà tempo). Con 3 GB resta tutto e il Polaris si riapre in 3,7 s, al prezzo di ~650 MB in più.
Ho lasciato 1,5 GB come valore normale perché chi usa il programma ha di solito la cache su disco accesa.

## Cose notate, non fatte qui

- **Texture senza cache su disco.** I 400 MB di immagini decodificate non bastano per le texture di una sola nave
  grande (Polaris: 257 texture) e ogni richiesta ricodifica l'immagine in JPEG/PNG. Per questo, senza cache su
  disco, anche una riapertura "in memoria" costa 2–4 s. Tenere in memoria i JPEG/PNG già pronti (circa un decimo
  del peso) risolverebbe; con la cache su disco accesa non serve.
- La stima conta solo i dati grossi: il processo dopo la prima nave occupa ~800 MB in più di quanto stimato
  (memoria di Python non restituita al sistema, oggetti piccoli). Il budget limita quindi i modelli, non il
  processo intero.

## Test

`python -m pytest tests -q`: tutti passati (i 72 di prima + 6 nuovi in `tests/test_modelcache.py` e
`tests/test_diskcache.py`).
