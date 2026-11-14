# Animazioni degli oggetti e "Nave completa" — disegno

Data: 14/11/2026 · Stato: approvato a voce, rivisto dopo la rilettura, da approvare per iscritto

## Obiettivo

VerseForge trova da solo le animazioni collegate a un modello, cioè l'arma che spara o ricarica e la nave che apre il
tettuccio o estrae il carrello. Le fa vedere nel visualizzatore e le mette dentro l'export GLB.
Un interruttore "Full ship" monta poi i componenti di base di navi e veicoli, carrello compreso, così le animazioni si
vedono intere.

Il lavoro è diviso in due fasi, ognuna con il suo piano e la sua versione:

- **Fase A, animazioni**: versione 1.6.0.
- **Fase B, nave completa**: versione 1.7.0. Usa i pezzi della fase A.

Restano fuori:

- le animazioni di personaggi e vestiti (migliaia di clip umane, non legate agli oggetti);
- la deformazione morbida dei `.skin`: i pezzi restano rigidi, vedi A3;
- le clip additive (flag 1 nell'intestazione: sono spostamenti da sommare a una posa, non pose a sé, per esempio
  `has_ammo_pose`). Si saltano, come per la P6-LR.

## Come il gioco collega oggetti e animazioni (verificato su Data.p4k)

