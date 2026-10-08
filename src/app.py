"""Compare published fuel prices within 15 km of an Italian municipality."""

from __future__ import annotations

from datetime import datetime, timedelta
from html import escape
from io import StringIO
from math import cos, radians
from pathlib import Path
from zoneinfo import ZoneInfo

import folium
import numpy as np
import pandas as pd
import requests
import streamlit as st
from branca.colormap import LinearColormap
from streamlit_folium import st_folium


STATIONS_URL = "https://www.mimit.gov.it/images/exportCSV/anagrafica_impianti_attivi.csv"
PRICES_URL = "https://www.mimit.gov.it/images/exportCSV/prezzo_alle_8.csv"
SOURCE_URL = "https://www.mimit.gov.it/it/open-data/elenco-dataset/carburanti-prezzi-praticati-e-anagrafica-degli-impianti"
ISTAT_URL = "https://www.istat.it/notizia/confini-delle-unita-amministrative-a-fini-statistici-al-1-gennaio-2018-2/"
CENTERS_PATH = Path(__file__).resolve().parents[1] / "resources" / "municipality_centers.csv"
RADIUS_KM = 15
STALE_AFTER = timedelta(days=7)
TABLE_PAGE_SIZE = 20
CHEAP_COLOR = "#00ad42"
AVERAGE_COLOR = "#ffd843"
EXPENSIVE_COLOR = "#d92323"


def read_ministry_csv(content: bytes, required_columns: set[str]) -> tuple[pd.DataFrame, str]:
    """Read either the current pipe-delimited feed or an older semicolon feed."""
    lines = content.decode("utf-8-sig").splitlines()
    if len(lines) < 3 or not lines[0].startswith("Estrazione del "):
        raise ValueError("The ministry returned an unexpected CSV format.")

    extraction_date = lines[0].removeprefix("Estrazione del ").strip()
    separator = "|" if "|" in lines[1] else ";"
    frame = pd.read_csv(
        StringIO("\n".join(lines[1:])),
        sep=separator,
        dtype={"idImpianto": "string"},
        on_bad_lines="skip",  # Older semicolon files contain unquoted addresses.
        low_memory=False,
    )
    if not required_columns.issubset(frame.columns):
        raise ValueError("The ministry CSV columns have changed.")
    return frame, extraction_date


@st.cache_data(ttl=3600, show_spinner="Caricamento dei dati del Ministero...")
def load_data() -> tuple[pd.DataFrame, str]:
    """Fetch the two daily ministry files and join prices to active stations."""
    response_stations = requests.get(STATIONS_URL, timeout=30)
    response_stations.raise_for_status()
    response_prices = requests.get(PRICES_URL, timeout=30)
    response_prices.raise_for_status()

    stations, _ = read_ministry_csv(
        response_stations.content,
        {"idImpianto", "Bandiera", "Indirizzo", "Comune", "Provincia", "Latitudine", "Longitudine"},
    )
    prices, prices_date = read_ministry_csv(
        response_prices.content,
        {"idImpianto", "descCarburante", "prezzo", "isSelf", "dtComu"},
    )
    return prepare_data(stations, prices), prices_date


def prepare_data(stations: pd.DataFrame, prices: pd.DataFrame) -> pd.DataFrame:
    """Clean coordinates and prices, then attach station details to each offer."""
    for column in ("Comune", "Provincia", "Bandiera", "Indirizzo"):
        stations[column] = stations[column].fillna("").astype(str).str.strip()
    for column in ("Latitudine", "Longitudine"):
        stations[column] = pd.to_numeric(stations[column], errors="coerce")
    stations = stations.loc[
        stations["Comune"].ne("")
        & stations["Provincia"].ne("")
        & stations["Latitudine"].between(35, 48)
        & stations["Longitudine"].between(6, 19)
    ]

    prices["prezzo"] = pd.to_numeric(prices["prezzo"], errors="coerce")
    prices["isSelf"] = pd.to_numeric(prices["isSelf"], errors="coerce")
    prices["dtComu"] = pd.to_datetime(prices["dtComu"], dayfirst=True, errors="coerce")
    prices = prices.loc[prices["prezzo"].gt(0) & prices["isSelf"].isin([0, 1])]

    data = prices.merge(stations, on="idImpianto", how="inner")
    if data.empty:
        raise ValueError("No usable station prices were found in the ministry files.")
    return data


@st.cache_data
def load_centers() -> pd.DataFrame:
    """Read municipality centers derived from ISTAT's 2026 boundaries."""
    return pd.read_csv(CENTERS_PATH, dtype={"code": "string"}, keep_default_na=False)


