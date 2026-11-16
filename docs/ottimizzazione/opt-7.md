# Ottimizzazione 7: texture progressive

**Raccomandazione: TENERE.** Il modello si vede con tutte le texture 3,5–4 volte prima e il blocco dello schermo
all'arrivo delle texture si riduce di 2–3 volte. Il prezzo: la risoluzione piena arriva un po' più tardi (0,3–0,8 s
a server freddo; a server caldo addirittura prima), il 5–9 % di byte in più, nessuna memoria in più.

Ramo `opt-7-texture-progressive`, partito da `main` 7370733.

## Cosa cambia

Prima, il viewer chiedeva ogni texture del gioco a 1024 px (decal 2048) e mostrava il modello solo quando
**tutte** erano arrivate. Ora (`web/gamelook.js`):

1. ogni texture viene chiesta prima a **256 px** (1/16 dei pixel); la barra di caricamento segue queste;
2. appena le piccole sono arrivate il modello compare, già con i colori, le normali e la lucentezza giusti;
3. subito dopo partono le richieste a 1024/2048: ogni texture grande, appena arriva, prende il posto della piccola
   nel materiale (stessi parametri: ripetizione, spazio colore, filtri) e la piccola viene liberata (`dispose`);
4. ogni scambio chiede un ridisegno (`invalidate(100)`), così il disegno su richiesta aggiorna l'immagine.

Dettagli:

- una texture più piccola di 256 px è già intera: niente seconda richiesta;
- se la stessa texture serve a 1024 su uno scafo e a 2048 su un decal, la piccola è una sola e diventa 2048;
- se si cambia modello a metà, le texture grandi in arrivo del modello vecchio vengono buttate;
- `dispose()` ora libera anche le copie con ripetizione propria (prima restavano sulla scheda video);
- interruttori per le misure: `GameLook.progressive` (false = comportamento vecchio), `GameLook.bust` (salta la
  cache HTTP del browser), `__verseforge.look`; script di misura in `tools/bench_textures.js`.

Il server non cambia: `/api/texture` accettava già `size=256` (usa un livello mip piccolo, quindi costa poco).

## Come ho misurato

- server `--no-disk-cache`, **riavviato prima di ogni giro**; texture con un parametro anti-cache diverso a ogni giro;
- viewer a 1536×1152, interni accesi, fotogrammi guidati con `__verseforge.tick()` ogni 16 ms;
- 3 giri a freddo per ogni caso, alternati; nella tabella la **mediana**;
- i tempi assoluti contengono anche la costruzione del modello sul server (12–17 s, molto variabile perché altre
  sessioni usavano il processore nello stesso momento): il confronto onesto è il tempo **dall'inizio delle
  texture** (prima richiesta `/api/texture`), che è la parte toccata da questa modifica;
- memoria: `renderer.info.memory.textures` conta gli oggetti texture; ho aggiunto una stima della memoria delle
  immagini in uso (larghezza × altezza × 4 byte × 4/3 per i mip), campionata ogni 250 ms durante il caricamento;
- dopo le misure ho fatto un ultimo ritocco (lista delle texture da sostituire tenuta per ogni `apply()`, per lo
  sfondo officina) che con un solo modello non cambia nulla: ricontrollato, risultato identico pixel per pixel.

## Prima / dopo (a freddo, mediana di 3 giri)

