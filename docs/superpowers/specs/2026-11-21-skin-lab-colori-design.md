# Skin Lab, tappa 1 (colori e finiture): progetto

Data: 21/11/2026 · Stato: disegno approvato dall'utente in chat, specifica rivista (1 giro, 8 punti corretti), da rileggere dall'utente · Ramo: `skin-lab` (da creare
all'inizio dello sviluppo)

## Scopo

Dare all'utente un creatore di skin per navi, armi e armature: parte da una vernice del gioco, cambia colori e
finiture, salva il risultato e lo ritrova tra le vernici. Nel gioco vero una skin non si può caricare: vive in
VerseForge e in ciò che VerseForge esporta.

Il creatore completo è diviso in cinque tappe, ognuna con specifica, piano e versione pubblicabile:

1. **Skin Lab con colori e finiture** (questo documento).
2. Motivi: maschere mimetiche del gioco, PNG dell'utente, colori, scala, opacità.
3. Decal: catalogo del gioco, PNG dell'utente, testo scritto nell'app, al posto dei decal di serie (si sostituisce
   l'immagine dove il gioco ha già un decal; non si piazzano liberamente).
4. Export e condivisione: GLB/OBJ col mimetico cotto nelle texture, immagini.
5. Stampa e pittura: scheda colori in PDF, foglio decal coi loghi dell'utente.

Fuori da tutte le tappe: pittura libera col pennello, galleria online (il formato del file la deve permettere in
seguito senza essere rifatto).

## Scelte fissate con l'utente

- Profondità: colori, finiture, motivi e decal; niente pittura libera.
- Usi: libreria, export 3D e immagini, condivisione, aiuto per stampa e pittura.
- Interfaccia: una modalità a parte, "Skin Lab", non un riquadro nel menu vernici.
- Condivisione: solo file ora, galleria forse dopo.
- Sorgenti per motivi e decal (tappe 2-3): maschere del gioco, decal del gioco, immagini dell'utente, testo.
- Architettura mista: il file della skin sul server è l'unica fonte; il visualizzatore ricolora dal vivo mentre si
  trascina e il server conferma al rilascio.

## Com'è oggi (verificato il 21/11)

- Navi, armi e armature usano la stessa strada: `variants.build` legge ogni entità con geometria, `get_model` /
  `with_variant` valgono per tutte.
- Una vernice è `{tag, label, material, palette, stock}` (`variants.py`). La tavolozza ha `A`, `B`, `C`, `glass`,
  `spec{A,B,C}`, `gloss{A,B,C}`, più `decal` e `decal_colors` per il mimetico.
- I colori sono calcolati dal server: `materials.py` moltiplica la tavolozza (gamma 2) dentro albedo, spec e gloss;
  `gamelook.js` li imposta una volta alla costruzione del materiale. Dal vivo oggi cambiano solo lucidità e i
  parametri della maschera mimetica (uniform).
- `PaintSwap` (`web/paint.js`) sostituisce i materiali di un "gruppo di vernice" coi dati di `/api/model/paint`.
  I modelli con meno di 2 vernici non hanno i gruppi (`server.py`, controllo "keyed").
- `/api/export` riceve `variant`: GLB e OBJ portano il colore della vernice scelta, non il mimetico né la lucidità.
- Dati dell'utente: impostazioni in `%APPDATA%\VerseForge\config.json`, export in `Documenti\VerseForge`. Non c'è
  una cartella di libreria.

## Il file della skin

- Estensione `.vfskin`: uno zip con `skin.json` e una cartella `images/` (vuota in questa tappa).
- Libreria: cartella fissa `paths.documents_dir()/Skins` (`Documenti\VerseForge\Skins`), un file per skin. Non
  segue `export_dir`: cambiare la cartella degli export non fa sparire la libreria. Condividere = copiare il file.
- `skin.json`:

```json
{
  "format": 1,
  "id": "8 caratteri esadecimali, generati al primo salvataggio",
  "name": "Night Raid",
  "author": "",
  "app": "1.17.0",
  "created": "2026-11-21T10:00:00Z",
  "modified": "2026-11-21T10:00:00Z",
  "target": {"model": "percorso del modello nel p4k", "label": "Perseus"},
  "base": {"material": "percorso del .mtl della livrea, vuoto per quella di serie",
           "palette": "nome della tavolozza del gioco", "label": "Black Magic"},
  "palette": {
    "A": [r, g, b], "B": [r, g, b], "C": [r, g, b], "glass": [r, g, b],
    "finish": {"A": {"preset": "gloss", "gloss": 220}, "B": {...}, "C": {...}}
  },
  "pattern": null,
  "decals": {}
}
```

- In `palette` stanno solo le voci cambiate; ciò che manca viene dalla vernice di partenza. Colori sRGB 0-255,
  come nelle tavolozze del gioco. I colori sono quelli scelti dall'utente: riflesso e albedo effettivi li ricava
  `skins.apply` dal preset (vedi Finiture), non stanno nel file.
- `base` non è il tag della vernice: i tag sono indici di un elenco ordinato per nome e per lingua, e cambiano con
  una patch o cambiando lingua. La vernice di partenza si ritrova per percorso del materiale + nome della
  tavolozza; `label` serve solo a mostrarla se non si trova più.
- `pattern` e `decals` sono riservati alle tappe 2 e 3. Un file con `format` maggiore di quello conosciuto viene
  rifiutato; campi sconosciuti dentro un formato conosciuto vengono conservati al salvataggio.
- Una skin è legata a un modello. Portarla su un altro modello resta fuori da questa tappa.

### Finiture

Per ogni colore A, B, C un preset. Dal colore scelto `c` e dal preset, `skins.apply` scrive nella tavolozza
effettiva tre valori: tinta (albedo), riflesso (`spec`), lucidità (`gloss`).

| Preset | Tinta | Riflesso | Lucidità (0-255) |
|---|---|---|---|
| Base (di serie) | `c` | quello della vernice di partenza | quella della vernice di partenza |
| Gloss | `c` | grigio dielettrico `D` | alta |
| Satin | `c` | `D` | media |
| Matte | `c` | `D` | bassa |
| Metal | `c × k` (quasi nero) | `c` | alta |

Metal segue il modello del gioco: albedo scura e F0 colorato. `D`, `k` e i tre livelli di lucidità sono costanti
di `skins.py`, tarate nel piano sulle vernici del gioco (riferimento: le icone `PaintColorLogos`). Sotto il preset
c'è un cursore fine: cambia solo `gloss` e lascia il preset.

Sotto una skin la tavolozza effettiva ha **sempre** riflesso e lucidità per A, B e C: se la vernice di partenza non
li ha e il preset è Base, valgono quelli di Satin. Conseguenza voluta: i materiali con uno slot non usano mai la
mappa del riflesso mentre una skin è applicata, quindi cambiare finitura dal vivo non cambia il programma dello
shader.

## Server

Nuovo modulo `sc_explorer/skins.py`, senza dipendenze dal resto oltre a `paths`:

- `library_dir()`, `list_skins(model=None)`, `load(id)`, `save(skin)`, `delete(id)`, `import_file(path)`,
  `export_file(id, dest)`;
- `validate(data)`: tipi, intervalli dei colori, `format`, lunghezza del nome; errori con un codice e un testo;
- `apply(variant, skin)`: restituisce una copia della vernice di partenza con la tavolozza sostituita. È una
  funzione pura, la sola che conosce il rapporto tra skin e tavolozza.

Integrazione:

- **Un solo punto di risoluzione.** Oggi un tag sconosciuto diventa in silenzio la vernice di serie (`tag_of`,
  `get_model`). Si aggiunge in `server.py` una funzione `resolve_variant(model, tag)` usata da tutti i punti che
  ricevono `variant` (`get_model`, `with_variant`, `/api/model/info`, `/api/model/paint`,
  `/api/model/paint/texture`, `/api/export`): per i tag `skin:...` restituisce `skins.apply(base, skin)`, per gli
  altri la vernice del gioco. Un tag `skin:` che non si risolve è un errore 404, non la vernice di serie. Così
  l'export porta i colori della skin senza codice suo.
- **Due tag.** `skin:<id>` è una skin salvata. `skin:draft` è la bozza in memoria del Skin Lab (vedi
  Visualizzatore): una sola, mai su disco.
- **Cache.** Le voci per vernice (modelli in memoria, `paint_ok`, cache su disco di GLB e texture di vernice) usano
  come chiave `skin:<id>:<modified>`; al salvataggio e alla cancellazione di una skin le sue voci vecchie si
  buttano. La bozza non va mai nella cache su disco e ha una sola voce in memoria, sostituita a ogni invio.
- **Elenco.** L'elenco delle skin non entra nella risposta di `/api/model/info` messa in cache: viene aggiunto dopo
  la lettura della cache, a ogni richiesta, dopo le vernici del gioco e con `custom: true`.
- **`tint` nel `shading`.** Per ogni materiale che dipende dalla tavolozza:
  `{slot, albedo_base, color_base, layer_spec, layer_gloss, stencil_slots}`.
  - `slot`: `A`, `B` o `C` (uno strato e uno slot per materiale: è il caso di `materials.py` oggi).
  - `albedo_base` e `color_base`: i due valori che il server moltiplica per la tinta (gamma 2) per ottenere
    `albedo` e `color` (i decal usano `color`, gli altri `albedo`).
  - Riflesso e lucidità **non** si moltiplicano: sono quelli della tavolozza, che sotto una skin ci sono sempre;
    `layer_spec` e `layer_gloss` servono solo a mostrare il valore di serie.
  - `stencil_slots`: per gli scafi mimetici, che usano A, B e C insieme come colori della maschera
    (`gameStencilColors`), quali slot vanno in quali canali.
  - Il vetro non passa da `shading` (oggi restituisce None) e usa la curva sRGB, non gamma 2: resta sulla strada
    `glassTint` di `paint.js`.
- **Gruppi di vernice.** Entrando nel Skin Lab con un modello che non li ha (meno di 2 vernici), il modello viene
  ricaricato **una volta** con i gruppi; la chiave del GLB nella cache su disco comprende questo stato, altrimenti
  verrebbe servito il GLB vecchio senza gruppi. Per i modelli che li hanno già non c'è ricaricamento.
- **Modelli senza vernici.** La vernice di partenza è quella di serie con la tavolozza predefinita dell'entità. Se
  nessun materiale ha uno slot, il Skin Lab si apre con il messaggio "this model has no paintable parts" e i
  comandi dei colori spenti.
- **Vernice di partenza non scambiabile** (`paints.check` fallisce, `swappable: false`): la conferma del server
  avviene ricaricando il modello con `variant=skin:draft` invece che con lo scambio; l'anteprima dal vivo resta.

`skins.py` riceve la cartella della libreria come argomento (di serie quella di `paths`), così le prove usano una
cartella temporanea e il modulo non dipende dallo stato del server.

Chiamate nuove:

| Chiamata | Cosa fa |
|---|---|
| `GET /api/skins?model=` | elenco delle skin di un modello (o di tutte) |
| `POST /api/skins` | crea o aggiorna una skin, risponde con l'id |
| `DELETE /api/skins/{id}` | la cancella (il file va nel cestino del sistema se possibile) |
| `POST /api/skins/import` | importa un file `.vfskin` scelto dall'utente |
| `POST /api/skins/{id}/export` | salva una copia dove l'utente sceglie |
| `POST /api/skins/draft` | riceve la skin in lavorazione e la tiene in memoria come `skin:draft` |

## Visualizzatore

Nuovo file `web/skinlab.js` con tutta la modalità; `app.js` riceve solo l'entrata e l'uscita.

- **Entrata**: pulsante "Skin Lab" nella barra e voce "+ New skin" in fondo ai tasselli delle vernici. Attivo solo
  con un modello caricato.
- **Scena**: lo stesso modello già caricato (ricaricato una volta solo se non ha i gruppi di vernice), sfondo
  studio, posa e inquadratura conservate. All'entrata la skin, o la vernice di partenza con riflesso e lucidità
  completi, viene applicata dal server con lo scambio normale: è qui che i materiali vengono ricostruiti; dopo,
  `retint` cambia solo valori.
  All'uscita tornano sfondo e vernice di prima, o la skin appena salvata se l'utente lo sceglie.
- **Sinistra, strumenti**: nome; vernice di partenza; tre righe colore A/B/C e una per il vetro, ciascuna con
  selettore, codice esadecimale e campioni presi dalle vernici del gioco di quel modello; finitura per A, B, C.- **Destra, libreria**: le skin dell'utente per quel modello, poi le vernici del gioco come punto di partenza.
- **Comandi**: Save, Save as copy, Delete, Import, Export, Compare with original, Exit. Uscendo con modifiche non
  salvate si chiede conferma.
- **Dal vivo**: `gamelook.js` espone `retint(palette)`, che percorre i materiali vivi di `PaintSwap.live()`
  (compreso `userData.gameMaterial` dei pezzi fusi dal batching) e per quelli con `tint` ricalcola il colore
  (base × tinta, gamma 2), imposta riflesso e lucidità della tavolozza e i colori della maschera mimetica; il vetro
  passa da `glassTint`.
- **Conferma**: 300 ms dopo l'ultimo ritocco il visualizzatore manda la skin a `POST /api/skins/draft` e chiede a
  `/api/model/paint?variant=skin:draft` i materiali definitivi, che sostituiscono quelli ricolorati. Obiettivo:
  meno di 1 s sulla Perseus con *Full ship* + *Interiors*. La bozza è solo in memoria: **il file in libreria cambia
  soltanto con Save**, e la conferma all'uscita si basa sulla differenza tra bozza e file.
- Regola esistente da rispettare: mai aggiungere o togliere luci né cambiare le define dei materiali dopo la
  compilazione. `retint` cambia solo valori.
- **Vista normale**: le skin salvate compaiono tra i tasselli delle vernici con un segno che le distingue, e si
  scambiano come le altre.
- Testi nelle 11 lingue (`i18n`).

Prima del codice dell'interfaccia: un'anteprima della schermata in `docs/anteprime/skin-lab/`, da far approvare
all'utente. Deve tenere l'aspetto attuale dell'app, senza grafica "da IA".

## Errori

| Caso | Comportamento |
|---|---|
| File non zip, senza `skin.json`, o JSON non valido | rifiutato, messaggio con il motivo |
| `format` più nuovo | rifiutato: "made with a newer VerseForge" |
| Modello della skin assente dal gioco installato | resta in libreria, segnata come non apribile |
| Vernice di partenza sparita | si usa quella di serie, con un avviso |
| Nome già usato nella libreria | si aggiunge un numero |
| Cartella della libreria non scrivibile | messaggio con il percorso; la skin resta aperta nel Lab |
| Conferma del server fallita dopo il ritocco dal vivo | resta l'anteprima dal vivo, avviso discreto, si riprova al ritocco dopo |

## Prove

- `tests/test_skins.py`: formato, lettura e scrittura, file rotti, `validate`, `apply`, nomi doppi, campi
  sconosciuti conservati.
- `tests/test_skins_api.py`: le chiamate col TestClient e una libreria in cartella temporanea.
- Una skin senza modifiche dà gli stessi materiali della sua vernice di partenza.
- `tint` nel `shading`: per ogni materiale, `albedo_base` e `color_base` × tinta coincidono con `albedo` e `color`
  calcolati dal server; riflesso e lucidità coincidono con quelli della tavolozza effettiva.
- `skins.apply`: i cinque preset, la tavolozza effettiva sempre completa, la vernice di partenza ritrovata per
  materiale + tavolozza anche se l'ordine dell'elenco cambia.
- Un tag `skin:` inesistente dà 404; salvare o cancellare una skin aggiorna subito l'elenco in `/api/model/info`.
- `tools/skin_check.py` (sul modello di `paint_check.py`): confronto dei pixel tra anteprima dal vivo e conferma
  del server; tempo di un ritocco; draw call e tempo per fotogramma invariati rispetto a prima.
- Prove sul gioco vero (saltate senza `Data.p4k`): una nave, un'arma, un'armatura.
- Export: un GLB esportato con una skin ha i colori della skin.

## Note di realizzazione (21/11/2026, ramo `skin-lab`)

Cose scoperte e decise durante lo sviluppo, che cambiano o precisano quanto sopra.

- **Colori delle parti.** Le armature e molte parti delle armi non prendono i colori dalla tavolozza A/B/C: ogni
  materiale ha una tinta propria (`TintColor` dello strato, `PaletteTint` 0). Con la sola tavolozza lo Skin Lab su
  molte armature non avrebbe cambiato nulla. La skin ha quindi anche `materials`: `{nome del materiale: {color,
  finish}}`. Il server lo passa dentro la tavolozza (`palette["materials"]`) e `materials._material` sostituisce la
  tinta dello strato. Nel pannello sono la sezione "Part colours", ordinata per superficie (le prime 10, poi "Show
  all"). Limite noto: il visualizzatore disegna solo il primo strato dei materiali a più strati, quindi si
  ricolora quello.
- **Voci della tavolozza vuote.** Una voce che né la vernice né la skin colorano resta vuota: i suoi materiali
  tengono il grigio scuro che il gioco dà loro. La regola "riflesso e lucidità sempre presenti" vale per le voci
  che hanno un colore.
- **Finiture tarate sul gioco.** Su 13.761 voci di tavolozza del gioco: riflesso 59,59,59 nel 60 % dei casi,
  lucidità mediana 218 (5 % sotto 121). Valori scelti: riflesso dielettrico 59; Gloss 250, Satin 200, Matte 120,
  Metal 235 con tinta × 0,2.
- **`tint` nel `shading`** è `{slot, base, own, spec_base}`: `slot` è `A`/`B`/`C` o `m:<materiale>`; `base` × colore
  (gamma 2) dà l'albedo; `own` è il colore proprio in sRGB; `spec_base` c'è per gli strati metallici, dove il colore
  tinge il riflesso. La maschera mimetica che usa la tavolozza porta `stencil.tinted`.
- **Punto unico di risoluzione**: `State.variant(path, tag)` in `server.py`. Le voci con tag `skin:` non vanno mai
  nella cache su disco. L'elenco delle skin si chiede a `/api/skins?path=` e il visualizzatore lo unisce ai tasselli.
- **Gruppi di vernice su richiesta**: parametro `keyed=true` su `/api/model/info`, `/api/model/glb`,
  `/api/model/paint`, mandato quando il modello ha skin o si è nello Skin Lab.
- **Chiamate in più**: `GET /api/skins/base` (tavolozza completa della vernice di partenza, voci usate, materiali
  con colore proprio, costanti delle finiture), `GET /api/skins/{id}`.
- **Import ed Export**: Import con il selettore di file della pagina; Export copia il file nella cartella degli
  export. Delete sposta il file nella sottocartella `Deleted` della libreria (recuperabile).
- **Vetro e decal** non si ricolorano dal vivo: seguono la conferma del server (circa mezzo secondo).
- **Anteprima da approvare prima del codice**: non fatta; l'utente ha dato piena autonomia, la schermata è stata
  costruita direttamente. Schermate delle prove in `docs/anteprime/skin-lab/`.
- `diskcache.FORMAT` 13; `start.py --skins-dir` per le prove.

Misure nell'anteprima (21/11, finestra 1440 × 860):

| Modello | Ricolorazione dal vivo | Conferma del server | Pixel diversi tra le due |
|---|---|---|---|
| Gladius, nave completa | 0,8 ms | 0,37 s | 0 |
| Perseus, nave completa + interni (15.129 parti) | 0,8 ms | 0,58-0,60 s | 0 |
| Elmo Strata (colori delle parti) | meno di 1 ms | meno di 0,5 s | 0 |
| Granata con una sola vernice (ricaricata coi gruppi all'entrata) | meno di 1 ms | meno di 0,5 s | 0 |

**Anticipo della tappa 3 (decal), fatto il 21/11 su richiesta dell'utente.** `sc_explorer/skindecals.py`: le navi
hanno due tipi di riquadro che il gioco riempie al volo e che il visualizzatore non disegnava: le targhe del nome
(MeshDecal con `$RenderToTexture`) e i riquadri del logo (MeshDecal + `%STENCIL_MAP`). La skin ha
`decals: {text: {value, color}, image: {file}}`: il testo va sulle targhe, l'immagine (tenuta dentro il file
`.vfskin`, `POST /api/skins/{id}/image`) sui riquadri del logo. Per ogni riquadro si trova la zona di UV e le sue
proporzioni reali, e vi si disegna dentro; l'immagine risultante è servita come una texture qualunque (percorso
`skinimg:<hash>`), quindi vale per visualizzatore, export e fogli decal. Un testo tutto maiuscolo usa il carattere
del gioco (solo maiuscole), altrimenti un grassetto di sistema. Nello Skin Lab è la sezione "Decals" (niente
anteprima dal vivo: segue la conferma del server). Provato sulla Liberator (5 targhe, 4 riquadri del logo). Resta
della tappa 3: scegliere tra i decal del gioco, sostituire i decal che hanno già un'immagine propria, scegliere su
quali riquadri mettere cosa, dimensione e carattere del testo.

Non fatto: `tools/skin_check.py` (le misure sopra sono state prese a mano dall'anteprima); prova nella finestra
dell'app installata (WebView2) e su Linux; rilettura delle traduzioni da parte di un madrelingua.

## Fuori da questa tappa

Motivi, decal, mimetico negli export, scheda di pittura, portare una skin su un altro modello, galleria online.

## Note per il piano

- Batching: nei GLB con i gruppi ogni batch è un solo gruppo di vernice con un solo materiale (`batching.js`,
  `paint.js`), quindi non ostacola la ricolorazione.
- Slot 0 degli strati (tinta propria, non della tavolozza): non modificabile in questa tappa; va detto
  nell'interfaccia se una parte non cambia colore.
- Interni: usano una tavolozza grigia fissa, restano fuori.
