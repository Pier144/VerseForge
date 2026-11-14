# Fase A, animazioni: piano di lavoro

> **Per chi esegue:** si usa superpowers:executing-plans, passo per passo. Le caselle `- [ ]` servono a segnare i
> passi fatti.

**Obiettivo:** VerseForge trova, mostra ed esporta in GLB le animazioni collegate a un modello. Spec:
`docs/superpowers/specs/2026-11-14-animazioni-oggetti-design.md`.

**Architettura:** quattro moduli nuovi e piccoli:

- `caf.py`, `dba.py`: lettura delle clip;
- `animations.py`: scoperta, `.chrparams` più `.adb`;
- `rig.py`: scheletro e assegnazione dei pezzi a snodi e ossa;
- `anim_glb.py`: blocco `animations` nel GLB.

C'è anche `entities.py`, che fa da indice dal DataCore. `model.py`, `export.py`, `server.py` e `web/app.js` cambiano
poco, e solo per i modelli che hanno clip.

**Strumenti:** Python 3.11, numpy, trimesh, FastAPI, three.js (AnimationMixer), pytest.

**Comando delle prove:** `python -m pytest tests -q`. Le prove sul gioco installato si saltano se manca `Data.p4k`.

## Fatti verificati prima del piano (14/11, sul gioco installato)

- **`.dba`**: è un file #ivo con due chunk.
  - Il chunk `0xF7351608` contiene un `u32` con il numero di clip, un `u32` da saltare, poi una voce da 48 byte per
    clip e infine i nomi.
    - Ogni voce ha lo stesso formato `<IHHIII` del chunk `ANIM_INFO` del `.caf` (flags, fps, n ossa, ?, frame
      iniziale, frame finale), seguito da un quaternione e da una posizione.
    - I nomi sono percorsi `.caf` terminati da NUL, nello stesso ordine delle voci.
  - Il chunk `0x194FBC50` contiene i blocchi `#dba`, uno dopo l'altro.
    - Il primo `#dba` si trova a pochi byte dall'inizio del chunk.
    - Il blocco *k* sta a `inizio_{k-1} + 12 + 28·n_ossa`.
    - Il formato è identico a `#caf`: `u16` n ossa, `u16` 0xAA55, `u32` dimensione dei dati, poi gli hash e i descrittori
      da 24 byte. Gli offset sono relativi al descrittore dell'osso.
  - Il lettore delle tracce del `.caf` funziona senza modifiche.
- **Hash**: sono il CRC32 del nome esatto, maiuscole comprese, sia per le ossa dei `.chr` sia per gli snodi delle `.cga`.
  Nel Gladius tutte le tracce di tettuccio, scaletta, carrello e pannelli corrispondono a snodi dello scafo. Le tracce
  che non corrispondono (cruscotto, pulsanti, rastrelliera) sono di altri oggetti che usano lo stesso `.dba`: si
  ignorano.
- **Valori delle tracce**: sono relativi al genitore, quindi sono già i TRS locali del glTF. Al frame 0 di
  `ladder_deploy`, la posizione di `Door_A` è uguale alla posa di riposo `inv(world_padre) @ world`. I quaternioni sono
  in ordine xyzw.
- **`.adb`**: si trova in `SAnimationControllerParams.AnimationDatabase`, un percorso relativo a
  `Animations/Mannequin/ADB/`.
  - Gladius: `Spaceships/Ships/AEGS/Gladius_SCItem/AEGS_Gladius_SCItem_Anims.adb`.
  - P6-LR: `Items/Weapons/FPS/behr_sniper_ballistic_01.adb`.
  - Struttura: `FragmentList/<Gruppo>/Fragment[@FragTags]/AnimLayer/Animation[@name,@speed]`.
  - Lo stesso gruppo e la stessa azione possono comparire più volte con `Tags` diversi: vince la prima.
  - `speed` può valere `-1` o, ad esempio, `1.6`.

Scelte rispetto alla spec, da riportare nella spec:

- `reverse` diventa `speed` (un numero; se è negativo la clip va al contrario).
- La posa locale si ricava sempre come `inv(world_padre) @ world`, anche per le ossa, quindi `ivo.bones` non cambia.
- La regola sul nome toglie i token iniziali che compaiono nel nome del file del modello, poi il numero finale. Non
  serve il prefisso comune.

---

## Task 1: lettore `.caf` nel pacchetto

**File:**
- Nuovo: `sc_explorer/caf.py`.
- Nuovo: `tests/test_animations.py`.

Interfaccia:

```python
ANIM_INFO, CAF_DATA, ROOT_HASH = 0x4733C6ED, 0xA9496CB5, 0x16F4F95B

@dataclass
class ClipInfo:
    flags: int; fps: int; n_bones: int; start: int; end: int
    additive -> bool  (flags & 1)
    duration -> float ((end - start) / fps, 0 if fps == 0)
    pose -> bool      (end <= start)

@dataclass
class Track:
    rot_t: np.ndarray | None; rot: np.ndarray | None   # (n,), (n,4) xyzw
    pos_t: np.ndarray | None; pos: np.ndarray | None   # (n,), (n,3)

@dataclass
class Clip:
    info: ClipInfo
    tracks: dict[int, Track]

def info_from(data, off) -> ClipInfo
def read_block(data, c, info) -> Clip     # c = offset of "#caf"/"#dba"
def header(data) -> ClipInfo
def read(data) -> Clip
```

