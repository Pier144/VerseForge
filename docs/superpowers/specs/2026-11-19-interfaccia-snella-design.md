# Interfaccia snella (proposta A + nascondi pannelli)

19/11/2026. L'utente trova l'interfaccia troppo piena di testo e pulsanti. Ha scelto la proposta A delle anteprime
in `docs/anteprime/interfaccia/` più il tasto che nasconde i pannelli. Stile (vetro, colori) e funzioni restano.

## Cosa cambia

1. **Colonna sinistra** (320 → 280 px). Categorie: griglia di sole icone, 7 per riga; nome e numero nel suggerimento.
   Il conteggio sopra l'elenco dice la categoria scelta ("Ships · 113"). Elenco: una riga per modello, nome a
   sinistra e costruttore a destra; con "Main models" spento a destra c'è il nome del file. Percorso nel suggerimento.
2. **Barra in basso**: solo icone. Il nome compare subito passando sopra (suggerimento disegnato dall'app, non quello
   lento del sistema). In più un pulsante "pannelli".
3. **Pillole in alto**: restano Full ship e Interiors. Textures, Decals, Glass, Screens e Proxy vanno nel menu "Layers".
4. **Pannello destro** (324 → 300 px). Misure su una riga (larghezza × lunghezza × altezza, triangoli, parti; i valori
   completi nel suggerimento). Sotto la vernice, quattro schede a icona, quella aperta mostra anche il nome:
   Animations, Export, 3D print (stampa + foglio decal), Materials (materiali + stessa cartella). Una scheda senza
   contenuto per il modello aperto non si vede. La scheda scelta si ricorda (`vf.ptab`).
5. **Nascondi pannelli**: pulsante nella barra e tasto H (Esc li riporta). Spariscono barra in alto, colonna sinistra
   e pannello destro; la vista si ricentra sulla finestra intera. Non si ricorda al riavvio.

## Come

Solo `web/` (index.html, style.css, app.js) più due testi nuovi nelle 11 lingue (`layersBtn`, `panelsTitle`).
Gli id dei controlli non cambiano (`texOn`, `data-kind`, `fullOn`, `intOn`, i riquadri `*Box`), così il resto del
codice e gli strumenti in `tools/` continuano a funzionare. Le schede sono un attributo `data-ptab` sul pannello e
sui riquadri: il CSS nasconde quelli delle altre schede, un osservatore tiene i pulsanti in pari con i riquadri
che il codice mostra o nasconde.

## Prove

`pytest` (le prove i18n controllano che ogni lingua abbia i testi nuovi), poi a mano nell'anteprima: nave con
animazioni, modello senza animazioni, menu Layers, schede, H/Esc, tema chiaro, finestra stretta.