def find_nearby(
    data: pd.DataFrame, center_lat: float, center_lon: float, fuel: str, self_service: bool
) -> pd.DataFrame:
    """Return all matching stations within 15 km, ordered by price."""
    matching = data.loc[
        data["descCarburante"].eq(fuel)
        & data["isSelf"].eq(int(self_service))
    ].copy()
    latitudes = np.radians(matching["Latitudine"].to_numpy(dtype=float))
    longitudes = np.radians(matching["Longitudine"].to_numpy(dtype=float))
    center_lat_rad = radians(center_lat)
    center_lon_rad = radians(center_lon)
    haversine = (
        np.sin((latitudes - center_lat_rad) / 2) ** 2
        + cos(center_lat_rad) * np.cos(latitudes) * np.sin((longitudes - center_lon_rad) / 2) ** 2
    )
    matching["distance_km"] = 2 * 6371.0088 * np.arcsin(np.sqrt(np.clip(haversine, 0, 1)))
    matching = matching.loc[matching["distance_km"].le(RADIUS_KM)]
    return (
        matching.sort_values(["prezzo", "dtComu"], ascending=[True, False])
        .drop_duplicates("idImpianto")
        .reset_index(drop=True)
    )


def price_legend_html(stations: pd.DataFrame, unit: str) -> str:
    """Build a color scale that fits the available width above the map."""
    minimum = float(stations["prezzo"].min())
    average = float(stations["prezzo"].mean())
    maximum = float(stations["prezzo"].max())
    if minimum == maximum:
        bar_color = AVERAGE_COLOR
        labels = f"Prezzo unico: €{minimum:.3f}/{escape(unit)}"
    else:
        mean_position = 100 * (average - minimum) / (maximum - minimum)
        bar_color = (
            f"linear-gradient(to right, {CHEAP_COLOR} 0%, "
            f"{AVERAGE_COLOR} {mean_position:.2f}%, {EXPENSIVE_COLOR} 100%)"
        )
        labels = (
            f'<span>Min €{minimum:.3f}/{escape(unit)}</span>'
            f'<span>Media €{average:.3f}/{escape(unit)}</span>'
            f'<span>Max €{maximum:.3f}/{escape(unit)}</span>'
        )
    return (
        '<div style="width:100%;max-width:480px;box-sizing:border-box;margin:0.25rem 0 0.75rem">'
        f'<div style="font-weight:600;margin-bottom:0.4rem">Prezzo €/{escape(unit)}</div>'
        f'<div style="width:100%;height:14px;border-radius:8px;background:{bar_color}"></div>'
        '<div style="display:flex;flex-wrap:wrap;justify-content:space-between;gap:0.25rem;'
        f'font-size:0.82rem;margin-top:0.3rem">{labels}</div>'
        '</div>'
    )


def station_map(
    stations: pd.DataFrame,
    center_lat: float,
    center_lon: float,
    unit: str,
    now: datetime,
) -> folium.Map:
    """Show the 15 km search area and price-colored station markers."""
    center = [center_lat, center_lon]
    map_view = folium.Map(
        location=center, zoom_start=11, tiles="OpenStreetMap", control_scale=True, prefer_canvas=True
    )
    folium.Circle(
        location=center, radius=RADIUS_KM * 1000, color="#4b5563", weight=2, fill=False, dash_array="5, 5"
    ).add_to(map_view)

    if not stations.empty:
        minimum = float(stations["prezzo"].min())
        average = float(stations["prezzo"].mean())
        maximum = float(stations["prezzo"].max())
        if minimum == maximum:
            colors = LinearColormap(
                [AVERAGE_COLOR, AVERAGE_COLOR], vmin=minimum - 0.001, vmax=maximum + 0.001
            )
        else:
            colors = LinearColormap(
                [CHEAP_COLOR, AVERAGE_COLOR, EXPENSIVE_COLOR],
                index=[minimum, average, maximum],
                vmin=minimum,
                vmax=maximum,
            )

    for row in stations.itertuples(index=False):
        label = f"€{row.prezzo:.3f}/{unit} · {row.distance_km:.1f} km"
        if pd.isna(row.dtComu):
            updated = "non disponibile"
            warning = "<br><strong>⚠️ Data del prezzo non disponibile</strong>"
        else:
            updated = row.dtComu.strftime("%d/%m/%Y")
            warning = (
                "<br><strong>⚠️ Prezzo comunicato oltre 7 giorni fa</strong>"
                if row.dtComu < now - STALE_AFTER else ""
            )
        update_html = f"Ultimo aggiornamento: {escape(updated)}{warning}"
        details = (
            f"<strong>{escape(label)}</strong><br>"
            f"{escape(str(row.Bandiera))}<br>{escape(str(row.Indirizzo))}<br>"
            f"{escape(str(row.Comune))} ({escape(str(row.Provincia))})<br>"
            f"{update_html}"
        )
        folium.CircleMarker(
            location=[row.Latitudine, row.Longitudine],
            radius=7,
            color="#ffffff",
            weight=1,
            fill=True,
            fill_color=colors(row.prezzo),
            fill_opacity=0.9,
            popup=folium.Popup(details, max_width=300),
        ).add_to(map_view)

    lat_span = RADIUS_KM / 111.32
    lon_span = RADIUS_KM / (111.32 * cos(radians(center_lat)))
    map_view.fit_bounds(
        [[center_lat - lat_span, center_lon - lon_span],
         [center_lat + lat_span, center_lon + lon_span]],
        padding=(20, 20),
    )
    return map_view


