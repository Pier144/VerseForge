# Ottimizzazione 5 — geometria compressa per il visualizzatore

**Esito: la compressione della geometria va scartata. Va invece tenuto il nuovo calcolo delle normali**, nato
durante la prova: dà lo stesso identico risultato ed è 3 volte più veloce.

Branch `opt-5-geometria`. Sul branch resta solo il calcolo delle normali (`web/normals.js`) più questo
resoconto. Il codice della compressione, completo e verificato, è nel commit `6a266e3` del branch (vedi in
fondo), se un giorno servisse.

## Cosa ho provato

Il file che il visualizzatore scarica (`/api/model/glb?...&lite=true`) è fatto di tre cose: posizioni dei vertici
(float a 32 bit), coordinate UV (float a 32 bit) e indici dei triangoli (interi a 32 bit). Sul Perseus con interni
sono 79 + 49 + 60 MB.

1. **Quantizzazione** (estensione glTF `KHR_mesh_quantization`, letta da three.js senza aggiunte):
   - posizioni in interi a 16 bit, una griglia per nodo, centrata sull'origine del nodo; il nodo riceve la scala
     che le riporta in metri;
   - UV in interi a 16 bit quando stanno tra 0 e 1 (o tra −1 e 1), comprese quelle degli stencil mimetici `_UV2`;
   - indici a 16 bit per le mesh sotto i 65.536 vertici.
2. **meshopt** (estensione `EXT_meshopt_compression`) sopra la quantizzazione: per Python non esiste un pacchetto
   meshoptimizer installabile (Python 3.13, Windows), quindi ho scritto il codificatore in numpy
   (`sc_explorer/meshopt.py`). Il decodificatore è quello di three r160 (meshoptimizer 0.18, licenza MIT).

Solo il file "lite" del visualizzatore cambiava: esportazioni GLB/OBJ/STL e stampa 3D restavano identiche.

## Risultati

Stesso computer, stesso server. Il computer era occupato all'~85% dalle altre sessioni in parallelo, quindi ogni
confronto è A/B alternato sulla stessa richiesta (stesso modello già in memoria, file costruito da capo ogni volta),
e i valori sono mediane di 3–5 giri.

### Dimensione del file scaricato

| Modello | Prima | Quantizzato | Quantizzato + meshopt |
|---|---:|---:|---:|
| Quartz | 2,3 MB | 1,5 MB | 1,1 MB |
| Gladius | 10,8 MB | 7,3 MB | 3,9 MB |
| Gladius full ship | 30,5 MB | 20,2 MB | 11,6 MB |
| Perseus con interni | 188,9 MB | 151,7 MB | 62,5 MB |
| Carrack con interni | 139,0 MB | 111,5 MB | 45,4 MB |

### Server: tempo per costruire il file (modello già in memoria)

| Modello | Prima | Quantizzato | Quantizzato + meshopt |
|---|---:|---:|---:|
| Quartz | 0,09 s | 0,13 s | 0,15 s |
| Gladius | 0,14 s | 0,16 s | 0,23 s |
| Gladius full ship | 0,58 s | 0,70 s | 0,75 s |
| Perseus con interni | 1,49 s | 1,79 s | **3,30 s** |
| Carrack con interni | 1,53 s | 2,06 s | **3,23 s** |

La codifica meshopt usa 8 thread; senza, sul Perseus costava 4,4 s.

### Browser: download + lettura del file + normali

| Modello | Prima | Solo normali nuove (tenuto) | Quantizzato + normali nuove | meshopt + normali nuove |
|---|---:|---:|---:|---:|
| Gladius | 71 ms | 61 ms | 53 ms | 47 ms |
| Gladius full ship | 208 ms | 163 ms | 125 ms | 135 ms |
| Perseus con interni | 881 ms | 593 ms | 526 ms | 497 ms |
| Carrack con interni | 684 ms | 509 ms | 493 ms | 427 ms |

Sul Perseus il download passa da 202 a 74 ms con meshopt, ma la lettura sale da 93 a 151 ms (decodifica).

### Bilancio sulla prima apertura (il caso normale)

Perseus con interni, rispetto al solo calcolo nuovo delle normali: il server spende **+1,8 s** per comprimere, il
browser risparmia **0,1 s**. Risultato: **circa 1,7 s più lento**. Carrack: +1,7 s contro −0,08 s. Anche la sola
quantizzazione è in pari o in perdita (+0,3 s sul server, −0,07 s nel browser).

