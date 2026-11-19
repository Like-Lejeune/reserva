#!/usr/bin/env bash
# Installe Reserva sur un serveur Ubuntu (22.04 ou 24.04) ou Debian 12 neuf.
#
#   sudo bash installer.sh
#
# Le script peut être relancé sans risque : il saute ce qui est déjà fait et ne touche jamais
# au fichier .env ni aux données existantes.
#
# Ce qu'il met en place :
#   - l'utilisateur système « reserva », le code dans /opt/reserva, les données dans /var/lib/reserva ;
#   - Python 3.12 (via uv) et Node.js 22 pour compiler le site ;
#   - le service systemd qui lance l'application et la relance si elle s'arrête ;
#   - Nginx devant l'application, et le certificat HTTPS (Let's Encrypt) ;
#   - la sauvegarde de chaque nuit, à 2 h 30.
set -euo pipefail

DOMAIN="${DOMAIN:-reserva.psikalab.space}"
EMAIL="${EMAIL:-contact@psikalab.space}"            # pour les alertes d'expiration du certificat
REPO="${REPO:-https://github.com/Like-Lejeune/reserva.git}"
BRANCH="${BRANCH:-main}"
APP_DIR=/opt/reserva
DATA_DIR=/var/lib/reserva
APP_USER=reserva
ENV_FILE="$APP_DIR/backend/.env"

step() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
fail() { printf '\n\033[1;31mErreur : %s\033[0m\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || fail "lancez ce script avec sudo."
command -v apt-get >/dev/null || fail "ce script est prévu pour Ubuntu ou Debian."

step "Paquets du système"
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -y -q sudo git curl ca-certificates nginx certbot python3-certbot-nginx \
  libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b fonts-dejavu-core sqlite3
# WeasyPrint (PDF) : ce paquet n'existe pas sous ce nom partout, il est donc facultatif.
apt-get install -y -q libharfbuzz-subset0 2>/dev/null || true

step "Node.js 22 (pour compiler le site)"
if ! command -v node >/dev/null || [ "$(node -p 'process.versions.node.split(".")[0]')" -lt 20 ]; then
  curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
  apt-get install -y -q nodejs
fi
node --version

step "Utilisateur et dossiers"
id "$APP_USER" >/dev/null 2>&1 || useradd --system --create-home --home-dir /home/$APP_USER --shell /usr/sbin/nologin "$APP_USER"
mkdir -p "$DATA_DIR/backups"
chown -R "$APP_USER:$APP_USER" "$DATA_DIR"
chmod 750 "$DATA_DIR"

step "Code de l'application"
if [ ! -d "$APP_DIR/.git" ]; then
  git clone --branch "$BRANCH" "$REPO" "$APP_DIR"
fi
chown -R "$APP_USER:$APP_USER" "$APP_DIR"

step "uv et Python 3.12"
if [ ! -x /home/$APP_USER/.local/bin/uv ]; then
  sudo -u "$APP_USER" -H sh -c 'curl -LsSf https://astral.sh/uv/install.sh | sh'
fi

step "Fichier de configuration (.env)"
if [ ! -f "$ENV_FILE" ]; then
  SECRET=$(head -c 48 /dev/urandom | base64 | tr -d '/+=\n' | head -c 64)
  cat > "$ENV_FILE" <<EOF
# Configuration de production de Reserva. Les autres réglages possibles sont dans .env.example.
RESERVA_ENV=production
RESERVA_SECRET_KEY=$SECRET
RESERVA_DATA_DIR=$DATA_DIR
RESERVA_PUBLIC_BASE_URL=https://$DOMAIN
RESERVA_CORS_ORIGINS=["https://$DOMAIN"]

# Administrateurs de la plateforme : l'identifiant de connexion, chiffres seuls.
RESERVA_ADMIN_LOGINS=["695249549"]

# Paiement Mobile Money (TrustChange). À remplir à la main : ne jamais envoyer ces clés par message.
RESERVA_TRUSTCHANGE_API_KEY=
RESERVA_TRUSTCHANGE_WEBHOOK_SECRET=
RESERVA_TRUSTCHANGE_CALLBACK_URL=https://$DOMAIN/api/payments/webhook
RESERVA_PAYMENT_SIMULATION=false

# Assistance IA en ligne (facultatif) : sans clé, classement par mots-clés.
RESERVA_AI_PROVIDER=rules
EOF
  echo "Fichier créé : $ENV_FILE (clé secrète générée)."
else
  echo "Fichier déjà présent, laissé tel quel : $ENV_FILE"
fi
chown "$APP_USER:$APP_USER" "$ENV_FILE"
chmod 600 "$ENV_FILE"

step "Dépendances et compilation"
bash "$APP_DIR/deploy/mettre-a-jour.sh" --sans-git --sans-redemarrage

step "Service systemd"
install -m 644 "$APP_DIR/deploy/reserva.service" /etc/systemd/system/reserva.service
install -m 644 "$APP_DIR/deploy/reserva-sauvegarde.service" /etc/systemd/system/reserva-sauvegarde.service
install -m 644 "$APP_DIR/deploy/reserva-sauvegarde.timer" /etc/systemd/system/reserva-sauvegarde.timer
systemctl daemon-reload
systemctl enable --now reserva.service
systemctl enable --now reserva-sauvegarde.timer

step "Nginx"
sed "s/__DOMAIN__/$DOMAIN/g" "$APP_DIR/deploy/nginx-reserva.conf" > /etc/nginx/sites-available/reserva
ln -sf /etc/nginx/sites-available/reserva /etc/nginx/sites-enabled/reserva
nginx -t
systemctl reload nginx

step "Vérification locale"
for _ in $(seq 1 20); do
  if curl -fsS http://127.0.0.1:8000/health >/dev/null; then break; fi
  sleep 1
done
curl -fsS http://127.0.0.1:8000/health || fail "l'application ne répond pas. Journal : journalctl -u reserva -n 50"
echo

step "Certificat HTTPS"
SERVER_IP=$(curl -fsS -4 https://ifconfig.me 2>/dev/null || true)
DNS_IP=$(getent ahostsv4 "$DOMAIN" | awk 'NR==1 {print $1}' || true)
if [ -n "$SERVER_IP" ] && [ "$DNS_IP" != "$SERVER_IP" ]; then
  echo "Attention : $DOMAIN pointe vers « ${DNS_IP:-rien} », ce serveur est $SERVER_IP."
  echo "Corrigez l'enregistrement DNS (type A), attendez qu'il se propage, puis relancez ce script."
  echo "En attendant, l'application tourne en HTTP sur ce serveur."
  exit 0
fi
certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos -m "$EMAIL" --redirect

step "Terminé"
curl -fsS "https://$DOMAIN/health" && echo
cat <<EOF

Reserva est en ligne : https://$DOMAIN

Reste à faire à la main :
  1. Renseigner la clé et le secret TrustChange dans $ENV_FILE, puis : sudo systemctl restart reserva
  2. Déclarer chez TrustChange l'adresse du webhook : https://$DOMAIN/api/payments/webhook
  3. Vous inscrire sur le site avec le 695 249 549 : ce compte aura accès à l'administration.
  4. Copier les sauvegardes hors du serveur (voir DEPLOIEMENT.md).
EOF
