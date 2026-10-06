#!/usr/bin/env bash
# Exporta data.json y publica index.html + data.json en la rama gh-pages.
# La rama se reescribe en cada publicación (force push), así el historial
# del repo no crece con cada actualización de datos.
#
# Uso:  ./publish.sh            (usa python3)
#       PYTHON=/ruta/a/python ./publish.sh
set -euo pipefail
cd "$(dirname "$0")"
PYTHON="${PYTHON:-python3}"
DB="${DB:-bicimad.sqlite}"

REMOTE="$(git remote get-url origin)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

cp docs/index.html "$TMP/"
"$PYTHON" export_dashboard.py --db "$DB" --out "$TMP/data.json"
touch "$TMP/.nojekyll"

cd "$TMP"
git init -q -b gh-pages
git add -A
git commit -q -m "Datos $(date '+%Y-%m-%d %H:%M')"
git push -q -f "$REMOTE" gh-pages
echo "Publicado $(date '+%Y-%m-%d %H:%M')"