| | Perseus + interni prima | Perseus + interni dopo | Carrack + interni prima | Carrack + interni dopo |
|---|---|---|---|---|
| Modello con tutte le texture (basse), dall'inizio delle texture | 5,5 s | **1,6 s** | 9,0 s | **2,3 s** |
| Modello a risoluzione piena, dall'inizio delle texture | 5,5 s | 6,3 s (+0,8) | 9,0 s | 9,3 s (+0,3) |
| Stessi tempi dall'apertura del modello (basse / piena) | 18,7 s | 15,8 s / 20,3 s | 25,6 s | 16,7 s / 23,7 s |
| Blocco del primo fotogramma con le texture | 1,79 s | **0,77 s** | 2,17 s | **0,69 s** |
| Fotogramma più lungo durante gli scambi | - | 92 ms | - | 78 ms |
| Richieste di texture | 204 | 406 | 432 | 849 |
| Byte delle texture | 172,4 MB | 180,5 MB (+4,7 %) | 211,7 MB | 229,6 MB (+8,5 %) |
| di cui texture piccole | - | 9,3 MB | - | 18,1 MB |
| Picco `renderer.info.memory.textures` | 160 | 160 | 336 | 335 |
| Picco memoria immagini (stima) | 1547 MB | 1542 MB | 2163 MB | 2147 MB |

Giri singoli (dall'inizio delle texture, basse / piena):
Perseus prima 5,49 · 5,36 · 6,17 s; dopo 1,79/6,29 · 1,58/6,25 · 0,99/5,31 s.
Carrack prima 10,54 · 8,61 · 8,99 s; dopo 2,48/10,49 · 2,31/9,31 · 2,31/9,00 s.

A server caldo (texture già decodificate in memoria, simile alla cache su disco accesa), Perseus, 2 giri:
prima 6,0 e 5,4 s; dopo basse 1,19 e 1,23 s, piena 4,84 e 4,86 s; qui anche la piena arriva prima, perché il
lavoro del browser (decodifica JPEG/PNG e caricamento sulla scheda video) viene distribuito invece di
accumularsi in un unico fotogramma.

## Qualità dell'immagine

Stessa inquadratura ravvicinata sul Perseus, confronto pixel per pixel:

- risoluzione piena dopo lo scambio contro la versione di prima: **identica** (differenza 0 su tutti i pixel);
- fase con le texture piccole contro quella di prima: differenza media 0,3 su 255, solo lo 0,03 % dei pixel
  differisce di più di 24 livelli (dettagli fini un po' morbidi); colori giusti, nessun buco o texture nera;
- lo scambio non fa sfarfallare: la texture grande è già scaricata quando prende il posto della piccola e viene
  caricata sulla scheda video prima del disegno.

Cambio di modello a metà degli scambi (Gladius → Quartz) e 5 ricaricamenti di fila del Quartz: nessun errore
JavaScript, numero di texture stabile (nessuna perdita).

Sfondo "officina" (gli oggetti del gioco sul banco usano lo stesso meccanismo, più oggetti caricati insieme):
125 texture piccole, 119 sostituite dalla grande, le altre 6 erano già intere (≤ 256 px); nessuna rimasta
piccola per errore. Ogni `apply()` tiene la propria lista di texture da sostituire, così due oggetti caricati
insieme non si rubano le texture a vicenda.

## Provato e scartato

**Il server prepara la versione grande mentre manda la piccola** (parametro `later`, 8 thread in background): la
fase grande scendeva da 3,9 a 2,1 s, ma quella piccola saliva da 0,9 a 2,7 s (i thread Python si contendono il
GIL), cioè il modello compariva più tardi. Tolto.

## Da sapere

- La barra di caricamento finisce con le texture piccole; il passaggio a quelle grandi avviene in silenzio (dura
  4–7 s a freddo). Se serve, si può aggiungere un'indicazione discreta.
- Trovato per strada, non toccato: in `web/app.js` `invalidate()` senza durata (usato dagli hook `needsUpdate`
  di texture e materiali) **non** fa disegnare il fotogramma successivo, perché `renderUntil` = adesso è già
  passato al tick seguente; il disegno arriva solo con la rete di sicurezza di 1 s. Per questo gli scambi usano
  `invalidate(100)`. Conviene correggerlo a parte (es. una durata minima di un fotogramma).
- Test: `python -m pytest tests -q` passa (vedi commit). La modifica è solo nel viewer: non ci sono test
  automatici JavaScript.