def main() -> None:
    st.set_page_config(page_title="Prezzi carburante Italia", page_icon="⛽", layout="wide")
    st.title("⛽ Trova il distributore più conveniente")
    st.warning(
        "Un prezzo comunicato più di 7 giorni fa potrebbe essere superato: tocca o clicca un punto sulla mappa per controllare la data.",
        icon="⚠️",
    )
    st.caption("Confronta i prezzi comunicati al Ministero entro 15 km dal centro di un comune italiano.")

    try:
        data, extraction_date = load_data()
        centers = load_centers()
    except (requests.RequestException, ValueError, pd.errors.ParserError) as error:
        st.error(f"Impossibile caricare i dati del Ministero: {error}")
        st.stop()

    centers = centers.sort_values(["municipality", "province"])
    choices = {
        row.code: f"{row.municipality} ({row.province})"
        for row in centers.itertuples(index=False)
    }
    default_location = "058091" if "058091" in choices else next(iter(choices))
    fuel_options = sorted(data["descCarburante"].dropna().unique())

    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        location_code = st.selectbox(
            "Comune", options=list(choices), index=list(choices).index(default_location), format_func=choices.get
        )
    with col2:
        fuel = st.selectbox(
            "Carburante", options=fuel_options, index=fuel_options.index("Benzina") if "Benzina" in fuel_options else 0
        )
    with col3:
        service = st.selectbox("Servizio", options=["Self service", "Servito"])

    location = centers.loc[centers["code"].eq(location_code)].iloc[0]
    selected = find_nearby(
        data, location["latitude"], location["longitude"], fuel, service == "Self service"
    )
    st.caption(
        f"Dati estratti il {extraction_date} · Prezzi alle 8:00 · "
        "Il prezzo alla pompa può essere cambiato."
    )
    unit = "kg" if fuel.casefold().startswith("metano") else "L"
    now = datetime.now(ZoneInfo("Europe/Rome")).replace(tzinfo=None)
    st.subheader(f"{len(selected)} distributori entro 15 km da {location['municipality']}")
    if selected.empty:
        st.info("Nessun prezzo disponibile in questo raggio per la scelta fatta.")
    else:
        min_col, mean_col, max_col = st.columns(3)
        min_col.metric("Prezzo più basso", f"€{selected['prezzo'].min():.3f}/{unit}")
        mean_col.metric("Prezzo medio", f"€{selected['prezzo'].mean():.3f}/{unit}")
        max_col.metric("Prezzo più alto", f"€{selected['prezzo'].max():.3f}/{unit}")
        st.html(price_legend_html(selected, unit), width="stretch")

    st_folium(
        station_map(selected, location["latitude"], location["longitude"], unit, now),
        height=500,
        use_container_width=True,
        returned_objects=[],
        key=f"map-{location_code}-{fuel}-{service}-{extraction_date}",
    )
    st.caption("Il cerchio tratteggiato mostra i 15 km dal centro del comune.")
    st.caption(
        f"Fonti: [prezzi MIMIT]({SOURCE_URL}) · [centri comunali ISTAT]({ISTAT_URL})."
    )

    if not selected.empty:
        page_count = (len(selected) + TABLE_PAGE_SIZE - 1) // TABLE_PAGE_SIZE
        page = st.selectbox(
            "Pagina della tabella",
            options=range(1, page_count + 1),
            format_func=lambda number: f"{number} di {page_count}",
            key=f"table-page-{location_code}-{fuel}-{service}",
        )
        start = (page - 1) * TABLE_PAGE_SIZE
        page_stations = selected.iloc[start:start + TABLE_PAGE_SIZE]
        table = page_stations[["prezzo", "distance_km", "Bandiera", "Comune", "Indirizzo", "dtComu"]].copy()
        table.insert(0, "#", range(start + 1, start + len(table) + 1))
        table["prezzo"] = table["prezzo"].map(lambda price: f"€{price:.3f}/{unit}")
        table["distance_km"] = table["distance_km"].map(lambda distance: f"{distance:.1f} km")
        stale = table["dtComu"].isna() | table["dtComu"].lt(now - STALE_AFTER)
        table["dtComu"] = table["dtComu"].dt.strftime("%d/%m/%Y").fillna("—")
        table.loc[stale, "dtComu"] += " ⚠️"
        table.columns = ["#", "Prezzo", "Distanza (Linea d'aria)", "Bandiera", "Comune", "Indirizzo", "Ultimo aggiornamento"]
        st.table(table, hide_index=True, width="stretch", height="content")

    st.divider()
    st.markdown(
        "Le informazioni sono indicative e possono essere inesatte o non aggiornate. "
        "Verifica sempre il prezzo esposto al distributore: l'autore del sito non si assume "
        "responsabilità per errori nei dati o decisioni prese sulla base delle informazioni mostrate. 🦝"
    )


if __name__ == "__main__":
    main()