| Anello | Esempio | Ruolo |
|---|---|---|
| `<modello>.chrparams` accanto al `.chr`/`.cga` (4.282 nel gioco) | `AEGS_Gladius.chrparams` | `AnimationList`: `#filepath` = cartella base, `$TracksDatabase` = `.dba`, poi voci `name` → `path` (anche `*` / `*/*.caf`) |
| `.caf` singolo | `Animations/fps_weapons/.../p6lr/bsnp_behr_p6lr_fire_bolt_01.caf` | una clip (formato #ivo già decifrato per la P6-LR) |
| `.dba` | `Animations/Spaceships/Ships/AEGS/Gladius.dba` | contenitore #ivo (`#dba`) di molte clip; dentro ci sono i percorsi `.caf` originali |
| Mannequin `.adb` | `Animations/Mannequin/ADB/Spaceships/Ships/AEGS/Gladius_SCItem/AEGS_Gladius_SCItem_Anims.adb` | significato: gruppo (`Canopy`, `Left_Ladder`) + azione (`Open`/`Close`) → nome della clip, eventuale `speed="-1"` (clip al contrario: il tettuccio si apre con `canopy_close` all'indietro) |
| DataCore `EntityClassDefinition` | `AEGS_Gladius` | `SGeometryResourceParams` (geometria), `SEntityComponentDefaultLoadoutParams` (60 voci porta → componente), percorsi `.cdf` delle gambe del carrello |

Esempi: lo scafo del Gladius elenca circa 30 clip (`canopy_open`, `ladder_deploy`, `landing_gear_extend`, pannelli,
prese d'aria). Ogni gamba del carrello (`AEGS_Gladius_LandingGear_Front.cdf` → `_CHR.chr` + `.chrparams`) ha
`landing_gear_extend`, `landing_gear_retract` e `landing_gear_compress`. La P6-LR elenca la sua cartella con `*.caf`.

## Aggiornamento dopo i passi di ricerca (14/11)

I passi di ricerca 1 (`.dba`, snodi `.cga`) e 2 (`.adb`) sono riusciti. Il dettaglio sta nel piano
`docs/superpowers/plans/2026-11-14-animazioni-fase-a.md`. Quattro cose cambiano rispetto a quanto scritto sotto:

- `reverse` diventa `speed`, un numero: se è negativo la clip va al contrario. L'`.adb` usa anche valori come `1.6`.
- La posa locale si ricava sempre come `inv(world_padre) @ world`, anche per le ossa, quindi `ivo.bones` non cambia.
- La regola sul nome toglie i token iniziali che compaiono nel nome del file del modello, poi il numero finale. Non
  serve il prefisso comune.
- Il campo dell'`.adb` è `SAnimationControllerParams.AnimationDatabase`, un percorso relativo a
  `Animations/Mannequin/ADB/`.

## Fase A — Animazioni

### A1. Lettura delle clip: `sc_explorer/caf.py` e `sc_explorer/dba.py`

- `caf.py` è il lettore della P6-LR (`_temp/p6lr_script/caf.py`), ripulito e portato dentro il pacchetto. Offre due
  funzioni:
  - `header(data) -> ClipInfo`: fps, frame finale, flag additiva, numero di ossa. Legge solo il chunk `0x4733C6ED`,
    quindi è veloce.
  - `read(data) -> Clip`: `ClipInfo` più le tracce per hash (CRC32 del nome dell'osso o dello snodo). Ogni traccia ha
    tempi e quaternioni per la rotazione, tempi e vettori per la posizione.
- `dba.py` offre le stesse due funzioni, su ogni voce: `headers(data) -> dict[percorso_caf_minuscolo, ClipInfo]` e
  `read(data, voce) -> Clip`.
  - **Primo passo di ricerca del piano: decifrare il `.dba`.** Si prova su `LandingGear/Gladius.dba` (122.720 byte,
    9 clip: `landinggear_{front,backleft,backright}_{extend,retract,compress}`) e su `Ships/AEGS/Gladius.dba` (circa
    40 clip, tra cui `canopy_open`).
  - Il passo riesce quando le 9 clip del carrello danno durate maggiori di 0 e tracce i cui hash corrispondono alle
    ossa di `AEGS_Gladius_LandingGear_Front_CHR.chr`. Ci si aspetta che ogni voce riusi i blocchi `#caf` già noti.
- Nello stesso passo si verifica che le clip delle `.cga` muovano gli snodi con hash = CRC32 del nome dello snodo, come
  per le ossa. Il controllo si fa sugli snodi di `AEGS_Gladius.cga`.
- La traccia con hash `0x16F4F95B` è la radice o locatore che sposta l'intero oggetto: si ignora, come per la P6-LR.
- I formati sconosciuti di chiavi o tempi sollevano un `ValueError` con un messaggio chiaro. Chi chiama salta quella
  clip, non tutto il modello.

### A2. Scoperta: `sc_explorer/animations.py`

`find(archive, model_path, adb_path=None) -> list[AnimRef]`

- `adb_path` viene da `entities.adb_for(model_path)`, vedi A2b. Se è `None`, vale la regola sul nome.

- Il `.chrparams` si cerca così:
  - `.chr`/`.cga`: lo stesso nome con estensione `.chrparams`;
  - `.cdf`: il `.chr` indicato in `<Model File>`;
  - `.cgf`/`.skin` sciolti: nessuno.
- Ogni voce `AnimationList` diventa un percorso dentro `#filepath`:
  - un nome esplicito dà una clip con quel nome;
  - un carattere jolly elenca i `.caf` della cartella (il nome viene dal file);
  - con `$TracksDatabase` il percorso si cerca prima nel `.dba`, poi come `.caf` sciolto.
- `AnimRef` è un'azione che si può suonare. Campi:
  - `id` = `gruppo/azione` in minuscolo, unico nel modello (`canopy/open`);
  - `label` (`Open`), `group` (`Canopy`);
  - `clip` = nome della clip nel `.chrparams` (`canopy_close`);
  - `source` = `.caf` oppure `.dba` + voce;
  - `reverse` = vero se l'`.adb` dice `speed="-1"`;
  - `duration` (secondi), `pose` (vero se il frame finale è uguale a quello iniziale, cioè la clip è una posa ferma).
  - Due azioni possono usare la stessa clip, una al contrario.
- `duration` e `pose` vengono da `header()`: `find` non decodifica mai le tracce.
- **Etichette dall'`.adb`, secondo passo di ricerca del piano.** Si cerca in DataCore il campo dell'entità che porta
  all'`.adb`: un componente con un percorso `Animations/Mannequin/ADB/...`.
  - Il passo riesce se dal record `AEGS_Gladius` si arriva a `AEGS_Gladius_SCItem_Anims.adb` e se ne ricavano
    Canopy (Open/Close) e Left_Ladder (Open/Close).
  - Le clip dell'`.adb` che non sono nel `.chrparams` si ignorano. Le clip del `.chrparams` che l'`.adb` non nomina
    seguono la regola sul nome qui sotto.
- Senza `.adb`, vale la regola sul nome. Usa sempre il `name` del `.chrparams`, mai il percorso della voce nel `.dba`:
  le gambe del carrello si chiamano `landing_gear_extend` nel `.chrparams` e `landinggear_front_extend` nel `.dba`, e
  l'unione di B2 funziona solo sul primo.
  - L'ultima parola è l'azione, il resto è il gruppo (`canopy_open` → gruppo "Canopy", azione "Open").
  - Per i jolly, dove il nome viene dal file: si tolgono il numero finale e il prefisso comune a tutte le clip
    dell'oggetto (`bsnp_behr_p6lr_fire_bolt_01` → "Fire · Bolt"). Se c'è una clip sola, o se il prefisso comune
    coprirebbe tutto il nome, si toglie solo la parte che coincide con il nome del file del modello.
- Le pose ferme finiscono nel gruppo "Poses", in fondo all'elenco. Le additive sono già escluse (vedi Obiettivo).
- La lista va in cache insieme al modello.

### A2b. Collegamento all'`.adb`: `sc_explorer/entities.py` (prima parte)

Il DataCore non resta in memoria: oggi `variants.build` lo legge solo per costruire la cache. Si fa lo stesso.

- `entities.build(dcb_bytes) -> dict` gira insieme a `variants.build` e salva su disco
  `entities_v1_<chiave p4k>.json`.
- Nella fase A il file contiene solo `adb`: `percorso geometria → percorso .adb`, per le entità che hanno sia
  `SGeometryResourceParams` sia il campo trovato nel secondo passo di ricerca.
- `entities.adb_for(path)` lo legge dalla cache già caricata dal server.
- Se più entità hanno la stessa geometria, vince quella il cui nome di record finisce col nome del file
  (`AEGS_Gladius` per `AEGS_Gladius.cga`). Altrimenti vince la prima in ordine alfabetico, che ha un `.adb`.
- Nella fase B lo stesso file riceve anche `vehicles` (B1) e la versione passa a `entities_v2`.

### A3. Modello con gerarchia: `sc_explorer/ivo.py` e `sc_explorer/model.py`

Oggi `load_geometry` porta ogni vertice nello spazio dell'oggetto, quindi niente si può muovere. Cambia così:

- **`ivo.bones`** restituisce anche la posa locale, `lq`/`lp`, letta dallo stesso record del chunk (i campi 3–9 che
  `build.py` leggeva a mano).
  - **`ivo.nodes`** non cambia. La matrice locale si ricava in `model.py`: `inv(world_padre) @ world`.
- `Part` riceve `node: str`, il nome dello snodo o dell'osso a cui è attaccato (`""` = radice).
  - `.cga`: lo snodo del sotto-insieme.
  - `.skin` e attachment `CA_SKIN` di un `.cdf`: ogni triangolo va sull'osso dominante (`ivo.vertex_bones`). L'indice
    è quello delle ossa del `.skin` e va tradotto **per nome** nello scheletro del `.chr`, come in `build.py`.
  - Attachment `CA_BONE` di un `.cdf`: `node = BoneName`.
  - Il resto: radice.
- `Model` riceve due campi:
  - `skeleton`: una lista di `Bone(name, parent, local)` in posa di riposo, con `local` matrice 4×4;
  - `animations`: la lista di `AnimRef` di A2.
- I vertici restano nello spazio dell'oggetto, come oggi, quindi OBJ, STL e stampa non cambiano. È la scrittura GLB
  animata a portarli nello spazio locale dello snodo (`inv(world_snodo)`).
- `with_variant()` crea il modello con `dataclasses.replace(model, parts=…)` invece di `Model(path, parts, warnings)`,
  così `skeleton` e `animations` restano anche cambiando vernice.
- I modelli senza clip hanno `skeleton` e `animations` vuoti e si caricano esattamente come oggi.

### A4. GLB animato: `sc_explorer/anim_glb.py`, chiamato da `export.to_glb`

`to_glb(model, …, anim=True)`: se `anim` è vero e `model.animations` non è vuota, la scena si costruisce così:

- **Snodi separati**: quelli toccati da almeno una traccia, più tutti i loro antenati fino alla radice. Gli antenati
  non animati restano nel grafo come nodi vuoti con la loro trasformazione di riposo, altrimenti le trasformazioni
  locali non tornano. I pezzi degli snodi non separati restano fusi per materiale sotto la radice, come oggi, così le
  chiamate di disegno di una nave non esplodono.
- **Pezzi**: sotto ogni snodo separato si fondono per materiale, con `merged_by_material`, nello spazio locale dello
  snodo.
- **Nomi**: i nodi delle mesh tengono il formato attuale `kind|materiale|i`, perché `app.js` (righe 210–215) ne ricava
  vetro, decal e proxy. I nodi dello scheletro si chiamano col nome dello snodo.
- **Costruzione**: trimesh costruisce la scena con la gerarchia (`scene.graph`, trasformazioni di riposo), con
  materiali e texture come oggi. Poi `anim_glb.add_animations(glb_bytes, clips, node_index) -> glb_bytes` aggiunge al
  JSON il blocco `animations` e mette i dati in coda al buffer binario.
  - Campionatori `LINEAR`: `translation` per le posizioni, `rotation` per i quaternioni.
  - I tempi sono frame / fps.
  - Una clip glTF per ogni **clip** usata (non per azione): `reverse` lo gestisce il visualizzatore.
- **Asse**: da Z-su a Y-su (`Z_UP_TO_Y_UP`), applicato a un nodo radice in cima.
- Il visualizzatore e l'export usano lo stesso GLB. OBJ e STL restano statici, nella posa di riposo.
- La chiave della cache GLB in `Model.cache`, usata da `model_glb`, diventa `("glb", tex, anim)`. Il modello montato
  della fase B è già una voce di cache a parte, quindi non serve aggiungere `full`.

### A5. Server: `sc_explorer/server.py`

- `/api/model/info` aggiunge `animations: [{id, label, group, clip, duration, reverse, pose}]`.
- `/api/model/glb` include le animazioni.
- `/api/export?fmt=glb` riceve `anim: bool = True`.
- Gli errori di una singola clip finiscono in `warnings` (`warn_anim_error`, testi in `i18n.py`, in inglese come il
  resto dell'interfaccia).

### A6. Visualizzatore: `web/app.js`, `index.html`, `style.css`

- Pannello "Animations" nel pannello di destra. Compare solo se `animations` non è vuoto.
  - Elenco per gruppo, con un pulsante per ogni azione (Canopy: Open · Close).
  - Comandi: play/pausa, ripeti, barra del tempo trascinabile.
- `THREE.AnimationMixer` sulla scena caricata.
  - L'azione sceglie la clip glTF per `clip`.
  - `reverse` diventa `timeScale = -1`, partendo dalla fine.
  - Una clip nuova ferma la precedente, e alla fine il modello resta nella posa finale (`clampWhenFinished`), così
    "Open" lascia davvero aperto.
- Nelle impostazioni di export compare la casella "Include animations", attiva di default.
- Lo stile è quello attuale (glass UI), in inglese.

## Fase B — Interruttore "Full ship"

### B1. Indice entità: `sc_explorer/entities.py` (seconda parte)

Lo stesso file di cache di A2b (`entities_v2_<chiave p4k>.json`) riceve due cose:

- **`vehicles`**: `percorso geometria → albero del loadout` solo per le entità con `VehicleComponentParams` (navi e
  veicoli).
  - Se più entità hanno la stessa geometria, vince quella il cui nome di record finisce col nome del file, come in
    A2b. Se non ce n'è una, vince quella col loadout più lungo.
  - Ogni nodo dell'albero è `{port, geometry, material, children}`, ricorsivo da
    `SEntityComponentDefaultLoadoutParams`.
  - Si saltano le voci vuote e le entità senza geometria (controller, `hardpoint_paint`), ma si seguono i loro figli.
  - Profondità massima 4.
- **Componenti di base** = tutto ciò che il loadout di fabbrica monta e che ha una geometria: propulsori, sedili,
  cruscotti, armi, lanciamissili e missili, prese d'aria, componenti interni. È ciò che il gioco mostra su una nave
  appena comprata.
- **Carrello, terzo passo di ricerca del piano.** Le gambe (`.cdf`) sono citate in DataCore ma non come voci del
  loadout (`landingpad_helper` → `Default_LandingSystem`). Si cerca il record che lega ogni `.cdf` a uno snodo o a una
  porta dello scafo, e si aggiunge all'albero come nodo `{port: <snodo>, geometry: <cdf>}`.
  - Il passo riesce se per il Gladius si trovano le tre gambe, ognuna con uno snodo dello scafo che esiste.
  - Si verifica anche su Cutlass (DRAK), Avenger (AEGS, carrello diverso) e Aurora (RSI).

### B2. Montaggio: `model.load_full(archive, path, tree)`

- Ogni nodo dell'albero si carica con `load_model`, che dà il suo `skeleton`, i suoi pezzi e le sue `animations`.
- **Aggancio**: un componente va sullo snodo o helper **del suo genitore nell'albero** con il nome della porta (senza
  badare a maiuscole e minuscole). Il genitore è lo scafo per i componenti di primo livello, il lanciamissili per i
  missili. Diventa figlio di quello snodo, così segue le animazioni del genitore: se l'ala si muove, il propulsore
  sull'ala si muove con lei.
- **Spazio dei nomi**: gli snodi di ogni istanza prendono il prefisso del percorso di porte
  (`hardpoint_thruster_main_left/…`). Le tre gambe del carrello hanno ossa con lo stesso nome, quindi ogni traccia si
  lega all'istanza da cui viene la sua clip, mai per nome globale.
- **Porte mancanti**: un componente la cui porta non c'è nella geometria del genitore si salta, con un avviso e il
  conteggio (`warn_ports_missing`).
- **Unione delle azioni per `id`**: le azioni con lo stesso `id`, come `landing_gear/extend` su scafo e gambe,
  diventano una sola azione. Ha una clip glTF combinata con i canali di tutte le istanze, e dura quanto la più lunga.
  Le azioni di un solo componente restano, sotto un gruppo col nome della porta.
- Il modello montato va in cache come oggi, ma con una chiave diversa (`full=True`).

### B3. Interfaccia e API

- `/api/model/info`, `/api/model/glb`, `/api/export` e `/api/print` ricevono `full: bool = False`.
  - `_run_print_job` passa `full` a `get_model`.
- `info` dice anche `can_full`: vero se il percorso è nell'indice `vehicles`.
- Nella barra del visualizzatore compare l'interruttore "Full ship" (testo "Full vehicle" per i veicoli), visibile solo
  se `can_full`. Si ricorda per tutta la sessione.
- Con l'interruttore acceso tutti gli export contengono la nave montata: il GLB animato, OBJ e STL statici, e anche la
  stampa 3D.

## Errori e limiti

- Una clip che non si legge viene saltata con un avviso, e le altre restano.
- Un componente che non si carica viene saltato con un avviso, e la nave resta.
- Modelli senza `.chrparams`: nessun pannello, nessun cambiamento.
- Le tracce si decodificano solo quando serve il GLB. `info` e la ricerca leggono solo le intestazioni.
- Prestazioni: il piano misura e scrive il tempo di caricamento del Gladius completo rispetto al solo scafo.
  L'obiettivo è stare sotto i 2×. Se si va oltre, lo si segnala all'utente prima di continuare.

## Prove

In `tests/test_formats.py`, con lo stesso stile: test di integrazione sul gioco installato, saltati se manca
`Data.p4k`. Più un test sintetico.

- **sintetico, senza gioco** (`tests/test_anim_glb.py`): una scena con due snodi e una clip finta di due chiavi passa
  da `add_animations`. Si controlla che il GLB sia valido, che i canali puntino ai nodi giusti e che i tempi siano
  corretti.
- **caf**:
  - `bsnp_behr_p6lr_fire_bolt_01.caf` dà durata maggiore di 0 e almeno una traccia;
  - `bsnp_behr_p6lr_has_ammo_pose.caf` risulta additiva ed è esclusa da `find`.
- **dba**:
  - `LandingGear/Gladius.dba` dà 9 clip con i nomi attesi;
  - `Ships/AEGS/Gladius.dba` contiene `canopy_open`.
- **scoperta**:
  - lo scafo del Gladius ha almeno 25 azioni, tra cui `canopy/open` (con `reverse` se l'`.adb` lo dice) e
    `landing_gear/extend`;
  - la P6-LR ha azioni da `fire_bolt_01` e `reload_full_01`;
  - un modello senza `.chrparams` dà una lista vuota.
- **variante**: `with_variant` sulla P6-LR conserva `skeleton` e `animations`.
- **GLB**:
  - per Gladius e P6-LR, nel JSON del GLB `animations` non è vuoto, ogni canale punta a un nodo che esiste e i nodi
    mesh hanno nomi `kind|…`;
  - i modelli senza clip danno lo stesso numero di mesh e di triangoli di oggi.
- **montaggio**:
  - il Gladius completo ha più triangoli del solo scafo;
  - contiene le tre gambe del carrello e i propulsori;
  - `landing_gear/extend` ha canali sia sullo scafo sia su tutte e tre le gambe, legati a istanze diverse.
- **a vista**: anteprima `verseforge-dev` (porta 8767).
  - Si provano P6-LR (sparo, ricarica), il Gladius (tettuccio, carrello, con e senza "Full ship") e un attrezzo
    (multitool).
  - Il GLB esportato si apre in Blender e l'animazione si muove.

## Rilascio

Ogni fase finisce con queste cose:

- aggiornamento del numero di versione in `sc_explorer/__init__.py`, `version_info.txt` (FileVersion, ProductVersion
  e le tuple numeriche) e `installer/VerseForge.iss`;
- aggiornamento del README (sezione Usage);
- una build.

La pubblicazione su GitHub si fa solo dopo che l'utente lo chiede.