- [ ] Prove, da far fallire prima: con `fire_bolt_01` la durata è maggiore di 0, ci sono tracce e i quaternioni hanno
  norma circa 1. `has_ammo_pose` risulta additiva.
- [ ] Portare `times`, `quat48`, `rots` e `poss` da `_temp/p6lr_script/caf.py`. Al posto degli `assert` si sollevano
  `ValueError`.
- [ ] Le prove passano. Commit: "caf: compiled animation reader".

## Task 2: lettore `.dba`

**File:**
- Nuovo: `sc_explorer/dba.py`.
- Prove in `tests/test_animations.py`.

```python
META, BLOCKS = 0xF7351608, 0x194FBC50
def entries(data) -> list[tuple[str, ClipInfo, int]]   # (lowercase .caf path, info, block offset)
def headers(data) -> dict[str, ClipInfo]
def read(data, name) -> Clip
```

- [ ] Prove: `LandingGear/Gladius.dba` dà 9 voci con i nomi attesi, e le tracce di `landinggear_front_extend`
  corrispondono tutte alle ossa di `AEGS_Gladius_LandingGear_Front_CHR.chr`. `Ships/AEGS/Gladius.dba` contiene
  `canopy_open`, la cui unica traccia è lo snodo `Canopy` della `.cga`.
- [ ] Implementazione. Se un blocco non comincia con `#dba` si solleva `ValueError`.
- [ ] Commit: "dba: animation database reader".

## Task 3: indice `adb` da DataCore

**File:**
- Nuovo: `sc_explorer/entities.py`.
- Modifica: `sc_explorer/server.py`: `State.entities`, `_entities()` con cache `entities_v1_<size>_<mtime>.json`,
  chiamata in `load()` dopo `_variants`, con lo stesso tipo di gestione degli errori.

```python
ADB_ROOT = "Animations/Mannequin/ADB/"
def build(dcb: bytes) -> dict          # {"adb": {geometry path lowercase "/": adb path}}
def adb_for(index: dict, path: str) -> str | None
```

- Si scorre `EntityClassDefinition` con `record_view`, come fa `variants`.
- Geometria: `SGeometryResourceParams.Geometry.Geometry.Geometry.path`.
- `.adb`: `SAnimationControllerParams.AnimationDatabase`.
- Vince il record il cui nome finisce col nome del file della geometria. Altrimenti vince il primo in ordine
  alfabetico.

- [ ] Prove: nell'indice, `objects/spaceships/ships/aegs/gladius/aegs_gladius.cga` porta a `…/AEGS_Gladius_SCItem_Anims.adb`.
  La `.cdf` della P6-LR porta a `…/behr_sniper_ballistic_01.adb`.
- [ ] Implementazione e misura del tempo di `build`.
- [ ] Commit: "entities: geometry -> Mannequin database index".

## Task 4: scoperta delle azioni

**File:**
- Nuovo: `sc_explorer/animations.py`.

```python
@dataclass
class AnimRef:
    id: str; label: str; group: str; clip: str; source: str; dba: str | None
    speed: float; duration: float; pose: bool

def chrparams_for(archive, model_path) -> str | None
def find(archive, model_path, adb_path=None) -> list[AnimRef]
def load_clips(archive, refs) -> tuple[dict[str, Clip], list[tuple]]   # by clip name, warnings
```

- La lista dei `.caf` di una cartella si prende da un indice delle cartelle costruito una volta per archivio (dizionario
  a livello di modulo con chiave `id(archive)`).
- Jolly: `*.caf` e `*/*.caf`, dove `*/` può essere vuoto, quindi si accettano anche le sottocartelle.
- Le clip additive si escludono. Quelle illeggibili si saltano.

- [ ] Prove:
  - Gladius (con l'`.adb` dell'indice) ha almeno 25 azioni.
  - `canopy/open` ha `clip == "canopy_close"` e `speed < 0`.
  - `landing_gear/deploy` ha `clip == "landing_gear_extend"`.
  - La P6-LR ha `fire/bolt` e `reload/full`, e non ha clip additive.
  - `Objects/fps_weapons/attachments/magazines/behr/mgzn_s03_behr_p6lr.cgf` dà una lista vuota.
- [ ] Implementazione.
- [ ] Commit: "animations: discover clips from chrparams and Mannequin".

## Task 5: scheletro e pezzi assegnati

**File:**
- Modifica: `sc_explorer/model.py`:
  - `Part.node: str = ""`, `Part.vbones` (np.ndarray | None), `Part.bone_names` (tuple | None);
  - `Model.skeleton`, `Model.animations`;
  - `load_geometry` riempie `node` (nome dello snodo) e, per le mesh con mappa delle ossa, `vbones`/`bone_names`;
  - `load_cdf` mette `node = BoneName` sui pezzi `CA_BONE`;
  - `with_variant` usa `replace(model, parts=…, warnings=list(…), cache={})`;
  - `load_model(archive, path, adb_path=None)` chiama `animations.find`, poi `rig.attach` se ci sono azioni. In caso di
    errore aggiunge un avviso e continua.
