# Ottimizzazione 6 — meno chiamate di disegno per le parti ripetute

**Consiglio: TENERE** la modifica al server (ramo `opt-6-istanze`). **Scartata** la seconda prova (unire nel browser
le parti che si muovono).

## Da dove venivano le chiamate di disegno

Il visualizzatore fa una chiamata di disegno per ogni pezzo (mesh). Il server unisce già i pezzi che hanno lo stesso
materiale, ma solo **dentro lo stesso nodo**. Le cause trovate:

1. **Navi animate (Perseus, Gladius, Carrack):** per far muovere carrello, ali, portelli, il server teneva come nodi
   separati le parti mobili **e tutti i loro "antenati"**. Molti antenati non si muovono mai (sul Perseus
   `geo_front` e `geo_main_wings` portano da soli 178 pezzi). Sul Perseus 264 dei 392 pezzi visibili erano fermi ma
   divisi su 23 nodi, quindi la stessa vernice veniva disegnata più volte.
2. **Materiali "quasi uguali":** negli interni lo stesso materiale arriva in copie che differiscono solo in dettagli
   che l'aspetto da gioco (`gamelook.js`) rifà comunque da capo, per esempio il nome dello shader. Il server li teneva
   separati.
3. **Parti mobili ripetute** (gambe del carrello, alette, propulsori): ognuna si muove per conto suo, quindi ogni
   nodo mobile ha i suoi pezzi.

**Perché niente "instancing"** (InstancedMesh / EXT_mesh_gpu_instancing): serve quando lo stesso oggetto è disegnato
tante volte come pezzi separati. Qui gli oggetti ripetuti e fermi (casse, sedili, luci) sono già fusi nel pezzo del
loro materiale: una sola chiamata, meglio di quanto darebbe l'instancing. Le parti ripetute che si muovono, invece, si
muovono ognuna in modo diverso. Per loro ho provato l'alternativa giusta, cioè la "pelle rigida" (punto B qui sotto).

## Cosa ho cambiato (tenuto)

