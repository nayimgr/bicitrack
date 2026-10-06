# bicitrack

¿A qué hora reponen BiciMAD? Recoge cada minuto el estado de las estaciones
(feed GBFS público de BiciMAD), detecta reposiciones y retiradas por los saltos
bruscos en el número de bicis, y publica un dashboard en GitHub Pages.

| Archivo | Qué hace |
|---|---|
| `collector.py` | Consulta el feed y guarda los cambios en `bicimad.sqlite` (solo librería estándar) |
| `detect_refills.py` | Análisis offline: `events.csv`, resumen por estación y gráficas |
| `export_dashboard.py` | Genera el `data.json` que lee el dashboard |
| `docs/index.html` | Dashboard (mapa, reloj de 24 h, histograma, heatmap, tabla) |
| `publish.sh` | Exporta y publica en la rama `gh-pages` |
| `bicitrack.service` | Servicio systemd de usuario para dejar el recolector corriendo |

Requisitos para análisis y dashboard: `pip install -r requirements.txt`

Ver el dashboard en local:

    python export_dashboard.py --out docs/data.json
    cd docs && python -m http.server 8000     # abre http://localhost:8000
