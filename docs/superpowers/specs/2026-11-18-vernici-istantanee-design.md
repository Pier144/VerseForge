# Vernici istantanee: progetto

Data: 18/11/2026 · Stato: disegno approvato dall'utente in chat, specifica da rileggere · Ramo: `vernici-istantanee`

## Scopo

Cambiare vernice (livrea) senza ricaricare il modello, come nel Paint Viewer di The Impound. Oggi il menu
"Variant / paint" chiama `loadModel(state.current, true)`: il server rifà il GLB, il visualizzatore lo riscarica, rifà
normali, materiali, batch e shader. Sulla Perseus (cache calda) servono 0,6-1,4 s; con *Full ship* e *Interiors*
3,4 s, e intanto la nave si sfoca sotto la scritta "Loading".

Obiettivo misurabile: Perseus con *Full ship* + *Interiors*, da una livrea già vista a un'altra già vista, meno di
0,3 s dal clic al primo fotogramma con la nuova vernice; da una livrea mai vista, meno di 1 s (le texture nuove
arrivano dopo, in piccolo e poi in grande, come oggi). Nessuna schermata di caricamento, nessuno sfocato.

Scelte fissate con l'utente:
- resta il menu a tendina di oggi, con **3 pallini di colore** (A, B, C della tavolozza) prima di ogni nome, anche
  sul pulsante chiuso; la vernice di serie, che nel gioco non ha tavolozza propria, ha **3 cerchi tratteggiati**
  (anteprima approvata: `docs/anteprime/menu-vernici.png`);
- sotto il menu un pulsante **"Compare with stock paint"**: acceso mostra la vernice di serie, un altro clic torna
  alla livrea scelta;
- la grafica del pannello resta quella di oggi.

Fuori da questo lavoro: shader nuovi delle vernici (strati, cangianti), ricerca nel menu, lista sempre aperta.

## Perché oggi serve ricaricare

`export.merged_by_material` unisce i pezzi con lo stesso materiale (chiave `repr(material)`, o `_lite_key` nel GLB
"lite"). Il materiale dipende dalla vernice (tavolozza e `.mtl` principale sostituito), quindi con un'altra vernice
cambiano i gruppi e quindi le mesh del GLB. Il visualizzatore non può tenere la geometria.

## Idea

Per i modelli con **almeno 2 vernici**, il GLB del visualizzatore unisce i pezzi con una chiave che **non dipende
dalla vernice**. Così la geometria è la stessa per tutte le vernici e il visualizzatore deve solo sostituire i
materiali. I modelli con una sola vernice (o nessuna) restano come oggi, byte per byte.

### Chiave di gruppo indipendente dalla vernice

`model.with_variant` lascia i pezzi nello stesso ordine e cambia solo `part.material`: il `.mtl` principale viene
sostituito da quello della vernice, ogni `.mtl` viene caricato con la tavolozza della vernice. Due pezzi con lo stesso
"posto" (stesso `mtl_path` dichiarato e stesso `mat_id`) hanno quindi lo stesso materiale in ogni vernice.

Chiave del pezzo `i`: `(p.mtl_path, p.mat_id, repr(materiale del pezzo i nella vernice di serie))`, più la stanza come
oggi per i pezzi solidi degli interni. La terza voce tiene separati i pezzi che condividono il posto ma non il
materiale (per esempio componenti del loadout con un materiale di record diverso). Pezzi senza `mtl_path` o con
`mat_id < 0`: chiave `repr(material)` (non cambiano con la vernice).

La "vernice di serie" è la prima della lista (`variant_list(path)[0]`), cioè quella che il server usa quando
`variant` manca.

### Verifica: il modello si può ridipingere?

Il server considera un modello "ridipingibile" (`paintable`) solo se, per ogni vernice:
1. ha lo stesso numero di pezzi della vernice di serie, nello stesso ordine (stesso `node` e stesso numero di
   facce per pezzo);
2. ogni gruppo ha in tutte le vernici lo stesso `kind` e lo stesso nome di materiale (il nome della mesh nel GLB è
   `kind|nome|n` e lo usano batch, interruttori dei materiali, decal, schermi, stanze);
3. tutti i pezzi di un gruppo hanno lo stesso materiale anche in quella vernice;
4. il gruppo ha la stessa scala delle UV (`uv_scale` di `materials.shading` e di `material_textures`) in tutte le
   vernici, perché il GLB la moltiplica dentro le UV.

Se una condizione manca, `paintable = false` e il cambio vernice ricarica il modello come oggi. Il risultato è
calcolato una volta per (modello, full, interior) e tenuto in memoria nel server.

