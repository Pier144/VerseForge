# Vernici istantanee: progetto

Data: 18/11/2026 · Stato: disegno approvato dall'utente in chat, specifica rivista (3 giri di revisione, approvata dal
revisore), da rileggere dall'utente · Ramo: `vernici-istantanee`

## Scopo

Cambiare vernice (livrea) senza ricaricare il modello, come nel Paint Viewer di The Impound. Oggi il menu
"Variant / paint" chiama `loadModel(state.current, true)`: il server rifà il GLB, il visualizzatore lo riscarica e
rifà normali, materiali, batch e shader.

Misure di partenza sulla Perseus (18 vernici, cache calda, 18/11):
- solo scafo: 0,6-1,4 s a ogni cambio; con *Full ship* + *Interiors*: 3,4 s, e intanto la nave si sfoca sotto la
  scritta "Loading";
- server, prima volta che si vede una vernice: `/api/model/info` 0,8-1,1 s con *Full ship*, **5,1-6,6 s** con
  *Full ship* + *Interiors* (rifà tutti gli interni, vedi sotto);
- scena con *Full ship* + *Interiors*: 316 draw call, ~3,9 ms per fotogramma (pannello piccolo, GPU dell'utente).

Obiettivi, Perseus con *Full ship* + *Interiors*, game look acceso:
- da una vernice già vista a un'altra già vista: **meno di 0,3 s** dal clic al primo fotogramma con la nuova vernice;
- da una vernice mai vista: **meno di 1,5 s** (le texture grandi arrivano dopo, come oggi);
- nessuna schermata di caricamento, nessuno sfocato; camera, posa, sezione, stanze restano come sono;
- draw call e tempo per fotogramma non peggiorano più del 10 %.

Scelte fissate con l'utente:
- resta il menu a tendina di oggi, con **3 pallini di colore** (A, B, C della tavolozza) prima di ogni nome, anche
  sul pulsante chiuso; una vernice senza tavolozza ha **3 cerchi tratteggiati** (anteprima approvata:
  `docs/anteprime/menu-vernici.png`);
- sotto il menu un pulsante **"Compare with stock paint"**: acceso mostra la vernice di serie, un altro clic torna
  alla livrea scelta;
- la grafica del pannello resta quella di oggi.

Fuori da questo lavoro: shader nuovi delle vernici (strati, cangianti), ricerca nel menu, lista sempre aperta.
Trovato durante la revisione e lasciato a parte (difetto già esistente, da segnalare all'utente): il `with_variant`
esterno ricarica i materiali da `p.mtl_path` e perde i materiali di record che `load_full` aveva messo sui pezzi del
loadout (assembly.py:54, model.py:234).

## Parole

- **Vernice di serie**: la vernice dell'entità "semplice" del modello (`plain[:1]` in `variants.build`). Non sempre
  esiste: se il modello ha solo livree, la prima della lista è la prima in ordine alfabetico. `variants.build` segna
  la vera vernice di serie con `"stock": true`.
- **Vernice di riferimento**: la prima della lista (`variant_list(path)[0]`), quella che il server usa quando
  `variant` manca. È la vernice di serie quando questa esiste.
- **Modello a chiavi**: un modello con almeno 2 vernici, nel GLB del visualizzatore (`lite=True`). I suoi pezzi sono
  uniti con chiavi che non dipendono dalla vernice (sotto).
- **Vernice scambiabile**: una vernice di un modello a chiavi che ha superato la verifica (sotto) rispetto alla
  vernice di riferimento. Solo queste si cambiano senza ricaricare.

## Perché oggi serve ricaricare

`export.merged_by_material` unisce i pezzi con lo stesso materiale (chiave `repr(material)`, o `_lite_key` nel GLB
"lite"). Il materiale dipende dalla vernice (tavolozza e `.mtl` principale sostituito), quindi con un'altra vernice
cambiano i gruppi e quindi le mesh del GLB.

## Idea

### Chiave di gruppo indipendente dalla vernice

`model.with_variant` lascia un pezzo per pezzo, nello stesso ordine, e cambia solo `part.material`
(model.py:233-245): il `.mtl` principale viene sostituito da quello della vernice e ogni `.mtl` viene caricato con la
tavolozza della vernice. Due pezzi con lo stesso `mtl_path` dichiarato e lo stesso `mat_id` hanno quindi lo stesso
materiale in ogni vernice.

Chiave del pezzo `i` di un modello a chiavi: `(p.mtl_path, p.mat_id, repr(materiale del pezzo i nella vernice di
riferimento))`. Pezzi senza `mtl_path` o con `mat_id < 0`: `repr(material)`. Il **gruppo** `g` è l'indice della
chiave nella lista delle chiavi distinte, in ordine di prima comparsa: è lo stesso in tutte le vernici e non contiene
la stanza. L'unione delle mesh usa `(g, stanza)` per i pezzi solidi degli interni, come oggi usa
`(materiale, stanza)`; quindi un gruppo può dare più mesh nel GLB (stanze diverse, ossa diverse nel GLB animato), tutte
con lo stesso materiale.

`variant=None` nelle richieste vale la vernice di riferimento anche nelle chiavi delle cache di `get_model`, così la
vernice di riferimento non viene costruita due volte.

Nel GLB animato (`_to_glb_animated`) i pezzi vengono copiati con `replace()` prima di essere uniti: le chiavi si
abbinano ai pezzi per indice prima della copia.

### Decal stencil: stessa forma in tutte le vernici

Un MeshDecal con `%STENCIL_MAP` è `decal` solo se la tavolozza ha l'atlante `decal`, altrimenti `hidden`
(materials.py:186-194), e un `hidden` esce dal GLB senza UV. Perché il gruppo abbia la stessa forma in ogni vernice,
`materials` segna questi materiali con `stencil_decal = True` qualunque sia la tavolozza. Nel GLB di un modello a
chiavi i loro gruppi escono **sempre** così:
- `kind` `decal`, con le UV, `alphaMode` `BLEND`;
- con l'atlante nella vernice del GLB: come oggi (texture colorata incorporata, voce di shading e `sid`);
- senza atlante: nessuna texture, `sid` vuoto, colore base con **alpha 0**. Il visualizzatore, al caricamento, mette
  `material.visible = false` ai decal con opacità 0 (sul materiale, non sulla mesh: `applyVisibility` riscrive
  `o.visible`, app.js:558), così non compare la lastra nera di cui parla il commento in materials.py:187-188 e non
  costano un disegno; essendo trasparenti non entrano nei batch.

Nella tabella di una vernice questi gruppi hanno `visible` (atlante sì/no) e `texture`. La verifica considera
`hidden` e `decal` uguali per questi gruppi e li esclude dalla condizione 5 (sono sempre `BLEND`).

### Interni: costruiti una volta

Gli interni non dipendono dalla vernice dello scafo: `load_interior` aggiunge i pezzi delle stanze dopo i pezzi dello
scafo e li colora con `INTERIOR_PALETTE` (assembly.py:213-214, 262). Oggi però `get_model(..., interior=True)` li
ricostruisce per ogni vernice (5-6,6 s).

Nuovo comportamento di `State.get_model` con `interior=True` e una vernice diversa da quella di riferimento: prende il
modello con interni della vernice di riferimento e sostituisce solo i pezzi dello scafo
(`parts = variante_scafo.parts + rif_interni.parts[len(rif_scafo.parts):]`, `cache = {}`, il resto copiato). Se il
numero dei pezzi dello scafo non coincide, si ricade nel `load_interior` di oggi. Questo vale per tutto (info, GLB,
export, stampa): stessi pezzi di oggi, molto più veloce.

### Verifica di una vernice (rispetto alla vernice di riferimento)

Calcolata alla prima richiesta di quella vernice (`/api/model/glb` o `/api/model/paint`) e tenuta in memoria per
(modello, full, interior, vernice). Le condizioni 1, 2, 4, 5 guardano i pezzi dello scafo (o della nave completa): i
pezzi degli interni sono uguali per costruzione; la 3 guarda tutti i pezzi del modello chiesto, interni compresi.
Una vernice è scambiabile se:
1. ha lo stesso numero di pezzi, con lo stesso `node` e lo stesso numero di facce, nello stesso ordine;
2. ogni gruppo ha lo stesso `kind` (con l'eccezione dei decal stencil) e lo stesso nome di materiale: il nome della
   mesh nel GLB è `kind|nome|n` e lo usano batch, interruttori dei materiali, decal, schermi, stanze;
3. tutti i pezzi di un gruppo hanno lo stesso materiale anche in questa vernice, compresi i pezzi degli interni che
   finissero nello stesso gruppo di pezzi dello scafo (loro restano con `INTERIOR_PALETTE`);
4. ogni gruppo ha la stessa scala delle UV (`uv_scale` di `materials.shading` e di `material_textures`), perché il
   GLB la moltiplica dentro le UV;
5. ogni gruppo ha la stessa trasparenza **finale nel visualizzatore**, perché batch (batching.js:31) e ombre
   (app.js:741) dipendono da `material.transparent`. Una funzione del server `see_through(mat)` la ricava come il
   visualizzatore: `alphaMode` del GLB (`OPAQUE`/`MASK`/`BLEND`); per i decal anche `opacity < 1` senza emissivo
   (gamelook.js:418) e `pom` (sempre trasparente, gamelook.js:314). Si confronta `(alphaMode, see_through, pom)`.

Il costo è un `with_variant` dello scafo o della nave completa: 0,8-1,1 s sulla Perseus con *Full ship*, già oggi
pagato a ogni cambio. Non si costruiscono mai tutte le vernici insieme.

I gruppi entrano nel GLB **solo per le vernici che superano la verifica**: `merged_by_material` dà a ogni mesh il
materiale del primo pezzo (export.py:85), quindi con una vernice che non la supera i gruppi della vernice di
riferimento darebbero materiali sbagliati. Per quelle il GLB è quello di oggi e il cambio ricarica.

## Pezzi

### A. Server: `sc_explorer/paints.py` (nuovo)

Un modulo con un compito solo: come si raggruppano i pezzi e com'è fatto ogni gruppo in una vernice.

- `group_keys(ref_model) -> (keys, groups)`: `keys[i]` è la chiave del pezzo `i`, `groups[i]` il numero del suo
  gruppo.
- `check(ref_model, model, groups) -> bool`: le condizioni 1-5; `ref_model` e `model` sono i modelli della vernice
  di riferimento e di quella chiesta con lo stesso `full` e `interior`.
- `paint_table(model, groups) -> list`: una voce per gruppo, indice = numero del gruppo, con i dati del materiale in
  quella vernice (sotto). I gruppi che stanno solo negli interni hanno `null` (non cambiano).
- `swatches(palette) -> [[r,g,b]]*3 | None`: i colori A, B, C in sRGB 0-255; `None` se la tavolozza manca o è tutta
  nera (la vernice di serie della Perseus ha 0,0,0).

Si prova da solo, con modelli finti.

### B. Server: `export.py` e `materials.py`

- `Material.stencil_decal` (nuovo campo, vedi sopra).
- `merged_by_material(..., groups=None)`: con `groups` (lista allineata ai pezzi) la chiave di unione è il gruppo
  (più la stanza come oggi), al posto di `repr`/`_lite_key`. Senza `groups` tutto come oggi.
- `to_glb(..., groups=None)` e `_to_glb_animated(..., groups=None)` passano i gruppi ai pezzi.
- In un GLB a chiavi ogni materiale porta il gruppo nel nome, come campo `g<numero>`:
  - materiali PBR: `kind|nome|sid|g<numero>` (quarto campo; `GameLook.apply` legge il `sid` dal terzo, come oggi);
  - schermi: il campo va **prima** del suffisso, `screen|nome|g<numero>|rtt`, `screen|nome|g<numero>|holo` o
    `screen|nome|g<numero>`, perché app.js:772 e 778 riconoscono monitor e HUD con `endsWith("|rtt")` /
    `endsWith("|holo")`.
  Una funzione sola nel visualizzatore (`groupOf(material)`, il campo che comincia per `g` seguito da cifre) lo legge.
  I nodi restano `kind|nome|n`. I gruppi decal stencil escono come detto sopra.
- Gli export per l'utente non cambiano.

### C. Server: `server.py`, `variants.py`, `diskcache.py`

- `variants.build` aggiunge `"stock": true` alla vernice dell'entità semplice; il nome del file di cache
  (`variants_v5_` in server.py:137 e 143) passa a `variants_v6_`.
- `/api/model/info`: ogni vernice ha anche `colors` (da `swatches`, o `null`) e `stock`; il modello ha `keyed`
  (modello a chiavi).
- `/api/model/glb`: per un modello a chiavi con `lite=True` calcola i gruppi sul modello della vernice di riferimento
  (stesso `full`, `interior`); se la vernice chiesta supera la verifica li passa a `to_glb`, altrimenti GLB di oggi.
  La verifica fatta qui resta in memoria e serve anche a `/api/model/paint`.
- `/api/model/info` dice anche `keyed_glb`: se il GLB di questa vernice è a gruppi (il visualizzatore prova lo
  scambio solo partendo da un GLB a gruppi).
- `diskcache.FORMAT` passa da 4 a 5: i GLB e le info vecchie sulla cache non vengono riusati. Svuota tutta la
  cartella, texture comprese (diskcache.py:38-41): la prima apertura dopo l'aggiornamento è più lenta, una volta.
- Nuovo `GET /api/model/paint?path&variant&full&interior` →
  `{variant, swappable, groups: [...], shading: {...}, materials: [...], stickers, screen}`.
  `groups[g]` sono i dati del gruppo `g` (o `null`), `shading` le descrizioni del game look usate da quei gruppi,
  `materials` la lista dei materiali per il pannello, `screen` come in `/api/model/info` (colore degli schermi).
  Con `swappable = false` risponde solo `{variant, swappable: false}`. Errori: 404 come le altre rotte.
- Nuovo `GET /api/model/paint/texture?path&variant&full&group&map=base|normal` → l'immagine che `_glb_mesh`
  incorporerebbe nel GLB per quel gruppo in quella vernice (`material_textures`: per esempio il decal stencil colorato
  dalla tavolozza), PNG o JPEG come nel GLB, cache su disco come le altre texture; 404 se il gruppo non ne ha. Non
  serve `interior`: i pezzi dello scafo vengono prima degli interni, quindi i numeri dei gruppi dello scafo sono gli
  stessi con e senza interni.

### Dati di un gruppo in una vernice

La voce di un gruppo è **il materiale glTF che `_glb_mesh` scriverebbe per quel gruppo in quella vernice**, in forma
JSON, più due campi. Così il visualizzatore rifà lo stesso materiale che GLTFLoader avrebbe creato dal GLB e lo passa a
`GameLook.build` come `old`, esattamente come oggi:

```
{ "name": "kind|nome|sid|g12",     // nome del materiale (schermi: con il suffisso, vedi B)
  "color": [r,g,b], "alpha": 1.0,   // baseColorFactor (lineare, come nel GLB)
  "metallic": 0.3, "roughness": 0.6,
  "emissive": [r,g,b] | null,       // emissiveFactor
  "alpha_mode": "OPAQUE" | "MASK" | "BLEND", "alpha_cutoff": 0.5 | null,
  "texture": true | false,          // baseColorTexture incorporata (decal stencil colorato)
  "normal_texture": true | false,   // normalTexture incorporata
  "visible": true }                 // false: decal stencil senza atlante in questa vernice (alpha 0)
```

Da qui il materiale finto ha `transparent` (`BLEND`), `alphaTest` (`MASK`), `depthWrite`, `opacity`, `map`,
`normalMap`, `emissive` come li avrebbe dati GLTFLoader. Le due immagini incorporate (quelle di
`material_textures`, cioè dove oggi `_glb_mesh` non lascia il lavoro al game look) si chiedono a
`/api/model/paint/texture?...&group&map=base|normal`. Per gli schermi l'emissiveMap è l'immagine fissa
`screen_image()`, che il visualizzatore riusa dal materiale già in scena.

Vetri: `color`/`alpha` sono il corpo di `materials.glass_look`; il visualizzatore rifà lo strato di `glassLook`.
Schermi: nella tabella perché il loro emissivo viene da `decal_colors[0]` della tavolozza (materials.py:229-232).
I gruppi `hidden` (proxy) restano fuori.

### D. Visualizzatore: `web/paint.js` (nuovo)

Classe `PaintSwap` con un compito solo: portare i materiali del modello in scena a un'altra vernice.

- `constructor({ renderer, gameLook, batches, root, compile, section })`. `compile(root, section)` è il
  `compileShaders` di `app.js`; `section` è `info.interior` (con gli interni servono anche le varianti con il piano
  di taglio).
- `async apply(paint)` (risposta di `/api/model/paint`):
  1. per ogni gruppo costruisce il materiale: con `shading` usa `gameLook.build(sh, old, kind, opts, geometry, slots)`
     dove `old` è un materiale finto fatto dai dati del gruppo (colore, alpha, emissivo, mappa del decal stencil
     se `texture`); senza `shading` copia colore, emissivo, metallo; vetro: colore del corpo e strato di tinta di
     `glassLook`; `visible: false` → materiale invisibile;
  2. compila gli shader nuovi prima di usarli: una scena di prova con una mesh per materiale (geometria di una mesh
     del gruppo) e un piccolo `BatchedMesh` per i materiali dei batch, così si compila anche la variante
     `USE_BATCHING`; poi `compile(scena di prova)`;
  3. in un solo fotogramma assegna: per ogni mesh del gruppo e per ogni batch del gruppo il materiale nuovo va in
     `userData.gameMaterial` quando c'è (resina accesa: `applyResin` ha spostato lì il materiale di gioco di mesh **e**
     batch, app.js:630-639), altrimenti in `material`; aggiorna `batch.hook`; rimette `o.onBeforeRender` dei decal POM;
     `material.visible` dei decal stencil; ombre da rifare. I gruppi degli schermi li salta: li assegna `afterPaint`
     (sotto), dopo aver spento le classi degli schermi;
  4. chiama `gameLook.upgrade(materiali, slots)` per le texture grandi.
- Memoria delle ultime 3 vernici (dati e materiali pronti): tornare indietro, e il confronto, non ricostruiscono
  niente. All'inizio contiene già la vernice caricata (materiali presi dalle mesh in scena, per gruppo). Un materiale
  si libera solo quando la sua vernice esce da questa memoria o cambia il modello.
- `dispose()`: annulla uno scambio in corso e libera i materiali in memoria tranne quelli in scena (li libera
  `loadModel` come oggi). `loadModel` lo chiama prima di caricare un altro modello.
- Le texture restano nella cache di `GameLook` (una sola istanza per modello, come oggi).
- Se arriva un'altra richiesta mentre una è in corso, vince l'ultima.

### E. Visualizzatore: `web/batching.js`

La chiave di un batch oggi contiene `o.material.uuid`. Se il nome del materiale porta `g<numero>`, la chiave usa il
gruppo al posto dell'uuid: tutti i pezzi di un batch hanno lo stesso materiale in ogni vernice e il cambio è
`batch.material = nuovo`. Senza `g` resta l'uuid. `Batches` espone `byGroup(g)` per trovare i batch di un gruppo.

### F. Visualizzatore: `web/app.js`

- Il cambio vernice è istantaneo quando `info.keyed_glb && state.tex && state.look` (il GLB senza game look non ha
  gruppi) e `/api/model/paint` dice `swappable`. Altrimenti `loadModel(state.current, true)` come oggi.
- `afterPaint(paint)` rifà quello che dipende dai materiali: `applyWireframe`, `applyVisibility` (gli interruttori
  sono per nome, che non cambia), `applyResin` se attiva, `showMaterials`, riquadro decal (`stickers`), ombre.
  Schermi, in quest'ordine: `dispose()` di `AmmoScreen` / `ShipScreens`, poi il nuovo materiale dello schermo dalla
  tabella, poi li ricrea col nuovo `screen`. Oggi le due classi sostituiscono il materiale della mesh con un clone
  (screen.js:42 e 204) e `dispose()` libera solo la texture: si aggiunge che ogni classe ricorda per ogni mesh il
  materiale di partenza e il proprio clone, e `dispose()` rimette il primo e libera il secondo. Non tocca camera, animazioni, posa, sezione, stanze.
- Errori (rete, server, materiale): `toast` e ricarica completa come oggi.
- `state.variant` resta la vernice scelta nel menu; export, stampa, decal sheet e segnalazioni usano quella.

### G. Menu e confronto

- `dropdown()` legge i colori da `data-colors` sull'`<option>` e disegna 3 pallini prima del testo, sul pulsante e
  nella lista (`<span class="dots">` con tre `<i>`, costruiti con metodi DOM; tratteggiati senza colori). CSS come
  nell'anteprima: 11 px, distanza 3 px, bordino chiaro.
- Pulsante "Compare with stock paint" sotto il menu, solo se il modello ha una vernice `stock` e quella scelta è
  un'altra. Acceso: mostra la vernice di serie senza cambiare `state.variant` né il menu; testo
  "Showing stock paint · click to go back". Spento, o cambiando vernice o modello: torna alla scelta.
- Se la vernice di serie non è scambiabile, il confronto ricarica: `loadModel(item, true, { paint: tag })` chiede
  quella vernice al server ma non tocca `state.variant` né il menu (oggi `loadModel` copia `info.variant` in
  `state.variant` e ridisegna il menu: con `paint` lo salta).
- Testi nuovi in `i18n` (`compareStock`, `showingStock`), tradotti nelle 10 lingue.

## Prove

Python (`tests/`), con modelli finti:
- `group_keys` e `merged_by_material(groups=...)`: due vernici danno le stesse mesh nello stesso ordine; senza
  gruppi l'output è identico a oggi.
- `check`: falso se una vernice cambia `kind` (tranne decal stencil), nome, `uv_scale`, trasparenza o numero di pezzi.
- decal stencil: con e senza atlante esce come `decal` con UV; `paint_table` dice `visible` giusto.
- `swatches`: tavolozza nera o assente → `None`.
- GLB a chiavi: nomi dei materiali con `g<n>`; due vernici danno la stessa geometria (stessi accessori di posizione,
  indici e UV).
- interni: il modello con interni di una vernice ha gli stessi pezzi di `load_interior` (stessi vertici, stanze),
  con i materiali dello scafo della vernice.
- `variants`: `stock` solo sull'entità semplice.

Sul gioco (saltate senza p4k, come le altre): `/api/model/paint` sulla Perseus, tutte le 18 vernici scambiabili.

Visualizzatore, con Edge headless (come `tools/readme_media.py`), senza usare lo schermo dell'utente: nuovo
`tools/paint_check.py` che apre la Perseus con *Full ship* + *Interiors* e misura tempi del cambio (vista e non
vista), assenza della scritta di caricamento, posa/camera/sezione uguali, draw call e ms per fotogramma prima e dopo,
confronto con la vernice di serie avanti e indietro, resina accesa durante il cambio.

Le prove già presenti restano verdi.

## Rischi

- **Più draw call**: la chiave nuova toglie anche l'unione "lite" di decal, vetri e pezzi sotto nodi animati, che i
  batch non recuperano. Misurate con `paint_check.py`; se si va oltre il 10 %, la chiave diventa
  `repr(materiale nella vernice di riferimento)` per i pezzi che non vengono dal `.mtl` principale sostituito dalle
  livree: due materiali uguali, dallo stesso tipo di file e con la stessa tavolozza, restano quasi sempre uguali in
  ogni vernice, e la condizione 3 della verifica prende i casi rari in cui non succede (allora si ricarica).
- **Interni condivisi**: se un giorno gli interni dipendessero dalla vernice, il controllo sul numero dei pezzi non
  basterebbe. Oggi `INTERIOR_PALETTE` è fissa: una prova lo tiene d'occhio.