Il motivo: il server è sullo stesso computer, e 189 MB passano in circa 0,2 s. Comprimere in Python costa più di
quanto si risparmia a trasferire. I guadagni veri sarebbero solo di spazio:
- cache su disco: un Perseus occuperebbe 62 MB invece di 189 (circa 3 volte più navi nei 10 GB);
- memoria del server per il file tenuto in RAM: 3 volte meno;
- memoria della scheda video per i vertici: −14% (Perseus 267 → 230 MB, Carrack 194 → 166 MB).

## Controlli fatti

- **Precisione**: errore massimo sulla posizione 0,007 mm (Quartz), 0,13 mm (Gladius), 0,15 mm (Gladius full ship),
  0,5 mm (Perseus con interni), 0,48 mm (Carrack con interni). UV entro 0,000015, indici identici. meshopt non
  perde nulla: decodificato con il decodificatore vero di three, ogni blocco torna identico byte per byte.
- **A vista** (immagine a 1536×1152, vecchio contro nuovo; vecchio contro vecchio dà 0 differenze), quota di pixel
  che cambiano in modo appena percepibile:
  - Gladius: 0,05–0,07% (bordi sottili delle linee dei pannelli);
  - Gladius full ship con le animazioni ferme a metà: 0,05–0,09%;
  - Perseus, livrea con mimetico digitale rosso (stencil `_UV2`): 0,25–0,68%, solo bordi; mimetico e decal identici;
  - Perseus con interni tagliato al ponte 1: stessi 5 pulsanti dei ponti, stesso taglio (−3,60 m); 0,17–1,4%. Oltre ai
    bordi, in due punti cambia quale di due superfici diverse del modello originale vince: sono perfettamente
    sovrapposte (stessa distanza dalla telecamera al centesimo di millimetro), quindi già nel file originale il
    vincitore cambia muovendo la vista.
- **Errori trovati e corretti durante la prova** (utili se la si riprende):
  - trimesh riusa lo stesso blocco di posizioni per pezzi identici appesi a nodi diversi: quantizzarlo per un nodo
    rompeva l'altro. Ora un blocco condiviso viene quantizzato solo se tutti i suoi nodi usano la stessa griglia;
  - spostare il nodo verso il centro della griglia cambiava l'ordine in cui three.js disegna i vetri (li ordina per
    posizione del nodo): attraverso il tettuccio del Perseus si vedeva un'altra cosa. Ora la griglia è centrata
    sull'origine del nodo, che non si sposta;
  - con le posizioni in interi a 16 bit il calcolo delle normali di three.js diventava molto più lento. Da qui il
    calcolo nuovo (sotto).

## Cosa resta: normali calcolate più in fretta

Il file del visualizzatore non porta le normali, che il browser calcola a ogni apertura (già misurato come la
voce più lenta del browser: 346 ms sul Perseus a macchina scarica). `web/normals.js` fa lo stesso calcolo di three.js
(normali delle facce pesate per area, sommate per vertice, poi normalizzate) lavorando direttamente sugli array,
senza creare un oggetto per ogni vertice. Il risultato è **identico al bit** (verificato su tutti i 6,6 milioni di
vertici del Perseus con interni e su Quartz e Gladius). Funziona anche con posizioni float o interi.

| Modello | Normali di three.js | Normali nuove |
|---|---:|---:|
| Quartz | 13 ms | 4 ms |
| Gladius | 48 ms | 14 ms |
| Gladius full ship | 152 ms | 46 ms |
| Perseus con interni | 700 ms | 229 ms |
| Carrack con interni | 518 ms | 166 ms |

(mediane di 5 giri alternati, stesso file). Server, file e aspetto non cambiano.

## Raccomandazione

- **Tenere** `web/normals.js` (e le due righe in `web/app.js` che lo usano): un modello grande si apre ~0,3–0,5 s
  prima, senza nessun cambiamento visibile.
- **Scartare** quantizzazione e meshopt: sulla prima apertura rallentano le navi grandi di circa 1,7 s.
- Se in futuro lo spazio della cache su disco diventasse un problema, il codice è pronto: si potrebbe comprimere
  **dopo** aver mandato il file (in sottofondo, solo per la cache su disco e quella in memoria), così la prima
  apertura non paga nulla e le riaperture leggono un file 3 volte più piccolo. Non l'ho provato.

## Dove sta il codice

- Commit `6a266e3` ("Experiment: quantized + meshopt viewer GLB") sul branch `opt-5-geometria`: `sc_explorer/glb_pack.py`,
  `sc_explorer/meshopt.py`, `web/vendor/three/examples/jsm/libs/meshopt_decoder.module.js` e i collegamenti in
  `export.py` / `app.js`. Il commit successivo li toglie: il branch, unito, porta solo le normali e questo resoconto.
- Nota per chi unisce: la sessione opt-10 tocca `model_glb` in `server.py`; questo branch non tocca `server.py`.
