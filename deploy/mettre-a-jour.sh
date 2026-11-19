#!/usr/bin/env bash
# Met Reserva à jour avec la dernière version de GitHub.
#
#   sudo bash /opt/reserva/deploy/mettre-a-jour.sh
#
# Récupère le code, installe les dépendances, recompile le site et relance le service.
# Les migrations de la base s'appliquent seules au redémarrage. Une sauvegarde est faite avant.
set -euo pipefail

APP_DIR=/opt/reserva
APP_USER=reserva
UV=/home/$APP_USER/.local/bin/uv
GIT=1
RESTART=1
for arg in "$@"; do
  case "$arg" in
    --sans-git) GIT=0 ;;
    --sans-redemarrage) RESTART=0 ;;
  esac
done

[ "$(id -u)" -eq 0 ] || { echo "Lancez ce script avec sudo." >&2; exit 1; }
as_app() { sudo -u "$APP_USER" -H "$@"; }

if [ "$RESTART" -eq 1 ] && systemctl is-active --quiet reserva; then
  echo "==> Sauvegarde avant mise à jour"
  systemctl start reserva-sauvegarde.service
fi

if [ "$GIT" -eq 1 ]; then
  echo "==> Récupération du code"
  as_app git -C "$APP_DIR" pull --ff-only
  as_app git -C "$APP_DIR" log -1 --format='Version : %h %s'
fi

echo "==> Python et dépendances du serveur"
as_app bash -c "cd $APP_DIR/backend && $UV venv --python 3.12 --allow-existing .venv && $UV pip install --python .venv/bin/python -e ."

echo "==> Compilation du site"
as_app bash -c "cd $APP_DIR/web && npm ci --no-audit --no-fund && npm run build"

if [ "$RESTART" -eq 1 ]; then
  echo "==> Redémarrage"
  systemctl restart reserva
  for _ in $(seq 1 20); do
    curl -fsS http://127.0.0.1:8000/health >/dev/null && { echo "Reserva répond."; exit 0; }
    sleep 1
  done
  echo "L'application ne répond pas après la mise à jour. Journal : journalctl -u reserva -n 50" >&2
  exit 1
fi
