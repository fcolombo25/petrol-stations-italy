import unittest
from datetime import datetime

import folium
from src.app import (
    RADIUS_KM,
    find_nearby,
    load_centers,
    prepare_data,
    price_legend_html,
    read_ministry_csv,
    station_map,
)


class PetrolAppTests(unittest.TestCase):
    def test_current_and_legacy_csv_separators(self):
        for separator in ("|", ";"):
            content = (
                f"Estrazione del 2026-10-07\n"
                f"idImpianto{separator}prezzo\n"
                f"1{separator}1.749\n"
            ).encode()
            frame, extraction_date = read_ministry_csv(content, {"idImpianto", "prezzo"})
            self.assertEqual(extraction_date, "2026-10-07")
            self.assertEqual(frame.iloc[0]["prezzo"], 1.749)

    def test_radius_includes_neighboring_municipalities_and_excludes_far_stations(self):
        station_csv = (
            "Estrazione del 2026-10-07\n"
            "idImpianto|Bandiera|Indirizzo|Comune|Provincia|Latitudine|Longitudine\n"
            "1|Brand A|Via Uno|TEST|AA|41.9|12.5\n"
            "2|Brand B|Via Due|NEIGHBOR|BB|41.95|12.5\n"
            "3|Brand C|Via Tre|TEST|AA|41.7|12.5\n"
            "4|Brand D|Via Quattro|TEST|AA|0|0\n"
            "5|Brand E|Via Cinque|NEIGHBOR|BB|41.85|12.5\n"
        ).encode()
        price_csv = (
            "Estrazione del 2026-10-07\n"
            "idImpianto|descCarburante|prezzo|isSelf|dtComu\n"
            "1|Benzina|1.6|1|07/10/2026 08:00:00\n"
            "2|Benzina|1.8|1|07/10/2026 08:00:00\n"
            "3|Benzina|1.1|1|07/10/2026 08:00:00\n"
            "4|Benzina|1.2|1|07/10/2026 08:00:00\n"
            "5|Benzina|2.0|1|07/10/2026 08:00:00\n"
        ).encode()
        stations, _ = read_ministry_csv(station_csv, {"idImpianto", "Comune"})
        prices, _ = read_ministry_csv(price_csv, {"idImpianto", "prezzo"})
        data = prepare_data(stations, prices)

        matching = find_nearby(data, 41.9, 12.5, "Benzina", True)
        self.assertEqual(matching["idImpianto"].tolist(), ["1", "2", "5"])
        self.assertTrue(matching["distance_km"].le(RADIUS_KM).all())
        self.assertAlmostEqual(matching["prezzo"].mean(), 1.8)
        self.assertTrue(find_nearby(data, 41.9, 12.5, "Gasolio", True).empty)
        map_view = station_map(matching, 41.9, 12.5, "L", datetime(2026, 10, 8, 8))
        map_html = map_view.get_root().render()
        self.assertIn("#00ad42", map_html)
        self.assertIn("#d92323", map_html)
        self.assertIn("€1.600/L", map_html)
        self.assertNotIn("legend.leaflet-control", map_html)
        self.assertIn("Ultimo aggiornamento: 07/10/2026", map_html)
        self.assertNotIn("Ultimo aggiornamento: 07/10/2026 08:00", map_html)
        self.assertNotIn("⚠️ Prezzo comunicato oltre 7 giorni fa", map_html)
        self.assertEqual(
            sum(type(child) is folium.CircleMarker for child in map_view._children.values()),
            len(matching),
        )
        for marker in map_view._children.values():
            if type(marker) is folium.CircleMarker:
                self.assertFalse(any(isinstance(child, folium.Tooltip) for child in marker._children.values()))
                self.assertTrue(any(isinstance(child, folium.Popup) for child in marker._children.values()))
        stale_html = station_map(
            matching, 41.9, 12.5, "L", datetime(2026, 10, 15, 8, 1)
        ).get_root().render()
        self.assertIn("⚠️ Prezzo comunicato oltre 7 giorni fa", stale_html)
        legend = price_legend_html(matching, "L")
        self.assertIn("width:100%;max-width:480px", legend)
        self.assertIn("#ffd843 50.00%", legend)
        self.assertIn("Min €1.600/L", legend)
        self.assertIn("Media €1.800/L", legend)
        self.assertIn("Max €2.000/L", legend)
        self.assertIn("Prezzo unico: €1.600/L", price_legend_html(matching.head(1), "L"))

    def test_centers_include_municipalities_without_price_data(self):
        centers = load_centers()
        self.assertEqual(len(centers), 7894)
        self.assertEqual(centers.loc[centers.code.eq("058091"), "municipality"].iloc[0], "Roma")
        self.assertEqual(centers.loc[centers.code.eq("063049"), "province"].iloc[0], "NA")


if __name__ == "__main__":
    unittest.main()
