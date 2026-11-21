# Skin Lab, tappa 1 (colori e finiture): piano di sviluppo

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or
> superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** l'utente crea una skin (colori A/B/C, vetro, finiture) partendo da una vernice del gioco, la vede dal
vivo, la salva in una libreria e la ritrova tra le vernici; vale per navi, armi e armature.

**Architecture:** una skin è un file `.vfskin` che il server trasforma in una "vernice in più" (stesso materiale
della vernice di partenza, tavolozza sostituita), così passa da `get_model`, dallo scambio istantaneo e dagli
export senza strade nuove. Il visualizzatore ricolora dal vivo i materiali usando il campo `tint` del `shading` e
fa confermare il risultato al server con una bozza in memoria.

**Tech stack:** Python (FastAPI, pytest), three.js r160, nessuna dipendenza nuova.

Specifica: `docs/superpowers/specs/2026-11-21-skin-lab-colori-design.md`. Ramo `skin-lab`, cartella di lavoro
`SC-Model-Explorer-skin-lab` (worktree). Prove: `python -m pytest -q` con `VERSEFORGE_DISK_CACHE=0`.

## Scelte prese leggendo il codice (precisano la specifica)

- Il punto unico di risoluzione è `State.variant(path, tag)`: per `skin:<id>` e `skin:draft[:n]` legge la skin,
  trova la vernice di partenza (`skins.find_base`) e applica `skins.apply`; un tag `skin:` sconosciuto dà 404.
  `get_model`, `tag_of`, `swappable` passano da lì. La chiave di cache è `skin:<id>:<mtime>` o `skin:draft:<rev>`.
- Le voci con tag `skin:` non vanno mai nella cache su disco (info, GLB, texture di vernice).
- `/api/model/info` non elenca le skin: il visualizzatore le chiede a `/api/skins?path=` e le unisce ai tasselli.
- I gruppi di vernice per i modelli con meno di 2 vernici si chiedono con il parametro `keyed=true` su
  `/api/model/info`, `/api/model/glb`, `/api/model/paint`; il visualizzatore lo manda quando il modello ha skin o si
  è nel Skin Lab. Il parametro entra nella chiave del GLB su disco.
- `tint` nel `shading`: `{slot, base}` (base = il valore che moltiplicato per la tinta dà `albedo`); la maschera
  mimetica che usa la tavolozza porta `stencil.tinted = true`. Dal vivo si ricolorano i materiali `solid` e i
  colori della maschera; decal e vetro si aggiornano con la conferma del server (entro ~0,5 s).
- Import dal visualizzatore con `<input type=file>` (funziona in finestra e nel browser); Export salva nella
  cartella degli export e mostra il percorso.
- `diskcache.FORMAT` 12 → 13 (i nomi dei materiali nel GLB cambiano perché cambia l'id del `shading`).

## File

| File | Cosa |
|---|---|
| `sc_explorer/skins.py` (nuovo) | formato, `validate`, libreria su disco, `effective`, `find_base`, `apply`, preset |
| `sc_explorer/materials.py` | `Material.tint`, `tint` in `shading()`, `stencil.tinted` |
| `sc_explorer/server.py` | `State.variant`, bozza, `keyed`, chiamate `/api/skins*`, niente cache su disco per le skin |
| `sc_explorer/i18n.py`, `web/locales/*.json` | testi del Skin Lab nelle 11 lingue |
| `web/gamelook.js` | `userData.tint`, `retint()` |
| `web/skinlab.js` (nuovo) | la modalità: stato della skin, pannelli, dal vivo, conferma, libreria |
| `web/app.js` | entrata/uscita, tasselli delle skin, `keyed` nelle richieste |
| `web/index.html`, `web/style.css` | pulsante, due pannelli del Lab |
| `tests/test_skins.py`, `tests/test_skins_api.py`, `tests/test_skins_game.py` (nuovi) | prove |
| `tools/skin_check.py` (nuovo) | confronto dal vivo / conferma, tempi |

## Task

### Task 1: `skins.py`, formato e libreria
- [x] prove: `validate` (tipi, intervalli, formato più nuovo, nome), scrittura e rilettura, zip rotto, nomi doppi,
      campi sconosciuti conservati, cancellazione
- [x] `validate`, `new_id`, `save`, `load`, `list_skins`, `delete`, `import_bytes`, `export_path`
- [x] commit

### Task 2: `skins.py`, tavolozza effettiva
- [x] prove: i cinque preset, tavolozza sempre completa, cursore fine, `find_base` per materiale + tavolozza con
      elenco riordinato, base sparita → di serie, modello senza vernici
- [x] `PRESETS`, `effective(base_palette, skin)`, `find_base(variants, skin)`, `apply(base, skin)`
- [x] commit

### Task 3: `tint` nei materiali
- [x] prove (su XML finti, come `test_paints.py`): `shading()["tint"]`, base × tinta = albedo, `stencil.tinted`,
      skin senza modifiche = vernice di partenza per colore
- [x] `Material.tint`, `_material`, `_hull_stencil`, `shading`; `FORMAT` 13
- [x] commit

### Task 4: server, skin come vernice
- [x] prove col TestClient (stato finto come `test_paint_api.py`): `State.variant`, 404, chiave che cambia al
      salvataggio, bozza, `keyed`
- [x] `State.variant`, `tag_of`, `get_model`, `keyed(path, force)`, `swappable`, bozza, salto della cache su disco
- [x] chiamate `/api/skins`, `/api/skins/{id}`, `/api/skins/draft`, `/api/skins/base`, import, export
- [x] commit

### Task 5: testi
- [x] chiavi in `i18n.py` e nelle 10 lingue; `tests/test_i18n.py` verde
- [x] commit

### Task 6: `retint` nel visualizzatore
- [x] `gamelook.js`: `userData.tint`, `retint(materials, palette)`; `paint.js`: niente da cambiare oltre a esporre
      i materiali vivi
- [x] commit

### Task 7: schermata Skin Lab
- [x] `index.html` + `style.css`: pulsante nella barra, pannello strumenti (sinistra), pannello libreria (destra)
- [x] `skinlab.js`: entrata (ricarica con `keyed` se serve, sfondo studio), righe colore con selettore, esadecimale
      e campioni, finiture, vetro, dal vivo + conferma a 300 ms, Save / Save as copy / Delete / Import / Export /
      Compare / Exit, conferma all'uscita con modifiche non salvate
- [x] `app.js`: skin tra i tasselli con segno, "+ New skin", `keyed` nelle richieste, export con la skin scelta
- [x] commit

### Task 8: prove sul gioco e nell'anteprima
- [x] `tests/test_skins_game.py` (saltate senza `Data.p4k`): una nave, un'arma, un'armatura; GLB esportato coi
      colori della skin
- [ ] `tools/skin_check.py` (non fatto: misure prese a mano)
- [x] prova a mano nell'anteprima con screenshot (`docs/anteprime/skin-lab/`)
- [x] tutte le prove verdi; commit

## Fuori dal piano

Motivi, decal, mimetico negli export, scheda di pittura, skin su un altro modello, galleria: tappe 2-5.
