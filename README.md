# Reserva — rapports de finition assistés

Nom provisoire. Une photo et une phrase par défaut ; l'outil classe, numérote, met en page le PDF,
l'envoie par WhatsApp et suit les corrections. Fonctionne sans connexion.

| Dossier | Contenu |
|---|---|
| `backend/` | Serveur FastAPI : API, PDF, abonnements, paiement TrustChange, administration |
| `web/` | Site React TypeScript : vitrine, espace utilisateur (installable sur téléphone), administration |
| `mobile/` | Application Flutter (écrite, pas encore compilée : voir `mobile/README.md`) |

## Lancer en développement

```bash
cd backend
pip install -e . && pip install pytest
cp .env.example .env            # puis renseigner au moins RESERVA_SECRET_KEY
uvicorn app.main:app --reload   # http://localhost:8000, documentation de l'API sur /docs

cd ../web
npm install
npm run dev                     # http://localhost:5173, relié au serveur ci-dessus
```

Tests du serveur : `cd backend && python -m pytest`.

Pour servir le site par le serveur lui-même (comme en production) : `cd web && npm run build`,
puis ouvrir http://localhost:8000.

## Base de données : migrations

La base est créée et mise à jour par des migrations (Alembic), appliquées seules au démarrage.
Après toute modification de `backend/app/models.py` :

```bash
cd backend
alembic revision --autogenerate -m "ce qui change"   # crée migrations/versions/xxxx.py : la relire
python -m pytest                                      # un test vérifie que modèles et migrations concordent
```

Une base créée avant la mise en place des migrations doit être supprimée (`data/reserva.db`) :
c'est la dernière fois.

## Sauvegardes

```bash
cd backend && python -m app.backup --keep 14          # archive base + photos dans data/backups
```

À planifier chaque nuit, puis à copier hors du serveur. Exemple de ligne cron :

```
30 2 * * *  cd /var/www/reserva/backend && .venv/bin/python -m app.backup --keep 14 && rclone copy data/backups distant:reserva
```

Restaurer : arrêter le serveur, extraire l'archive, remettre `reserva.db` et `media/` dans `data/`, relancer.

## Avant la mise en production

Dans `backend/.env` :

- `RESERVA_ENV=production` : le serveur refuse alors de démarrer avec un réglage dangereux.
- `RESERVA_SECRET_KEY` : valeur aléatoire (`python -c "import secrets; print(secrets.token_urlsafe(48))"`).
- `RESERVA_PUBLIC_BASE_URL=https://votre-domaine` et `RESERVA_CORS_ORIGINS`.
- `RESERVA_ADMIN_LOGINS` : identifiants des administrateurs de la plateforme.
- `RESERVA_TRUSTCHANGE_*` : clé, secret de webhook, adresse du webhook (`/api/payments/webhook`).
- `RESERVA_SMS_*` ou `RESERVA_SMTP_*` : pour envoyer les codes « mot de passe oublié ».
- `RESERVA_AI_*` : pour l'assistance par modèle en ligne (sinon, classement par mots-clés).

Lancer uvicorn avec `--proxy-headers` derrière Nginx, sur **un seul processus** (les limites de
tentatives sont comptées en mémoire).

Dans `web/src/lib/site.ts` : nom, numéro WhatsApp de contact, identité de l'éditeur, clients de
référence. Les pages légales sont des modèles à faire relire par un juriste, puis `LEGAL_DRAFT = false`.

Offres, prix et limites : `backend/app/plans.py`.
