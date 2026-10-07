# bicitrack

¿A qué hora reponen BiciMAD? Recoge cada minuto el estado de las estaciones
(feed GBFS público de BiciMAD) y publica en GitHub Pages un dashboard con la
ocupación de cada estación a lo largo del tiempo. La detección de reposiciones
(`detect_refills.py`) queda como análisis offline hasta que haya datos
suficientes para ver dónde está la señal.

| Archivo | Qué hace |
|---|---|
| `collector.py` | Consulta el feed y guarda los cambios en `bicimad.sqlite` (solo librería estándar) |
| `detect_refills.py` | Análisis offline de reposiciones: `events.csv`, resumen por estación y gráficas |
| `export_dashboard.py` | Genera el `data.json` del dashboard: ocupación cada 15 min de los últimos 7 días, día típico y % de tiempo vacía/llena (`--step`, `--days`) |
| `docs/index.html` | Dashboard (mapa de ocupación, serie temporal, día típico, mapa de calor de todas las estaciones, tabla) |
| `publish.sh` | Exporta y publica en la rama `gh-pages` |
| `bicitrack.service` | Servicio systemd de usuario para dejar el recolector corriendo |

Requisitos para análisis y dashboard: `pip install -r requirements.txt`

Ver el dashboard en local:

    python export_dashboard.py --out docs/data.json
    cd docs && python -m http.server 8000     # abre http://localhost:8000