Costo: costruire i materiali di tutte le vernici. `with_variant` carica ogni `.mtl` del modello una volta per vernice.
Da misurare sulla Perseus con interni (18 vernici). Se supera ~1 s, la verifica 1-4 si fa al primo cambio di
vernice invece che al caricamento, e fino ad allora il GLB usa già la chiave nuova (la chiave non ha bisogno della
verifica: serve solo a sapere se il cambio istantaneo è sicuro).

## Pezzi

### A. Server: `sc_explorer/paints.py` (nuovo)

Un modulo con un compito solo: dire come si raggruppano i pezzi e com'è fatto ogni gruppo in una vernice.

- `group_keys(base_model) -> list` — la chiave di ogni pezzo (sopra), allineata a `model.parts`.
- `check(models_by_tag, keys) -> bool` — le condizioni 1-4.
- `paint_table(model, keys, glb_groups) -> dict` — per ogni gruppo del GLB (nello stesso ordine delle mesh) la
  descrizione del materiale in quella vernice (sotto, "Dati di una vernice").
- `swatches(variant) -> [[r,g,b]]*3 | None` — i colori A, B, C della tavolozza in sRGB 0-255; `None` se la tavolozza
  manca o è tutta nera (la vernice di serie della Perseus ha 0,0,0).

### B. Server: `export.py`

- `merged_by_material(..., keys=None)`: con `keys` (lista allineata ai pezzi) il gruppo usa `keys[i]` al posto di
  `repr`/`_lite_key`. Senza `keys` tutto come oggi.
- `to_glb(..., keys=None)` e `_to_glb_animated(..., keys=None)` passano le chiavi (nel GLB animato i pezzi sono
  divisi per nodo prima: le chiavi seguono i pezzi).
- Ogni materiale del GLB porta il numero del suo gruppo come quarto campo del nome: `kind|nome|sid|g<numero>`.
  Il numero è l'indice della chiave nella lista delle chiavi distinte, quindi uguale per tutte le vernici. Il
  visualizzatore legge già solo i primi tre campi; i nodi restano `kind|nome|n`.
- Solo il GLB del visualizzatore (`lite=True`) usa le chiavi; gli export per l'utente restano come oggi.

### C. Server: `server.py`

- `/api/model/info` aggiunge per ogni vernice `colors` (da `swatches`, o `null`) e il campo `paintable` del modello.
- `/api/model/glb`: con un modello ridipingibile (`len(variant_list) >= 2`) passa le chiavi a `to_glb`. La chiave
  della cache su disco prende un numero di formato `"glb2"`, così i GLB vecchi non vengono riusati.
- Nuovo `GET /api/model/paint?path&variant&full&interior` → `{variant, paintable, groups: [...], shading: {...},
  materials: [...], stickers}`. `groups[g]` descrive il gruppo `g` (sotto). `shading` e `materials` sono quelli che
  oggi manda `/api/model/info` per quella vernice. Con `paintable = false` risponde solo `{paintable: false}`.
- Nuovo `GET /api/model/paint/texture?path&variant&full&interior&group` → l'immagine colorata della tavolozza per un
  gruppo decal con `stencil_colors` (oggi incorporata nel GLB da `material_textures`), PNG, cache su disco come le
  altre texture.

### Dati di una vernice (per gruppo)

```
{ "name": "kind|nome|sid|g12",   // nome del materiale come nel GLB per questa vernice
  "color": [r,g,b], "alpha": 1.0, "emissive": [r,g,b] | null, "metal": true|false,
  "glass": [r,g,b,alpha] | null,  // corpo del vetro (materials.glass_look), solo kind glass
  "texture": true|false }         // decal colorato dalla tavolozza: chiedere /api/model/paint/texture
```

Gli altri materiali (schermi, nascosti) non cambiano con la vernice e non sono nella tabella.

### D. Visualizzatore: `web/paint.js` (nuovo)

Classe `PaintSwap` con un compito solo: portare i materiali del modello in scena a un'altra vernice.

- `constructor({ renderer, gameLook, batches, root })`.
- `async apply(table)`: per ogni gruppo costruisce il materiale nuovo (con `gameLook.build` per i materiali con
  `shading`, altrimenti copia colore, emissivo, metallo; vetro: aggiorna colore del corpo e strato di tinta;
  decal con `texture`: carica `/api/model/paint/texture`). Compila gli shader nuovi (`compileShaders`) **prima**
  di assegnarli, poi in un solo fotogramma assegna i materiali alle mesh e ai batch (`batch.material`), libera i
  materiali vecchi e chiede di ridisegnare (ombre comprese).