Solo nel file 3D che il server prepara per il visualizzatore (`lite`). **Le esportazioni dell'utente restano identiche**
(c'è un test che lo controlla).

- `sc_explorer/export.py`: ogni parte viene appesa al suo **antenato che si muove davvero** e non al primo antenato
  tenuto. Le parti ferme tornano così alla radice e si uniscono con le altre dello stesso materiale. Le parti mobili
  restano sotto il loro nodo animato, quindi le animazioni funzionano come prima.
- Sempre lì: nel file per il visualizzatore si uniscono anche i materiali che l'aspetto da gioco disegna uguali:
  stesso nome, stesso tipo, stessa descrizione di shading, stesso colore, stessa luce propria, stesso flag metallo.
  Il nome resta separato, così la lista materiali può ancora nasconderli uno per uno.
- `sc_explorer/diskcache.py`: `FORMAT = 2`. I file già salvati sul disco hanno la forma vecchia e vengono rifatti
  una volta sola.
- Test nuovi: `test_viewer_glb_merges_still_parts` (Gladius e Perseus: stessi triangoli, stessi triangoli in
  movimento, stesse animazioni sugli stessi nodi, almeno il 15% di pezzi in meno, esportazione utente identica) e
  `test_lite_merge_joins_materials_the_game_look_draws_the_same`.

## Prima / dopo

Server senza cache su disco; browser con luce hangar (ombre accese), tela 1536×1152, vista di tre quarti come
"Reset view". Il frame è la media di 25 `renderer.render` + `gl.readPixels`; vale il migliore di 4 giri, alternando
prima e dopo, perché altre sessioni usavano la stessa scheda video nello stesso momento. "CPU" è il tempo di
`renderer.render` senza aspettare la scheda: è il lavoro che le chiamate di disegno costano al processore.

| Modello | Chiamate di disegno | Frame (ms) | CPU per frame (ms) | File GLB | Export sul server* | Apertura nel browser** |
|---|---|---|---|---|---|---|
| Perseus con interni | 403 → **243** (−40%) | 5,21 → **4,38** (−16%) | 1,91 → **1,23** (−36%) | 188,9 → 188,7 MB | 1,66 → **1,41 s** | 1,41 → **1,06 s** |
| Carrack con interni | 662 → **500** (−24%) | 7,74 → 7,62 (−2%) | 4,98 → **3,10** (−38%) | 139,0 → 138,9 MB | 1,65 → 1,55 s | 1,30 → **1,09 s** |
| Gladius nave completa | 648 → **472** (−27%) | 5,64 → 5,39 (−4%) | 3,11 → **2,62** (−16%) | 30,5 → 32,3 MB (+6%) | 0,83 → **0,56 s** | 0,25 → 0,28 s |

\* Tempo per scrivere il GLB con il modello già costruito in memoria. Con il server "freddo" (modello da leggere dal
p4k) il totale resta dominato dalla costruzione: Perseus 6,4 → 6,0 s, Carrack 7,6 → 6,5 s, Gladius 2,0 → 2,4 s
(differenza nel rumore).
\** Server già caldo, fino al modello pronto con le texture di gioco (migliore di 4).

In parole semplici: **il processore lavora un terzo in meno per ogni fotogramma** su Perseus e Carrack. Il fotogramma
intero migliora meno (2–16%) perché, guardando la nave da fuori con le ombre, sul mio PC il limite è la scheda video
(milioni di triangoli). Su un PC con processore più debole, o con il portatile in risparmio energetico, il guadagno si
sente di più. Il Gladius pesa 1,8 MB in più perché oggi il server salva una volta sola i pezzi identici appesi a nodi
diversi (sinistra/destra); fusi nella radice quella condivisione si perde. Perseus e Carrack non cambiano.

## Controlli fatti (tutto funziona come prima)

Confronto **pixel per pixel** fra prima e dopo (768×576), stessa camera:

- Gladius completo, fermo: diverso lo 0,005% dei pixel (rumore di z-fighting, cioè superfici sovrapposte).
- Gladius, carrello a metà della "Retract" e alla fine: 0,005%. Le parti mobili si muovono uguali.
- Perseus con interni, sezione al 45% e 5 materiali nascosti dalla lista: 0,019%. Stessi 117 materiali in lista,
  stessi pulsanti dei ponti (1–4, All).
- Carrack con interni: fermo 0,005%; con i livelli invertiti (decal/vetro/schermi/proxy) 0,01%; wireframe 0,26%
  (linee sottili che si sovrappongono).
- Ombre accese in tutte le prove; l'aspetto da gioco si applica come prima (stesse texture richieste).
- `python -m pytest tests -q`: **75 passati** (i 72 di prima più i 3 nuovi), in 106 s.

## Provato e scartato

**B. "Pelle rigida" nel browser** (`SkinnedMesh`): le parti mobili con lo stesso materiale diventano un solo pezzo e
ogni vertice segue il suo nodo animato. Le chiamate scendono ancora (Perseus 134, Carrack 451, Gladius 198), ma:

| Modello | Frame (ms) solo server → con B | CPU (ms) solo server → con B |
|---|---|---|
| Perseus | 4,38 → 4,35 | 1,23 → 1,20 |
| Carrack | 7,62 → 7,91 | 3,10 → 3,63 |
| Gladius | 5,39 → 5,02 | 2,62 → 2,36 |

Il guadagno è piccolo o nullo (sul Carrack peggiora). L'immagine del Gladius differiva nel 5% dei pixel, quindi c'è
almeno un errore da capire. Inoltre lo scheletro ricarica la sua texture a ogni fotogramma e l'apertura dura circa
70 ms in più. Non vale la complessità. Il codice è conservato fuori dal repo, nella cartella delle note condivise:
`opt6-merge-skinned-scartato.js`.

## Nota per chi misura nel pannello nascosto

Con il pannello del browser nascosto, `frame()` dell'app mette la camera **al centro del modello** (la tela misura
0×0), quindi le misure sono fatte da dentro lo scafo. Per misurare ho rifatto l'inquadratura a mano (stesso calcolo di
`frame()` con 1536×1152). Le mie prime misure, fatte da dentro, davano lo stesso verso: Perseus 4,04 → 3,05 ms.
