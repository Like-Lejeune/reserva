# Mettre Reserva en ligne sur reserva.psikalab.space

Serveur visé : Ubuntu 22.04 ou 24.04 (ou Debian 12), adresse 169.58.220.165.
Durée : une vingtaine de minutes, dont l'essentiel en téléchargements.

## 1. Vérifier le nom de domaine

Depuis votre ordinateur :

```bash
nslookup reserva.psikalab.space
```

La réponse doit donner **169.58.220.165**. Si elle donne une autre adresse, ou rien :
dans la zone DNS de psikalab.space (chez Hostinger si le domaine y est géré), créez ou corrigez
un enregistrement **A** : nom `reserva`, valeur `169.58.220.165`. La propagation prend de quelques
minutes à quelques heures.

Sans cela, l'installation marche mais s'arrête avant le HTTPS, et l'appareil photo, la dictée
et l'installation sur téléphone ne fonctionnent qu'en HTTPS.

## 2. Installer

Connecté au serveur en SSH :

```bash
curl -fsSL https://raw.githubusercontent.com/Like-Lejeune/reserva/main/deploy/installer.sh -o installer.sh
sudo bash installer.sh
```

Le script installe tout, crée le fichier de configuration avec une clé secrète aléatoire, lance
l'application, configure Nginx et demande le certificat HTTPS. Il peut être relancé sans risque,
par exemple après avoir corrigé le DNS.

À la fin, https://reserva.psikalab.space/health doit afficher `{"ok":true}`.

| Quoi | Où |
|---|---|
| Code | `/opt/reserva` |
| Configuration | `/opt/reserva/backend/.env` (lisible par l'application seule) |
| Base et photos | `/var/lib/reserva` |
| Sauvegardes | `/var/lib/reserva/backups`, chaque nuit à 2 h 30, les 14 dernières |

## 3. Brancher le paiement

**Ne jamais envoyer la clé TrustChange par message, e-mail ou chat.** Elle se tape directement
sur le serveur :

```bash
sudo nano /opt/reserva/backend/.env
```

Remplissez :

```
RESERVA_TRUSTCHANGE_API_KEY=tc_live_...
RESERVA_TRUSTCHANGE_WEBHOOK_SECRET=...    # fourni par TrustChange avec la clé
```

puis :

```bash
sudo systemctl restart reserva
```

Chez TrustChange, déclarez l'adresse de notification :
`https://reserva.psikalab.space/api/payments/webhook`

**Premier essai avec une clé live = un vrai débit.** Faites-le avec la plus petite somme : une
recharge de crédit IA de 500 FCFA depuis « Mon compte ». Envoyez-moi ensuite :
- la réponse de `https://reserva.psikalab.space/api/payments/operators` (connecté) ;
- l'état final du paiement dans l'administration ;
- les 50 dernières lignes du journal : `sudo journalctl -u reserva -n 50`.

Ils servent à confirmer les noms des en-têtes du webhook et les statuts de TrustChange. Si le
paiement reste « En attente » alors que vous avez validé sur le téléphone, c'est un de ces deux
points : on le corrige, et vous validez le paiement à la main depuis l'administration.

## 4. Votre compte administrateur

Inscrivez-vous sur le site avec le **695 249 549** : ce numéro est déclaré administrateur dans
`RESERVA_ADMIN_LOGINS`, l'onglet « Administration » apparaît. Pour en ajouter un autre, ajoutez son
identifiant (chiffres seuls) à cette liste, puis relancez le service.

## 5. Copier les sauvegardes hors du serveur

Une sauvegarde restée sur le serveur ne sert à rien si le disque lâche. Le plus simple : rclone
vers un Google Drive ou un stockage S3.

```bash
sudo apt install rclone
sudo -u reserva rclone config        # créer un « remote » nommé distant
sudo -u reserva crontab -e
# ajouter :
45 2 * * * rclone copy /var/lib/reserva/backups distant:reserva-sauvegardes
```

Testez une restauration une fois : arrêter le service, extraire une archive dans un dossier de test,
ouvrir `reserva.db` avec `sqlite3`.

## Au quotidien

| Pour | Commande |
|---|---|
| Mettre à jour (après un envoi sur GitHub) | `sudo bash /opt/reserva/deploy/mettre-a-jour.sh` |
| Voir si l'application tourne | `systemctl status reserva` |
| Lire le journal | `sudo journalctl -u reserva -f` |
| Redémarrer | `sudo systemctl restart reserva` |
| Sauvegarder maintenant | `sudo systemctl start reserva-sauvegarde` |
| Lister les sauvegardes | `ls -lh /var/lib/reserva/backups` |

La mise à jour fait d'abord une sauvegarde, puis applique les migrations de la base au redémarrage.

## Être prévenu si le site tombe

Créez une sonde gratuite sur UptimeRobot (ou équivalent) vers
`https://reserva.psikalab.space/health`, toutes les 5 minutes, avec alerte par e-mail ou SMS.
