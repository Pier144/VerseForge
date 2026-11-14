# Animazioni degli oggetti e "Nave completa" — disegno

Data: 14/11/2026 · Stato: approvato a voce, da rileggere

## Obiettivo

VerseForge trova da solo le animazioni collegate a un modello, cioè l'arma che spara o ricarica e la nave che apre il
tettuccio o estrae il carrello. Le fa vedere nel visualizzatore e le mette dentro l'export GLB.
Un interruttore "Full ship" monta poi i componenti di base di navi e veicoli, carrello compreso, così le animazioni si
vedono intere.

Il lavoro è diviso in due fasi, ognuna con il suo piano e la sua versione:

- **Fase A, animazioni**: versione 1.6.0.
- **Fase B, nave completa**: versione 1.7.0. Usa i pezzi della fase A.

Restano fuori le animazioni di personaggi e vestiti (migliaia di clip umane, non legate agli oggetti) e la deformazione
morbida dei `.skin`: i pezzi `.skin` restano rigidi, vedi A3.

## Come il gioco collega oggetti e animazioni (verificato su Data.p4k)

| Anello | Esempio | Ruolo |
|---|---|---|
| `<modello>.chrparams` accanto al `.chr`/`.cga` (4.282 nel gioco) | `AEGS_Gladius.chrparams` | `AnimationList`: `#filepath` = cartella base, `$TracksDatabase` = `.dba`, poi voci `name` → `path` (anche `*` / `*/*.caf`) |
| `.caf` singolo | `Animations/fps_weapons/.../p6lr/bsnp_behr_p6lr_fire_bolt_01.caf` | una clip (formato #ivo già decifrato per la P6-LR) |
| `.dba` | `Animations/Spaceships/Ships/AEGS/Gladius.dba` | contenitore #ivo (`#dba`) di molte clip; dentro ci sono i percorsi `.caf` originali |
| Mannequin `.adb` | `Animations/Mannequin/ADB/Spaceships/Ships/AEGS/Gladius_SCItem/AEGS_Gladius_SCItem_Anims.adb` | significato: gruppo (`Canopy`, `Left_Ladder`) + azione (`Open`/`Close`) → nome animazione, eventuale `speed="-1"` (clip al contrario) |
| DataCore `EntityClassDefinition` | `AEGS_Gladius` | `SGeometryResourceParams` (geometria), `SEntityComponentDefaultLoadoutParams` (60 voci porta → componente), percorsi `.cdf` delle gambe del carrello |

Esempi: lo scafo del Gladius elenca circa 30 clip (`canopy_open`, `ladder_deploy`, `landing_gear_extend`, pannelli,
prese d'aria). Ogni gamba del carrello (`AEGS_Gladius_LandingGear_Front.cdf` → `_CHR.chr` + `.chrparams`) ha
`landing_gear_extend`, `landing_gear_retract` e `landing_gear_compress`. La P6-LR elenca la sua cartella con `*.caf`.

## Fase A — Animazioni

### A1. Lettura delle clip: `sc_explorer/caf.py` e `sc_explorer/dba.py`

- `caf.py` è il lettore della P6-LR (`_temp/p6lr_script/caf.py`), ripulito e portato dentro il pacchetto.
  `read(data) -> Clip`, dove `Clip` contiene fps, durata, il flag additiva e le tracce per hash di osso o snodo
  (CRC32 del nome). Ogni traccia ha tempi e quaternioni per la rotazione, tempi e vettori per la posizione.
- `dba.py`: `read(data) -> dict[percorso_caf_minuscolo, Clip]`. Il formato è ancora da decifrare: è il **primo passo
  del piano** e si prova su `LandingGear/Gladius.dba` (9 clip) e `Ships/AEGS/Gladius.dba` (circa 40 clip). Ci si
  aspetta che ogni voce riusi i blocchi `#caf` già noti.
- Da verificare nello stesso passo: le clip delle `.cga` muovono gli snodi con hash = CRC32 del nome dello snodo, come
  per le ossa.
- I formati sconosciuti di chiavi o tempi sollevano un `ValueError` con un messaggio chiaro. Chi chiama salta quella
  clip, non tutto il modello.

### A2. Scoperta: `sc_explorer/animations.py`

`find(archive, model_path) -> list[AnimRef]`

- Il `.chrparams` si cerca così:
  - `.chr`/`.cga`: lo stesso nome con estensione `.chrparams`;
  - `.cdf`: il `.chr` indicato in `<Model File>`;
  - `.cgf`/`.skin` sciolti: nessuno.
- Ogni voce `AnimationList` diventa un percorso dentro `#filepath`:
  - un nome esplicito dà una clip con quel nome;
  - un carattere jolly elenca i `.caf` della cartella (il nome viene dal file);
  - con `$TracksDatabase` il percorso si cerca prima nel `.dba`, poi come `.caf` sciolto.
- `AnimRef` contiene: `id` (stabile, il nome della clip), `label`, `group`, `source` (`.caf` oppure `.dba` + voce),
  `reverse`.
- Etichette e gruppi vengono dall'`.adb`, quando è collegato all'entità in DataCore. Il componente esatto si cerca nel
  piano, vicino al punto in cui si legge `SGeometryResourceParams`. Senza `.adb` vale una regola sul nome: l'ultima
  parola è l'azione, il resto è il gruppo (`canopy_open` → gruppo "Canopy", azione "open").
- Le pose (`*_pose`, una chiave sola) e le clip additive finiscono nel gruppo "Poses". Si possono vedere ma non sono
  in testa all'elenco.
- Il risultato si mette in cache insieme al modello, come già succede per le varianti di vernice.

### A3. Modello con gerarchia: `sc_explorer/model.py`

Oggi `load_geometry` porta ogni vertice nello spazio dell'oggetto, quindi niente si può muovere. Ecco cosa cambia:

- `Part` riceve `node: str` (nome dello snodo o dell'osso a cui è attaccato, `""` = radice).
- `Model` riceve `skeleton`: una lista di `(name, parent, local_matrix)` in posa di riposo, presa da `ivo.nodes`
  (`.cga`) o da `ivo.bones` (`.chr`).
- I vertici restano nello spazio dell'oggetto, come oggi, quindi export ed esportazione STL non cambiano. È la
  scrittura GLB animata a portarli nello spazio locale dello snodo.
- `.skin`: ogni triangolo va sull'osso dominante (`ivo.vertex_bones`), come per la P6-LR.
- Questo vale solo quando il modello ha delle clip: gli altri modelli si caricano esattamente come oggi.

### A4. GLB animato: `sc_explorer/export.py`

- Si separano dagli altri solo gli **snodi toccati da almeno una clip**, con i loro figli. Tutto il resto resta fuso per
  materiale sotto la radice, come oggi, così le chiamate di disegno di una nave non esplodono.
- trimesh costruisce la scena con la gerarchia degli snodi (`scene.graph`, con le trasformazioni di riposo). Poi una
  funzione aggiunge al JSON del GLB il blocco `animations`: campionatori `LINEAR` per la posizione, e `LINEAR` sui
  quaternioni per la rotazione. I dati vanno in coda al buffer binario. Materiali e texture restano quelli di oggi.
- Asse: da Z-su a Y-su, come `Z_UP_TO_Y_UP`, applicato alla radice.
- Il visualizzatore e l'export usano lo stesso GLB. OBJ e STL restano statici, nella posa di riposo.

### A5. Server: `sc_explorer/server.py`

- `/api/model/info` aggiunge `animations: [{id, label, group, duration, reverse, pose}]`.
- `/api/model/glb` include le animazioni.
- `/api/export?fmt=glb` riceve `anim: bool = True`.
- Gli errori di una singola clip finiscono in `warnings` (`warn_anim_error`, testi in `i18n.py`, in inglese come il
  resto dell'interfaccia).

### A6. Visualizzatore: `web/app.js`, `index.html`, `style.css`

- Pannello "Animations" nel pannello di destra. Compare solo se `animations` non è vuoto.
  - Elenco per gruppo, con un pulsante per ogni azione (Canopy: Open · Close).
  - Comandi: play/pausa, ripeti, barra del tempo trascinabile.
- `THREE.AnimationMixer` sulla scena caricata. `reverse` diventa `timeScale = -1`, partendo dalla fine. Una clip nuova
  ferma la precedente, e alla fine il modello resta nella posa finale (`clampWhenFinished`), così "Open" lascia
  davvero aperto.
- Nelle impostazioni di export compare la casella "Include animations", attiva di default.
- Lo stile è quello attuale (glass UI), in inglese.

## Fase B — Interruttore "Full ship"

### B1. Indice entità: `sc_explorer/entities.py`

- All'avvio, insieme a nomi e varianti, si costruisce una mappa `percorso geometria → EntityClassDefinition` da
  `SGeometryResourceParams`. Si salva nella cache su disco con la chiave della versione del p4k, come gli indici di
  oggi.
- `loadout(record) -> albero di (porta, entità figlia, figli)` legge `SEntityComponentDefaultLoadoutParams` in modo
  ricorsivo:
  - salta le voci vuote e le entità senza geometria (controller, `hardpoint_paint`);
  - profondità massima 4.
- Carrello: le gambe (`.cdf`) sono citate in DataCore ma non come voci del loadout (`landingpad_helper` →
  `Default_LandingSystem`). Il primo passo della fase B trova il record che le lega a uno snodo o porta dello scafo.
  Si verifica su Gladius (AEGS), Cutlass (DRAK), Avenger (AEGS, carrello diverso) e Aurora (RSI).

### B2. Montaggio: `model.load_full(archive, path)`

- Ogni componente si carica con `load_model` e si attacca allo snodo o helper dello scafo che ha il nome della porta
  (senza badare a maiuscole e minuscole). Diventa figlio di quello snodo, così segue le animazioni dello scafo: se
  l'ala si muove, il propulsore sull'ala si muove con lei.
- Una porta non trovata nella geometria fa saltare il componente e mettere un avviso con il conteggio
  (`warn_ports_missing`).
- Clip: si fa l'unione per `id`. Le clip con lo stesso nome, come `landing_gear_extend` su scafo e gambe, diventano
  una clip sola che muove tutto insieme. La durata è la più lunga.
- Il modello montato va in cache come oggi, ma con una chiave diversa (`full=True`).

### B3. Interfaccia e API

- `/api/model/info`, `/api/model/glb` e `/api/export` ricevono `full: bool = False`.
- `info` dice anche `can_full`: vero se il percorso ha un'entità con loadout non vuoto.
- Nella barra del visualizzatore compare l'interruttore "Full ship" (testo "Full vehicle" per i veicoli), visibile solo
  se `can_full`. Si ricorda per tutta la sessione.
- Con l'interruttore acceso tutti gli export contengono la nave montata: il GLB animato, OBJ e STL statici, e anche la
  stampa 3D.

## Errori e limiti

- Una clip che non si legge viene saltata con un avviso, e le altre restano.
- Un componente che non si carica viene saltato con un avviso, e la nave resta.
- Modelli senza `.chrparams`: nessun pannello, nessun cambiamento.
- Prestazioni: le clip si decodificano solo quando serve il GLB, non durante la ricerca. Si misura il tempo di
  caricamento dei Gladius completo: l'obiettivo è stare sotto i 2× del solo scafo di oggi.

## Prove

In `tests/test_formats.py`, con lo stesso stile: test di integrazione sul gioco installato, saltati se manca
`Data.p4k`.

- **caf**: `bsnp_behr_p6lr_fire_bolt_01.caf` → durata maggiore di 0, almeno una traccia.
  `bsnp_behr_p6lr_has_ammo_pose.caf` → una chiave.
- **dba**: `LandingGear/Gladius.dba` → 9 clip con i nomi attesi. `Ships/AEGS/Gladius.dba` → contiene `canopy_open`.
- **scoperta**: lo scafo del Gladius ha almeno 25 clip, con `canopy_open` e `landing_gear_extend`. La P6-LR ha
  `fire_bolt_01` e `reload_full_01`. Un modello senza `.chrparams` dà una lista vuota.
- **GLB**: per Gladius e P6-LR si analizza il JSON del GLB e si controlla che `animations` non sia vuoto e che ogni
  canale punti a un nodo che esiste. I modelli senza clip danno un GLB identico a quello di oggi (stesso numero di mesh
  e di triangoli).
- **montaggio**: il Gladius completo ha più triangoli del solo scafo, contiene le tre gambe del carrello e i
  propulsori, e `landing_gear_extend` ha canali sia sullo scafo sia sulle gambe.
- **a vista**: anteprima `verseforge-dev` (porta 8767). Si provano P6-LR (sparo, ricarica), il Gladius (tettuccio,
  carrello, con e senza "Full ship") e un attrezzo (multitool). Il GLB esportato si apre in Blender e l'animazione
  si muove.

## Rilascio

Ogni fase finisce con un aggiornamento del numero di versione nei tre file, del README (sezione Usage) e con una build.
La pubblicazione su GitHub si fa solo dopo che l'utente lo chiede.
