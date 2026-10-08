# Petrol Station Italy

Il prezzo del carburante può cambiare molto anche tra distributori vicini. Petrol Station Italy aiuta a trovare dove fare rifornimento spendendo meno, senza controllare ogni stazione una per una.

Scegli un comune italiano, il carburante e la modalità self-service o servito. La mappa mostra i distributori disponibili entro 15 km in linea d'aria dal centro del comune, anche nei comuni vicini. I punti verdi indicano i prezzi più convenienti, quelli gialli sono vicini alla media e quelli rossi sono i più cari. La tabella elenca tutti i distributori trovati, ordinati per prezzo.

I prezzi provengono dai [dati pubblicati ogni giorno dal Ministero delle Imprese e del Made in Italy](https://www.mimit.gov.it/it/open-data/elenco-dataset/carburanti-prezzi-praticati-e-anagrafica-degli-impianti). I centri dei comuni sono ricavati dai [confini ISTAT del 2026](https://www.istat.it/notizia/confini-delle-unita-amministrative-a-fini-statistici-al-1-gennaio-2018-2/). Tocca o clicca un punto sulla mappa per vedere la data dell'ultimo aggiornamento; un avviso segnala i prezzi comunicati più di sette giorni fa. Il prezzo alla pompa potrebbe essere cambiato.

## Avvio in locale

Servono Python 3.11 o successivo e [uv](https://docs.astral.sh/uv/).

```sh
uv sync
uv run streamlit run src/app.py
```

L'app richiede una connessione Internet per caricare i dati. Su Streamlit Community Cloud, imposta `src/app.py` come file principale.