- Una piccola memoria: le tabelle e i materiali costruiti delle ultime 3 vernici restano pronti, così tornare indietro
  (e il confronto con la vernice di serie) non ricostruisce niente.
- Le texture restano nella cache di `GameLook` (una sola istanza per modello, come oggi): una texture usata da due
  vernici si scarica una volta sola.

### E. Visualizzatore: `web/batching.js`

La chiave di un batch oggi contiene `o.material.uuid`. Con il nome del materiale che porta `g<numero>`, la chiave usa
il gruppo (`labelOf + gruppo`) al posto dell'uuid, così tutti i pezzi di un batch hanno lo stesso materiale in ogni
vernice e il cambio è `batch.material = nuovo`. Senza `g` nel nome resta l'uuid come oggi.

Effetto possibile: due gruppi diversi con lo stesso shading nella vernice attuale oggi finiscono in un batch solo,
domani in due. Da misurare (draw call e fps della Perseus prima/dopo).

### F. Visualizzatore: `web/app.js`

- Il cambio nel menu: se `info.paintable`, `PaintSwap.apply(await paint(tag))` e poi `afterPaint()`; altrimenti
  `loadModel(state.current, true)` come oggi.
- `afterPaint()` rifà quello che dipende dai materiali: `applyWireframe`, `applyVisibility` (gli interruttori dei
  materiali sono per nome, che non cambia), `applyResin` se attiva, `showMaterials`, riquadro decal (`stickers`),
  ombre. Non tocca camera, animazioni, posa, sezione, stanze, schermi.
- Se una richiesta arriva mentre un'altra è in corso, vince l'ultima (come `state.current !== item` oggi).
- Errori (rete, server): avviso con `toast` e ricarica completa come oggi, così l'utente vede comunque la vernice.
- `state.variant` è la vernice scelta nel menu; gli export e le segnalazioni usano quella.

### G. Menu e confronto

- `dropdown()` riceve per ogni opzione i colori (attributo `data-colors` sull'`<option>`) e disegna i 3 pallini
  prima del testo, sul pulsante e nella lista (`<span class="dots">` con tre `<i>`; tratteggiati senza colori).
  CSS come nell'anteprima: pallini da 11 px, distanza 3 px, bordino chiaro.
- Pulsante "Compare with stock paint" sotto il menu (solo se la vernice scelta non è quella di serie). Acceso:
  mostra la vernice di serie (`PaintSwap`, senza cambiare `state.variant` né il menu), testo
  "Showing stock paint · click to go back". Spento, o cambiando vernice o modello: torna alla scelta.
- Testi nuovi in `i18n` (`compareStock`, `showingStock`) con le traduzioni nelle 10 lingue.
- Con un modello non ridipingibile il confronto funziona lo stesso, ricaricando (più lento).

## Prove

Python (`tests/`):
- `group_keys` e `merged_by_material(keys=...)`: due vernici di un modello finto danno le stesse mesh nello stesso
  ordine; senza chiavi l'output è identico a oggi.
- `check`: falso se una vernice cambia `kind`, nome o `uv_scale` di un gruppo, o il numero di pezzi.
- `swatches`: tavolozza nera o assente → `None`.
- GLB: con chiavi, i nomi dei materiali hanno il quarto campo `g<n>` e due vernici danno GLB con la stessa geometria
  (stessi accessori di posizione, indici e UV).
- `/api/model/paint`: risposta per un modello vero se il p4k c'è (come le altre prove sul gioco, saltate senza p4k).

Visualizzatore, con un browser invisibile (Edge headless, come `tools/readme_media.py`), senza usare lo schermo
dell'utente: nuovo `tools/paint_check.py` che apre la Perseus con *Full ship* + *Interiors* e misura
- il tempo dal cambio di vernice al primo fotogramma nuovo (obiettivo sopra);
- che la scritta di caricamento non compaia;
- che posa, camera e sezione restino uguali;
- draw call e fps prima e dopo il lavoro;
- che il confronto con la vernice di serie vada e torni.

Le prove già presenti devono restare verdi.

## Rischi

- **Prestazioni della verifica** (tutte le vernici costruite): misurata, con il ripiego descritto sopra.
- **Più draw call**: misurate; se la Perseus perde fps in modo visibile, si ripiega su una chiave del batch che unisce
  i gruppi uguali in *tutte* le vernici (calcolata dal server e mandata nel nome come oggi `g`).
- **Cache su disco**: i GLB vecchi hanno un'altra struttura; la chiave `glb2` li esclude.
