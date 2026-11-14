# Fase B, interruttore "Full ship": piano di lavoro

> **Per chi esegue:** si usa superpowers:executing-plans. Le caselle `- [ ]` servono a segnare i passi fatti.

**Obiettivo:** con un interruttore, la nave o il veicolo si carica con il loadout di base e le gambe del carrello al
loro posto. Le animazioni dello scafo muovono anche i componenti, e "Landing Gear · Deploy" fa uscire le gambe. Spec:
`docs/superpowers/specs/2026-11-14-animazioni-oggetti-design.md`, sezione Fase B.

## Fatti verificati (14/11, Gladius)

- **Carrello**: `VehicleComponentParams.landingSystem` porta al record `VehicleLandingGearSystem`.
  - Il record ha `gears[]`, con `bone` (snodo dello scafo, ad esempio `helper_landing_gear_front`) e
    `geometry.path` (la `.cdf` della gamba).
  - `fragment` = `Landing_Gear`, `fragmentDeploy` = `Deploy`.
- **Loadout**: `SEntityComponentDefaultLoadoutParams.loadout.entries[]` contiene `itemPortName`, `entityClassName` o
  `entityClassReference`, e un `loadout` annidato (facoltativo).
  - Sul Gladius 56 porte su 60 sono snodi della `.cga`. Le 4 mancanti sono controller e ganci senza geometria.
- **Clip in comune**: le gambe hanno `landing_gear_extend`, `retract` e `compress`. L'`.adb` dello scafo usa
  `landing_gear_extend` per Deploy (velocità 1) e per Retract (−1).

## Scelte

- **Le animazioni si uniscono per nome di clip, non per `id` di azione.** È un cambiamento rispetto alla spec, perché
  le gambe non hanno un `.adb` e la loro azione si chiamerebbe "Extend", non "Deploy".
  - Una clip glTF unica, per esempio `landing_gear_extend`, contiene i canali di tutte le istanze.
  - Le azioni dello scafo restano quelle dell'`.adb`.
  - Le azioni dei componenti la cui clip non è già usata dallo scafo si aggiungono una volta sola per `id`, ad esempio
    "Landing Gear · Compress".
- **Istanze e nomi**: ogni componente animato porta il suo scheletro con il prefisso `porta/` (o `porta/porta/` se è
  annidato), e la sua radice diventa figlia dello snodo della porta. I componenti statici sono pezzi con
  `node = snodo della porta`.
- **Sorgenti delle animazioni**: `Model.anim_sets = [AnimSet(prefix, refs)]`, con prefisso `""` per lo scafo.
  - `animations.sources(archive, model)` restituisce `[(nome clip, Clip, {hash: nome nodo})]` e gli avvisi.
  - `export.to_glb(…, sources=…)` sostituisce `clips=`.
  - `anim_glb.add_animations(glb, sources)` fonde i canali con lo stesso nome.

## Task

1. **`entities.build` v2**: aggiunge `vehicles`, cioè `percorso geometria → {"tree": [...], "gears": [...]}` per le entità
   con `VehicleComponentParams`.
   - Ogni nodo è `{port, geometry, adb, children}` e viene da `entityClassName` (indice per nome, senza badare a
     maiuscole e minuscole) o da `entityClassReference`.
   - I figli vengono dal `loadout` annidato, se c'è, altrimenti dal loadout di base dell'entità figlia.
   - Profondità massima 4. Le entità senza geometria si saltano, insieme ai loro figli.
   - `gears` = `[{port: bone, geometry}]`.
   - Cache `entities_v2_*`.
   - Prova: il Gladius ha le 3 gambe, `hardpoint_thruster_main_left` porta a una `.cga` del propulsore, e c'è almeno un
     figlio annidato su una porta d'arma.
2. **anim_set e sources**:
   - `rig.attach` riempie `model.anim_sets = [AnimSet("", refs)]`;
   - `animations.sources`;
   - `anim_glb.add_animations(glb, sources)`, con la fusione per nome;
   - `export.to_glb(sources=)`;
   - aggiornare il server e le prove.
   - Tutte le prove della fase A devono restare verdi.
3. **`model.load_full(archive, path, vehicle, adb_path)`**:
   - lo scafo si carica con lo scheletro anche se è statico (`rig.skeleton`);
   - per ogni nodo dell'albero si chiama `load_model` (con l'`.adb` del componente, se c'è), si cerca la porta nello
     scheletro del genitore, si spostano i vertici con la matrice world della porta, si rinominano gli snodi con il
     prefisso e si aggiunge l'AnimSet;
   - porte mancanti: avviso `warn_ports_missing` con il conteggio;
   - azioni unite come descritto sopra;
   - prova: il Gladius completo ha più triangoli, 3 istanze di gamba, e la sorgente `landing_gear_extend` tocca nodi
     dello scafo e di tutte e 3 le gambe.
4. **Server e interfaccia**:
   - `full: bool` su `info`, `glb`, `export` e `print`, con la chiave di cache `(path, variant, full)`;
   - `can_full` in `info`;
   - interruttore "Full ship" ("Full vehicle" per i veicoli di terra) nella barra degli strumenti in alto a destra del
     visualizzatore, ricordato per la sessione.
5. **Verifica**:
   - Gladius, Cutlass Black, Avenger Titan, Aurora MR e un veicolo di terra (Cyclone);
   - tempi misurati, completo contro solo scafo;
   - render Blender di prima e dopo Deploy;
   - README e versione 1.7.0.