- Nuovo: `sc_explorer/rig.py`:

```python
@dataclass
class Bone: name: str; parent: int; local: np.ndarray; world: np.ndarray   # 4x4, Cry space
def skeleton(archive, path) -> list[Bone]      # .cga nodes, .chr bones, .cdf -> its .chr
def attach(archive, model) -> None             # sets model.skeleton; splits skinned parts by dominant bone
```

- [ ] Prove:
  - Senza clip (caricatore della P6-LR, `AEGS_Gladius_Int.cga`) il numero di pezzi e di triangoli è uguale a prima, e
    `skeleton` è vuoto.
  - Sulla P6-LR, `skeleton` contiene `bolt` e almeno un pezzo ha `node == "bolt"`.
  - `with_variant` sulla P6-LR conserva `animations` e `skeleton`.
- [ ] Implementazione.
- [ ] `python -m pytest tests -q`: tutte le prove già esistenti restano verdi.
- [ ] Commit: "model: skeleton and per-node parts for animated models".

## Task 6: GLB animato

**File:**
- Nuovo: `sc_explorer/anim_glb.py`:

```python
def add_animations(glb: bytes, clips: dict[str, Clip], targets: dict[int, str]) -> bytes
    # targets: CRC32 -> node name. Converts node "matrix" to TRS, appends accessors/bufferViews to the BIN chunk,
    # one glTF animation per clip (name = clip name), LINEAR, input min/max, times = (t - start) / fps.
```

- Modifica: `sc_explorer/export.py`: `to_glb(…, clips=None)`. Con `clips` e `model.skeleton` si usa il percorso
  animato:
  - snodi animati, cioè quelli i cui hash compaiono nelle tracce, più i loro antenati, come nodi del grafo;
  - radice `__root__` con `Z_UP_TO_Y_UP`;
  - mesh per materiale sotto ogni snodo, in spazio locale, con i nomi `kind|nome|i`;
  - il resto fuso sotto la radice.
- Nuovo: `tests/test_anim_glb.py` (sintetico): una scena trimesh con due nodi e una clip finta. Si controllano il GLB
  valido, i canali sui nodi giusti, i tempi e l'assenza di `matrix` sui nodi animati.

- [ ] Prova sintetica, da far fallire prima, poi implementazione di `add_animations`.
- [ ] Prova sul gioco: `to_glb` di P6-LR e Gladius con le clip. `animations` non è vuoto, ogni `target.node` esiste e i
  nodi delle mesh cominciano con un tipo noto.
- [ ] Commit: "export: animated GLB".

## Task 7: server

**File:**
- Modifica: `sc_explorer/server.py`:
  - `_base_model` passa `entities.adb_for(...)`;
  - `model_info` aggiunge `animations`;
  - `model_glb(anim: bool = True)` usa la chiave `("glb", tex, anim)`, con le clip in `m.cache["clips"]`;
  - `export_model(anim: bool = True)`.
- Modifica: `sc_explorer/i18n.py`: `warn_anim_error`.

- [ ] Prova con FastAPI `TestClient`, se c'è già nelle dipendenze. Altrimenti una chiamata diretta alle funzioni:
  `model_info` del Gladius ha `animations`.
- [ ] Commit: "server: animations in info, viewer GLB and export".

## Task 8: visualizzatore

**File:**
- Modifica: `web/index.html`: sezione "Animations" nel pannello di destra, e la casella "Include animations" nel
  riquadro di export.
- Modifica: `web/app.js`:
  - `AnimationMixer` sul `gltf.scene`, aggiornato nel ciclo di disegno con un `THREE.Clock`;
  - elenco per gruppo, play/pausa, ripeti e barra del tempo;
  - `speed` diventa `timeScale`; se è negativo si parte dalla fine;
  - `clampWhenFinished` sempre attivo.
- Modifica: `web/style.css`: stili coerenti con il pannello dei materiali.

- [ ] Anteprima `verseforge-dev` (porta 8767):
  - P6-LR: Fire · Bolt si muove;
  - Gladius: Canopy · Open apre il tettuccio e Landing Gear · Deploy apre gli sportelli;
  - Multitool;
  - modello senza clip: nessun pannello e nessun errore nella console.
- [ ] Screenshot da dare all'utente.
- [ ] Commit: "viewer: animations panel".

## Task 9: chiusura della fase A

- [ ] Prove complete verdi.
- [ ] Export GLB del Gladius aperto in Blender (in modo non interattivo, con `--background --python`): ci sono le
  azioni e il nodo `Canopy` ha dei fotogrammi chiave.
- [ ] README (Usage, Animations) e versione 1.6.0 in `__init__.py`, `version_info.txt` e `VerseForge.iss`.
- [ ] Commit: "Release 1.6.0: object animations". Niente build pubblicata né push senza l'ok dell'utente.
