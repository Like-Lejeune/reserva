#!/usr/bin/env bash
# Copie une version livrée en zip (dossier décompressé) dans le dossier de l'application.
#
#   bash copier-version.sh /chemin/du/zip/decompresse /opt/reserva
#
# Remplace le code et le site compilé ; ne touche jamais au fichier .env, à l'environnement
# Python (.venv) ni aux données (/var/lib/reserva). Appelé par installer.sh.
set -euo pipefail

SRC="$1"
DEST="$2"
[ -f "$SRC/web/dist/index.html" ] || { echo "Pas de site compilé dans $SRC/web/dist : ce n'est pas une version zip." >&2; exit 1; }
[ "$(cd "$SRC" && pwd)" != "$(mkdir -p "$DEST" && cd "$DEST" && pwd)" ] || exit 0

# Les fichiers retirés d'une version à l'autre ne doivent pas traîner : on vide ce qui sera remplacé.
rm -rf "$DEST/backend/app" "$DEST/backend/migrations" "$DEST/backend/tests" "$DEST/web/dist" "$DEST/deploy"

items=()
for item in backend web/dist deploy DEPLOIEMENT.md README.md VERSION; do
  [ -e "$SRC/$item" ] && items+=("$item")
done
(cd "$SRC" && tar --exclude='backend/.env' --exclude='backend/.venv' --exclude='backend/data' \
  --exclude='__pycache__' -cf - "${items[@]}") | tar -C "$DEST" -xf -

echo "Version copiée dans $DEST : $(cat "$DEST/VERSION" 2>/dev/null || echo 'inconnue')"
