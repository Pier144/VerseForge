# Ottimizzazione 9 — livelli di dettaglio (LOD)

**Raccomandazione: SCARTARE.** Nessuna modifica al codice su questo ramo, solo questo resoconto.

## L'idea

Il gioco ha versioni più leggere di quasi ogni oggetto (`<nome>_lod1.cga` … `_lod5`). Oggi gli arredi degli
interni usano già il LOD1 (`assembly.load_interior`). L'idea era andare oltre per tenere fluide le navi grandi:

- **A. Scambio vicino/lontano:** interni (e oggetti montati) al LOD3 quando la nave si vede intera, LOD1 quando la
  telecamera si avvicina.
- **B. Interni più leggeri al caricamento:** LOD2 invece di LOD1, sempre.
- **C. Oggetti montati (nave completa) al LOD1.**

Esportazioni e stampa 3D sarebbero rimaste al dettaglio pieno.

## Come ho misurato

- PC: AMD Radeon RX 7900 XTX (WebGL con ANGLE su D3D11). Tela forzata a 1536×1152, pixel ratio 1.
- Fotogramma = media di 25 `renderer.render` + `gl.readPixels` (sincronizzazione), sulla stessa vista iniziale.
- Server: costruzione del modello a freddo + GLB "lite" del visualizzatore, in un processo nuovo, senza cache su
  disco.
- Per provare B e A senza scriverli per intero ho reso il livello degli interni un parametro temporaneo (LOD1, 2, 3)
  e ho caricato le navi a ogni livello.
- Attenzione: durante le misure altre quattro sessioni usavano CPU e scheda video, quindi i tempi per fotogramma
  oscillano molto (stessa scena: da 7 a 12 ms). Per questo la prova principale è un confronto A/B alternato nella
  stessa pagina (sotto).

## Prova chiave: i triangoli contano poco su questo PC

Stessa scena, stessi materiali, stesse chiamate di disegno; a ogni oggetto faccio disegnare solo **un quarto** dei
suoi triangoli (`drawRange`). Alterno pieno / un quarto 6–12 volte e prendo la mediana. È il massimo guadagno che
qualunque LOD potrebbe mai dare (un LOD vero toglie meno del 75 %).

| Nave (con interni) | Triangoli | Chiamate di disegno | Tutti i triangoli | Solo 1/4 dei triangoli |
|---|---:|---:|---:|---:|
| Perseus | 5,0 M | 403 | 5,45 ms | 4,27 ms |
| Carrack | 3,9 M | 662 | 8,63 ms | 8,34 ms |
| Polaris | 8,2 M | 632 | 7,15 ms (9,4) | 5,79 ms (8,3) |
| Polaris, nave completa | 12,9 M | **2.697** | 24 ms | 31 ms (rumore: nessun guadagno) |

Tra parentesi la seconda serie, fatta con il PC più carico: la differenza resta 1,1–1,5 ms.

Il tempo per fotogramma segue soprattutto il **numero di chiamate di disegno**, non i triangoli: la Carrack con
3,9 M triangoli è più lenta della Polaris con 8,2 M, e le navi complete (2.000–2.700 chiamate) stanno a 20–25 ms
qualunque cosa si faccia ai triangoli. Anche rimpicciolendo la tela a 256×192 la Carrack passa solo da 7,7 a 7,3 ms:
non è nemmeno il riempimento dei pixel.

## Prima / dopo: interni al LOD1 (oggi), LOD2, LOD3

Server, costruzione a freddo (modello + GLB lite):

| Nave (con interni) | | Oggi (LOD1) | LOD2 | LOD3 |
|---|---|---:|---:|---:|
| Perseus | triangoli | 5,00 M | 3,30 M | 2,51 M |
| | GLB | 189 MB | 131 MB | 98 MB |
| | costruzione | 6,1 s | 5,3 s | 5,3 s |
| Carrack | triangoli | 3,89 M | 1,77 M | 0,93 M |
| | GLB | 139 MB | 67 MB | 36 MB |
| | costruzione | 7,4 s | 7,0 s | 5,3 s |
| Polaris | triangoli | 8,25 M | 5,15 M | 3,61 M |
| | GLB | 315 MB | 207 MB | 143 MB |
| | costruzione | 11,6 s | 10,0 s | 9,2 s |
| Polaris completa | triangoli | 12,86 M | 9,76 M | 8,22 M |
| | GLB | 405 MB | 297 MB | 233 MB |
| | costruzione | 16,1 s | 15,9 s | 15,5 s |

Fotogramma con i modelli veri (valori indicativi per il rumore):

| Nave (con interni) | Oggi (LOD1) | LOD2 | LOD3 |
|---|---:|---:|---:|
| Perseus | 4,05 ms | — | 4,0 ms (4,0–4,7) |
| Polaris | 7,3–8,3 ms | 7,0–8,5 ms | 6,3 ms (prima misura) |
| Carrack | 8,5 ms | — | 7,5–9,2 ms |
| Polaris completa | 20–23 ms | — | 14–22 ms (stesse 2.690 chiamate) |

Il tempo di caricamento nel browser non è confrontabile (da 4 a 37 s per la stessa nave a seconda del carico delle
altre sessioni); lato server la costruzione cambia di 0–2 s, il file invece cala molto.

## Perché scartare

- **A (vicino/lontano):** guadagno massimo ~1 ms solo quando si guarda la nave intera da fuori, cioè quando gli
  interni sono comunque quasi tutti nascosti dallo scafo. In cambio il GLB dovrebbe contenere **due copie** degli
  interni (stima Polaris: 315 → ~380 MB, +20 %), più tempo di caricamento, uno scatto visibile al cambio e più
  complessità nel GLB animato (nodi che si muovono, sezione, ponti). Il conto è in perdita.
- **B (LOD2 sempre):** file molto più piccolo (−31 % Perseus, −52 % Carrack, −34 % Polaris) ma fluidità invariata
  entro il rumore, e a ~6 m si vedono già dettagli persi (griglie dei pavimenti, ringhiere, piccoli arredi). Chi apre
  gli interni li vuole guardare da vicino: non lo metterei come scelta predefinita. Al massimo potrebbe diventare
  un'opzione "interni leggeri" per PC deboli — ma non l'ho potuta misurare su una scheda debole.
- **C (oggetti montati al LOD1):** le navi complete sono limitate dalle chiamate di disegno; meno triangoli non
  cambiano il fotogramma. Inoltre molti file LOD non hanno la tabella dei nodi, e torrette e carrelli animati si
  romperebbero.
- Lo scafo non l'ho toccato: è la parte che si guarda di più, e i suoi LOD rischiano di perdere nodi animati e
  decal.

## Cosa conviene invece

Il collo di bottiglia vero sono le **chiamate di disegno**, soprattutto nelle navi complete: il GLB animato divide i
pezzi per osso mosso × materiale (`export._to_glb_animated`), e la Polaris completa passa da ~630 a ~2.700
chiamate. Ridurre quelle (istanze, unione per osso solo dove serve) è la strada per le navi grandi; ho lasciato una
nota per le sessioni che ci lavorano.

## Come ripetere

- Livello degli interni: parametro `lod` di `load_interior` (oggi fisso a 1) — la prova ha usato una funzione
  `lod_model(archive, path, level)` che sceglie `_lod<level>` o il più dettagliato disponibile sotto, con la `.mtl`
  del LOD0.
- Prova "un quarto dei triangoli" nel browser: per ogni mesh `geometry.setDrawRange(0, indici/4)`, alternata con
  `setDrawRange(0, Infinity)`, misurando 25 `render` + `readPixels` per volta.
